import time
import os
import sys
import threading
import numpy as np
from PIL import ImageGrab, Image

import json
import ctypes

from ctypes import wintypes

try:
    from master_config import (
        ENABLE_SCREEN_DIFF_TRIGGER,
        DIFF_THRESHOLD,
        STABILIZE_DELAY,
        POLL_INTERVAL,
        MAX_STABILIZE_TIMEOUT,
        AUTO_COOLDOWN,
        UPLOAD_INITIAL_QUESTION,
        MOUSE_TRIGGER_ENABLED,
        MOUSE_CORNER_WIDTH,
        MOUSE_CORNER_HEIGHT,
        MOUSE_HOVER_TIME,
        MOUSE_TRIGGER_COOLDOWN,
        MOUSE_TRIGGER_CONFIG_FILE,
    )
except ImportError:
    ENABLE_SCREEN_DIFF_TRIGGER = False
    DIFF_THRESHOLD = 0.025
    STABILIZE_DELAY = 0.8
    POLL_INTERVAL = 0.25
    MAX_STABILIZE_TIMEOUT = 4.0
    AUTO_COOLDOWN = 2.0
    UPLOAD_INITIAL_QUESTION = False
    MOUSE_TRIGGER_ENABLED = True
    MOUSE_CORNER_WIDTH = 120
    MOUSE_CORNER_HEIGHT = 80
    MOUSE_HOVER_TIME = 0.3
    MOUSE_TRIGGER_COOLDOWN = 2.0
    MOUSE_TRIGGER_CONFIG_FILE = "master_mouse_trigger_config.json"

try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

_user32 = ctypes.windll.user32

def _get_cursor_pos():
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

def _get_screen_size():
    return int(_user32.GetSystemMetrics(0)), int(_user32.GetSystemMetrics(1))


class ScreenMonitor:
    """
    主电脑屏幕画面变动监控器：
    - 基于高频帧差对比与防抖状态机全自动识别切题；
    - 内存中直接传递 PIL 图像对象，彻底杜绝多线程写单文件的磁盘覆盖竞争；
    - 初始截图失败具备自动持续重试能力；
    - 支持将启动时的首屏画面作为第 1 题自动上传。
    """

    def __init__(
        self,
        roi,
        on_question_detected=None,
        grab_fn=None,
        log_fn=None,
        diff_threshold=None,
        stabilize_delay=None,
        poll_interval=None,
        max_stabilize_timeout=None,
        cooldown=None,
        upload_initial=None,
        enable_screen_diff_trigger=None,
        mouse_trigger_enabled=None,
        mouse_corner_w=None,
        mouse_corner_h=None,
        mouse_hover_time=None,
        mouse_trigger_cooldown=None,
    ):
        self.roi = roi
        self.bbox = (
            int(roi["x"]),
            int(roi["y"]),
            int(roi["x"] + roi["width"]),
            int(roi["y"] + roi["height"]),
        )
        self.on_question_detected = on_question_detected
        self.grab_fn = grab_fn
        self.log_fn = log_fn or print

        # 直接采用配置传入的参数，杜绝隐式硬编码覆盖
        self.diff_threshold = diff_threshold if diff_threshold is not None else DIFF_THRESHOLD
        self.stabilize_delay = stabilize_delay if stabilize_delay is not None else STABILIZE_DELAY
        self.poll_interval = poll_interval if poll_interval is not None else POLL_INTERVAL
        self.max_stabilize_timeout = (
            max_stabilize_timeout if max_stabilize_timeout is not None else MAX_STABILIZE_TIMEOUT
        )
        self.cooldown = cooldown if cooldown is not None else AUTO_COOLDOWN
        self.upload_initial = (
            upload_initial if upload_initial is not None else UPLOAD_INITIAL_QUESTION
        )
        self.enable_screen_diff_trigger = (
            enable_screen_diff_trigger if enable_screen_diff_trigger is not None else ENABLE_SCREEN_DIFF_TRIGGER
        )

        # 鼠标热区（屏幕右上角 / 自定义热区）触发配置
        self.mouse_trigger_enabled = (
            mouse_trigger_enabled if mouse_trigger_enabled is not None else MOUSE_TRIGGER_ENABLED
        )
        self.mouse_corner_w = (
            mouse_corner_w if mouse_corner_w is not None else MOUSE_CORNER_WIDTH
        )
        self.mouse_corner_h = (
            mouse_corner_h if mouse_corner_h is not None else MOUSE_CORNER_HEIGHT
        )
        self.mouse_hover_time = (
            mouse_hover_time if mouse_hover_time is not None else MOUSE_HOVER_TIME
        )
        self.mouse_trigger_cooldown = (
            mouse_trigger_cooldown if mouse_trigger_cooldown is not None else MOUSE_TRIGGER_COOLDOWN
        )
        self.mouse_trigger_roi = None
        self._last_mouse_config_mtime = 0.0
        self._hover_start_time = 0.0
        self._last_mouse_trigger_time = 0.0
        self._corner_already_triggered = False
        self._mouse_thread = None

        # 启动时初次载入鼠标触发区
        self._reload_mouse_trigger_roi()

        self.is_running = False
        self.is_paused = False
        self._thread = None

        self.state = "IDLE"
        self.ref_frame = None
        self.last_transient_frame = None
        self.change_start_time = 0
        self.first_trigger_time = 0
        self.last_snap_time = 0.0
        self._initial_uploaded = False

    def _reload_mouse_trigger_roi(self):
        """检查并热重载鼠标触发区配置"""
        if not self.mouse_trigger_enabled or not os.path.exists(MOUSE_TRIGGER_CONFIG_FILE):
            return
        try:
            mtime = os.path.getmtime(MOUSE_TRIGGER_CONFIG_FILE)
            if mtime != self._last_mouse_config_mtime:
                self._last_mouse_config_mtime = mtime
                with open(MOUSE_TRIGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if all(k in data for k in ("x", "y", "width", "height")):
                        old_roi = self.mouse_trigger_roi
                        self.mouse_trigger_roi = {
                            "x": int(data["x"]),
                            "y": int(data["y"]),
                            "width": int(data["width"]),
                            "height": int(data["height"])
                        }
                        if old_roi != self.mouse_trigger_roi:
                            self._log(
                                f"[鼠标触发区] 热加载就绪: x={self.mouse_trigger_roi['x']}, "
                                f"y={self.mouse_trigger_roi['y']}, w={self.mouse_trigger_roi['width']}, "
                                f"h={self.mouse_trigger_roi['height']}，鼠标移入或点击将自动延时截题！"
                            )
        except Exception:
            pass

    def _log(self, msg):
        try:
            self.log_fn(msg)
        except Exception:
            print(msg)

    def _grab_raw(self):
        """抓取高分辨率 ROI 原始图像"""
        if self.grab_fn:
            try:
                img = self.grab_fn(self.roi)
                if img is not None:
                    return img
            except Exception:
                pass

        try:
            return ImageGrab.grab(bbox=self.bbox, all_screens=True)
        except Exception:
            pass

        try:
            from mss import MSS

            with MSS() as sct:
                monitor = {
                    "top": int(self.roi["y"]),
                    "left": int(self.roi["x"]),
                    "width": int(self.roi["width"]),
                    "height": int(self.roi["height"]),
                }
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as e:
            raise RuntimeError(f"屏幕截图抓取失败: {e}")

    def _get_processed_frame(self, raw_img=None):
        """转换为 160x160 灰度矩阵进行快速帧差对比"""
        if raw_img is None:
            raw_img = self._grab_raw()
        small_gray = raw_img.convert("L").resize((160, 160), Image.Resampling.BILINEAR)
        return np.asarray(small_gray, dtype=np.float32)

    @staticmethod
    def _calc_diff(arr1, arr2):
        if arr1 is None or arr2 is None:
            return 0.0
        return float(np.mean(np.abs(arr1 - arr2)) / 255.0)

    def sync_ref_frame(self, raw_img=None):
        """手动截题（如中键单击）时同步基准帧与冷却，避免连续重复触发"""
        try:
            if raw_img is not None:
                self.ref_frame = self._get_processed_frame(raw_img)
            else:
                self.ref_frame = self._get_processed_frame()
            self.last_transient_frame = self.ref_frame
            self.last_snap_time = time.time()
            self.state = "IDLE"
        except Exception as e:
            self._log(f"[基准帧同步异常] {e}")

    def toggle_pause(self):
        """暂停/恢复自动切题感知"""
        self.is_paused = not self.is_paused
        status = "已暂停自动切题监控" if self.is_paused else "已恢复自动切题监控"
        self._log(f"[监控状态] {status}")
        if not self.is_paused:
            self.sync_ref_frame()

    def start(self):
        if self.is_running:
            return
        self.is_running = True

        if self.enable_screen_diff_trigger:
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            self._log(
                f"[全自动切题引擎] 画面像素帧差检测已开启。监控区域: {self.bbox}, "
                f"变动阈值: {self.diff_threshold*100:.1f}%, 防抖稳定: {self.stabilize_delay}s, "
                f"采样间隔: {self.poll_interval}s, 冷却时间: {self.cooldown}s"
            )
        else:
            self._log(
                f"[截题模式] 画面像素帧差检测已关闭（零误触），唯一截题触发通道："
                f"鼠标在屏幕右上角停留 {self.mouse_hover_time:.1f}s 截题！"
            )

        if self.mouse_trigger_enabled:
            self._mouse_thread = threading.Thread(target=self._mouse_trigger_loop, daemon=True)
            self._mouse_thread.start()
            if self.enable_screen_diff_trigger:
                self._log(
                    f"[鼠标触发就绪] 鼠标在屏幕右上角（宽度: {self.mouse_corner_w}px, 高度: {self.mouse_corner_h}px）"
                    f"停留达到 {self.mouse_hover_time:.1f}s 即可自动截屏！"
                )

    def stop(self):
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if hasattr(self, "_mouse_thread") and self._mouse_thread and self._mouse_thread.is_alive():
            self._mouse_thread.join(timeout=1.0)

    def _mouse_trigger_loop(self):
        """轻量级高频鼠标热区感知线程（约 30Hz，CPU < 0.05%）"""
        last_cfg_check = 0.0
        while self.is_running:
            try:
                time.sleep(0.03)

                if self.is_paused or not self.mouse_trigger_enabled:
                    continue

                now = time.time()
                # 每隔 1 秒检查一次鼠标热区自定义配置文件是否有更新（支持热加载）
                if now - last_cfg_check >= 1.0:
                    last_cfg_check = now
                    self._reload_mouse_trigger_roi()

                mx, my = _get_cursor_pos()
                sw, sh = _get_screen_size()

                # 1. 判定是否处于触发区：
                # A. 屏幕右上角区域（默认宽度 120px、高度 80px，面积适中）
                in_top_right = (mx >= sw - self.mouse_corner_w) and (0 <= my <= self.mouse_corner_h)

                # B. 自定义框选的区域（若配置了）
                in_custom = False
                if self.mouse_trigger_roi:
                    rx = self.mouse_trigger_roi["x"]
                    ry = self.mouse_trigger_roi["y"]
                    rw = self.mouse_trigger_roi["width"]
                    rh = self.mouse_trigger_roi["height"]
                    in_custom = (rx <= mx <= rx + rw and ry <= my <= ry + rh)

                in_zone = in_top_right or in_custom

                if in_zone:
                    if self._hover_start_time == 0.0:
                        self._hover_start_time = now
                    hover_dur = now - self._hover_start_time

                    if hover_dur >= self.mouse_hover_time and not self._corner_already_triggered:
                        cooldown_ok = (now - self._last_mouse_trigger_time >= self.mouse_trigger_cooldown) and (now - self.last_snap_time >= min(self.mouse_trigger_cooldown, 1.0))
                        if cooldown_ok:
                            location_desc = "屏幕右上角" if in_top_right else "自定义触发区"
                            self._log(
                                f"[鼠标停留触发] 检测到鼠标在{location_desc}停留达到 {self.mouse_hover_time:.1f}s "
                                f"(坐标: {mx}, {my})，立即截屏送题！"
                            )
                            self._last_mouse_trigger_time = now
                            self._corner_already_triggered = True  # 标记当前停留已触发，离开前不再重复触发

                            try:
                                raw = self._grab_raw()
                                self.sync_ref_frame(raw)
                                self.last_snap_time = time.time()
                                self.state = "IDLE"
                                self._log(f"[鼠标截题成功] 题目画面捕获完成，已送入上传队列！")
                                if self.on_question_detected:
                                    self.on_question_detected(raw, is_manual=False, trigger_name=f"鼠标停留{location_desc}")
                            except Exception as e:
                                self._log(f"[鼠标截题异常] 抓取题目画面失败: {e}")
                else:
                    # 鼠标移出触发区，重置计时器与触发标记，重新就绪！
                    self._hover_start_time = 0.0
                    self._corner_already_triggered = False

            except Exception:
                time.sleep(0.1)

    def _monitor_loop(self):
        if not self.enable_screen_diff_trigger:
            return
        last_fail_log = 0.0

        while self.is_running:
            try:
                time.sleep(self.poll_interval)

                if self.is_paused:
                    continue

                # ── 1. 初始基准帧获取（若初始失败持续自动重试，不陷入死循环） ──
                if self.ref_frame is None:
                    try:
                        raw = self._grab_raw()
                        self.ref_frame = self._get_processed_frame(raw)
                        self.last_transient_frame = self.ref_frame
                        self._log(f"[全自动切题] 初始基准画面获取成功。")
                        if self.upload_initial and not self._initial_uploaded:
                            self._initial_uploaded = True
                            self._log("[初始切题] 正在将当前屏幕显示的第 1 题加入上传队列...")
                            if self.on_question_detected:
                                self.on_question_detected(raw, is_manual=False, trigger_name="初始第1题")
                    except Exception as e:
                        now_t = time.time()
                        if now_t - last_fail_log >= 3.0:
                            last_fail_log = now_t
                            self._log(f"[监控警告] 无法获取基准画面，正在重试: {e}")
                        continue

                # ── 2. 正常画面抓取与差异度对比 ──
                now = time.time()
                curr_raw = self._grab_raw()
                curr_frame = self._get_processed_frame(curr_raw)

                if self.state == "IDLE":
                    # 冷却期内不判定新一轮切题
                    if now - self.last_snap_time < self.cooldown:
                        continue

                    diff_from_ref = self._calc_diff(curr_frame, self.ref_frame)
                    if diff_from_ref >= self.diff_threshold:
                        self._log(
                            f"[画面变动] 检测到可能翻页 (差异率: {diff_from_ref*100:.1f}% >= "
                            f"{self.diff_threshold*100:.1f}%)，等待画面稳定 ({self.stabilize_delay}s)..."
                        )
                        self.state = "STABILIZING"
                        self.change_start_time = now
                        self.first_trigger_time = now
                        self.last_transient_frame = curr_frame

                elif self.state == "STABILIZING":
                    jitter_diff = self._calc_diff(curr_frame, self.last_transient_frame)
                    timeout_triggered = (now - self.first_trigger_time) >= self.max_stabilize_timeout

                    # 若画面持续剧烈变动且未超时，重置稳定计时器
                    if jitter_diff > 0.02 and not timeout_triggered:
                        self.change_start_time = now
                        self.last_transient_frame = curr_frame
                    else:
                        elapsed = now - self.change_start_time
                        if elapsed >= self.stabilize_delay or timeout_triggered:
                            final_diff = self._calc_diff(curr_frame, self.ref_frame)
                            if final_diff >= (self.diff_threshold * 0.75) or timeout_triggered:
                                if timeout_triggered:
                                    self._log(
                                        f"[超时触发] 画面变动超过 {self.max_stabilize_timeout}s 上限（可能含动态元素），"
                                        f"执行切题确认 (差异率: {final_diff*100:.1f}%)..."
                                    )
                                else:
                                    self._log(
                                        f"[全自动切题] 画面稳定确认！差异率: {final_diff*100:.1f}%，"
                                        f"正在将新题目送入上传队列..."
                                    )
                                self.ref_frame = curr_frame
                                self.last_snap_time = time.time()
                                self.state = "IDLE"

                                # 直接将内存 PIL 对象交由上传器处理，杜绝静态文件覆盖冲突
                                if self.on_question_detected:
                                    self.on_question_detected(
                                        curr_raw, is_manual=False, trigger_name="自动翻页感知"
                                    )
                            else:
                                self._log(
                                    f"[防抖重置] 画面差异率回落至 {final_diff*100:.1f}%，判定为临时光标或弹窗遮挡，重置监控。"
                                )
                                self.state = "IDLE"

            except Exception as e:
                time.sleep(0.5)
