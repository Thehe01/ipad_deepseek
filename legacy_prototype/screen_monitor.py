import time
import os
import threading
import numpy as np
from PIL import ImageGrab, Image
from config import (
    DIFF_THRESHOLD,
    STABILIZE_DELAY,
    POLL_INTERVAL,
    TEMP_IMAGE_PATH
)

class ScreenMonitor:
    """
    负责实时截取指定 ROI 区域，并通过帧差算法检测切题。
    内建防抖状态机，确保在翻页动画完全静止后才触发回调。
    """
    def __init__(self, roi, on_question_detected=None):
        self.roi = roi
        self.bbox = (
            roi["x"],
            roi["y"],
            roi["x"] + roi["width"],
            roi["y"] + roi["height"]
        )
        self.on_question_detected = on_question_detected

        self.is_running = False
        self.is_paused = False
        self._thread = None

        # 状态机变量
        self.state = "IDLE"  # "IDLE" 或 "STABILIZING"
        self.ref_frame = None           # 基准静止参考帧 (用于检测是否切题)
        self.last_transient_frame = None # 瞬态前一帧 (用于检测翻页动画是否已停滞)
        self.change_start_time = 0

    def _grab_raw(self):
        """截取原始高分辨率 ROI 区域图像，支持 ImageGrab 与 mss 双重兜底"""
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
                    "height": int(self.roi["height"])
                }
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as e:
            raise RuntimeError(f"屏幕截图失败（请确保屏幕处于解锁活动状态）: {e}")

    def _get_processed_frame(self, raw_img=None):
        """将图像转为低分辨率灰度数组，用于极速帧差计算"""
        if raw_img is None:
            raw_img = self._grab_raw()
        # 降采样到 200x200 快速计算
        small_gray = raw_img.convert("L").resize((200, 200), Image.Resampling.BILINEAR)
        return np.asarray(small_gray, dtype=np.float32)

    @staticmethod
    def _calc_diff(arr1, arr2):
        """计算两帧之间的平均像素归一化差异 (0.0 ~ 1.0)"""
        if arr1 is None or arr2 is None:
            return 0.0
        return float(np.mean(np.abs(arr1 - arr2)) / 255.0)

    def trigger_manual(self):
        """手动强制触发截屏发送（如按 F8）"""
        print("\n[快捷键] 收到手动截题指令，正在截取并发送当前屏幕...")
        raw_img = self._grab_raw()
        raw_img.save(TEMP_IMAGE_PATH, format="PNG")
        # 更新基准参考帧，避免被自动检测重复捕获
        self.ref_frame = self._get_processed_frame(raw_img)
        self.state = "IDLE"
        if self.on_question_detected:
            self.on_question_detected(TEMP_IMAGE_PATH, is_manual=True)

    def toggle_pause(self):
        """切换暂停/继续监听状态（如按 F9）"""
        self.is_paused = not self.is_paused
        status = "已暂停监控" if self.is_paused else "已恢复监控"
        print(f"\n[状态变更] {status}")
        if not self.is_paused:
            # 恢复时刷新基准帧
            self.ref_frame = self._get_processed_frame()
            self.state = "IDLE"

    def start(self):
        """启动后台监听线程"""
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print(f"[监控运行中] 区域: {self.bbox}, 阈值: {DIFF_THRESHOLD*100:.1f}%, 防抖延迟: {STABILIZE_DELAY}s")

    def stop(self):
        """停止监听"""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        # 初始化基准帧
        self.ref_frame = self._get_processed_frame()
        self.last_transient_frame = self.ref_frame
        self.state = "IDLE"
        last_heartbeat = 0

        while self.is_running:
            try:
                time.sleep(POLL_INTERVAL)

                if self.is_paused:
                    continue

                curr_raw = self._grab_raw()
                curr_frame = self._get_processed_frame(curr_raw)

                if self.state == "IDLE":
                    diff_from_ref = self._calc_diff(curr_frame, self.ref_frame)
                    
                    # 动态心跳显示（每 3 秒刷新一次当前波动率，让用户直观看到变化）
                    now = time.time()
                    if now - last_heartbeat >= 3.0:
                        last_heartbeat = now
                        print(f"[监控心跳] 正常运行中 | 画面差异: {diff_from_ref*100:.2f}% (触发阈值: {DIFF_THRESHOLD*100:.1f}%)")

                    # 当画面与基准帧差异超过阈值，说明切题了
                    if diff_from_ref >= DIFF_THRESHOLD:
                        print(f"\n[检测到切题] 差异率: {diff_from_ref*100:.2f}% >= {DIFF_THRESHOLD*100:.1f}%，等待画面静止 ({STABILIZE_DELAY}s)...")
                        self.state = "STABILIZING"
                        self.change_start_time = now
                        self.first_trigger_time = now
                        self.last_transient_frame = curr_frame

                elif self.state == "STABILIZING":
                    now = time.time()
                    jitter_diff = self._calc_diff(curr_frame, self.last_transient_frame)
                    
                    # 强制最大防抖超时时间（最多等待 2.5 秒，绝不允许无限死锁）
                    force_trigger = (now - getattr(self, "first_trigger_time", now)) >= 2.5

                    # 如果连续两帧仍在剧烈晃动（翻页动画中），且未超过最大超时
                    if jitter_diff > 0.015 and not force_trigger:
                        self.change_start_time = now
                        self.last_transient_frame = curr_frame
                    else:
                        elapsed = now - self.change_start_time
                        if elapsed >= STABILIZE_DELAY or force_trigger:
                            final_diff = self._calc_diff(curr_frame, self.ref_frame)
                            # 最终确认新画面确实与原基准有足够差异
                            if final_diff >= (DIFF_THRESHOLD * 0.7) or force_trigger:
                                print(f"[切题确认完毕] 画面已静止，差异率: {final_diff*100:.2f}%，正在保存并发送题目...")
                                curr_raw.save(TEMP_IMAGE_PATH, format="PNG")
                                self.ref_frame = curr_frame
                                self.state = "IDLE"
                                last_heartbeat = time.time()

                                if self.on_question_detected:
                                    self.on_question_detected(TEMP_IMAGE_PATH, is_manual=False)
                            else:
                                print(f"[防抖判定] 差异率仅 {final_diff*100:.2f}%，判定为鼠标滑动或临时偶发抖动，重置监控。")
                                self.state = "IDLE"
                                last_heartbeat = time.time()

            except Exception as e:
                print(f"[监控异常] {e}")
                time.sleep(1.0)

