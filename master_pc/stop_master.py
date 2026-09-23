import os
import psutil

killed = False
for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        cmd = p.info.get("cmdline") or []
        if any("master_main.py" in str(c) for c in cmd) and p.pid != os.getpid():
            p.kill()
            print(f"[已停止] 成功终止后台主电脑进程 PID: {p.pid}")
            killed = True
    except Exception:
        pass

if not killed:
    print("[提示] 当前没有检测到运行中的 master_pc 后台进程。")
