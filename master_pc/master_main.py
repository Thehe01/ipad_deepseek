import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import argparse
import threading
import ctypes
from ctypes import wintypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import requests
import keyboard
from PIL import ImageGrab, Image

from master_config import (
    HOTKEY_TRIGGER,
    ROI_CONFIG_FILE,
    TEMP_IMAGE_PATH,
    CLIPBOARD_SERVER_PORT,
)
from discovery import discover_secondary_pc
from roi_selector import get_roi_interactive
from screen_monitor import ScreenMonitor

# ── 主电脑剪切板工具（Win32 ctypes 64位完全兼容）──
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
        print(f"[剪切板] 写入失败: {e}")
        return False


# ── 全局状态 ────────────────────────────────────────────────
_secondary_url = None
_roi = None
_screen_monitor = None
_lock = threading.Lock()
_uploading = False          # 防止快捷键连按重叠上传
_running = True
_latest_content = ""        # 缓存辅助电脑推送过来的最新题目内容（代码/选择题/简答题等）
_ctrl_had_other_key = False # 跟踪 Ctrl 按下期间是否有其他按键，避免组合键误触发
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_run.log")


def _log(msg):
    """同时输出到控制台与本地日志文件，方便无界面后台运行时核对"""
    try:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{now_str}] {msg}\n"
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except Exception:
            pass
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def fetch_content_to_clipboard(trigger_name="快捷键"):
    """
    按下快捷键后：直接将最新题目内容（不管是选择题、简答题还是代码题）拷贝进剪切板！
    """
    global _latest_content

    if _latest_content and _latest_content.strip():
        ok = _write_clipboard(_latest_content)
        if ok:
            _log(f"[{trigger_name}] ✅ 最新题目内容已拷贝进剪切板（共 {len(_latest_content)} 字符）！直接 Ctrl+V 粘贴即可！")
            return True
        else:
            _log(f"[{trigger_name}] ⚠️ 写入剪切板失败！")
            return False
    else:
        _log(f"[{trigger_name}] ⚪ 当前尚未收到题目答案，辅助电脑生成答案后按快捷键即可拷贝。")
        return False


def on_double_ctrl_trigger():
    return fetch_content_to_clipboard(trigger_name="双击 Ctrl")


class ClipboardServer:
    """轻量 HTTP 服务，监听辅助电脑反推过来的题目答案（代码/选择/文本）并暂存。"""

    def __init__(self, port=CLIPBOARD_SERVER_PORT):
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # 静默

            def do_POST(self):
                if self.path == "/api/clipboard":
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(length)
                        ans_text = body.decode("utf-8")
                        global _latest_content
                        _latest_content = ans_text

                        # 默认不自动修改剪切板，保护用户电脑正常复制粘贴；按快捷键后才写入
                        _log(f"[答案就绪] 辅助电脑推送最新内容（{len(ans_text)} 字符）。默认未改动系统剪切板，按下【双击 Ctrl】/【Ctrl+Q】/【F9】立即拷贝！")

                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"ok"}')
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f'{{"status":"error","msg":"{e}"}}'.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[剪切板服务] 主电脑剪切板接收器已启动，监听端口 {self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

# ── 纯 Win32 GDI 屏幕抓取工具（秒杀所有保护模式，零报错）──

_gdi = ctypes.windll.gdi32
_gdi.CreateDCA.restype = wintypes.HDC
_gdi.CreateDCA.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi.SelectObject.restype = wintypes.HGDIOBJ
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi.BitBlt.restype = wintypes.BOOL
_gdi.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
_gdi.DeleteDC.argtypes = [wintypes.HDC]
_gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]


def _capture_gdi(x, y, w, h):
    """通过 DISPLAY 设备上下文直接拷贝显存，兼容性最强、速度最快"""
    hdc_screen = _gdi.CreateDCA(b"DISPLAY", None, None, None)
    if not hdc_screen:
        raise RuntimeError("CreateDCA DISPLAY failed")
    hdc_mem = _gdi.CreateCompatibleDC(hdc_screen)
    hbm = _gdi.CreateCompatibleBitmap(hdc_screen, w, h)
    old = _gdi.SelectObject(hdc_mem, hbm)

    _gdi.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, 0x00CC0020)  # SRCCOPY

    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = (ctypes.c_char * (w * h * 4))()
    lines = _gdi.GetDIBits(hdc_mem, hbm, 0, h, ctypes.byref(buf), ctypes.byref(bmi), 0)

    _gdi.SelectObject(hdc_mem, old)
    _gdi.DeleteObject(hbm)
    _gdi.DeleteDC(hdc_mem)
    _gdi.DeleteDC(hdc_screen)

    if lines != h:
        raise RuntimeError(f"GetDIBits failed, expected {h} lines, got {lines}")
    return Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")


def parse_args():
    parser = argparse.ArgumentParser(description="主电脑端：快捷键截题并通过局域网直传辅助电脑")
    parser.add_argument("--reselect", action="store_true", help="强制重新框选屏幕监控区域")
    parser.add_argument("--server", type=str, default=None,
                        help="手动指定辅助电脑地址（如 http://192.168.1.105:8080）")
    return parser.parse_args()


def grab_roi(roi):
    """截取指定 ROI 区域，优先使用原生 GDI 拷贝，失败时回退 PIL"""
    x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["width"]), int(roi["height"])
    try:
        return _capture_gdi(x, y, w, h)
    except Exception as e:
        print(f"[GDI 截图异常，尝试回退] {e}")

    # 回退 1: PIL ImageGrab
    bbox = (x, y, x + w, y + h)
    try:
        return ImageGrab.grab(bbox=bbox)
    except Exception:
        pass

    # 回退 2: mss
    try:
        from mss import mss as MSS
        with MSS() as sct:
            monitor = {"top": y, "left": x, "width": w, "height": h}
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception as e:
        raise RuntimeError(f"屏幕截图失败: {e}")


def upload_image(image_path):
    """通过局域网 HTTP POST 上传图片给辅助电脑"""
    global _uploading
    if _uploading:
        _log("[提示] 上一张截图仍在上传中，请稍候再按快捷键...")
        return
    _uploading = True
    start_t = time.time()
    try:
        with open(image_path, "rb") as f:
            files = {"image": ("question.png", f, "image/png")}
            res = requests.post(
                f"{_secondary_url}/api/upload_question",
                files=files,
                proxies={"http": None, "https": None},
                timeout=6.0,
            )
        elapsed_ms = int((time.time() - start_t) * 1000)
        if res.status_code == 200:
            _log(f"[上传成功] 全屏截图已送达辅助电脑！耗时 {elapsed_ms} 毫秒，DeepSeek R1 正在解题...")
        else:
            _log(f"[上传警告] 辅助电脑返回异常状态码: {res.status_code}，内容: {res.text}")
    except Exception as e:
        _log(f"[上传失败] 无法发送截图至辅助电脑: {e}")
    finally:
        _uploading = False


def on_hotkey_trigger(trigger_name="快捷键"):
    """快捷键/鼠标中键回调：截图 → 保存 → 异步上传"""
    global _roi, _secondary_url, _screen_monitor
    if _secondary_url is None or _roi is None:
        _log("[提示] 尚未就绪，请稍候...")
        return
    _log(f"[{trigger_name}触发] 正在截取监控区域并发送给辅助电脑...")

    try:
        img = grab_roi(_roi)
        img.save(TEMP_IMAGE_PATH, format="PNG")
        _log(f"[截图保存成功] {TEMP_IMAGE_PATH}")
        if _screen_monitor:
            _screen_monitor.sync_ref_frame(img)
    except Exception as e:
        _log(f"[截图失败] {e}")
        return
    # 在新线程中上传，不阻塞热键监听
    threading.Thread(target=upload_image, args=(TEMP_IMAGE_PATH,), daemon=True).start()


def on_auto_question_detected(image_path, is_manual=False):
    """全自动画面翻页感知回调：自动上传截图"""
    threading.Thread(target=upload_image, args=(image_path,), daemon=True).start()


def _win32_hotkey_polling_loop():
    """
    Win32 原生 GetAsyncKeyState 全局热键与鼠标按键极速轮询：
    1. 截题：
       - 【鼠标滚轮中键单击】：推荐！手始终在鼠标上，双手零碰键盘，100% 规避监考检测；
       - 【鼠标侧键】：备用微动截题；
       - 【Ctrl+Shift】 与 【F8】：键盘备用通道。
    2. 提取内容至剪切板（大题/代码题按需触发）：
       - 【双击 Ctrl】 / 【Ctrl+Q】 / 【F9】
    """
    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
    VK_SHIFT = 0x10
    VK_ALT = 0x12
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79
    VK_Q = 0x51
    VK_MBUTTON = 0x04   # 鼠标滚轮中键
    VK_XBUTTON1 = 0x05  # 鼠标侧键 1
    VK_XBUTTON2 = 0x06  # 鼠标侧键 2

    u32 = ctypes.windll.user32
    u32.GetAsyncKeyState.restype = ctypes.c_short

    last_snap_pressed = False
    last_snap_time = 0.0
    ctrl_down_prev = False
    f9_prev = False
    f10_prev = False
    ctrl_q_prev = False
    last_ctrl_press_time = 0.0

    while _running:
        try:
            ctrl = bool((u32.GetAsyncKeyState(VK_CONTROL) & 0x8000) or
                        (u32.GetAsyncKeyState(VK_LCONTROL) & 0x8000) or
                        (u32.GetAsyncKeyState(VK_RCONTROL) & 0x8000))
            shift = bool(u32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
            alt = bool(u32.GetAsyncKeyState(VK_ALT) & 0x8000)
            f8 = bool(u32.GetAsyncKeyState(VK_F8) & 0x8000)
            f9 = bool(u32.GetAsyncKeyState(VK_F9) & 0x8000)
            f10 = bool(u32.GetAsyncKeyState(VK_F10) & 0x8000)
            q = bool(u32.GetAsyncKeyState(VK_Q) & 0x8000)
            mbutton = bool(u32.GetAsyncKeyState(VK_MBUTTON) & 0x8000)
            xbutton = bool((u32.GetAsyncKeyState(VK_XBUTTON1) & 0x8000) or
                           (u32.GetAsyncKeyState(VK_XBUTTON2) & 0x8000))

            # ── 1. 截题触发：鼠标滚轮中键 / 鼠标侧键 / Ctrl+Shift / F8 ──
            snap_triggered = mbutton or xbutton or (ctrl and shift) or f8
            if snap_triggered and not last_snap_pressed:
                last_snap_pressed = True
                now = time.time()
                if now - last_snap_time >= 0.8:
                    last_snap_time = now
                    if mbutton:
                        t_name = "鼠标滚轮中键"
                    elif xbutton:
                        t_name = "鼠标侧键"
                    elif ctrl and shift:
                        t_name = "Ctrl+Shift"
                    else:
                        t_name = "F8"
                    on_hotkey_trigger(trigger_name=t_name)
                else:
                    _log("[提示] 截题过于频繁，已忽略重复触发。")
            elif not snap_triggered:
                last_snap_pressed = False

            # ── 2. 快捷键提取内容：Ctrl + Q ──
            ctrl_q = ctrl and q
            if ctrl_q and not ctrl_q_prev:
                fetch_content_to_clipboard(trigger_name="快捷键 Ctrl+Q")
            ctrl_q_prev = ctrl_q

            # ── 3. 单键获取内容备选：F9 ──
            if f9 and not f9_prev:
                fetch_content_to_clipboard(trigger_name="按键 F9")
            f9_prev = f9

            # ── 3.5 暂停/恢复自动切题监控：F10 ──
            if f10 and not f10_prev:
                if _screen_monitor:
                    _screen_monitor.toggle_pause()
            f10_prev = f10

            # ── 4. 双击 Ctrl 独立检测（宽松时间 0.03s ~ 0.85s，无 Shift/Alt 干扰）──
            if ctrl and not ctrl_down_prev:
                now = time.time()
                if not shift and not alt and not q:
                    diff = now - last_ctrl_press_time
                    if 0.03 < diff <= 0.85:
                        last_ctrl_press_time = 0.0
                        fetch_content_to_clipboard(trigger_name="双击 Ctrl")
                    else:
                        last_ctrl_press_time = now

            ctrl_down_prev = ctrl

        except Exception:
            pass

        time.sleep(0.015)  # 15ms 高频极速响应，不漏按键



def _kill_previous_instances():
    """清理遗留的旧 master_main.py 进程，防止多开冲突"""
    try:
        current_pid = os.getpid()
        import subprocess
        cmd = f'powershell -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object {{ ($_.CommandLine -like \'*master_main*\') -and ($_.ProcessId -ne {current_pid}) }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=4)
    except Exception:
        pass


def main():
    global _secondary_url, _roi, _running, _ctrl_had_other_key

    # 清理之前可能遗留的旧后台实例，杜绝端口冲突或多实例并发
    _kill_previous_instances()

    args = parse_args()

    print("=" * 65)
    print("      【主电脑端】全自动翻页截题 → 局域网秒级直传辅助电脑")
    print("=" * 65)
    print(f"  [全自动感知切题]      默认开启！画面翻页稳定 0.8s 自动保存上传（完全零按键）")
    print(f"  [鼠标滚轮中键]        点击滚轮中键手动立即截题保底（手不离鼠标，防监考检测）")
    print(f"  [鼠标侧键]            点击侧键亦可截题（前进/后退键）")
    print(f"  [Ctrl+Shift] 或 [F8]  键盘截题备选通道")
    print(f"  [F10]                暂停/恢复全自动切题监控")
    print(f"  [双击 Ctrl] / [Ctrl+Q] / [F9] 拷贝最新题目内容至剪切板（大题需要粘贴时使用）")
    print(f"  [Ctrl+C]             退出程序")
    print("=" * 65)

    _log("========== 【主电脑端】启动 (无界面无任务栏后台模式) ==========")

    # 0. 启动剪切板接收服务（辅助电脑解完题后反推答案内容到这里）
    clipboard_srv = ClipboardServer()
    clipboard_srv.start()
    _log(f"[内容接收服务] 监听端口 {clipboard_srv.port}（默认不改动剪切板，快捷键触发拷贝）")

    # 1. 立即启动全局热键监听线程与备用热键（杜绝网络发现阻塞热键启动）
    t_poll = threading.Thread(target=_win32_hotkey_polling_loop, daemon=True)
    t_poll.start()

    try:
        keyboard.add_hotkey("ctrl+shift", on_hotkey_trigger)
        keyboard.add_hotkey("f8", on_hotkey_trigger)
        keyboard.add_hotkey("ctrl+q", lambda: fetch_content_to_clipboard(trigger_name="快捷键 Ctrl+Q"))
        keyboard.add_hotkey("f9", lambda: fetch_content_to_clipboard(trigger_name="按键 F9"))
        keyboard.add_hotkey("f10", lambda: _screen_monitor.toggle_pause() if _screen_monitor else None)
    except Exception:
        pass

    _log("[监听就绪] 全自动感知切题已待命！手动截题 [鼠标滚轮中键] / [鼠标侧键] / [Ctrl+Shift] / [F8]、内容提取 [双击 Ctrl] / [Ctrl+Q] / [F9] 已激活！")

    # 2. 框选或复用题目区域并立即启动全自动切题监控
    try:
        _roi = get_roi_interactive(force_reselect=args.reselect)
        _log(f"[监控区域] 已锁定: x={_roi['x']}, y={_roi['y']}, w={_roi['width']}, h={_roi['height']}")
        # 启动全自动切题监控引擎（纯画面感知）
        _screen_monitor = ScreenMonitor(
            roi=_roi,
            on_question_detected=on_auto_question_detected,
            grab_fn=grab_roi,
            log_fn=_log,
        )
        _screen_monitor.start()
    except Exception as e:
        _log(f"[提示] 获取监控区域或启动全自动切题: {e}")

    # 3. 后台线程持续寻找辅助电脑（不阻塞本地监控启动）
    def _discovery_worker():
        global _secondary_url
        if args.server:
            _secondary_url = args.server.rstrip("/")
            _log(f"[配置] 已手动指定辅助电脑地址: {_secondary_url}")
            return
        while _running and not _secondary_url:
            url = discover_secondary_pc(timeout=3.0)
            if url:
                _secondary_url = url
                _log(f"[连接成功] 辅助电脑已对齐: {_secondary_url}")
                break
            time.sleep(2.0)

    t_disc = threading.Thread(target=_discovery_worker, daemon=True)
    t_disc.start()

    print(f"\n[监听就绪] 纯画面全自动切题已激活！")
    print(f"  * 只要屏幕/iPad发生换题翻页，画面稳定 0.8 秒后自动保存并上传 DeepSeek！")
    print(f"  * 手动截题保底：【鼠标滚轮中键】 / 【鼠标侧键】 / 【Ctrl+Shift】 / 【F8】随时可用。")
    print(f"  * 【F10】快捷键随时暂停/恢复自动切题监控。")
    print(f"  * 大题/代码题按需按 [双击 Ctrl] / [Ctrl+Q] / [F9] 提取至剪切板。")
    print(f"  * 完全静音静默后台运行。")

    print("\n" + "#" * 65)
    print(f"【就绪】已连接至辅助电脑: {_secondary_url}")
    print(f"  换题时自动感知上传；亦可随时按【鼠标滚轮中键】手动截题；")
    print(f"  需要代码答案时按 [双击 Ctrl] 自动写入剪切板（Ctrl+V 即粘贴）。")
    print("#" * 65 + "\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[正在退出] 用户主动终止...")
    finally:
        _running = False
        if _screen_monitor:
            _screen_monitor.stop()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        clipboard_srv.stop()
        print("[已退出] 主电脑端已安全停止。")



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
        print(f"【主电脑端运行异常】: {e}")
        traceback.print_exc()
        print("!" * 65)
        try:
            input("\n按回车键 (Enter) 退出...")
        except Exception:
            pass
    except KeyboardInterrupt:
        pass
    sys.exit(exit_code)

