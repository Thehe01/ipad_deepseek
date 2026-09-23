import os
import sys
import subprocess

killed = False

# 1. 尝试使用 psutil 优雅查找并结束
try:
    import psutil
    current_pid = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = p.info.get("cmdline") or []
            if any("master_main.py" in str(c) for c in cmd) and p.pid != current_pid:
                p.kill()
                print(f"[已停止] 成功终止后台主电脑进程 PID: {p.pid}")
                killed = True
        except Exception:
            pass
except ImportError:
    pass

# 2. 若 psutil 不可用或未找到，使用 Windows 原生 PowerShell 进行进程扫描
if not killed:
    try:
        current_pid = os.getpid()
        ps_cmd = (
            f'Get-CimInstance Win32_Process | '
            f'Where-Object {{ ($_.CommandLine -like "*master_main*") -and ($_.ProcessId -ne {current_pid}) }} | '
            f'ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force; Write-Output $_.ProcessId }}'
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5
        )
        pids = [line.strip() for line in res.stdout.splitlines() if line.strip().isdigit()]
        if pids:
            for pid in pids:
                print(f"[已停止] 成功终止后台主电脑进程 PID: {pid}")
            killed = True
    except Exception:
        pass

if not killed:
    print("[提示] 当前没有检测到运行中的 master_pc 后台进程。")

