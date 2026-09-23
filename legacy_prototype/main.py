import os
import sys
import time
import argparse
import keyboard

# 保证 Windows 控制台 UTF-8 打印不乱码
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import (
    HOTKEY_TRIGGER,
    HOTKEY_PAUSE,
    DEFAULT_PROMPT,
    ENABLE_R1,
    WEB_SERVER_PORT
)
from roi_selector import get_roi_interactive
from screen_monitor import ScreenMonitor
from deepseek_bot import DeepSeekBot
from web_server import DashboardServer

def parse_args():
    parser = argparse.ArgumentParser(description="iPad 腾讯会议屏幕监控 + DeepSeek R1 自动化解题助手")
    parser.add_argument("--reselect", action="store_true", help="强制重新框选屏幕监控区域")
    return parser.parse_args()

def main():
    args = parse_args()

    print("=" * 65)
    print("      iPad 腾讯会议题目监控 + DeepSeek R1 自动化解题系统")
    print("=" * 65)
    print(f"[配置] 默认模型: {'DeepSeek-R1 (深度思考)' if ENABLE_R1 else 'DeepSeek-V3 (普通模式)'}")
    print(f"[快捷键] {HOTKEY_TRIGGER.upper()}: 手动立即截题并发送")
    print(f"[快捷键] {HOTKEY_PAUSE.upper()}: 暂停 / 继续自动监控")
    print("=" * 65)

    # 1. 启动 iPhone 实时大字看板 Web 服务
    server = DashboardServer(port=WEB_SERVER_PORT)
    try:
        server.start()
    except Exception as e:
        print(f"[提示] 看板服务启动提示 (端口可能被占用): {e}")

    # 回调函数定义
    def on_new_answer(answer_text):
        server.post_answer(answer_text)

    def on_status_change(status_text):
        server.set_status(status_text)

    # 2. 优先拉起 DeepSeek 自动化浏览器（让用户立即看到浏览器弹出）
    bot = DeepSeekBot(
        on_answer_callback=on_new_answer,
        on_status_callback=on_status_change
    )
    try:
        server.set_status("正在启动 Chrome 浏览器...")
        bot.start()
        server.set_status("🟢 浏览器就绪，正在准备监控")
    except Exception as e:
        print(f"\n[错误] 启动 Chrome 自动化浏览器失败: {e}")
        server.stop()
        return

    # 3. 确定或框选监控区域
    try:
        roi = get_roi_interactive(force_reselect=args.reselect)
    except Exception as e:
        print(f"\n[错误] 获取监控区域异常: {e}")
        server.stop()
        bot.stop()
        return

    # 4. 题目检测回调函数
    def on_question_ready(img_path, is_manual=False):
        trigger_type = "手动快捷键触发" if is_manual else "画面变动自动捕获"
        print(f"\n>>> [{trigger_type}] 正在将题目投递给 DeepSeek R1 ...")
        server.set_status("🟡 正在向 DeepSeek 发送题目...")
        bot.send_question(img_path)

    # 5. 初始化屏幕监控器
    monitor = ScreenMonitor(roi, on_question_detected=on_question_ready)

    # 6. 注册全局快捷键
    def handle_toggle_pause():
        monitor.toggle_pause()
        server.set_status("🔴 监控已暂停" if monitor.is_paused else "🟢 监控中 (等待切题)")

    try:
        keyboard.add_hotkey(HOTKEY_TRIGGER, monitor.trigger_manual)
        keyboard.add_hotkey(HOTKEY_PAUSE, handle_toggle_pause)
        print(f"\n[快捷键就绪] 全局热键 [{HOTKEY_TRIGGER.upper()}] 与 [{HOTKEY_PAUSE.upper()}] 已激活。")
    except Exception as e:
        print(f"[提示] 快捷键注册受限 (可能需要管理员权限): {e}")

    # 7. 启动监控线程
    monitor.start()
    server.set_status("🟢 正在监控题目屏幕...")

    print("\n" + "#" * 65)
    print("【正在监控中】请保持腾讯会议窗口可见！")
    print(f"- iPhone 手机请打开: {server.get_url()}")
    print(f"- 当 iPad 翻页切题后，系统将等待约 1.5 秒画面稳定并自动发送解题。")
    print(f"- 随时可按 [{HOTKEY_TRIGGER.upper()}] 强制对当前题提问。")
    print(f"- 随时可按 [{HOTKEY_PAUSE.upper()}] 暂停/恢复监听。")
    print(f"- 按 Ctrl+C 可终止程序。")
    print("#" * 65 + "\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[正在退出] 用户主动终止，正在清理资源...")
    finally:
        monitor.stop()
        bot.stop()
        server.stop()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        print("[已退出] 系统已安全停止。")


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except SystemExit as se:
        exit_code = se.code if se.code is not None else 0
    except Exception as e:
        exit_code = 1
        import traceback
        print("\n" + "!" * 65)
        print(f"【程序执行异常】: {e}")
        traceback.print_exc()
        print("!" * 65)
        try:
            input("\n按回车键 (Enter) 退出...")
        except Exception:
            pass
    except KeyboardInterrupt:
        pass
    sys.exit(exit_code)

