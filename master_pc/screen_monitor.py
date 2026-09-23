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
        TEMP_IMAGE_PATH,
    )
except ImportError:
    DIFF_THRESHOLD = 0.06
    STABILIZE_DELAY = 0.8
    POLL_INTERVAL = 0.25
    TEMP_IMAGE_PATH = "temp_capture.png"


class ScreenMonitor:
    """
    负责主电脑实时截取指定 ROI 区域，并通过关键帧差算法全自动检测切题。
    内建防抖状态机与冷却机制：
    1. 画面变动超过阈值 -> 进入 STABILIZING 防抖观察期；
    2. 动画或翻页结束、画面完全稳定 0.8s -> 毫秒级自动保存高清原图并触发上传；
    3. 全程零人工介入，双手无需触碰鼠标或键盘。
    """

    def __init__(self, roi, on_question_detected=None, grab_fn=None, log_fn=None):
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

        self.diff_threshold = DIFF_THRESHOLD if DIFF_THRESHOLD > 0.03 else 0.06
        self.stabilize_delay = STABILIZE_DELAY if STABILIZE_DELAY >= 0.5 else 0.8
        self.poll_interval = POLL_INTERVAL if POLL_INTERVAL >= 0.1 else 0.25
        self.cooldown = 2.5  # 自动切题后冷却时间，防止单题连发

        self.is_running = False
        self.is_paused = False
        self._thread = None

        self.state = "IDLE"
        self.ref_frame = None
        self.last_transient_frame = None
        self.change_start_time = 0
        self.first_trigger_time = 0
        self.last_snap_time = 0.0

    def _log(self, msg):
        try:
            self.log_fn(msg)
        except Exception:
            print(msg)

    def _grab_raw(self):
        """优先使用传入的高性能 GDI 截图函数，失败时回退 PIL/mss"""
        if self.grab_fn:
            try:
                return self.grab_fn(self.roi)
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
            raise RuntimeError(f"屏幕截图失败: {e}")

    def _get_processed_frame(self, raw_img=None):
        """将截图快速缩放为 160x160 灰度矩阵，快速计算绝对帧差"""
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
        """手动触发截图（如滚轮中键）时同步最新基准帧，防止重复自动截题"""
        try:
            self.ref_frame = self._get_processed_frame(raw_img)
            self.last_snap_time = time.time()
            self.state = "IDLE"
        except Exception:
            pass

    def toggle_pause(self):
        """切换暂停/恢复自动检测"""
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
            f"变动阈值: {self.diff_threshold*100:.1f}%, 防抖稳定: {self.stabilize_delay}s"
        )

    def stop(self):
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _monitor_loop(self):
        try:
            self.ref_frame = self._get_processed_frame()
            self.last_transient_frame = self.ref_frame
        except Exception as e:
            self._log(f"[监控启动警告] 初始帧抓取异常: {e}")

        self.state = "IDLE"

        while self.is_running:
            try:
                time.sleep(self.poll_interval)

                if self.is_paused or self.ref_frame is None:
                    continue

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
                    # 检查画面是否还在滑动/动画过程中（动态抖动率）
                    jitter_diff = self._calc_diff(curr_frame, self.last_transient_frame)
                    force_trigger = (now - self.first_trigger_time) >= 3.0

                    if jitter_diff > 0.02 and not force_trigger:
                        # 画面仍在动态变化，重置计时器
                        self.change_start_time = now
                        self.last_transient_frame = curr_frame
                    else:
                        # 画面处于静止状态，检查持续时间
                        elapsed = now - self.change_start_time
                        if elapsed >= self.stabilize_delay or force_trigger:
                            final_diff = self._calc_diff(curr_frame, self.ref_frame)
                            if final_diff >= (self.diff_threshold * 0.75) or force_trigger:
                                self._log(
                                    f"[全自动切题] 画面稳定确认！差异率: {final_diff*100:.1f}%，"
                                    f"正在全自动保存高清截图并上传辅助电脑..."
                                )
                                curr_raw.save(TEMP_IMAGE_PATH, format="PNG")
                                self.ref_frame = curr_frame
                                self.last_snap_time = time.time()
                                self.state = "IDLE"

                                if self.on_question_detected:
                                    self.on_question_detected(TEMP_IMAGE_PATH, is_manual=False)
                            else:
                                self._log(
                                    f"[防抖重置] 画面差异率已回落至 {final_diff*100:.1f}%，判定为临时光标或弹窗遮挡，重置监控。"
                                )
                                self.state = "IDLE"

            except Exception as e:
                time.sleep(0.5)
