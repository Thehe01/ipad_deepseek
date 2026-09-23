import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 监控区域配置文件
ROI_CONFIG_FILE = os.path.join(BASE_DIR, "master_roi_config.json")

# 主电脑设置与上次连接记录
MASTER_CONFIG_FILE = os.path.join(BASE_DIR, "master_config.json")

# 本地最新截图调试留存路径
TEMP_IMAGE_PATH = os.path.join(BASE_DIR, "temp_capture.png")

# 画面变动触发阈值（0.06 表示 6% 的灰度差异率，用于识别题目文字与布局大面积变动，滤除微弱噪点）
DIFF_THRESHOLD = 0.06

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
