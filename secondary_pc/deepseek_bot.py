import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import queue
import threading
import uuid
from playwright.sync_api import sync_playwright
from secondary_config import (
    DEEPSEEK_URL,
    USER_DATA_DIR,
    ENABLE_R1,
    DEFAULT_PROMPT,
    SYSTEM_PROMPT,
    TEMP_RECEIVED_IMAGE,
    RECEIVED_DIR,
)

class DeepSeekBot:
    """
    负责启动并接管持久化 Chrome 浏览器，与 DeepSeek 网页端进行自动化交互。
    采用单线程事件循环队列设计，完全隔离 Playwright 线程上下文。
    """
    def __init__(self, on_answer_callback=None, on_status_callback=None):
        self.task_queue = queue.Queue()
        self.ready_event = threading.Event()
        self.is_running = False
        self.is_busy = False
        self.error = None
        self._worker_thread = None
        self.on_answer_callback = on_answer_callback
        self.on_status_callback = on_status_callback

    def start(self):
        """启动浏览器工作线程并等待其就绪"""
        self.is_running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        
        print("[DeepSeek] 正在启动独立 Chrome 浏览器，请稍候...")
        self.ready_event.wait()
        if self.error:
            raise RuntimeError(f"启动浏览器失败: {self.error}")
        print("[DeepSeek] 浏览器自动化引擎就绪！")

    def stop(self):
        """关闭浏览器与工作线程"""
        if self.is_running:
            self.task_queue.put(("QUIT", None))
            self.is_running = False
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=3.0)

    def send_question(self, image_input, prompt=None):
        """
        提交题目发送任务到工作队列。
        支持独立文件路径（str/Path）或内存图像二进制（bytes）。
        保证每个排队任务持有独立图片内容与专属独立文件，彻底杜绝排队多图并发覆盖。
        """
        if not self.is_running:
            print("[警告] DeepSeekBot 尚未启动！")
            return
        if self.is_busy:
            print("[提示] 上一题仍在处理或 DeepSeek 正在生成中，将排队发送...")

        # 确保每个任务持有完全独立的专属图片文件
        os.makedirs(RECEIVED_DIR, exist_ok=True)
        task_id = f"task_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        independent_file_path = os.path.join(RECEIVED_DIR, f"{task_id}.png")

        if isinstance(image_input, bytes):
            with open(independent_file_path, "wb") as f:
                f.write(image_input)
            image_bytes = image_input
        elif isinstance(image_input, str):
            src_path = os.path.abspath(image_input)
            with open(src_path, "rb") as f:
                image_bytes = f.read()
            # 若传入的已是位于 RECEIVED_DIR 下的独立 task_xxx 文件，直接复用；否则（如传入公共临时文件）创建独立副本
            if os.path.dirname(src_path) == os.path.abspath(RECEIVED_DIR) and os.path.basename(src_path).startswith("task_"):
                independent_file_path = src_path
            else:
                with open(independent_file_path, "wb") as f:
                    f.write(image_bytes)
        else:
            raise ValueError(f"不支持的图像输入类型: {type(image_input)}")

        self.task_queue.put(("SEND_QUESTION", {
            "image_path": independent_file_path,
            "image_bytes": image_bytes,
            "prompt": prompt if prompt is not None else DEFAULT_PROMPT
        }))

    def _worker_loop(self):
        """专用的 Playwright 工作线程"""
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        try:
            with sync_playwright() as p:
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized"
                ]
                
                context = None
                try:
                    # 优先尝试使用已安装的 Google Chrome 渠道
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=USER_DATA_DIR,
                        channel="chrome",
                        headless=False,
                        no_viewport=True,
                        ignore_default_args=["--enable-automation"],
                        args=launch_args
                    )
                except Exception:
                    # 回退到默认 Chromium
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=USER_DATA_DIR,
                        headless=False,
                        no_viewport=True,
                        ignore_default_args=["--enable-automation"],
                        args=launch_args
                    )

                page = context.pages[0] if context.pages else context.new_page()

                print(f"[DeepSeek] 打开页面: {DEEPSEEK_URL}")
                page.goto(DEEPSEEK_URL, wait_until="domcontentloaded")

                # 登录状态检测与引导
                self._wait_for_login(page)

                # 确保开启 R1 深度思考模式
                if ENABLE_R1:
                    self._ensure_r1_enabled(page)

                # 向当前会话注入全局系统规则提示词
                self._inject_system_prompt(page)

                # 恢复历史由于崩溃或退出未完成的排队图片
                self._recover_pending_tasks()

                # 通知主线程已完全就绪
                self.ready_event.set()

                # 任务消费主循环
                while self.is_running:
                    try:
                        task_type, payload = self.task_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    if task_type == "QUIT":
                        break
                    elif task_type == "SEND_QUESTION":
                        self.is_busy = True
                        task_img = payload.get("image_path")
                        retry_count = payload.get("retry_count", 0)
                        send_success = False
                        try:
                            self._do_send_question(page, task_img, payload["prompt"])
                            send_success = True
                        except Exception as e:
                            print(f"[错误] 发送题目失败: {e}")
                            if self.on_status_callback:
                                self.on_status_callback(f"⚠️ 题目发送失败: {e}")
                        finally:
                            self.is_busy = False
                            if send_success:
                                # 只有真正成功完成发送与生成，才清理专属临时文件并结束任务
                                try:
                                    if task_img and os.path.exists(task_img) and os.path.abspath(task_img) != os.path.abspath(TEMP_RECEIVED_IMAGE):
                                        os.remove(task_img)
                                except Exception:
                                    pass
                                self.task_queue.task_done()
                            else:
                                # 发送失败分支：绝不删除图片！保留图片文件，重新入队重试或保留供人工恢复
                                MAX_RETRIES = 3
                                if retry_count < MAX_RETRIES and self.is_running:
                                    payload["retry_count"] = retry_count + 1
                                    print(f"[DeepSeek] ⚠️ 任务失败，已完整保留图片文件 ({task_img})，3 秒后自动重新入队重试 (第 {payload['retry_count']}/{MAX_RETRIES} 次)...")
                                    time.sleep(3.0)
                                    if self.is_running:
                                        self.task_queue.put(("SEND_QUESTION", payload))
                                    self.task_queue.task_done()
                                else:
                                    print(f"[DeepSeek] ❌ 任务重试 {MAX_RETRIES} 次仍失败，保留原题目文件供排查与恢复: {task_img}")
                                    self.task_queue.task_done()

                try:
                    context.close()
                except Exception:
                    pass
        except Exception as e:
            self.error = e
            print(f"\n[错误] 浏览器引擎异常: {e}")
            self.ready_event.set()

    def _recover_pending_tasks(self):
        """扫描 received_questions 目录，将历史由于异常退出未完成的图片重新排队"""
        if not os.path.exists(RECEIVED_DIR):
            return
        leftovers = []
        try:
            # 清理历史可能遗留的 .tmp 碎片
            for fname in os.listdir(RECEIVED_DIR):
                if fname.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(RECEIVED_DIR, fname))
                    except Exception:
                        pass

            for fname in os.listdir(RECEIVED_DIR):
                if fname.startswith("task_") and fname.endswith(".png"):
                    p = os.path.join(RECEIVED_DIR, fname)
                    try:
                        if os.path.getsize(p) > 0:
                            leftovers.append((os.path.getmtime(p), p))
                    except Exception:
                        pass
            leftovers.sort(key=lambda x: x[0])
            for _, p in leftovers:
                self.send_question(p)
            if leftovers:
                print(f"[DeepSeek] [启动恢复] 发现 {len(leftovers)} 道历史未完成处理题目，已自动恢复排队！")
        except Exception as e:
            print(f"[DeepSeek] [启动恢复] 扫描历史任务异常: {e}")

    def _wait_for_login(self, page):
        """检查登录状态并等待用户完成首次登录"""
        input_selector = "textarea, #chat-input, div[contenteditable='true']"
        
        try:
            page.wait_for_selector(input_selector, timeout=5000, state="visible")
            print("[DeepSeek] 检测到已处于登录状态，准备就绪。")
            return
        except Exception:
            pass

        print("\n" + "="*60)
        print("【提示】检测到尚未登录 DeepSeek！")
        print("请在弹出的 Chrome 浏览器中手动完成登录（微信扫码 / 手机验证码）。")
        print("登录成功并进入聊天界面后，脚本将自动检测并继续...")
        print("="*60 + "\n")

        while self.is_running:
            try:
                elem = page.query_selector(input_selector)
                if elem and elem.is_visible():
                    print("[DeepSeek] 登录成功！会话已保存在本地目录中。")
                    time.sleep(1.0)
                    break
            except Exception:
                pass
            time.sleep(2.0)

    def _ensure_r1_enabled(self, page):
        """确保 DeepSeek 网页端的「深度思考 (R1)」开关已激活"""
        try:
            time.sleep(1.0)
            r1_button = page.locator('button:has-text("深度思考"), div:has-text("深度思考 (R1)")').first
            if r1_button.count() > 0 and r1_button.is_visible():
                class_attr = r1_button.get_attribute("class") or ""
                aria_checked = r1_button.get_attribute("aria-checked") or ""
                is_active = "active" in class_attr.lower() or aria_checked == "true"
                
                if not is_active:
                    r1_button.click()
                    print("[DeepSeek] 已自动开启「深度思考 (R1)」模式。")
                else:
                    print("[DeepSeek]「深度思考 (R1)」模式已经是激活状态。")
        except Exception as e:
            print(f"[提示] 检查 R1 开关提示: {e}")

    def _inject_system_prompt(self, page):
        """在会话初始时发送系统提示词，确立全局答题最高规范"""
        if not SYSTEM_PROMPT:
            return
        try:
            print("\n[DeepSeek] 正在向当前会话注入全局系统规则...")
            chat_input = page.locator('textarea, #chat-input, div[contenteditable="true"]').first
            chat_input.fill(SYSTEM_PROMPT)
            time.sleep(0.5)
            chat_input.press("Enter")
            print("[DeepSeek] 系统规则已发送，等待模型确认生效...")
            time.sleep(3.0)
            print("[DeepSeek] ✅ 全局系统规则已生效！后续做题只输出题号与答案/纯代码。\n")
        except Exception as e:
            print(f"[提示] 注入系统规则提示: {e}")

    def _do_send_question(self, page, image_path, prompt):
        """执行上传图片与发送 Prompt 的具体动作，包含发送前清理、发送按钮点击与闭环验证"""
        print(f"\n[DeepSeek] 准备投递题目截图: {os.path.basename(image_path)} ...")

        # 1. 发送前预清理：若上一题仍在生成先点击停止，并清空输入框遗留的历史附件，杜绝多图堆积
        page.evaluate("""() => {
            const stopBtn = Array.from(document.querySelectorAll('button, div[role="button"]')).find(b => {
                const t = (b.innerText || '') + (b.getAttribute('aria-label') || '');
                return t.includes('停止') || t.includes('Stop');
            });
            if (stopBtn) {
                try { stopBtn.click(); } catch(e) {}
            }
            const deleteBtns = document.querySelectorAll('.ds-file-preview button, [class*="file-item"] button, [class*="upload-item"] button, [class*="close"], [aria-label*="删除"]');
            deleteBtns.forEach(btn => {
                try { btn.click(); } catch(e) {}
            });
            const input = document.querySelector('textarea, #chat-input, div[contenteditable="true"]');
            if (input) {
                if (input.value !== undefined) input.value = '';
                if (input.innerText !== undefined) input.innerText = '';
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }""")
        time.sleep(0.3)

        # 2. 定位并注入新图片
        file_input = page.locator('input[type="file"]')
        if file_input.count() == 0:
            upload_btn = page.locator('button:has(svg), div[role="button"]:has(svg)').first
            file_input = page.locator('input[type="file"]')

        file_input.set_input_files(image_path)
        print("[DeepSeek] 截图已注入网页，等待图片上传与解析完成...")

        # 循环等待直到图片上传完成且无 loading 动画（最多等待 8 秒）
        for _ in range(16):
            time.sleep(0.5)
            is_uploading = page.evaluate("""() => {
                const loaders = document.querySelectorAll('.ds-loading, [class*="uploading"], [class*="loading-spinner"], [class*="progress"]');
                return loaders.length > 0;
            }""")
            if not is_uploading:
                break

        # 3. 聚焦输入框并填入提示词（若提示词为空，则纯发图片不输入文字）
        chat_input = page.locator('textarea, #chat-input, div[contenteditable="true"]').first
        chat_input.focus()
        if prompt and prompt.strip():
            chat_input.fill(prompt.strip())
            time.sleep(0.5)
        else:
            chat_input.fill("")
            time.sleep(0.2)

        # 4. 点击发送按钮与闭环检验（带重试机制）
        send_confirmed = False
        for attempt in range(4):
            clicked = page.evaluate("""() => {
                const input = document.querySelector('textarea, #chat-input, div[contenteditable="true"]');
                if (!input) return false;
                const container = input.closest('form, [class*="input-container"], [class*="chat-input"]') || document;
                const btns = Array.from(container.querySelectorAll('button, div[role="button"]'));
                const sendBtn = btns.reverse().find(b => {
                    const aria = (b.getAttribute('aria-label') || '') + (b.getAttribute('title') || '');
                    if (aria.includes('发送') || aria.includes('Send')) return true;
                    const svg = b.querySelector('svg');
                    if (svg && !aria.includes('上传') && !aria.includes('搜索') && !aria.includes('深度思考')) return true;
                    return false;
                });
                if (sendBtn && !sendBtn.disabled && !sendBtn.classList.contains('disabled')) {
                    sendBtn.click();
                    return true;
                }
                return false;
            }""")

            if not clicked:
                try:
                    chat_input.focus()
                    chat_input.press("Enter")
                except Exception:
                    pass

            time.sleep(1.2)

            is_sent = page.evaluate("""() => {
                const input = document.querySelector('textarea, #chat-input, div[contenteditable="true"]');
                const container = input?.closest('form, [class*="input-container"], [class*="chat-input"]') || document;
                const remainingAttachments = container.querySelectorAll('.ds-file-preview, [class*="file-item"], [class*="upload-item"]');
                const val = input ? (input.value || input.innerText || '').trim() : '';
                
                const hasStop = Array.from(document.querySelectorAll('button, div[role="button"]')).some(b => {
                    const t = (b.innerText || '') + (b.getAttribute('aria-label') || '');
                    return t.includes('停止') || t.includes('Stop');
                });

                if (remainingAttachments.length === 0 && val === '') return true;
                if (hasStop) return true;
                return false;
            }""")

            if is_sent:
                send_confirmed = True
                print("[DeepSeek] 题目已确认成功发出！正在等待模型思考与解题...")
                break
            else:
                print(f"[提示] 发送尚未响应 (第 {attempt+1}/4 次重试)，正在重试发送...")
                time.sleep(1.0)

        if not send_confirmed:
            print("\n[警告] 题目未能成功触发发送，正在自动清理输入框以防后续堆叠！")
            page.evaluate("""() => {
                const deleteBtns = document.querySelectorAll('.ds-file-preview button, [class*="file-item"] button, [class*="upload-item"] button, [class*="close"], [aria-label*="删除"]');
                deleteBtns.forEach(btn => {
                    try { btn.click(); } catch(e) {}
                });
                const input = document.querySelector('textarea, #chat-input, div[contenteditable="true"]');
                if (input) {
                    if (input.value !== undefined) input.value = '';
                    if (input.innerText !== undefined) input.innerText = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }""")
            if self.on_status_callback:
                self.on_status_callback("⚠️ 题目发送未响应，已自动清空输入框，正在准备重试...")
            raise RuntimeError("题目未能成功触发发送（输入框无响应或发送按钮未生效）")

        if self.on_status_callback:
            self.on_status_callback("🟡 DeepSeek R1 正在深度思考解题...")
        
        # 5. 实时等待并捕获生成结果
        start_wait = time.time()
        max_wait_time = 120
        last_answer = ""
        generation_completed = False
        
        time.sleep(2.0)

        # 提取真实排版文本与代码的 JS 脚本
        # 优先使用 React Fiber 获取纯净无损的原生 Markdown（零 UI 杂物、100% 官方换行和缩进）
        # 备选使用 DOM 过滤：剔除复制/下载按钮，使用 <pre style="white-space: pre !important;"> 保证换行不丢失
        extract_markdown_js = """() => {
            const markdowns = document.querySelectorAll('.ds-markdown, [class*="markdown"]');
            if (!markdowns || markdowns.length === 0) return "";
            const latest = markdowns[markdowns.length - 1];

            // 1. 优先尝试从 React Fiber 读取原始 Markdown 数据流
            try {
                const fiberKey = Object.keys(latest).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (fiberKey) {
                    const queue = [latest[fiberKey]];
                    const visited = new Set();
                    let count = 0;
                    while (queue.length > 0 && count < 100) {
                        count++;
                        const f = queue.shift();
                        if (!f || visited.has(f)) continue;
                        visited.add(f);

                        const props = f.memoizedProps;
                        if (props) {
                            if (typeof props.content === 'string' && props.content.trim().length > 0) {
                                return props.content.trim();
                            }
                            if (typeof props.markdown === 'string' && props.markdown.trim().length > 0) {
                                return props.markdown.trim();
                            }
                            if (typeof props.text === 'string' && props.text.trim().length > 0) {
                                return props.text.trim();
                            }
                        }
                        if (f.return) queue.push(f.return);
                        if (f.child) queue.push(f.child);
                        if (f.sibling) queue.push(f.sibling);
                    }
                }
            } catch(e) {}

            // 2. 备用方案：挂载到真实 DOM 树进行无损过滤提取
            const holder = document.createElement('div');
            holder.style.cssText = 'position: fixed; left: -9999px; top: -9999px; width: 1200px; visibility: hidden; pointer-events: none;';
            document.body.appendChild(holder);

            try {
                const clone = latest.cloneNode(true);
                holder.appendChild(clone);

                // A. 移除思考过程
                clone.querySelectorAll('[class*="think"], .ds-think, [class*="thinking"]').forEach(el => el.remove());

                // B. 彻底清理复制/下载按钮、操作栏、图标等所有非代码文本
                clone.querySelectorAll('button, [role="button"], [class*="action"], [class*="tools"], [aria-label*="复制"], [aria-label*="下载"]').forEach(el => el.remove());

                // C. 处理代码块：使用 pre 标签（保留 white-space: pre !important），剔除语言头和按钮文本
                clone.querySelectorAll('pre').forEach(pre => {
                    pre.querySelectorAll('button, [class*="header"], [class*="toolbar"], [class*="action"]').forEach(b => b.remove());

                    const codeEl = pre.querySelector('code');
                    const langClass = (codeEl ? (codeEl.className || '') : (pre.className || ''));
                    const langMatch = langClass.match(/language-([\\w+#-]+)/i);
                    const lang = langMatch ? langMatch[1] : '';

                    let codeText = (codeEl ? (codeEl.innerText || codeEl.textContent) : (pre.innerText || pre.textContent)) || '';
                    // 彻底清除代码开头的“java复制下载”、“复制下载”等遗留残留
                    codeText = codeText.replace(/^(?:[a-zA-Z0-9+#-]+\\s*)?(?:复制|下载|Copy|Download)\\s*(?:复制|下载|Copy|Download)?\\s*/i, '');
                    codeText = codeText.trim();

                    const preNew = document.createElement('pre');
                    preNew.style.cssText = 'white-space: pre !important;';
                    preNew.innerText = '\\n\\n```' + lang + '\\n' + codeText + '\\n```\\n\\n';
                    pre.replaceWith(preNew);
                });

                // D. 处理列表项
                clone.querySelectorAll('li').forEach(li => {
                    li.prepend(document.createTextNode('- '));
                });

                let text = clone.innerText.trim();
                // 最终清洗：避免行内残留 ```java复制下载
                text = text.replace(/```([a-zA-Z0-9+#-]*)\\s*(?:复制|下载|Copy|Download)+/gi, '```$1\\n');
                return text;
            } finally {
                holder.remove();
            }
        }"""

        while time.time() - start_wait < max_wait_time:
            try:
                current_text = page.evaluate(extract_markdown_js)

                is_generating = page.evaluate("""() => {
                    const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
                    const hasStop = buttons.some(b => {
                        const t = (b.innerText || '') + (b.getAttribute('aria-label') || '');
                        return t.includes('停止') || t.includes('Stop');
                    });
                    if (hasStop) return true;
                    const loading = document.querySelector('.ds-loading, [class*="loading"]');
                    return !!loading;
                }""")

                if current_text:
                    last_answer = current_text

                if last_answer and not is_generating:
                    time.sleep(1.2)
                    final_text = page.evaluate(extract_markdown_js)
                    if final_text:
                        last_answer = final_text
                    generation_completed = True
                    break

            except Exception:
                pass

            time.sleep(0.8)


        # 答案生成完成性判定：
        # 必须显式标记 generation_completed 为 True 且 last_answer 非空；
        # 若达到 max_wait_time 超时退出且未生成完毕（即使已产生部分半截文本），也绝不能发布为完整答案，必须抛出 TimeoutError 并保留原图！
        if not generation_completed or not last_answer:
            # 如果超时仍处于生成状态，尝试点击停止按钮终止流式生成，避免后续污染
            try:
                page.evaluate("""() => {
                    const stopBtn = Array.from(document.querySelectorAll('button, div[role="button"]')).find(b => {
                        const t = (b.innerText || '') + (b.getAttribute('aria-label') || '');
                        return t.includes('停止') || t.includes('Stop');
                    });
                    if (stopBtn) {
                        try { stopBtn.click(); } catch(e) {}
                    }
                }""")
            except Exception:
                pass

            if last_answer:
                print(f"\n[错误] 本题等待 DeepSeek 生成答案超时 ({max_wait_time} 秒未生成完毕，仅获取到部分内容，判定失败并保留原图)！")
                if self.on_status_callback:
                    self.on_status_callback(f"⚠️ 解题超时未完成 (仅输出部分内容)，保留题目并准备重试...")
                raise TimeoutError(f"等待 DeepSeek 解题响应超时 ({max_wait_time} 秒未生成完毕，仅获取到部分回答)")
            else:
                print(f"\n[错误] 本题等待 DeepSeek 生成答案超时 ({max_wait_time} 秒未获取到有效回答)！")
                if self.on_status_callback:
                    self.on_status_callback(f"⚠️ 解题响应超时 ({max_wait_time}s)，保留题目并准备重试...")
                raise TimeoutError(f"等待 DeepSeek 解题响应超时 ({max_wait_time} 秒未获取到有效回答)")

        # 1. 第一时间以最高优先级发布答案，零延迟呈现给用户/手机看板
        print("\n" + "=" * 60)
        print(f"[DeepSeek 答案已生成并同步] >>>\n{last_answer}")
        print("=" * 60 + "\n")
        if self.on_answer_callback:
            self.on_answer_callback(last_answer)

        # 2. 答案发布完成后，在后台为下一题检查并确保「深度思考 (R1)」开关已激活
        if ENABLE_R1:
            try:
                time.sleep(0.5)
                self._ensure_r1_enabled(page)
            except Exception:
                pass
