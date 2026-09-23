import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import tkinter as tk

from tkinter import messagebox
from master_config import ROI_CONFIG_FILE

def load_saved_roi():
    """读取已保存的监控区域坐标"""
    if os.path.exists(ROI_CONFIG_FILE):
        try:
            with open(ROI_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if all(k in data for k in ("x", "y", "width", "height")):
                    return data
        except Exception:
            pass
    return None

def save_roi(roi):
    """保存监控区域坐标到配置文件"""
    try:
        with open(ROI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(roi, f, indent=2, ensure_ascii=False)
        print(f"[配置] 监控区域已保存: x={roi['x']}, y={roi['y']}, w={roi['width']}, h={roi['height']}")
    except Exception as e:
        print(f"[错误] 保存 ROI 失败: {e}")

class ROISelector:
    """全屏半透明鼠标拖拽框选工具"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("框选题目的监控区域")
        
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.35)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None
        self.text_id = None
        self.selected_roi = None

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Return>", self.on_confirm)
        self.root.bind("<Escape>", self.on_cancel)

        self.canvas.create_text(
            self.root.winfo_screenwidth() // 2,
            60,
            text="【主电脑·拖拽框选】按住鼠标左键拖拽选出腾讯会议中 iPad 题目的显示区域\n框选完成后松开鼠标，按 Enter 键确认，按 Esc 取消",
            fill="yellow",
            font=("Microsoft YaHei", 16, "bold"),
            justify=tk.CENTER
        )

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect:
            self.canvas.delete(self.rect)
        if self.text_id:
            self.canvas.delete(self.text_id)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=3, fill="white"
        )

    def on_move_press(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)
        
        w = abs(cur_x - self.start_x)
        h = abs(cur_y - self.start_y)
        info = f"{w} x {h} px"
        
        if self.text_id:
            self.canvas.delete(self.text_id)
        mid_x = (self.start_x + cur_x) // 2
        mid_y = max(20, min(self.start_y, cur_y) - 15)
        self.text_id = self.canvas.create_text(
            mid_x, mid_y, text=info, fill="cyan", font=("Microsoft YaHei", 12, "bold")
        )

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        width = x2 - x1
        height = y2 - y1

        if width > 50 and height > 50:
            self.selected_roi = {
                "x": int(x1),
                "y": int(y1),
                "width": int(width),
                "height": int(height)
            }
            if self.text_id:
                self.canvas.delete(self.text_id)
            self.text_id = self.canvas.create_text(
                x1 + width // 2, y1 + height // 2,
                text=f"区域已选定 ({width}x{height})\n按【回车键 Enter】确认",
                fill="red", font=("Microsoft YaHei", 14, "bold"), justify=tk.CENTER
            )

    def on_confirm(self, event=None):
        if self.selected_roi:
            save_roi(self.selected_roi)
            self.root.destroy()
        else:
            messagebox.showwarning("提示", "请先按住鼠标左键拖拽选出一个有效区域！")

    def on_cancel(self, event=None):
        self.selected_roi = None
        self.root.destroy()

    def select(self):
        self.root.mainloop()
        return self.selected_roi

def is_console_visible():
    """检测当前控制台窗口是否真实可见（隐藏窗口/pythonw/VBS 启动返回 False）"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return False
        return bool(u32.IsWindowVisible(hwnd))
    except Exception:
        return False


def get_roi_interactive(force_reselect=False):
    saved = load_saved_roi()
    if saved and not force_reselect:
        # 核心防卡死：如果控制台窗口不可见（静默后台），绝不调用 input() 阻塞，直接自动复用已保存的区域！
        if not is_console_visible():
            print("[后台静默模式] 控制台无可见窗口，自动复用历史监控区域。")
            return saved
        try:
            choice = input("是否直接使用上次的监控区域？[Y/n (输入 n 重新框选)]: ").strip().lower()
            if choice != 'n':
                return saved
        except Exception:
            return saved

    print("\n[提示] 正在打开全屏框选界面，请用鼠标左键拖拽框选题目区域，按 Enter 确认...")
    selector = ROISelector()
    roi = selector.select()
    if not roi:
        if saved:
            print("[提示] 取消了重新框选，恢复使用历史监控区域。")
            return saved
        else:
            print("\n[提示] 未框选区域，自动采用主屏幕全屏进行监控。")
            try:
                root = tk.Tk()
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                root.destroy()
            except Exception:
                sw, sh = 1920, 1080
            fallback_roi = {"x": 0, "y": 0, "width": sw, "height": sh}
            save_roi(fallback_roi)
            return fallback_roi
    return roi
