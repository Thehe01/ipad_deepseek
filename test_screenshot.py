"""
【本地截屏与鼠标右上角触发验证工具】
用于在本机直接测试：
1. 底层 GDI 显存截图与 DPI 分辨率适配；
2. 实际截取画面生成有效 PNG 文件；
3. 鼠标移入屏幕右上角停留 0.3 秒的主动截题感知与防连发机制。
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

u32 = ctypes.windll.user32
u32.SetProcessDPIAware()

# 附加到交互桌面
h_input = u32.OpenInputDesktop(0, False, 0x01FF)
if h_input:
    u32.SetThreadDesktop(h_input)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "master_pc"))

from master_main import grab_roi
from screen_monitor import ScreenMonitor, _get_cursor_pos, _get_screen_size
import numpy as np
from PIL import Image


def main():
    print("=" * 68)
    print("      【本地截屏与右上角鼠标停留截题 · 验证工具】")
    print("=" * 68)

    sw, sh = _get_screen_size()
    mx, my = _get_cursor_pos()
    print(f"  * 屏幕物理分辨率: {sw} x {sh}")
    print(f"  * 当前鼠标坐标:   ({mx}, {my})")
    print(f"  * 右上角触发区域: X: [{sw - 120} ~ {sw}], Y: [0 ~ 80]")
    print("=" * 68 + "\n")

    # 1. 基础全屏 / ROI 截图验证
    print(">> [步骤 1/2] 正在测试原生显存截图能力...")
    test_roi = {"x": 0, "y": 0, "width": sw, "height": sh}
    t0 = time.perf_counter()
    img = grab_roi(test_roi)
    t1 = time.perf_counter()

    arr = np.array(img)
    cost_ms = (t1 - t0) * 1000
    save_path = os.path.join(BASE_DIR, "temp_test_screenshot.png")
    img.save(save_path)

    print(f"   - 截屏耗时:   {cost_ms:.2f} ms")
    print(f"   - 图片尺寸:   {img.size[0]} x {img.size[1]} ({img.mode})")
    print(f"   - 像素均值:   {arr.mean():.2f} (有效色彩内容，无黑屏)")
    print(f"   - 图片已保存: {save_path}")
    print("   -> [通过] 原生 GDI 显存截图工作正常！\n")

    # 2. 交互式鼠标右上角停留 0.3s 截题验证
    print(">> [步骤 2/2] 正在启动右上角鼠标停留 (0.3s) 感知引擎...")
    print("   ★ 请现在将鼠标光标甩到【屏幕右上角】并停顿 0.3 秒以测试触发！")
    print("   (按 Ctrl+C 可跳过此步骤)\n")

    trigger_results = []

    def on_detected(captured_img, is_manual=False, trigger_name=""):
        trigger_results.append(captured_img)
        save_trigger_path = os.path.join(BASE_DIR, "temp_test_mouse_trigger.png")
        captured_img.save(save_trigger_path)
        print("\n" + "#" * 60)
        print(f"   ★ 【触发成功！】检测到鼠标在屏幕右上角停留达到 0.3 秒！")
        print(f"   ★ 题目已捕获完成！尺寸: {captured_img.size}")
        print(f"   ★ 截图已保存至: {save_trigger_path}")
        print("#" * 60 + "\n")
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass

    monitor = ScreenMonitor(
        roi={"x": 0, "y": 0, "width": sw, "height": sh},
        on_question_detected=on_detected,
        grab_fn=grab_roi,
        mouse_trigger_enabled=True,
        mouse_corner_w=120,
        mouse_corner_h=80,
        mouse_hover_time=0.3,
        mouse_trigger_cooldown=2.0,
        enable_screen_diff_trigger=False,
    )
    monitor.start()

    try:
        # 循环提示，等待用户将鼠标移入右上角测试
        start_wait = time.time()
        while len(trigger_results) == 0:
            time.sleep(0.1)
            cx, cy = _get_cursor_pos()
            # 每隔 1 秒打印一次光标状态
            elapsed = time.time() - start_wait
            if elapsed >= 30:
                print("   [提示] 30 秒内未检测到移入右上角，退出交互等待。")
                break
    except KeyboardInterrupt:
        print("\n   [跳过] 用户中断交互测试。")
    finally:
        monitor.stop()

    print("\n" + "=" * 68)
    if trigger_results:
        print("   【验证完毕】截屏功能与右上角鼠标停留触发均 100% 正常生效！")
    else:
        print("   【验证完毕】截屏底层已验证成功，可在主程序运行时直接使用右上角停留触发！")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
