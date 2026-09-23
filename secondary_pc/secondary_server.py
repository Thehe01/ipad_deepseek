import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
import socket
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from secondary_config import HTTP_PORT, DISCOVERY_PORT, TEMP_RECEIVED_IMAGE

import ctypes
from ctypes import wintypes
import re

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 剪切板工具（纯 Win32 ctypes，无需额外依赖）──
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_k32.GlobalAlloc.restype = wintypes.HGLOBAL
_k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k32.GlobalLock.restype = wintypes.LPVOID
_k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_u32.OpenClipboard.argtypes = [wintypes.HWND]
_u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def _copy_to_clipboard(text):
    """将文本写入 Windows 剪切板（UTF-16LE），失败时静默忽略。"""
    try:
        if not _u32.OpenClipboard(None):
            return
        try:
            _u32.EmptyClipboard()
            data = text.encode("utf-16le") + b"\x00\x00"
            h_mem = _k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            p_mem = _k32.GlobalLock(h_mem)
            ctypes.memmove(p_mem, data, len(data))
            _k32.GlobalUnlock(h_mem)
            _u32.SetClipboardData(13, h_mem)  # CF_UNICODETEXT = 13
        finally:
            _u32.CloseClipboard()
    except Exception as e:
        print(f"[剪切板] 写入失败（已忽略）: {e}")


def _extract_code_blocks(text):
    """从 Markdown 文本提取所有代码围栏内容（去掉语言标注行），合并为一段。"""
    if not text:
        return None
    # 优先匹配标准的 ```lang\n...```
    pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    blocks = pattern.findall(text)
    if not blocks:
        # 兼容无显式换行的代码围栏
        loose_pattern = re.compile(r"```(?:[a-zA-Z0-9+#-]*\s+)?(.*?)```", re.DOTALL)
        blocks = loose_pattern.findall(text)
    if not blocks:
        # 如果模型直接返回了裸代码（包含 class Solution / def 等但没加反引号）
        if "class Solution" in text or re.search(r"^(?:class|public|def|#include)\b", text, re.MULTILINE):
            blocks = [text]
    if not blocks:
        return None
    cleaned_blocks = []
    for b in blocks:
        # 彻底清洗代码开头可能出现的语言标签或复制下载残留
        cleaned = re.sub(r"^(?:[a-zA-Z0-9+#-]+\s*)?(?:复制|下载|Copy|Download)+\s*", "", b.strip(), flags=re.IGNORECASE)
        cleaned_blocks.append(cleaned)
    return "\n\n".join(cleaned_blocks)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>DeepSeek 实时看板</title>
    <!-- marked.js: Markdown 完整渲染引擎 -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- highlight.js: 代码语法高亮 -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css">
    <script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/highlight.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background-color: #000000;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif;
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
            width: 10px; height: 10px;
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

        .answer-card {
            background: #111216;
            border: 1px solid #23252e;
            border-radius: 24px;
            padding: 24px 20px;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.8);
            margin-bottom: 24px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            color: #8e8e93;
            margin-bottom: 16px;
        }
        .answer-content {
            min-height: 120px;
        }

        /* ── 统一正常舒适字体呈现（杜绝荧光大字，清晰护眼） ── */
        .answer-content {
            color: #f0f6fc;
            font-size: 18px;
            line-height: 1.8;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Helvetica Neue", sans-serif;
            word-break: break-word;
        }

        /* ── 单道短题（如 【第1题】 C）：舒适正常字体 ── */
        .answer-single {
            text-align: left;
            font-size: 20px;
            font-weight: 600;
            color: #f0f6fc;
            padding: 8px 0;
            letter-spacing: 0.02em;
            word-break: break-word;
        }

        /* ── 多道选择小题：普通整齐行列表，无荧光，无外框卡片，舒适阅读 ── */
        .choice-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
            padding: 4px 0;
        }
        .choice-item {
            font-size: 18px;
            font-weight: 500;
            color: #f0f6fc;
            line-height: 1.7;
            padding: 4px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }
        .choice-item:last-child {
            border-bottom: none;
        }

        /* ── Markdown 完整呈现容器 ── */
        .md-body {
            color: #f0f6fc;
            font-size: 17px;
            line-height: 1.75;
            word-break: break-word;
        }
        .md-body p { margin-bottom: 10px; }
        .md-body h1, .md-body h2, .md-body h3 {
            color: #f0f6fc;
            font-weight: 600;
            margin: 12px 0 8px;
            line-height: 1.35;
            background: none;
            border: none;
            padding: 0;
        }
        .md-body h1 { font-size: 20px; }
        .md-body h2 { font-size: 20px; }
        .md-body h3 { font-size: 18px; }
        .md-body ul, .md-body ol {
            padding-left: 20px;
            margin-bottom: 10px;
        }
        .md-body li { margin-bottom: 4px; }
        .md-body strong { color: #ffffff; font-weight: 700; }
        .md-body em { color: #a8d8ff; font-style: italic; }
        .md-body code {
            background: #1e2230;
            color: #79c0ff;
            padding: 2px 6px;
            border-radius: 5px;
            font-family: "SF Mono", Menlo, Consolas, Monaco, monospace;
            font-size: 15px;
        }
        /* 代码块：自动换行，绝无横向滚动条，行间距舒适 */
        .md-body pre {
            background: #0d1117 !important;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 14px 16px;
            margin: 12px 0;
            white-space: pre-wrap !important;
            word-wrap: break-word !important;
            word-break: break-word !important;
            overflow-x: hidden !important;
        }
        .md-body pre code {
            background: transparent !important;
            color: inherit;
            padding: 0;
            font-size: 14px;
            line-height: 1.65;
            white-space: pre-wrap !important;
            word-wrap: break-word !important;
            word-break: break-word !important;
            font-family: "SF Mono", Menlo, Consolas, "Courier New", monospace !important;
            tab-size: 4;
            -moz-tab-size: 4;
        }
        .md-body blockquote {
            border-left: 3px solid #30d158;
            padding-left: 14px;
            color: #8e8e93;
            margin: 10px 0;
        }
        .md-body hr {
            border: none;
            border-top: 1px solid #2c2c2e;
            margin: 14px 0;
        }
        .md-body table {
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0;
            font-size: 15px;
        }
        .md-body th, .md-body td {
            border: 1px solid #30363d;
            padding: 8px 10px;
            text-align: left;
        }
        .md-body th { background: #1c1c1e; color: #ffffff; }
    </style>
</head>
<body>
    <div class="header">
        <div class="status-badge" id="statusBadge">
            <span class="status-dot"></span>
            <span id="statusText">等待主电脑题目...</span>
        </div>
        <div class="wakelock-indicator" id="wakeLockStatus">
            ⚡ 屏幕常亮已保持
        </div>
    </div>

    <div class="answer-card" id="answerCard">
        <div class="card-header">
            <span>最新解题结果</span>
            <span id="answerTime">--:--:--</span>
        </div>
        <div class="answer-content" id="answerContent">
            <div style="color:#636366;font-size:18px;text-align:center;">
                暂无答题记录<br>请在主电脑按快捷键截题
            </div>
        </div>
    </div>

    <script>
        // ── WakeLock：保持屏幕常亮 ──
        let wakeLock = null;
        async function enableWakeLock() {
            try {
                if ('wakeLock' in navigator) {
                    wakeLock = await navigator.wakeLock.request('screen');
                    document.getElementById('wakeLockStatus').innerText = '⚡ 屏幕常亮已保持';
                }
            } catch (err) { console.log('WakeLock error:', err); }
        }
        enableWakeLock();
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') enableWakeLock();
        });
        document.body.addEventListener('click', enableWakeLock);

        // ── marked.js 配置 ──
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
                highlight: function(code, lang) {
                    if (typeof hljs !== 'undefined') {
                        if (lang && hljs.getLanguage(lang)) {
                            try { return hljs.highlight(code, { language: lang }).value; } catch(e) {}
                        }
                        try { return hljs.highlightAuto(code).value; } catch(e) {}
                    }
                    return escapeHtml(code);
                }
            });
        }

        // ── 状态轮询 ──
        let lastAnswerId = -1;
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const badge = document.getElementById('statusBadge');
                const text  = document.getElementById('statusText');
                text.innerText = data.status || '监控中';
                if (data.status && data.status.includes('解题')) {
                    badge.classList.add('busy');
                } else {
                    badge.classList.remove('busy');
                }

                if (data.answer_id && data.answer_id !== lastAnswerId) {
                    lastAnswerId = data.answer_id;
                    renderAnswer(data.latest_answer, data.timestamp);
                    if (navigator.vibrate) navigator.vibrate([150, 80, 150]);
                }
            } catch (e) {
                console.error('Fetch error:', e);
            }
        }

        // ── 渲染答案 ──
        function renderAnswer(answer, timestamp) {
            const container = document.getElementById('answerContent');
            document.getElementById('answerTime').innerText = timestamp || '';

            if (!answer || answer.trim() === '') {
                container.innerHTML = '<div style="color:#636366;font-size:18px;text-align:center;">等待模型输出...</div>';
                return;
            }

            let clean = answer.trim();

            // 剔除任何可能残留的“java复制下载”或“复制下载”按钮文本
            clean = clean.replace(/```([a-zA-Z0-9+#-]*)\s*(?:复制|下载|Copy|Download)+/gi, '```$1\n');
            clean = clean.replace(/(?:^|\n)([a-zA-Z0-9+#-]+\s*)?(?:复制|下载|Copy|Download){1,2}\s*/gi, '\n');
            clean = clean.trim();

            // 1. 单个短选项（例如 "【第1题】 C" 或 "1. B" 或纯 "C"）
            // 题号与答案统一格式、同一行正常呈现，杜绝荧光大写
            const shortMatch = clean.match(/^([【\[(]?第?\s*\d+\s*(?:题|小题)?[】\])]?[\s.:：、-]*)\s*([A-Za-z0-9对错√×]+)$/i);
            if (shortMatch && clean.length <= 40 && !/\r?\n/.test(clean)) {
                const qLabel = shortMatch[1].trim();
                const qAns = shortMatch[2].trim(); // 保留原始大小写，不强行 toUpperCase
                const fullText = (qLabel ? (qLabel + ' ') : '') + qAns;
                container.innerHTML = `
                    <div class="answer-single">${escapeHtml(fullText)}</div>
                `;
                return;
            }

            // 2. 多道选择小题连排（例如 "【第1题】 A\n【第2题】 D\n..."）
            // 题号与答案同格式同排，整齐逐行列出
            const lines = clean.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
            const isAllShortChoice = lines.length > 1 && lines.length <= 20 && lines.every(l => /^[【\[(]?第?\s*\d+\s*(?:题|小题)?[】\])]?[\s.:：、-]*[A-Za-z0-9对错√×]+$/i.test(l));
            if (isAllShortChoice) {
                let html = '<div class="choice-list">';
                for (const line of lines) {
                    const m = line.match(/^([【\[(]?第?\s*\d+\s*(?:题|小题)?[】\])]?[\s.:：、-]*)\s*([A-Za-z0-9对错√×]+)$/i);
                    const q = m ? m[1].trim() : '';
                    const a = m ? m[2].trim() : line; // 保留原始大小写
                    const lineText = (q ? (q + ' ') : '') + a;
                    html += `
                        <div class="choice-item">${escapeHtml(lineText)}</div>
                    `;
                }
                html += '</div>';
                container.innerHTML = html;
                return;
            }

            // 3. 编程代码题 / 问答大题（Markdown 渲染）
            // 题号与内容同格式自然排版，不单独强行拆行或加框
            // 如果模型未用代码围栏包裹纯代码，自动补全围栏以保真换行
            if (!clean.includes('```') && (/^(?:class\s+|public\s+|void\s+|int\s+|def\s+|#include)/m.test(clean) || clean.includes('class Solution'))) {
                clean = '```\n' + clean + '\n```';
            }

            if (typeof marked !== 'undefined') {
                try {
                    const rendered = marked.parse(clean);
                    container.innerHTML = `<div class="md-body">${rendered}</div>`;
                    if (typeof hljs !== 'undefined') {
                        container.querySelectorAll('pre code').forEach(block => {
                            try { hljs.highlightElement(block); } catch(e) {}
                        });
                    }
                } catch (err) {
                    container.innerHTML = `<div class="md-body" style="white-space: pre-wrap; font-family: monospace;">${escapeHtml(clean)}</div>`;
                }
            } else {
                container.innerHTML = `<div class="md-body" style="white-space: pre-wrap; font-family: monospace;">${escapeHtml(clean)}</div>`;
            }
        }

        function escapeHtml(str) {
            return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
        }

        setInterval(fetchStatus, 800);
        fetchStatus();
    </script>
</body>
</html>
"""

class SecondaryServer:
    """辅助电脑服务端：托管 iPhone 看板、接收主电脑图片上传、发送局域网 UDP 发现广播"""
    def __init__(self, port=HTTP_PORT, discovery_port=DISCOVERY_PORT,
                 on_question_received=None, clipboard_server_port=8081):
        self.port = port
        self.discovery_port = discovery_port
        self.on_question_received = on_question_received
        self.clipboard_server_port = clipboard_server_port
        self.server = None
        self._http_thread = None
        self._udp_thread = None
        self._running = False
        self._master_ip = None   # 最近一次上传截图的主电脑 IP，由上传请求自动记录

        self.state = {
            "status": "⚪ 辅助电脑就绪，等待主电脑传题...",
            "latest_answer": "",
            "timestamp": "",
            "answer_id": 0,
            "history": []
        }
        self._lock = threading.Lock()

    def set_status(self, status_text):
        with self._lock:
            self.state["status"] = status_text

    def _push_code_to_master(self, master_ip, code_text):
        """将代码答案 POST 到主电脑剪切板接收接口（后台线程调用）。"""
        url = f"http://{master_ip}:{self.clipboard_server_port}/api/clipboard"
        try:
            import urllib.request
            data = code_text.encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={"Content-Type": "text/plain; charset=utf-8",
                         "Content-Length": str(len(data))}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                status = resp.getcode()
            if status == 200:
                print(f"[剪切板] ✅ 代码已推送至主电脑剪切板 ({master_ip})，"
                      f"共 {len(code_text)} 字符，主电脑直接 Ctrl+V 粘贴即可！")
            else:
                print(f"[剪切板] ⚠️ 主电脑剪切板接口返回 {status}")
        except Exception as e:
            print(f"[剪切板] ⚠️ 推送失败（主电脑可能未启动剪切板服务）: {e}")

    def post_answer(self, answer_text):

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
            master_ip = self._master_ip

        # 不管什么题（选择题/连排题/简答题/代码题），均把答案内容反向推送给主电脑暂存（主电脑默认不修改剪切板，按快捷键后才写入）
        clip_content = _extract_code_blocks(answer_text)
        if not clip_content or not clip_content.strip():
            clip_content = answer_text.strip()

        if clip_content and master_ip:
            threading.Thread(
                target=self._push_code_to_master,
                args=(master_ip, clip_content),
                daemon=True
            ).start()

    def get_lan_ip(self):
        try:
            ips = socket.gethostbyname_ex(socket.gethostname())[2]
            for ip in ips:
                if ip.startswith("192.168."):
                    return ip
            for ip in ips:
                if ip.startswith("10."):
                    return ip
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("198.18."):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    def get_url(self):
        return f"http://{self.get_lan_ip()}:{self.port}"

    def print_qr_and_link(self):
        url = self.get_url()
        try:
            print("\n" + "=" * 65)
            print("【 📱 iPhone 手机看板已就绪 】")
            print("请确保 iPhone 与辅助电脑连接在同一个 Wi-Fi 网络下！")
            print(f">> 手机 Safari 浏览器打开: {url}")
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

    def _udp_broadcast_loop(self):
        """定期发送 UDP 局域网宣告，方便主电脑自动秒级发现"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)
        
        message = json.dumps({
            "service": "ipad_deepseek_solver",
            "ip": self.get_lan_ip(),
            "port": self.port
        }).encode("utf-8")

        while self._running:
            try:
                sock.sendto(message, ("<broadcast>", self.discovery_port))
            except Exception:
                pass
            time.sleep(2.0)
        try:
            sock.close()
        except Exception:
            pass

    def start(self):
        parent = self
        self._running = True

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
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

            def do_POST(self):
                # 接收主电脑上传的题目图片
                if self.path == "/api/upload_question":
                    try:
                        content_len = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(content_len)

                        content_type = self.headers.get("Content-Type", "")
                        file_data = b""

                        if "multipart/form-data" in content_type:
                            # 简易解析 multipart 图片主体
                            boundary = content_type.split("boundary=")[-1].encode()
                            parts = body.split(b"--" + boundary)
                            for p in parts:
                                if b"filename=" in p or b"Content-Type: image" in p:
                                    header_end = p.find(b"\r\n\r\n")
                                    if header_end != -1:
                                        file_data = p[header_end + 4:].rstrip(b"\r\n")
                                        break
                        else:
                            file_data = body

                        if file_data:
                            with open(TEMP_RECEIVED_IMAGE, "wb") as f:
                                f.write(file_data)

                            # 记录主电脑 IP（用于后续把代码答案推回给主电脑剪切板）
                            master_ip = self.client_address[0]
                            with parent._lock:
                                parent._master_ip = master_ip

                            parent.set_status("🟡 收到主电脑新题，正在调用 DeepSeek R1 解题...")
                            print(f"\n[主电脑联动] 成功收到主电脑上传的题目截图 ({len(file_data)} 字节)！来自 {master_ip}")

                            if parent.on_question_received:
                                parent.on_question_received(TEMP_RECEIVED_IMAGE)

                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(b'{"status":"ok","msg":"uploaded"}')
                        else:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'{"status":"error","msg":"no image data"}')
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f'{{"status":"error","msg":"{e}"}}'.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("0.0.0.0", self.port), RequestHandler)
        self._http_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._http_thread.start()

        # 启动 UDP 广播宣告线程
        self._udp_thread = threading.Thread(target=self._udp_broadcast_loop, daemon=True)
        self._udp_thread.start()

        self.print_qr_and_link()

    def stop(self):
        self._running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()
