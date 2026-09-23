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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "master_pc"))

from master_main import grab_roi, _ensure_input_desktop
from screen_monitor import ScreenMonitor, _get_cursor_pos, _get_screen_size
import numpy as np
from PIL import Image

_ensure_input_desktop()


def main():
    print("=" * 68, flush=True)
    print("      【本地截屏与右上角鼠标停留截题 · 验证工具】", flush=True)
    print("=" * 68, flush=True)

    sw, sh = _get_screen_size()
    mx, my = _get_cursor_pos()
    print(f"  * 屏幕物理分辨率: {sw} x {sh}", flush=True)
    print(f"  * 当前鼠标坐标:   ({mx}, {my})", flush=True)
    print(f"  * 右上角触发区域: X: [{sw - 120} ~ {sw}], Y: [0 ~ 80]", flush=True)
    print("=" * 68 + "\n", flush=True)

    # 1. 基础全屏 / ROI 截图验证
    print(">> [步骤 1/2] 正在测试原生显存截图能力...", flush=True)
    test_roi = {"x": 0, "y": 0, "width": sw, "height": sh}
    t0 = time.perf_counter()
    img = grab_roi(test_roi)
    t1 = time.perf_counter()

    arr = np.array(img)
    cost_ms = (t1 - t0) * 1000
    save_path = os.path.join(BASE_DIR, "temp_test_screenshot.png")
    img.save(save_path)

    mean_val = float(arr.mean())
    max_val = int(arr.max())
    std_val = float(arr.std())

    print(f"   - 截屏耗时:   {cost_ms:.2f} ms", flush=True)
    print(f"   - 图片尺寸:   {img.size[0]} x {img.size[1]} ({img.mode})", flush=True)
    print(f"   - 像素统计:   均值={mean_val:.2f}, 最大值={max_val}, 标准差={std_val:.2f}", flush=True)
    print(f"   - 图片已保存: {save_path}", flush=True)

    # 严密校验画面有效性：彻底防范全黑图 / 假通过
    is_valid = (mean_val >= 3.0 and max_val >= 10 and std_val >= 0.8)
    if not is_valid:
        print(f"\n   ❌ 【校验失败】截取到的画面为纯黑屏或全空图 (均值={mean_val:.2f}, 最大值={max_val})！", flush=True)
        print("      可能原因：当前屏幕处于锁屏状态、桌面受隔离保护或 GDI 显存拷贝异常。", flush=True)
        sys.exit(1)

    print("   -> ✅ [通过] 画面校验正常（有效色彩与界面元素，非纯黑屏）！\n", flush=True)

    if "--check-only" in sys.argv:
        print(">> 已指定 --check-only 参数，且画面真实有效，测试顺利通过！", flush=True)
        return

    # 2. 交互式鼠标右上角停留 0.3s 截题验证
    print(">> [步骤 2/2] 正在启动右上角鼠标停留 (0.3s) 感知引擎...", flush=True)
    print("   ★ 请现在将鼠标光标甩到【屏幕右上角】并停顿 0.3 秒以测试触发！", flush=True)
    print("   (按 Ctrl+C 可跳过此步骤)\n", flush=True)

    trigger_results = []

    def on_detected(captured_img, is_manual=False, trigger_name=""):
        trigger_results.append(captured_img)
        save_trigger_path = os.path.join(BASE_DIR, "temp_test_mouse_trigger.png")
        captured_img.save(save_trigger_path)
        print("\n\n" + "#" * 60, flush=True)
        print(f"   ★ 【触发成功！】检测到鼠标在屏幕右上角停留达到 0.3 秒！", flush=True)
        print(f"   ★ 题目已捕获完成！尺寸: {captured_img.size}", flush=True)
        print(f"   ★ 截图已保存至: {save_trigger_path}", flush=True)
        print("#" * 60 + "\n", flush=True)
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
        start_wait = time.time()
        last_print = 0.0
        while len(trigger_results) == 0:
            time.sleep(0.05)
            now = time.time()
            cx, cy = _get_cursor_pos()
            in_corner = (cx >= sw - 120) and (0 <= cy <= 80)
            
            if now - last_print >= 0.2:
                last_print = now
                if in_corner:
                    status = "【已进入右上角！保持停顿 0.3s...】"
                else:
                    dx = max(0, (sw - 120) - cx)
                    dy = max(0, cy - 80)
                    status = f"距离右上角差 X: {dx}px, Y: {dy}px"
                sys.stdout.write(f"\r   [光标跟踪] 坐标: ({cx:4d}, {cy:4d}) | {status}   ")
                sys.stdout.flush()

            elapsed = now - start_wait
            if elapsed >= 30:
                print("\n   [提示] 30 秒内未检测到移入右上角，退出交互等待。", flush=True)
                break
    except KeyboardInterrupt:
        print("\n   [跳过] 用户中断交互测试。", flush=True)
    finally:
        monitor.stop()

    print("\n" + "=" * 68, flush=True)
    if trigger_results:
        print("   【验证完毕】截屏功能与右上角鼠标停留触发均 100% 正常生效！", flush=True)
    else:
        print("   【验证完毕】截屏底层已验证成功，可在主程序运行时直接使用右上角停留触发！", flush=True)
    print("=" * 68 + "\n", flush=True)


if __name__ == "__main__":
    main()
