import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 监控区域配置文件（题目截图区域）
ROI_CONFIG_FILE = os.path.join(BASE_DIR, "master_roi_config.json")

# 是否启用鼠标热区触发
MOUSE_TRIGGER_ENABLED = True

# 屏幕右上角触发区域尺寸（像素，适度大小不占屏幕）
MOUSE_CORNER_WIDTH = 120
MOUSE_CORNER_HEIGHT = 80

# 鼠标在触发区内停留触发阈值（秒，停留0.3s即截屏）
MOUSE_HOVER_TIME = 0.3

# 鼠标触发后的冷却时间（秒，防止重复连续触发）
MOUSE_TRIGGER_COOLDOWN = 2.0

# 鼠标触发区自定义配置文件（若需要指定特定小区域）
MOUSE_TRIGGER_CONFIG_FILE = os.path.join(BASE_DIR, "master_mouse_trigger_config.json")

# 主电脑设置与上次连接记录
MASTER_CONFIG_FILE = os.path.join(BASE_DIR, "master_config.json")

# 本地最新截图调试留存路径
TEMP_IMAGE_PATH = os.path.join(BASE_DIR, "temp_capture.png")

# 主机待发送截图专属持久化目录（逐任务落盘，杜绝重启或崩溃丢图）
PENDING_UPLOAD_DIR = os.path.join(BASE_DIR, "pending_uploads")

# 截题模式配置：唯一只保留「鼠标在右上角停留 0.3s 截屏」
ENABLE_SCREEN_DIFF_TRIGGER = False  # 关闭画面像素帧差自动检测（彻底杜绝误报、动效干扰）
ENABLE_HOTKEY_SCREENSHOT = False    # 关闭其他按键截屏（中键、侧键、F8等全部关闭）
UPLOAD_INITIAL_QUESTION = False     # 启动时不自动上传，截题节奏 100% 由鼠标右上角停留触发掌控

# 画面变动触发阈值（当 ENABLE_SCREEN_DIFF_TRIGGER 为 True 时生效）
DIFF_THRESHOLD = 0.025

# 翻页防抖稳定时间（秒）
STABILIZE_DELAY = 0.8

# 画面采样间隔（秒）
POLL_INTERVAL = 0.25

# 防抖最长等待超时（秒）
MAX_STABILIZE_TIMEOUT = 4.0

# 自动截题触发后的冷却时间（秒）
AUTO_COOLDOWN = 2.0

# 辅助电脑 UDP 自动发现端口
DISCOVERY_PORT = 8888

