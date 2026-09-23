import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import argparse
import threading
import ctypes
from ctypes import wintypes
import io
import queue
import json
import uuid

import requests
from PIL import ImageGrab, Image

from master_config import (
    ROI_CONFIG_FILE,
    TEMP_IMAGE_PATH,
    PENDING_UPLOAD_DIR,
    ENABLE_SCREEN_DIFF_TRIGGER,
)
from discovery import discover_secondary_pc
from roi_selector import get_roi_interactive
from screen_monitor import ScreenMonitor

try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ── 全局状态 ────────────────────────────────────────────────
_secondary_url = None
_roi = None
_screen_monitor = None
_lock = threading.Lock()
_running = True
_connection_ready = threading.Event()
_upload_queue = queue.Queue()  # 无界队列：杜绝截题丢失，保证 task_done 与 put 计数 1:1 严格一致
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


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_user32.GetThreadDesktop.restype = wintypes.HDESK
_user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HDESK
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.SetThreadDesktop.restype = wintypes.BOOL
_user32.SetThreadDesktop.argtypes = [wintypes.HDESK]
_user32.CloseDesktop.restype = wintypes.BOOL
_user32.CloseDesktop.argtypes = [wintypes.HDESK]

_tls = threading.local()


def _ensure_input_desktop():
    """确保当前线程附加到用户的真实交互桌面 (Default)，防止多桌面隔离或后台调度导致截图黑屏或鼠标坐标归零"""
    if getattr(_tls, "attached", False):
        return
    try:
        tid = _kernel32.GetCurrentThreadId()
        h_thread = _user32.GetThreadDesktop(tid)
        buf = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if _user32.GetUserObjectInformationW(h_thread, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
            if buf.value.lower() == "default":
                _tls.attached = True
                return
        h_input = _user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            if _user32.SetThreadDesktop(h_input):
                _tls.attached = True
            else:
                _user32.CloseDesktop(h_input)
    except Exception:
        pass


def _capture_gdi(x, y, w, h):
    """通过 DISPLAY 设备上下文直接拷贝显存，兼容性最强、速度最快"""
    _ensure_input_desktop()
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
    _ensure_input_desktop()
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


def _atomic_write_bytes(filepath, data):
    """原子写入二进制数据：先写同目录下临时文件，再原子替换，防止断电导致文件截断损坏"""
    tmp_path = f"{filepath}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, filepath)


def _atomic_write_json(filepath, data):
    """原子写入 JSON 数据：先写同目录下临时文件，再原子替换，防止写入中断损坏 JSON"""
    tmp_path = f"{filepath}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, filepath)


def _clean_persisted_file(file_path, meta_path):
    """当题目确认成功上传或被客户端错误明确拒绝后，安全清除本地持久化文件"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    try:
        if meta_path and os.path.exists(meta_path):
            os.remove(meta_path)
    except Exception:
        pass


def recover_pending_uploads():
    """
    启动时扫描 pending_uploads 目录，将上次进程退出或异常中断未送达的截图恢复至上传队列。
    以 PNG 实体图片为第一准绳：
    - 哪怕伴生 JSON 元数据被意外截断或损坏，只要 PNG 图片完整，依然 100% 恢复，并自动重建规范元数据；
    - 自动清理上次中断遗留的 .tmp 临时碎片；
    - 严格按时间戳先后顺序排队，杜绝进程退出或崩溃导致的题目丢失。
    """
    os.makedirs(PENDING_UPLOAD_DIR, exist_ok=True)
    recovered = []
    try:
        # 1. 清理上次中断遗留的 .tmp 临时碎片
        for fname in os.listdir(PENDING_UPLOAD_DIR):
            if fname.endswith(".tmp"):
                try:
                    os.remove(os.path.join(PENDING_UPLOAD_DIR, fname))
                except Exception:
                    pass

        # 2. 遍历所有实体 PNG 图片作为首要数据源（绝对不因 JSON 损坏而漏题）
        for fname in os.listdir(PENDING_UPLOAD_DIR):
            if fname.endswith(".png"):
                file_path = os.path.join(PENDING_UPLOAD_DIR, fname)
                try:
                    size = os.path.getsize(file_path)
                    if size == 0:
                        continue  # 忽略 0 字节损坏文件
                except Exception:
                    continue

                base_name = os.path.splitext(fname)[0]
                meta_path = os.path.join(PENDING_UPLOAD_DIR, f"{base_name}.json")
                trigger_name = "历史待发截图"
                enqueue_time = os.path.getmtime(file_path)
                meta_valid = False

                # 尝试解析伴生元数据 JSON
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        if isinstance(meta, dict):
                            trigger_name = meta.get("trigger_name", trigger_name)
                            enqueue_time = meta.get("enqueue_time", enqueue_time)
                            meta_valid = True
                    except Exception as e:
                        _log(f"[启动恢复] 提示：元数据 {base_name}.json 损坏或被截断 ({e})，直接以对应完整图片恢复！")

                # 如果 JSON 损坏或不存在，原子重建一份规范元数据
                if not meta_valid:
                    try:
                        _atomic_write_json(meta_path, {
                            "task_id": base_name,
                            "trigger_name": trigger_name,
                            "enqueue_time": enqueue_time,
                            "image_file": fname,
                        })
                    except Exception:
                        pass

                try:
                    with open(file_path, "rb") as f:
                        img_bytes = f.read()
                    recovered.append((enqueue_time, img_bytes, trigger_name, file_path, meta_path))
                except Exception as e:
                    _log(f"[启动恢复] 读取图片 {fname} 异常: {e}")

        # 按时间升序排序，严格保证题目先后顺序
        recovered.sort(key=lambda x: x[0])
        for enq_t, img_bytes, t_name, f_path, m_path in recovered:
            _upload_queue.put((img_bytes, t_name, enq_t, f_path, m_path))

        if recovered:
            _log(f"[启动恢复] 发现 {len(recovered)} 张历史未送达截图，已自动恢复至上传队列排队等待发送！")
    except Exception as e:
        _log(f"[启动恢复] 扫描未完成任务异常: {e}")


def enqueue_upload(img_or_path, trigger_name="快捷键"):
    """
    将待上传图像打包为内存 PNG 字节流，并立即原子持久化落盘至 pending_uploads 目录。
    1. 逐任务保存独立持久化文件，彻底杜绝进程退出、崩溃或断电导致的未发送截图丢失；
    2. 采用临时文件+原子重命名写入，杜绝断电导致文件截断损坏；
    3. 加入内存上传队列排队等待发送；
    4. 仅在辅助电脑确认成功接收（HTTP 200）后才删除对应磁盘文件。
    """
    try:
        if isinstance(img_or_path, str):
            with open(img_or_path, "rb") as f:
                img_bytes = f.read()
        elif hasattr(img_or_path, "save"):
            buf = io.BytesIO()
            img_or_path.save(buf, format="PNG")
            img_bytes = buf.getvalue()
            # 顺便留存一份最新截图用于本地排查核对
            try:
                with open(TEMP_IMAGE_PATH, "wb") as f:
                    f.write(img_bytes)
            except Exception:
                pass
        else:
            _log(f"[{trigger_name}] 错误：不支持的图像对象类型 {type(img_or_path)}")
            raise TypeError(f"不支持的图像对象类型 {type(img_or_path)}")

        # 逐任务原子持久化落盘
        os.makedirs(PENDING_UPLOAD_DIR, exist_ok=True)
        now_ts = time.time()
        task_id = f"pending_{int(now_ts * 1000)}_{uuid.uuid4().hex[:6]}"
        file_path = os.path.join(PENDING_UPLOAD_DIR, f"{task_id}.png")
        meta_path = os.path.join(PENDING_UPLOAD_DIR, f"{task_id}.json")

        _atomic_write_bytes(file_path, img_bytes)
        _atomic_write_json(meta_path, {
            "task_id": task_id,
            "trigger_name": trigger_name,
            "enqueue_time": now_ts,
            "image_file": f"{task_id}.png",
        })

        _upload_queue.put((img_bytes, trigger_name, now_ts, file_path, meta_path))
    except Exception as e:
        _log(f"[{trigger_name}] 图像入队/持久化异常: {e}")
        raise


def _upload_worker():
    """
    后台单线程排队上传工人：
    1. 每次成功 get() 使用 try...finally 保证且仅保证调用一次 task_done()（杜绝退出时重复扣减未完成计数）；
    2. 辅机尚未连通时在队列中持久等待，绝不因超时抛弃题目；
    3. 严格按顺序串行上传，保证题目顺序与完整性；
    4. 遇到网络波动、辅机未就绪或临时断开时持续重试，直到成功送达（或遇到不可恢复的 4xx 客户端错误、或系统退出）；
    5. 仅在辅机确认收到（200 OK）或明确拒绝（4xx）后，才清除对应本地持久化文件，保证崩溃/断电不丢题。
    """
    global _running, _secondary_url
    while _running:
        try:
            item = _upload_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            if len(item) == 5:
                img_bytes, trigger_name, enqueue_time, file_path, meta_path = item
            else:
                img_bytes, trigger_name, enqueue_time = item[:3]
                file_path, meta_path = None, None

            # 1. 若辅助电脑尚未就绪，在队列中持续等待辅机上线，绝不抛弃当前题目
            if not _secondary_url:
                _log(f"[{trigger_name}] 辅助电脑连接尚未就绪，截图已在队列持续暂存，等待辅机上线...")
                while _running and not _secondary_url:
                    _connection_ready.wait(timeout=1.0)

            if not _running:
                break

            # 2. 持续上传重试循环，直到成功送达辅机或系统退出
            attempt = 0
            while _running:
                attempt += 1
                start_t = time.time()
                try:
                    files = {"image": ("question.png", img_bytes, "image/png")}
                    res = requests.post(
                        f"{_secondary_url}/api/upload_question",
                        files=files,
                        proxies={"http": None, "https": None},
                        timeout=7.0,
                    )
                    elapsed_ms = int((time.time() - start_t) * 1000)
                    if res.status_code == 200:
                        _log(f"[{trigger_name}] ✅ 截图已送达辅助电脑！耗时 {elapsed_ms} 毫秒，DeepSeek R1 正在解题...")
                        _clean_persisted_file(file_path, meta_path)
                        break
                    elif 400 <= res.status_code < 500:
                        _log(f"[{trigger_name}] ❌ 辅机返回客户端错误 {res.status_code}: {res.text}，跳过此题。")
                        _clean_persisted_file(file_path, meta_path)
                        break
                    else:
                        _log(f"[{trigger_name}] ⚠️ 辅机返回服务状态码 {res.status_code}，将在 2 秒后持续重试 (第 {attempt} 次)...")
                except Exception as e:
                    _log(f"[{trigger_name}] ⚠️ 上传异常: {e}，将在 2 秒后持续重试 (第 {attempt} 次)...")

                # 若多次连接失败，辅机可能重新开机或更换了 IP，尝试广播重探一次
                if attempt % 5 == 0:
                    try:
                        new_url = discover_secondary_pc(timeout=1.5)
                        if new_url and new_url != _secondary_url:
                            _secondary_url = new_url
                            _log(f"[{trigger_name}] 辅机网络地址已重新对齐: {_secondary_url}")
                    except Exception:
                        pass

                # 等待 2 秒后重试，每 0.1 秒检查一次 _running 状态以支持快速退出
                for _ in range(20):
                    if not _running:
                        break
                    time.sleep(0.1)
        finally:
            _upload_queue.task_done()


def on_auto_question_detected(raw_img, is_manual=False, trigger_name="自动翻页感知"):
    """画面感知/鼠标停留截题回调：直接将内存图像送入上传队列"""
    enqueue_upload(raw_img, trigger_name=trigger_name)


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
    global _secondary_url, _roi, _running, _screen_monitor

    # 清理之前可能遗留的旧后台实例，杜绝端口冲突或多实例并发
    _kill_previous_instances()

    args = parse_args()

    print("=" * 65)
    print("      【主电脑端】鼠标右上角停留截题 → 局域网秒级直传辅助电脑")
    print("=" * 65)
    print(f"  [唯一截题通道]        鼠标光标移到屏幕右上角停留 0.3s 即自动截题")
    print(f"  [纯净静默安全]        已彻底禁用键盘监听与剪切板读写，零挂钩、零写入")
    print(f"  [题目答案查看]        手机 / 辅助电脑常亮看板实时查看解题结果")
    print(f"  [Ctrl+C]             退出程序")
    print("=" * 65)

    _log("========== 【主电脑端】启动 (无界面无任务栏后台模式) ==========")

    # 0.4 恢复历史进程遗留的未发送截图（杜绝进程退出丢失）
    recover_pending_uploads()

    # 0.5 启动后台单线程排队上传服务（内存直接传递、自动等待连接就绪）
    t_upload = threading.Thread(target=_upload_worker, daemon=True)
    t_upload.start()

    _log("[截题监听就绪] 唯一截题通道已锁定：鼠标在屏幕右上角停留0.3s即截题！手机/辅机看板实时同步答案。")

    # 2. 框选或复用题目区域并立即启动全自动切题监控
    try:
        _roi = get_roi_interactive(force_reselect=args.reselect)
        _log(f"[监控区域] 已锁定: x={_roi['x']}, y={_roi['y']}, w={_roi['width']}, h={_roi['height']}")
        # 启动全自动切题监控引擎
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
            _connection_ready.set()
            _log(f"[配置] 已手动指定辅助电脑地址: {_secondary_url}")
            return
        while _running and not _secondary_url:
            url = discover_secondary_pc(timeout=3.0)
            if url:
                _secondary_url = url
                _connection_ready.set()
                _log(f"[连接成功] 辅助电脑已对齐: {_secondary_url}")
                break
            time.sleep(2.0)

    t_disc = threading.Thread(target=_discovery_worker, daemon=True)
    t_disc.start()

    print(f"\n[截题就绪] 截题通道已待命！")
    print(f"  * 唯一截题方式：鼠标光标移到屏幕右上角停留 0.3 秒，立即截题并送达 DeepSeek！")
    print(f"  * 手机 / 辅助电脑常亮看板实时查看解题答案。")
    print(f"  * 完全静音静默后台运行，零键盘挂钩，零剪切板读写。")

    print("\n" + "#" * 65)
    print(f"【就绪】已连接至辅助电脑: {_secondary_url}")
    print(f"  鼠标移至屏幕右上角停留 0.3s 自动截题；")
    print(f"  手机/辅机常亮看板实时显示 DeepSeek 答案！")
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

