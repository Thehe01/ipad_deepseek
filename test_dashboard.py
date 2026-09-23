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

# 引入项目模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "secondary_pc"))
sys.path.insert(0, os.path.join(BASE_DIR, "master_pc"))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from secondary_server import SecondaryServer

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
        "Java 编程题（题号置顶 + 完整换行缩进呈现）",
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
        "Python 算法题（题号置顶 + 语法高亮呈现）",
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


def main():
    print("=" * 68)
    print("        【 📱 iPhone 手机常亮看板 · 本地扫码测试工具 】")
    print("=" * 68)
    print("  * 无需启动第二台电脑，直接在本机测试手机端常亮看板显示！")
    print("  * 用 iPhone 相机 / 微信直接扫描下方终端二维码，即可打开看板。")
    print("  * 电脑端纯净运行，不弹出写字板与浏览器，不占用桌面空间。")
    print("  * 手机端常亮同步展示答案，主电脑不挂钩任何按键、不读写剪切板。")
    print("=" * 68 + "\n")

    # 启动看板服务端 (端口 8080)
    dash_server = SecondaryServer(port=8080)

    try:
        dash_server.start()
    except Exception as e:
        print(f"[错误] 看板端口 8080 启动失败: {e}")
        return

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
    print("  [q] 退出测试")
    print("-" * 68 + "\n")

    try:
        while True:
            cmd = input("请输入测试指令 (1-9 / r / q): ").strip().lower()

            if cmd == "q":
                break

            elif cmd == "r":
                dash_server.print_qr_and_link()

            elif cmd in PRESET_ANSWERS:
                title, content = PRESET_ANSWERS[cmd]
                print(f"\n>> 正在推送：{title}")
                dash_server.post_answer(content)
                print(">> 看板已更新！可在手机常亮看板中实时查看效果。\n")

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
                    print(">> 自定义内容已推送到看板！\n")
                else:
                    print(">> [提示] 内容为空，未发送。\n")

            else:
                print("未知指令，请输入 1-9, r 或 q。")

    except KeyboardInterrupt:
        print("\n[退出] 用户中断...")
    finally:
        print("[清理] 正在停止本地服务...")
        dash_server.stop()
        print("[完成] 本地测试服务已安全退出。")


if __name__ == "__main__":
    main()

