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

# 画面变动触发阈值（0.025 表示 2.5% 的灰度差异率，大幅提高对白底黑字文字细微变动的捕捉灵敏度）
DIFF_THRESHOLD = 0.025

# 翻页防抖稳定时间（秒，翻页或滑动后画面持续静止该时间即判定题目就绪）
STABILIZE_DELAY = 0.8

# 画面采样间隔（秒）
POLL_INTERVAL = 0.25

# 防抖最长等待超时（秒，若画面有局部倒计时或微小动效导致持续微抖，超过此时长进行强制对比上传）
MAX_STABILIZE_TIMEOUT = 4.0

# 自动截题触发后的冷却时间（秒，防止单题过渡动画导致连发）
AUTO_COOLDOWN = 2.0

# 是否在启动并连通后自动将当前屏幕显示的第 1 题上传
UPLOAD_INITIAL_QUESTION = True

# 全局快捷键设置
HOTKEY_TRIGGER = "ctrl+shift"

# 辅助电脑 UDP 自动发现端口
DISCOVERY_PORT = 8888

# 主电脑剪切板接收服务端口
CLIPBOARD_SERVER_PORT = 8081
