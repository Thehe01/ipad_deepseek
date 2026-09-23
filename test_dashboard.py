"""
【iPhone 手机常亮看板 · 本地扫码测试工具】
无需启动辅助电脑，直接在当前主机上生成看板二维码与模拟各题型推送！

功能：
1. 本地启动 iPhone 看板 HTTP 服务（默认端口 8080），在终端直接呈现清晰扫码二维码与局域网网址。
2. 手机 Safari 扫码即开、常亮不息屏显示题目。
3. 模拟各题型推送（单选、连排题、Java算法、Python算法、简答题等）。
4. 电脑端不弹出浏览器与写字板，纯净静默运行，支持全局热键静默存入剪切板。
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
import webbrowser
import threading
import urllib.request

# 引入项目模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "secondary_pc"))
sys.path.insert(0, os.path.join(BASE_DIR, "master_pc"))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from secondary_server import SecondaryServer, _extract_code_blocks
from master_main import ClipboardServer

# ── Win32 原生剪切板工具（64位完全兼容） ─────────────────────
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_u32.OpenClipboard.argtypes = [ctypes.c_void_p]
_u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_u32.SetClipboardData.restype = ctypes.c_void_p
_k32.GlobalAlloc.restype = ctypes.c_void_p
_k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalLock.argtypes = [ctypes.c_void_p]
_k32.GlobalUnlock.argtypes = [ctypes.c_void_p]


def _write_clipboard(text):
    """将文本写入 Windows 剪切板（UTF-16LE，64位完全兼容）。"""
    try:
        # 重试 5 次，以防其他窗口占用剪切板
        for _ in range(5):
            if _u32.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            return False

        try:
            _u32.EmptyClipboard()
            data = text.encode("utf-16le") + b"\x00\x00"
            h_mem = _k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not h_mem:
                return False
            p_mem = _k32.GlobalLock(h_mem)
            if not p_mem:
                return False
            ctypes.memmove(p_mem, data, len(data))
            _k32.GlobalUnlock(h_mem)
            res = _u32.SetClipboardData(13, h_mem)      # CF_UNICODETEXT
            return bool(res)
        finally:
            _u32.CloseClipboard()
    except Exception as e:
        print(f"[剪切板错误] {e}")
        return False


# 全局缓存最新代码
_latest_code = ""
_hotkey_running = True

# 预设测试数据
PRESET_ANSWERS = {
    "1": (
        "单选题（题号与答案同行同格式呈现，舒适自然字体）",
        "【第1题】 C"
    ),
    "2": (
        "多题连排（题号与答案同行同格式清单，无荧光）",
        "【第1题】 A\n【第2题】 D\n【第3题】 B\n【第4题】 C\n【第5题】 True"
    ),
    "3": (
        "Java 编程题（题号置顶 + 完整换行缩进 + 自动写入剪切板）",
        "【第2题】完整 Java 源代码如下：\n"
        "```java\n"
        "import java.util.*;\n\n"
        "public class Solution {\n"
        "    public int maxSubArray(int[] nums) {\n"
        "        int maxSum = nums[0];\n"
        "        int curSum = nums[0];\n"
        "        for (int i = 1; i < nums.length; i++) {\n"
        "            curSum = Math.max(nums[i], curSum + nums[i]);\n"
        "            maxSum = Math.max(maxSum, curSum);\n"
        "        }\n"
        "        return maxSum;\n"
        "    }\n"
        "}\n"
        "```"
    ),
    "4": (
        "Python 算法题（题号置顶 + 语法高亮 + 自动写入剪切板）",
        "【第3题】完整 Python 源代码如下：\n"
        "```python\n"
        "def two_sum(nums: list[int], target: int) -> list[int]:\n"
        "    lookup = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in lookup:\n"
        "            return [lookup[target - x], i]\n"
        "        lookup[x] = i\n"
        "    return []\n"
        "```"
    ),
    "5": (
        "问答题 / 简答题（概念要点排版）",
        "【第4题】简答题：简述 TCP 为什么需要三次握手？\n\n"
        "1. **防止历史重复连接的初始化**：若客户端发送的旧 SYN 报文因网络阻塞延迟到达，服务端回复 SYN+ACK 后，客户端可根据序列号识别并发送 RST 中止，避免建立无效连接。\n\n"
        "2. **同步双方初始序列号 (ISN)**：TCP 是全双工可靠传输，双方必须明确告知并互相确认对方的数据起始序号，这一往一返至少需要 3 次交互。\n\n"
        "3. **避免服务端资源浪费**：若只有两次握手，旧的连接请求到达服务端便立即建立连接，服务端会盲目开辟资源等待数据，造成严重资源泄露。"
    ),
    "6": (
        "综合多小题（含选择与完整代码块）",
        "【第1题】B\n\n"
        "【第2题】D\n\n"
        "【第3题】完整实现代码：\n"
        "```cpp\n"
        "#include <vector>\n"
        "#include <algorithm>\n\n"
        "int search(const std::vector<int>& nums, int target) {\n"
        "    int l = 0, r = nums.size() - 1;\n"
        "    while (l <= r) {\n"
        "        int mid = l + (r - l) / 2;\n"
        "        if (nums[mid] == target) return mid;\n"
        "        if (nums[mid] < target) l = mid + 1;\n"
        "        else r = mid - 1;\n"
        "    }\n"
        "    return -1;\n"
        "}\n"
        "```"
    ),
    "9": (
        "LeetCode 138 复制带随机指针的链表（实测题还原验证）",
        "【第138题】复制带随机指针的链表\n\n"
        "```java\n"
        "class Solution {\n"
        "    public Node copyRandomList(Node head) {\n"
        "        if (head == null) {\n"
        "            return null;\n"
        "        }\n"
        "        Node cur = head;\n"
        "        while (cur != null) {\n"
        "            Node copy = new Node(cur.val);\n"
        "            copy.next = cur.next;\n"
        "            cur.next = copy;\n"
        "            cur = copy.next;\n"
        "        }\n"
        "        cur = head;\n"
        "        while (cur != null) {\n"
        "            if (cur.random != null) {\n"
        "                cur.next.random = cur.random.next;\n"
        "            }\n"
        "            cur = cur.next.next;\n"
        "        }\n"
        "        Node newHead = head.next;\n"
        "        cur = head;\n"
        "        while (cur != null) {\n"
        "            Node copy = cur.next;\n"
        "            cur.next = copy.next;\n"
        "            if (copy.next != null) {\n"
        "                copy.next = copy.next.next;\n"
        "            }\n"
        "            cur = cur.next;\n"
        "        }\n"
        "        return newHead;\n"
        "    }\n"
        "}\n"
        "```"
    ),
}


def _get_clipboard_content(text):
    """根据题目内容提取剪切板文本：代码题提取纯净可编译运行的代码；其他题型提取完整答案。"""
    if not text:
        return ""
    code = _extract_code_blocks(text)
    if code and code.strip():
        return code.strip()
    return text.strip()


def _trigger_hotkey_copy(trigger_name):
    """快捷键触发时：将当前题目的内容直接拷贝进剪切板，并打印提示。"""
    global _latest_content
    if _latest_content and _latest_content.strip():
        ok = _write_clipboard(_latest_content)
        if ok:
            print(f"\n>> [{trigger_name} 触发成功] ✅ 最新题目内容已拷贝进系统剪切板（共 {len(_latest_content)} 字符）！直接 Ctrl+V 粘贴即可！\n", flush=True)
        else:
            print(f"\n>> [{trigger_name} 触发警告] 写入剪切板失败！\n", flush=True)
    else:
        print(f"\n>> [{trigger_name}] 当前尚未模拟题目，请先在菜单中输入 1-9 模拟题目！\n", flush=True)


def _hotkey_listener_loop():
    """实时监听全局热键（双击 Ctrl、Ctrl+Q、F9）"""
    global _hotkey_running
    u32 = ctypes.windll.user32
    u32.GetAsyncKeyState.restype = ctypes.c_short

    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
    VK_SHIFT = 0x10
    VK_ALT = 0x12
    VK_F9 = 0x78
    VK_Q = 0x51

    last_ctrl = False
    last_ctrl_time = 0.0
    f9_prev = False
    ctrl_q_prev = False

    while _hotkey_running:
        try:
            ctrl = bool((u32.GetAsyncKeyState(VK_CONTROL) & 0x8000) or
                        (u32.GetAsyncKeyState(VK_LCONTROL) & 0x8000) or
                        (u32.GetAsyncKeyState(VK_RCONTROL) & 0x8000))
            shift = bool(u32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
            alt = bool(u32.GetAsyncKeyState(VK_ALT) & 0x8000)
            f9 = bool(u32.GetAsyncKeyState(VK_F9) & 0x8000)
            q = bool(u32.GetAsyncKeyState(VK_Q) & 0x8000)

            # 1. Ctrl + Q
            ctrl_q = ctrl and q
            if ctrl_q and not ctrl_q_prev:
                _trigger_hotkey_copy("快捷键 Ctrl+Q")
            ctrl_q_prev = ctrl_q

            # 2. 单键 F9
            if f9 and not f9_prev:
                _trigger_hotkey_copy("按键 F9")
            f9_prev = f9

            # 3. 双击 Ctrl（宽松时间窗口 0.03s ~ 0.85s，且无 Shift/Alt 干扰）
            if ctrl and not last_ctrl:
                now = time.time()
                if not shift and not alt and not q:
                    diff = now - last_ctrl_time
                    if 0.03 < diff <= 0.85:
                        last_ctrl_time = 0.0
                        _trigger_hotkey_copy("双击 Ctrl")
                    else:
                        last_ctrl_time = now
            last_ctrl = ctrl

        except Exception:
            pass

        time.sleep(0.015)


def main():
    global _latest_content, _hotkey_running

    print("=" * 68)
    print("        【 📱 iPhone 手机常亮看板 · 本地扫码测试工具 】")
    print("=" * 68)
    print("  * 无需启动第二台电脑，直接在本机测试手机端常亮看板显示！")
    print("  * 用 iPhone 相机 / 微信直接扫描下方终端二维码，即可打开看板。")
    print("  * 电脑端纯净运行，不弹出写字板与浏览器，不占用桌面空间。")
    print("  * 支持全局热键：【双击 Ctrl】/【Ctrl+Q】/【F9】静默存入剪切板。")
    print("=" * 68 + "\n")

    # 1. 检查或启动剪切板接收器 (端口 8081)
    clip_server = None
    try:
        clip_server = ClipboardServer(port=8081)
        clip_server.start()
    except Exception:
        print("[提示] 主电脑后台服务正在运行中（端口 8081），内容推送将直接同步至主电脑后台！")
        clip_server = None

    # 2. 启动看板服务端 (端口 8080)
    dash_server = SecondaryServer(port=8080, clipboard_server_port=8081)
    dash_server._master_ip = "127.0.0.1"

    try:
        dash_server.start()
    except Exception as e:
        print(f"[错误] 看板端口 8080 启动失败: {e}")
        if clip_server:
            clip_server.stop()
        return

    # 启动快捷键监听后台线程
    t_hotkey = threading.Thread(target=_hotkey_listener_loop, daemon=True)
    t_hotkey.start()

    print("\n" + "-" * 68)
    print("【操作指令菜单】")
    print("  [1] 模拟【单选答案】(如：【第1题】 C)")
    print("  [2] 模拟【多题连排】(如：【第1题】 A ... 【第5题】 True)")
    print("  [3] 模拟【Java代码题】(完整缩进换行 Java 算法)")
    print("  [4] 模拟【Python代码题】(完整缩进换行 Python 算法)")
    print("  [5] 模拟【问答/简答题】(三次握手概念要点自然排版)")
    print("  [6] 模拟【综合大题】(含选择题与完整代码块)")
    print("  [7] 模拟【解题中等待状态】(黄色动态呼吸指示灯)")
    print("  [8] 手动输入自定义文本发送")
    print("  [9] 模拟【LeetCode 138】(链表深拷贝实测题，带完整换行代码)")
    print("  [r] 重新显示手机扫码二维码与网址")
    print("  [c] 快捷键模拟：手动将本题内容静默写入系统剪切板")
    print("  [q] 退出测试")
    print("-" * 68 + "\n")

    try:
        while True:
            cmd = input("请输入测试指令 (1-9 / r / c / q): ").strip().lower()

            if cmd == "q":
                break

            elif cmd == "r":
                dash_server.print_qr_and_link()

            elif cmd == "c":
                if _latest_content:
                    _write_clipboard(_latest_content)
                    print(f"\n>> [剪切板] ✅ 已将当前题目内容拷贝进 Windows 剪切板（{len(_latest_content)} 字符）！\n")
                else:
                    print("\n>> [提示] 当前尚未生成题目，请先输入 1-9 模拟题目！\n")

            elif cmd in PRESET_ANSWERS:
                title, content = PRESET_ANSWERS[cmd]
                print(f"\n>> 正在推送：{title}")
                dash_server.post_answer(content)

                # 缓存当前题目内容（提取代码纯净版或完整文字），默认绝不改动系统剪切板！
                _latest_content = _get_clipboard_content(content)

                # 同步推送至端口 8081（若后台 master_main 运行中）
                try:
                    req_data = _latest_content.encode("utf-8")
                    req = urllib.request.Request(
                        "http://127.0.0.1:8081/api/clipboard",
                        data=req_data,
                        headers={"Content-Length": str(len(req_data))}
                    )
                    urllib.request.urlopen(req, timeout=1)
                except Exception:
                    pass

                print(">> 看板已更新！可在手机常亮看板中实时查看效果。")
                print(">> [剪切板状态] ⚪ 默认未修改系统剪切板（保持自由使用）。")
                print(">> [提取说明]   👉 如需拷贝到电脑剪切板，按【双击 Ctrl】、【Ctrl+Q】或【F9】立即存入！\n")

            elif cmd == "7":
                print("\n>> 正在模拟：解题中状态...")
                dash_server.set_status("🟡 收到主电脑新题，正在调用 DeepSeek R1 解题...")
                print(">> 看板状态已切换为解题中！\n")

            elif cmd == "8":
                print("\n请输入你想推送到看板的内容（输入单行 END 或按 Ctrl+Z 回车结束）：")
                lines = []
                try:
                    while True:
                        line = input()
                        if line.strip() == "END":
                            break
                        lines.append(line)
                except EOFError:
                    pass
                custom_text = "\n".join(lines).strip()
                if custom_text:
                    dash_server.post_answer(custom_text)
                    _latest_content = _get_clipboard_content(custom_text)
                    print(">> 自定义内容已推送到看板！")
                    print(">> [剪切板状态] ⚪ 默认未修改系统剪切板。按下【双击 Ctrl】/【Ctrl+Q】/【F9】立即拷贝！\n")
                else:
                    print(">> [提示] 内容为空，未发送。\n")

            else:
                print("未知指令，请输入 1-9, r, c 或 q。")

    except KeyboardInterrupt:
        print("\n[退出] 用户中断...")
    finally:
        print("[清理] 正在停止本地服务...")
        _hotkey_running = False
        dash_server.stop()
        if clip_server:
            clip_server.stop()
        print("[完成] 本地测试服务已安全退出。")


if __name__ == "__main__":
    main()

