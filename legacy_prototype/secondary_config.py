import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DeepSeek 网页端地址
DEEPSEEK_URL = "https://chat.deepseek.com"

# 浏览器持久化目录（保留登录态）
USER_DATA_DIR = os.path.join(BASE_DIR, "deepseek_user_data")

# 服务端 HTTP 端口（同时供 iPhone 看板与主电脑传图使用）
HTTP_PORT = 8080

# 局域网 UDP 自动发现端口
DISCOVERY_PORT = 8888

# 是否启用 DeepSeek-R1 深度思考模式
ENABLE_R1 = True

# 会话启动时发送的全局系统提示词（题号与答案同行同格式，Markdown代码块包裹且无注释，严禁解析推导）
SYSTEM_PROMPT = (
    "【系统最高规则设定】从现在起，你是一个极度严苛的考试解题引擎，请严格遵守以下输出格式：\n\n"
    "1. 【题号与答案同格式同排】：每道题格式为【题号 + 答案选项】（如：【第1题】 C 或 1. C），题号与选项在同一行直接连着输出，无需拆成单独行；若有多道小题则逐行按题号列出（如 1. A \\n 2. D）；\n\n"
    "2. 【选择题/填空题】：只输出【题号 + 最终答案/选项】（严禁输出任何解题过程、推导或解析废话）；\n\n"
    "3. 【代码/编程题】：第一行输出题号（如【第3题】或原图题号），随后输出完整源代码，源代码必须用标准 Markdown 代码块包裹（如 ```java ... ```）以保留完整缩进和换行。代码中严禁包含任何注释（严禁 //、/* */、# 等），代码前后严禁输出任何思路说明或废话！\n\n"
    "如果完全理解，请仅回复：【收到，题号与答案输出规范已生效】"
)

# 后续每道题附带的提示词：强制题号与答案同排，代码换行完整且无注释
DEFAULT_PROMPT = (
    "【解题规范】仔细阅读图片中的题目：\n"
    "1. 题号与答案同格式同排：如【第1题】 C 或 1. C；多道小题逐行按题号列出；\n"
    "2. 选择/填空题：只输出题号和答案选项，严禁解析推导；\n"
    "3. 编程代码题：第一行输出题号，随后输出标准 Markdown 代码块（严禁在代码中写任何注释，严禁任何废话思路）。"
)

# 临时接收的题目图片存储路径
TEMP_RECEIVED_IMAGE = os.path.join(BASE_DIR, "temp_received_question.png")
