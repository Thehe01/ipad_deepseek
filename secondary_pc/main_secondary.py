import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
from secondary_config import HTTP_PORT, DISCOVERY_PORT, ENABLE_R1


from secondary_server import SecondaryServer
from deepseek_bot import DeepSeekBot

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def main():
    print("=" * 65)
    print("       【辅助电脑端】DeepSeek R1 解题与 iPhone 看板服务")
    print("=" * 65)
    print(f"[配置] 默认模型: {'DeepSeek-R1 (深度思考)' if ENABLE_R1 else 'DeepSeek-V3 (普通模式)'}")
    print(f"[服务] Web 看板端口: {HTTP_PORT} | UDP 广播发现端口: {DISCOVERY_PORT}")
    print("=" * 65)

    bot = None
    server = None

    def on_new_answer(answer_text):
        if server:
            server.post_answer(answer_text)

    def on_status_change(status_text):
        if server:
            server.set_status(status_text)

    def on_question_from_master(image_path):
        print(f"[调度中心] 接收到主电脑新题，正在交由 DeepSeek 处理...")
        if bot:
            bot.send_question(image_path)

    # 1. 启动接收与看板服务
    server = SecondaryServer(
        port=HTTP_PORT,
        discovery_port=DISCOVERY_PORT,
        on_question_received=on_question_from_master
    )
    server.start()

    # 2. 启动 DeepSeek 自动化浏览器
    bot = DeepSeekBot(
        on_answer_callback=on_new_answer,
        on_status_callback=on_status_change
    )
    try:
        server.set_status("正在启动 Chrome 浏览器...")
        bot.start()
        server.set_status("🟢 辅助电脑准备就绪，正在等待主电脑传题...")
    except Exception as e:
        print(f"\n[错误] 启动 DeepSeek 浏览器失败: {e}")
        server.stop()
        return

    print("\n" + "#" * 65)
    print("【辅助电脑服务运行中】")
    print("1. 请用 iPhone 扫描上方二维码打开常亮看板；")
    print("2. 保持本窗口运行，主电脑截题后将自动推送至本端求解。")
    print("3. 按 Ctrl+C 可停止服务。")
    print("#" * 65 + "\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[正在退出] 正在清理资源...")
    finally:
        if bot:
            bot.stop()
        if server:
            server.stop()
        print("[已退出] 辅助电脑端已安全停止。")

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
        print(f"【辅助电脑端运行异常】: {e}")
        traceback.print_exc()
        print("!" * 65)
        try:
            input("\n按回车键 (Enter) 退出...")
        except Exception:
            pass
    except KeyboardInterrupt:
        pass
    sys.exit(exit_code)
