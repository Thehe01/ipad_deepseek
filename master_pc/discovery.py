import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import socket

import time
import requests
from master_config import DISCOVERY_PORT, MASTER_CONFIG_FILE

def load_saved_secondary_url():
    """读取上次成功连接的辅助电脑地址"""
    if os.path.exists(MASTER_CONFIG_FILE):
        try:
            with open(MASTER_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("secondary_url")
        except Exception:
            pass
    return None

def save_secondary_url(url):
    """保存辅助电脑连接地址"""
    try:
        data = {}
        if os.path.exists(MASTER_CONFIG_FILE):
            try:
                with open(MASTER_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["secondary_url"] = url
        with open(MASTER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def test_connection(url):
    """测试与辅助电脑的连通性（直连局域网，绕过系统网络代理）"""
    try:
        res = requests.get(f"{url}/api/status", proxies={"http": None, "https": None}, timeout=2.0)
        return res.status_code == 200
    except Exception:
        return False

def discover_secondary_pc(timeout=3.0):
    """通过 UDP 局域网广播自动寻找辅助电脑"""
    print(f"[局域网配对] 正在自动搜索辅助电脑 (监听端口 {DISCOVERY_PORT})...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(timeout)
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(2048)
                payload = json.loads(data.decode("utf-8"))
                if payload.get("service") == "ipad_deepseek_solver":
                    ip = payload.get("ip") or addr[0]
                    port = payload.get("port", 8080)
                    target_url = f"http://{ip}:{port}"
                    print(f"[自动配对成功] 发现辅助电脑广播: {target_url}")
                    if test_connection(target_url):
                        save_secondary_url(target_url)
                        return target_url
            except socket.timeout:
                break
            except Exception:
                pass
    except Exception as e:
        print(f"[提示] UDP 监听受限: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass

    # 兜底 1: 检查历史保存地址
    saved_url = load_saved_secondary_url()
    if saved_url:
        print(f"[尝试历史连接] 正在测试上次连接的辅助电脑: {saved_url} ...")
        if test_connection(saved_url):
            print(f"[连接成功] 成功复用历史连接: {saved_url}")
            return saved_url
        else:
            print(f"[连接失败] 无法连通上次保存的辅助电脑。")

    # 检查是否为无控制台的后台模式
    def _is_visible():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            u32 = ctypes.windll.user32
            h = k32.GetConsoleWindow()
            return bool(h and u32.IsWindowVisible(h))
        except Exception:
            return False

    if not _is_visible():
        print("[后台模式] 暂未连上辅助电脑，等待 3 秒后重试发现...")
        time.sleep(3.0)
        return discover_secondary_pc(timeout=3.0)

    # 兜底 2: 手动输入 IP（仅在前台可见窗口时交互）
    print("\n" + "!" * 60)
    print("【提示】未能自动扫描到辅助电脑，可能是局域网关闭了 UDP 广播。")
    print("请查看辅助电脑控制台上显示的网址（如 http://192.168.1.105:8080）")
    print("!" * 60)

    while True:
        raw_ip = input("\n请输入辅助电脑的 IP 地址或网址 (例如 192.168.1.105 或直接回车重试): ").strip()
        if not raw_ip:
            # 重新尝试自动搜索一次
            return discover_secondary_pc(timeout=3.0)
        
        if not raw_ip.startswith("http"):
            if ":" not in raw_ip:
                target_url = f"http://{raw_ip}:8080"
            else:
                target_url = f"http://{raw_ip}"
        else:
            target_url = raw_ip.rstrip("/")

        print(f"正在测试连接 {target_url} ...")
        if test_connection(target_url):
            print(f"[连接成功] 成功连接至辅助电脑: {target_url}")
            save_secondary_url(target_url)
            return target_url
        else:
            print(f"[连接失败] 无法连接到 {target_url}，请确认辅助电脑已启动且在同一 Wi-Fi 下。")
