import os

# 项目基础目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DeepSeek 网页端地址
DEEPSEEK_URL = "https://chat.deepseek.com"

# 浏览器持久化用户数据目录（保留登录状态）
USER_DATA_DIR = os.path.join(BASE_DIR, "deepseek_user_data")

# 监控区域配置文件
ROI_CONFIG_FILE = os.path.join(BASE_DIR, "roi_config.json")

# 截图保存路径
TEMP_IMAGE_PATH = os.path.join(BASE_DIR, "temp_question.png")

# 图像变动检测阈值（0.0 ~ 1.0，值越小越敏感，默认 0.025 即 2.5% 的像素变化即触发）
DIFF_THRESHOLD = 0.025

# 翻页防抖等待时间（秒）：检测到画面变动后，等待该秒数确保翻页动画/滚动结束且画面静止
STABILIZE_DELAY = 1.0


# 画面采样检测间隔（秒）
POLL_INTERVAL = 0.3

# 是否默认启用 DeepSeek-R1 深度思考模式
ENABLE_R1 = True

# 会话启动时首条发送的全局系统提示词（立下最高答题规则：保留题号、代码用 Markdown 包裹、无注释无废话）
SYSTEM_PROMPT = (
    "【系统规则设定】从现在起，你是一个极度严苛的题目求解引擎，请严格遵守以下最高输出规范：\n\n"
    "1. 必须保留原题题号（例如：【第1题】C 或 1. C；若包含多道小题则逐一按题号标出，如 1. A 2. D）；\n\n"
    "2. 选择题/填空题：只输出【题号 + 最终答案/选项】（严禁输出任何解题过程、推导或解析）；\n\n"
    "3. 代码/编程题：只输出【题号 + 完整源代码】，源代码必须使用 Markdown 代码块包裹（如 ```java ... ```），以保留缩进和语法高亮。代码中严禁包含任何注释（严禁 //、/* */、# 等）。代码前后严禁输出任何思路说明或废话！\n\n"
    "如果完全理解，请仅回复：【收到，题号与答案输出规范已生效】"
)

# 后续每道题纯发图片，不附加任何文字提示词
DEFAULT_PROMPT = ""




# 全局快捷键设置
HOTKEY_TRIGGER = "f8"  # 手动立即截题并发送
HOTKEY_PAUSE = "f9"    # 暂停 / 恢复自动监控

# 局域网大字看板服务端口（iPhone 访问端口）
WEB_SERVER_PORT = 8080

