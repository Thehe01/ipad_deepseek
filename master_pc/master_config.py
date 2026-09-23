import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 监控区域配置文件
ROI_CONFIG_FILE = os.path.join(BASE_DIR, "master_roi_config.json")

# 主电脑设置与上次连接记录
MASTER_CONFIG_FILE = os.path.join(BASE_DIR, "master_config.json")

# 本地截图保存路径
TEMP_IMAGE_PATH = os.path.join(BASE_DIR, "temp_capture.png")

# 画面变动触发阈值（2.5% 敏感度）
DIFF_THRESHOLD = 0.025

# 翻页防抖等待时间（秒）
STABILIZE_DELAY = 1.0

# 画面采样频率（秒）
POLL_INTERVAL = 0.3

# 全局快捷键设置
HOTKEY_TRIGGER = "ctrl+shift"  # 手动立即截题并发送

# 辅助电脑 UDP 自动发现端口
DISCOVERY_PORT = 8888

# 主电脑剪切板接收服务端口（辅助电脑把代码答案 POST 回来）
CLIPBOARD_SERVER_PORT = 8081
