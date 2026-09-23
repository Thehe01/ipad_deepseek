import os
import sys
import json
import time
import socket
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# HTML 模板：针对 iPhone Safari 优化的 OLED 纯黑大字常亮看板
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>DeepSeek 实时大字看板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background-color: #000000;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Helvetica Neue", sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 20px 16px 40px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 8px 4px;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            background: #1c1c1e;
            border: 1px solid #2c2c2e;
            transition: all 0.3s ease;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #34c759;
            box-shadow: 0 0 10px #34c759;
        }
        .status-badge.busy .status-dot {
            background: #ff9f0a;
            box-shadow: 0 0 10px #ff9f0a;
            animation: pulse 1s infinite alternate;
        }
        @keyframes pulse { from { opacity: 0.4; } to { opacity: 1; } }

        .wakelock-indicator {
            font-size: 12px;
            color: #30d158;
            display: flex;
            align-items: center;
            gap: 4px;
            background: rgba(48, 209, 88, 0.12);
            padding: 4px 10px;
            border-radius: 12px;
        }

        /* 主答案卡片 */
        .answer-card {
            background: #111216;
            border: 1px solid #23252e;
            border-radius: 24px;
            padding: 24px 20px;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.8);
            margin-bottom: 24px;
            position: relative;
            overflow: hidden;
            transition: border-color 0.4s;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            color: #8e8e93;
            margin-bottom: 16px;
            letter-spacing: 0.5px;
        }
        .answer-content {
            min-height: 180px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }

        /* 针对单字母/数字选择题的特大字号样式 */
        .big-letter {
            font-size: 108px;
            font-weight: 900;
            color: #00ff88;
            text-shadow: 0 0 35px rgba(0, 255, 136, 0.45);
            line-height: 1.1;
            letter-spacing: 2px;
        }
        /* 中等长度文本答案 */
        .medium-answer {
            font-size: 32px;
            font-weight: 700;
            color: #00ff88;
            line-height: 1.4;
            text-align: left;
            word-break: break-word;
        }
        /* 原始输出容器：100% 原样保留 DeepSeek 的换行、空格、代码块与所有标点 */
        .raw-output {
            width: 100%;
            text-align: left;
            background: #000000;
            border: 1px solid #23252e;
            border-radius: 14px;
            padding: 16px;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Mono", Menlo, Consolas, Monaco, "PingFang SC", monospace;
            font-size: 17px;
            line-height: 1.6;
            color: #f0f6fc;
            white-space: pre-wrap;
            word-break: break-word;
            overflow-x: auto;
        }
        .raw-output.short {
            font-size: 48px;
            font-weight: 800;
            text-align: center;
            color: #00ff88;
            text-shadow: 0 0 25px rgba(0, 255, 136, 0.35);
            background: transparent;
            border: none;
            padding: 10px;
        }


        /* 历史记录 */
        .history-section {
            margin-top: auto;
        }
        .history-title {
            font-size: 13px;
            color: #636366;
            margin-bottom: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .history-item {
            background: #141416;
            border: 1px solid #202024;
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
        }
        .history-item .hist-ans {
            color: #30d158;
            font-weight: 600;
            max-width: 75%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .history-item .hist-time {
            color: #8e8e93;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="status-badge" id="statusBadge">
            <span class="status-dot"></span>
            <span id="statusText">等待题目...</span>
        </div>
        <div class="wakelock-indicator" id="wakeLockStatus">
            ⚡ 屏幕常亮已保持
        </div>
    </div>

    <!-- 最新答案展示区 -->
    <div class="answer-card" id="answerCard">
        <div class="card-header">
            <span>最新解题结果</span>
            <span id="answerTime">--:--:--</span>
        </div>
        <div class="answer-content" id="answerContent">
            <div style="color: #636366; font-size: 18px;">暂无答题记录<br>请在 iPad 上翻页或按 F8</div>
        </div>
    </div>

    <!-- 历史记录 -->
    <div class="history-section">
        <div class="history-title">历史答题流</div>
        <div id="historyList"></div>
    </div>

    <script>
        // 1. 强制 iOS Safari 屏幕常亮 (WakeLock API)
        let wakeLock = null;
        async function enableWakeLock() {
            try {
                if ('wakeLock' in navigator) {
                    wakeLock = await navigator.wakeLock.request('screen');
                    document.getElementById('wakeLockStatus').innerText = '⚡ 屏幕常亮已保持';
                }
            } catch (err) {
                console.log('WakeLock error:', err);
            }
        }
        enableWakeLock();
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') enableWakeLock();
        });
        // 点击任意位置再次激活 WakeLock
        document.body.addEventListener('click', enableWakeLock);

        // 2. 轮询最新状态与答案
        let lastAnswerId = -1;
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                // 更新状态标签
                const badge = document.getElementById('statusBadge');
                const text = document.getElementById('statusText');
                text.innerText = data.status || '监控中';
                if (data.status && data.status.includes('解题')) {
                    badge.classList.add('busy');
                } else {
                    badge.classList.remove('busy');
                }

                // 检查是否有新答案
                if (data.answer_id && data.answer_id !== lastAnswerId) {
                    lastAnswerId = data.answer_id;
                    renderAnswer(data.latest_answer, data.timestamp);
                    if (data.history) renderHistory(data.history);
                    
                    // 震动提示
                    if (navigator.vibrate) navigator.vibrate([150, 80, 150]);
                }
            } catch (e) {
                console.error('Fetch error:', e);
            }
        }

        function renderAnswer(answer, timestamp) {
            const container = document.getElementById('answerContent');
            document.getElementById('answerTime').innerText = timestamp || '';

            if (!answer || answer.trim() === '') {
                container.innerHTML = '<div style="color: #636366; font-size: 18px;">等待模型输出...</div>';
                return;
            }

            const clean = answer.trim();

            // 按照 DeepSeek 的答案 100% 原样输出（保留原始换行、Markdown 代码块、空格与符号，不做任何删改与拆分）
            if (clean.length <= 25 && !clean.includes('\n')) {
                // 极简单行短答案（如选择题【第1题】C 或 1. C），大字号居中呈现
                container.innerHTML = `<div class="raw-output short">${escapeHtml(clean)}</div>`;
            } else {
                // 多行题目/代码题：完全原样呈现，完整保留语言标签、代码围栏、缩进与全部标点
                container.innerHTML = `<div class="raw-output">${escapeHtml(clean)}</div>`;
            }
        }


        function renderHistory(history) {
            const list = document.getElementById('historyList');
            list.innerHTML = '';
            // 倒序展示最近 5 条
            const items = history.slice(-5).reverse();
            items.forEach(item => {
                const el = document.createElement('div');
                el.className = 'history-item';
                el.innerHTML = `
                    <span class="hist-ans">${escapeHtml(item.answer)}</span>
                    <span class="hist-time">${item.time}</span>
                `;
                list.appendChild(el);
            });
        }

        function escapeHtml(str) {
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        }

        // 每 800ms 刷新一次
        setInterval(fetchStatus, 800);
        fetchStatus();
    </script>
</body>
</html>
"""

class DashboardServer:
    """局域网实时大字看板 HTTP 服务"""
    def __init__(self, port=8080):
        self.port = port
        self.server = None
        self._thread = None

        # 看板共享状态
        self.state = {
            "status": "⚪ 系统准备就绪",
            "latest_answer": "",
            "timestamp": "",
            "answer_id": 0,
            "history": []
        }
        self._lock = threading.Lock()

    def set_status(self, status_text):
        """更新当前工作状态"""
        with self._lock:
            self.state["status"] = status_text

    def post_answer(self, answer_text):
        """发布最新题目答案"""
        with self._lock:
            now_str = time.strftime("%H:%M:%S")
            self.state["answer_id"] += 1
            self.state["latest_answer"] = answer_text
            self.state["timestamp"] = now_str
            self.state["status"] = "🟢 最新答案已就绪"
            self.state["history"].append({
                "id": self.state["answer_id"],
                "answer": answer_text[:60] + ("..." if len(answer_text) > 60 else ""),
                "time": now_str
            })

    def get_lan_ip(self):
        """优先获取物理 Wi-Fi 局域网 IP (192.168.x.x 或 10.x.x.x)"""
        try:
            ips = socket.gethostbyname_ex(socket.gethostname())[2]
            # 优先 192.168.x.x
            for ip in ips:
                if ip.startswith("192.168."):
                    return ip
            # 其次 10.x.x.x
            for ip in ips:
                if ip.startswith("10."):
                    return ip
            # 排除 127. 与 198.18. (VPN)
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("198.18."):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    def get_url(self):
        return f"http://{self.get_lan_ip()}:{self.port}"

    def print_qr_and_link(self):
        """在控制台打印访问网址与 ASCII 二维码"""
        url = self.get_url()
        try:
            print("\n" + "=" * 65)
            print("【 iPhone 手机看答案看板已开启 】")
            print("请确保 iPhone 与电脑连接在同一个 Wi-Fi 网络下！")
            print(f">> 手机 Safari 浏览器直接打开网址: {url}")
            print("或者用 iPhone 相机扫描下方二维码直接打开：\n")
            try:
                import qrcode
                qr = qrcode.QRCode(border=1)
                qr.add_data(url)
                qr.make(fit=True)
                qr.print_ascii(invert=True)
            except Exception:
                pass
            print("=" * 65 + "\n")
        except Exception:
            pass


    def start(self):
        """在独立后台守护线程中启动 HTTP 服务"""
        parent = self

        class DashboardHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静音普通请求日志，避免刷屏

            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
                elif self.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    with parent._lock:
                        payload = json.dumps(parent.state, ensure_ascii=False)
                    self.wfile.write(payload.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("0.0.0.0", self.port), DashboardHandler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self.print_qr_and_link()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

if __name__ == "__main__":
    server = DashboardServer(port=8080)
    server.start()
    server.post_answer("C")
    print("服务器运行中，按 Ctrl+C 退出测试...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
