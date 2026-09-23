import time
import os
import sys
import threading
import numpy as np
from PIL import ImageGrab, Image

try:
    from master_config import (
        DIFF_THRESHOLD,
        STABILIZE_DELAY,
        POLL_INTERVAL,
        MAX_STABILIZE_TIMEOUT,
        AUTO_COOLDOWN,
        UPLOAD_INITIAL_QUESTION,
    )
except ImportError:
    DIFF_THRESHOLD = 0.06
    STABILIZE_DELAY = 0.8
    POLL_INTERVAL = 0.25
    MAX_STABILIZE_TIMEOUT = 4.0
    AUTO_COOLDOWN = 2.0
    UPLOAD_INITIAL_QUESTION = True


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
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self._log(
            f"[全自动切题引擎] 已启动！监控区域: {self.bbox}, "
            f"变动阈值: {self.diff_threshold*100:.1f}%, 防抖稳定: {self.stabilize_delay}s, "
            f"采样间隔: {self.poll_interval}s, 冷却时间: {self.cooldown}s"
        )

    def stop(self):
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _monitor_loop(self):
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
