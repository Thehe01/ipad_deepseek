import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import tkinter as tk
from tkinter import messagebox
from master_config import MOUSE_TRIGGER_CONFIG_FILE

def load_mouse_trigger_roi():
    """读取已保存的鼠标触发区坐标"""
    if os.path.exists(MOUSE_TRIGGER_CONFIG_FILE):
        try:
            with open(MOUSE_TRIGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if all(k in data for k in ("x", "y", "width", "height")):
                    return data
        except Exception:
            pass
    return None

def save_mouse_trigger_roi(roi):
    """保存鼠标触发区坐标到配置文件"""
    try:
        with open(MOUSE_TRIGGER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(roi, f, indent=2, ensure_ascii=False)
        print(f"[配置] 鼠标触发区已保存: x={roi['x']}, y={roi['y']}, w={roi['width']}, h={roi['height']}")
    except Exception as e:
        print(f"[错误] 保存鼠标触发区失败: {e}")

class MouseTriggerSelector:
    """全屏半透明鼠标触发区框选工具（专门用于框选【下一题】等按钮热区）"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("框选【下一题】鼠标触发区域")
        
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

        sw = self.root.winfo_screenwidth()
        self.canvas.create_text(
            sw // 2,
            60,
            text="【设置鼠标触发区】按住鼠标左键在屏幕上拖拽框选【下一题】按钮区域\n"
                 "只要鼠标落在或点击此区域，系统将全自动延时抓取题目！\n"
                 "框选完成后松开鼠标，按【回车键 Enter】保存，按【Esc】取消",
            fill="#00ffcc",
            font=("Microsoft YaHei", 15, "bold"),
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
            outline="#00ffcc", width=3, fill="white"
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
            mid_x, mid_y, text=info, fill="#00ffcc", font=("Microsoft YaHei", 12, "bold")
        )

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        width = x2 - x1
        height = y2 - y1

        # 按钮可能较小，允许大于 10x10 的矩形
        if width >= 10 and height >= 10:
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
                text=f"【下一题】触发热区已选定 ({width}x{height})\n按【回车键 Enter】确认保存",
                fill="#00ff00", font=("Microsoft YaHei", 13, "bold"), justify=tk.CENTER
            )

    def on_confirm(self, event=None):
        if self.selected_roi:
            save_mouse_trigger_roi(self.selected_roi)
            self.root.destroy()
        else:
            messagebox.showwarning("提示", "请先按住鼠标左键在【下一题】按钮上拖拽选出一个有效区域！")

    def on_cancel(self, event=None):
        self.selected_roi = None
        self.root.destroy()

    def select(self):
        self.root.mainloop()
        return self.selected_roi

def main():
    print("=" * 60)
    print("   【主电脑】设置【下一题】鼠标触发区域可视化工具")
    print("=" * 60)
    print("使用说明：")
    print("1. 屏幕将进入半透明框选模式；")
    print("2. 按住鼠标左键在屏幕上的「下一题」按钮（或任何期望落入触发的区域）画框；")
    print("3. 松开鼠标后，按【回车键 Enter】即可保存生效；")
    print("4. 后台服务将自动热加载，无需手动重启！")
    print("=" * 60 + "\n")

    selector = MouseTriggerSelector()
    roi = selector.select()
    if roi:
        print(f"\n✅ 鼠标触发区设置成功！")
        print(f"坐标: x={roi['x']}, y={roi['y']}, w={roi['width']}, h={roi['height']}")
        print("以后只要鼠标落入或点击此区域，后台将全自动在 0.7 秒后截屏并上传！\n")
    else:
        print("\n[提示] 操作已取消，保持原有配置不变。")

if __name__ == "__main__":
    main()
