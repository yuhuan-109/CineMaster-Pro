# ==========================================
# CineMaster - AI 影视工业级分镜系统 (单文件版)
# 包含：智能选图、防崩溃布局、网络超时优化、风控拦截提示
# ==========================================

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import io
import requests
import time
import json
from PIL import Image, ImageTk

# ==========================================
# 全局常量
# ==========================================
COLOR_BG = "#1e1e2e"
COLOR_PANEL = "#2a2b3d"
COLOR_ACCENT = "#89b4fa"
COLOR_TEXT = "#cdd6f4"
COLOR_TEXT_DIM = "#6c7086"
COLOR_SUCCESS = "#a6e3a1"
COLOR_WARNING = "#f9e2af"
COLOR_ERROR = "#f38ba8"

FONT_MAIN = ("微软雅黑", 10)
FONT_TITLE = ("微软雅黑", 14, "bold")

# ==========================================
# 核心上下文
# ==========================================
class AppContext:
    def __init__(self):
        self.log_queue = queue.Queue()
        self.ui_event_queue = queue.Queue()
        self.stop_flag = False
        self.api_config = {}

    def log(self, message):
        self.log_queue.put(message)

    def push_ui_event(self, event_type, data=None):
        self.ui_event_queue.put({"type": event_type, "data": data})

# ==========================================
# 技能基类
# ==========================================
class BaseSkill:
    def __init__(self, ctx):
        self.ctx = ctx

# ==========================================
# 剧本生成技能
# ==========================================
class ScriptSkill(BaseSkill):
    def execute_generation(self, text, api_config):
        api_key = api_config.get("text_api_key")
        base_url = api_config.get("text_base_url")
        model = api_config.get("text_model")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        system_prompt = "你是一个专业的影视编剧和分镜师。请将用户提供的小说文本转换为工业级分镜剧本，包含景别、角度、运镜、光影、双语提示词等。"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "stream": False
        }
        
        try:
            res = requests.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=60)
            if res.status_code != 200:
                raise Exception(f"HTTP {res.status_code} - {res.text}")
            
            result = res.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            self.ctx.push_ui_event("script_done", {"text": content})
            self.ctx.log("[系统日志] 剧本生成成功！\n")
        except Exception as e:
            self.ctx.log(f"[系统日志] 剧本生成失败: {str(e)}\n")
        finally:
            self.ctx.push_ui_event("status", {"progress": False})

# ==========================================
# 图片生成技能
# ==========================================
class ImageSkill(BaseSkill):
    def execute_generation(self, prompt, api_config, count, aspect_ratio, resolution):
        api_key = api_config.get("media_api_key")
        base_url = api_config.get("media_base_url")
        img_model = api_config.get("img_model")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        url = f"{base_url.rstrip('/')}/images/generations"
        payload = {
            "model": img_model,
            "prompt": prompt,
            "n": count,
            "size": aspect_ratio,
            "response_format": "url"
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=60)
            if res.status_code != 200:
                raise Exception(f"HTTP {res.status_code} - {res.text}")
            
            res_json = res.json()
            images = res_json.get("data", []) or res_json.get("images", [])
            
            for idx, img_data in enumerate(images):
                img_url = img_data.get("url") or img_data.get("image_url")
                if img_url:
                    self.ctx.push_ui_event("image_done", {"url": img_url, "name": f"图片{idx+1}"})
            
            self.ctx.log(f"[系统日志] 成功生成 {len(images)} 张图片！\n")
        except Exception as e:
            self.ctx.log(f"[系统日志] 图片生成失败: {str(e)}\n")
        finally:
            self.ctx.push_ui_event("status", {"progress": False})

# ==========================================
# 视频生成技能 (含风控与超时优化)
# ==========================================
class VideoSkill(BaseSkill):
    def execute_generation(self, prompt, api_config, duration, aspect_ratio, resolution, ref_urls):
        api_key = api_config.get("media_api_key")
        base_url = api_config.get("media_base_url")
        vid_model = api_config.get("vid_model")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        try:
            is_seedance = "seedance-2" in vid_model.lower() or "seedance" in vid_model.lower()
            if is_seedance:
                self.ctx.log(f"[系统日志] 识别到 Seedance 模型，使用官方专用接口\n")
                url = f"{base_url.rstrip('/')}/contents/generations/tasks"
                content_array = [{"type": "text", "text": prompt}]
                for img_url in ref_urls:
                    content_array.append({"type": "image_url", "image_url": {"url": img_url}, "role": "reference_image"})
                payload = {"model": vid_model, "content": content_array, "generate_audio": True, "ratio": aspect_ratio, "duration": duration, "resolution": resolution, "watermark": False}
            else:
                self.ctx.log(f"[系统日志] 识别为通用模型，使用标准视频接口\n")
                url = f"{base_url.rstrip('/')}/video/generations"
                payload = {"model": vid_model, "prompt": prompt, "mode": "text-only", "duration": duration, "aspectRatio": aspect_ratio, "resolution": resolution, "generateAudio": True}
                if ref_urls:
                    payload["mode"] = "reference" 
                    payload["referenceImageUrls"] = ref_urls

            self.ctx.log(f"[系统日志] 正在发送视频请求到: {url}\n")
            
            res = requests.post(url, json=payload, headers=headers, timeout=60)
            
            self.ctx.log(f"[系统日志] 平台返回状态码: {res.status_code}\n")
            self.ctx.log(f"[系统日志] 平台返回内容: {res.text[:500]}\n")
            
            if res.status_code != 200: 
                raise Exception(f"HTTP {res.status_code} - {res.text}")

            res_json = res.json()
            if is_seedance:
                task_id = res_json.get("id")
                self.ctx.log(f"[系统日志] 视频任务已提交，任务ID: {task_id}\n")
                video_url = self._poll_seedance(base_url, headers, task_id)
            else:
                task_code = res_json.get("data", {}).get("taskCode") or res_json.get("task_id") or res_json.get("id")
                self.ctx.log(f"[系统日志] 视频任务已提交，任务码: {task_code}\n")
                video_url = self._poll_task(base_url, headers, task_code)
                
            self.ctx.push_ui_event("video_done", {"url": video_url})
            self.ctx.log(f"[系统日志] 视频生成成功！\n")
        except Exception as e:
            self.ctx.log(f"[系统日志] 视频生成失败: {str(e)}\n")
        finally:
            self.ctx.push_ui_event("status", {"text": "视频完毕", "btn_gen_vid": "normal", "progress": False})

    def _poll_task(self, base_url, headers, task_code):
        query_url = f"{base_url.rstrip('/')}/tasks/{task_code}"
        for _ in range(120):
            if self.ctx.stop_flag: raise Exception("用户停止")
            time.sleep(5)
            res = requests.get(query_url, headers=headers, timeout=60)
            if res.status_code == 200:
                res_json = res.json()
                data = res_json.get("data", {}) if "data" in res_json else res_json.get("task", {})
                if not data: data = res_json
                
                status = str(data.get("status", "")).upper()
                self.ctx.log(f"[系统日志] 视频轮询中... 状态: {status}\n")
                
                if "FAIL" in status or "ERROR" in status:
                    error_info = data.get("result", {}).get("error", {})
                    if error_info:
                        err_msg = error_info.get("userMessage") or error_info.get("message")
                        raise Exception(f"平台拦截: {err_msg}")
                    raise Exception("视频任务失败")
                    
                if "SUCCESS" in status or "DONE" in status or "COMPLETE" in status:
                    url = None
                    outputs = data.get("outputs", [])
                    if outputs and isinstance(outputs, list) and len(outputs) > 0:
                        url = outputs[0].get("url")
                    
                    if not url:
                        url = data.get("videoUrl") or data.get("video_url") or data.get("url") or \
                              data.get("output", {}).get("video_url") or data.get("output", {}).get("url") or \
                              data.get("results", {}).get("videos", [{}])[0].get("url") or data.get("video")
                    
                    if url: return url
                    else: raise Exception("视频任务成功但未找到URL字段")
        raise Exception("视频轮询超时")

    def _poll_seedance(self, base_url, headers, task_id):
        query_url = f"{base_url.rstrip('/')}/contents/generations/tasks/{task_id}"
        for _ in range(120):
            if self.ctx.stop_flag: raise Exception("用户停止")
            time.sleep(5)
            res = requests.get(query_url, headers=headers, timeout=60)
            if res.status_code == 200:
                res_json = res.json()
                status = str(res_json.get("status", "")).upper()
                self.ctx.log(f"[系统日志] 视频轮询中... 状态: {status}\n")
                
                if "FAILED" in status or "FAIL" in status or "ERROR" in status:
                    error_info = res_json.get("result", {}).get("error", {})
                    if error_info:
                        err_msg = error_info.get("userMessage") or error_info.get("message")
                        raise Exception(f"平台拦截: {err_msg}")
                    raise Exception("视频任务失败")
                    
                if "SUCCEEDED" in status or "SUCCESS" in status or "COMPLETE" in status:
                    video_url = res_json.get("content", {}).get("video_url")
                    if not video_url:
                        video_url = res_json.get("video_url") or res_json.get("url") or \
                                    res_json.get("output", {}).get("video_url") or res_json.get("output", {}).get("url")
                    if video_url: return video_url
                    raise Exception("任务成功但未找到 video_url")
        raise Exception("视频轮询超时")

# ==========================================
# 任务调度中心
# ==========================================
class Agent:
    def __init__(self, ctx):
        self.ctx = ctx
        self.script_skill = ScriptSkill(ctx)
        self.image_skill = ImageSkill(ctx)
        self.video_skill = VideoSkill(ctx)

    def generate_script(self, text, api_config):
        def task():
            try:
                self.ctx.log("[系统日志] 剧本生成任务已启动...\n")
                self.script_skill.execute_generation(text, api_config)
            except Exception as e:
                self.ctx.log(f"\n[系统日志] 剧本生成线程异常: {str(e)}\n")
                self.ctx.push_ui_event("status", {"progress": False})
        threading.Thread(target=task, daemon=True).start()

    def generate_images(self, prompt, api_config, count, aspect_ratio, resolution):
        def task():
            try:
                self.ctx.log("[系统日志] 图片生成任务已启动...\n")
                self.image_skill.execute_generation(prompt, api_config, count, aspect_ratio, resolution)
            except Exception as e:
                self.ctx.log(f"\n[系统日志] 图片生成线程异常: {str(e)}\n")
                self.ctx.push_ui_event("status", {"progress": False})
        threading.Thread(target=task, daemon=True).start()

    def generate_video(self, prompt, api_config, duration, aspect_ratio, resolution, ref_urls):
        def task():
            try:
                self.ctx.log("[系统日志] 视频生成任务已启动...\n")
                self.video_skill.execute_generation(prompt, api_config, duration, aspect_ratio, resolution, ref_urls)
            except Exception as e:
                self.ctx.log(f"\n[系统日志] 视频生成线程异常: {str(e)}\n")
                self.ctx.push_ui_event("status", {"btn_gen_vid": "normal", "progress": False})
        threading.Thread(target=task, daemon=True).start()

# ==========================================
# 主界面与交互逻辑
# ==========================================
class AppUI:
    def __init__(self, root, ctx, agent):
        self.root = root
        self.ctx = ctx
        self.agent = agent
        
        self.image_history = []
        self.video_ref_image_urls = []
        self.models_cache = {"image": [], "video": []}
        self.video_matched_ready = False
        self.pending_video_ref_urls = []
        
        self._setup_styles()
        self._build_ui()
        self._process_queues()

    def _setup_styles(self):
        self.root.configure(bg=COLOR_BG)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=COLOR_PANEL, foreground=COLOR_TEXT_DIM, padding=[15, 5], font=FONT_MAIN)
        style.map("TNotebook.Tab", background=[("selected", COLOR_ACCENT)], foreground=[("selected", COLOR_BG)])
        style.configure("TFrame", background=COLOR_PANEL)
        style.configure("TButton", background=COLOR_ACCENT, foreground=COLOR_BG, font=FONT_MAIN, borderwidth=0)
        style.map("TButton", background=[("active", COLOR_TEXT)])
        style.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=FONT_MAIN)
        style.configure("TEntry", fieldbackground=COLOR_BG, foreground=COLOR_TEXT, insertcolor=COLOR_TEXT, borderwidth=1)
        style.configure("Vertical.TScrollbar", background=COLOR_PANEL, troughcolor=COLOR_BG, borderwidth=0)

    def _build_ui(self):
        self.main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=COLOR_BG, sashwidth=5)
        self.main_pane.pack(fill=tk.BOTH, expand=True)
        self._build_left_panel()
        self._build_right_panel()

    def _build_left_panel(self):
        left_frame = tk.Frame(self.main_pane, bg=COLOR_BG)
        self.main_pane.add(left_frame, minsize=300, width=400)
        tk.Label(left_frame, text="CineMaster Pro", bg=COLOR_BG, fg=COLOR_ACCENT, font=FONT_TITLE).pack(pady=10)
        self.notebook = ttk.Notebook(left_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._build_text_tab()
        self._build_image_tab()
        self._build_video_tab()

    def _build_text_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="剧本生成")
        tk.Label(tab, text="输入小说文本:").pack(anchor="w", padx=10, pady=5)
        self.text_input = tk.Text(tab, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_TEXT, relief="flat", font=FONT_MAIN)
        self.text_input.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.btn_gen_script = tk.Button(tab, text="生成剧本", command=self._on_gen_script_click, bg=COLOR_ACCENT, fg=COLOR_BG, font=FONT_MAIN, relief="flat")
        self.btn_gen_script.pack(pady=10)

    def _build_image_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="图片生成")
        tk.Label(tab, text="图片提示词:").pack(anchor="w", padx=10, pady=5)
        self.entry_img_prompt = tk.Text(tab, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_TEXT, relief="flat", font=FONT_MAIN, height=5)
        self.entry_img_prompt.pack(fill=tk.X, padx=10, pady=5)
        param_frame = tk.Frame(tab, bg=COLOR_PANEL)
        param_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(param_frame, text="数量:").grid(row=0, column=0, padx=2, pady=5)
        self.combo_img_count = ttk.Combobox(param_frame, values=[1, 2, 3, 4], width=3, state="readonly")
        self.combo_img_count.set(2)
        self.combo_img_count.grid(row=0, column=1, padx=5)
        tk.Label(param_frame, text="比例:").grid(row=0, column=2, padx=2, pady=5)
        self.combo_img_ratio = ttk.Combobox(param_frame, values=["1:1", "16:9", "9:16"], width=5, state="readonly")
        self.combo_img_ratio.set("1:1")
        self.combo_img_ratio.grid(row=0, column=3, padx=5)
        self.btn_gen_img = tk.Button(tab, text="生成图片", command=self._on_gen_img_click, bg=COLOR_ACCENT, fg=COLOR_BG, font=FONT_MAIN, relief="flat")
        self.btn_gen_img.pack(pady=10)

    def _build_video_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="视频生成")
        tk.Label(tab, text="视频提示词:").pack(anchor="w", padx=10, pady=5)
        self.entry_vid_prompt = tk.Text(tab, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_TEXT, relief="flat", font=FONT_MAIN, height=5)
        self.entry_vid_prompt.pack(fill=tk.X, padx=10, pady=5)
        param_frame = tk.Frame(tab, bg=COLOR_PANEL)
        param_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(param_frame, text="时长:").grid(row=0, column=0, padx=2, pady=5)
        self.combo_vid_duration = ttk.Combobox(param_frame, values=[4, 5, 6, 7, 8, 9, 10], width=3, state="readonly")
        self.combo_vid_duration.set(5)
        self.combo_vid_duration.grid(row=0, column=1, padx=5)
        tk.Label(param_frame, text="比例:").grid(row=0, column=2, padx=2, pady=5)
        self.combo_vid_ratio = ttk.Combobox(param_frame, values=["16:9", "9:16", "1:1"], width=5, state="readonly")
        self.combo_vid_ratio.set("16:9")
        self.combo_vid_ratio.grid(row=0, column=3, padx=5)
        tk.Label(param_frame, text="分辨率:").grid(row=0, column=4, padx=2, pady=5)
        self.combo_vid_res = ttk.Combobox(param_frame, values=["480p", "720p", "1080p"], width=6, state="readonly")
        self.combo_vid_res.set("720p")
        self.combo_vid_res.grid(row=0, column=5, padx=5)

        self.ref_preview_canvas = tk.Canvas(tab, bg=COLOR_PANEL, highlightthickness=0, height=150)
        ref_preview_scroll = ttk.Scrollbar(tab, orient="vertical", command=self.ref_preview_canvas.yview)
        self.frame_vid_ref_inner = tk.Frame(self.ref_preview_canvas, bg=COLOR_PANEL)
        self.frame_vid_ref_inner.bind("<Configure>", lambda e: self.ref_preview_canvas.configure(scrollregion=self.ref_preview_canvas.bbox("all")))
        self.ref_preview_canvas.create_window((0, 0), window=self.frame_vid_ref_inner, anchor="nw")
        self.ref_preview_canvas.bind("<Configure>", lambda e: self.frame_vid_ref_inner.config(width=e.width))
        self.ref_preview_canvas.configure(yscrollcommand=ref_preview_scroll.set)
        self.ref_preview_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        ref_preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.btn_gen_vid = tk.Button(tab, text="🎬 生成视频 (智能匹配参考图)", command=self._on_gen_video_click, bg=COLOR_ACCENT, fg=COLOR_BG, font=FONT_MAIN, relief="flat")
        self.btn_gen_vid.pack(pady=10)
        self.label_vid_status = tk.Label(tab, text="等待生成...", fg=COLOR_TEXT_DIM)
        self.label_vid_status.pack()

    def _build_right_panel(self):
        right_frame = tk.Frame(self.main_pane, bg=COLOR_BG)
        self.main_pane.add(right_frame, minsize=400)
        tk.Label(right_frame, text="全文展示与历史记录", bg=COLOR_BG, fg=COLOR_ACCENT, font=FONT_TITLE).pack(pady=10)
        self.notebook_right = ttk.Notebook(right_frame)
        self.notebook_right.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        tab_log = ttk.Frame(self.notebook_right)
        self.notebook_right.add(tab_log, text="系统日志")
        self.log_text = tk.Text(tab_log, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_TEXT, relief="flat", font=FONT_MAIN, wrap="word")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll = ttk.Scrollbar(tab_log, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        tab_img = ttk.Frame(self.notebook_right)
        self.notebook_right.add(tab_img, text="图片历史")
        self.history_canvas = tk.Canvas(tab_img, bg=COLOR_PANEL, highlightthickness=0)
        hist_scroll = ttk.Scrollbar(tab_img, orient="vertical", command=self.history_canvas.yview)
        self.history_frame_inner = tk.Frame(self.history_canvas, bg=COLOR_PANEL)
        self.history_frame_inner.bind("<Configure>", lambda e: self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all")))
        self.history_canvas.create_window((0, 0), window=self.history_frame_inner, anchor="nw")
        self.history_canvas.bind("<Configure>", lambda e: self.history_frame_inner.config(width=e.width))
        self.history_canvas.configure(yscrollcommand=hist_scroll.set)
        self.history_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _process_queues(self):
        try:
            while not self.ctx.log_queue.empty():
                msg = self.ctx.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
            
        try:
            while not self.ctx.ui_event_queue.empty():
                event = self.ctx.ui_event_queue.get_nowait()
                self._handle_ui_event(event)
        except queue.Empty:
            pass
            
        self.root.after(100, self._process_queues)

    def _handle_ui_event(self, event):
        etype = event["type"]
        data = event["data"]
        if etype == "script_done":
            self.text_input.delete("1.0", tk.END)
            self.text_input.insert("1.0", data["text"])
        elif etype == "image_done":
            self._handle_image_done(data["url"], data["name"])
        elif etype == "video_done":
            self.label_vid_status.config(text="视频生成成功！")
            messagebox.showinfo("成功", f"视频已生成：\n{data['url']}")
        elif etype == "status":
            if "progress" in data and not data["progress"]:
                self.btn_gen_script.config(state=tk.NORMAL)
                self.btn_gen_img.config(state=tk.NORMAL)
                if "btn_gen_vid" in data:
                    self.btn_gen_vid.config(state=tk.NORMAL, text="🎬 生成视频 (智能匹配参考图)")

    def _handle_image_done(self, url, name):
        try:
            res = requests.get(url, timeout=30)
            pil_img = Image.open(io.BytesIO(res.content))
            pil_img.info.pop("icc_profile", None) # 消除 libpng 警告
            self.image_history.append({"url": url, "img": pil_img, "name": name})
            self._update_history_ui()
            self.ctx.log(f"[系统日志] 图片 {name} 下载并展示成功\n")
        except Exception as e:
            self.ctx.log(f"[系统日志] 图片下载失败: {str(e)}\n")

    def _update_history_ui(self):
        for widget in self.history_frame_inner.winfo_children(): widget.destroy()
        for idx, item in enumerate(self.image_history):
            row, col = idx // 3, idx % 3
            thumb = item["img"].copy()
            thumb.thumbnail((150, 100))
            tk_thumb = ImageTk.PhotoImage(thumb)
            lbl = tk.Label(self.history_frame_inner, image=tk_thumb, bg=COLOR_PANEL, cursor="hand2")
            lbl.image = tk_thumb # 防止垃圾回收
            lbl.grid(row=row, column=col, padx=10, pady=10)

    def _get_api_config(self):
        # 实际应用中应从配置文件或界面读取
        return {
            "text_api_key": "YOUR_TEXT_KEY",
            "text_base_url": "https://api.openai.com/v1",
            "text_model": "gpt-4o",
            "media_api_key": "YOUR_MEDIA_KEY",
            "media_base_url": "https://claw-open.feeling.ltd",
            "img_model": "dall-e-3",
            "vid_model": "doubao-seedance-2.0"
        }

    def _on_gen_script_click(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text: return
        self.btn_gen_script.config(state=tk.DISABLED)
        self.agent.generate_script(text, self._get_api_config())

    def _on_gen_img_click(self):
        prompt = self.entry_img_prompt.get("1.0", tk.END).strip()
        if not prompt: return
        self.btn_gen_img.config(state=tk.DISABLED)
        count = int(self.combo_img_count.get())
        ratio = self.combo_img_ratio.get()
        self.agent.generate_images(prompt, self._get_api_config(), count, ratio, "standard")

    def _on_gen_video_click(self):
        prompt = self.entry_vid_prompt.get("1.0", tk.END).strip()
        if not prompt:
            return

        if not self.video_matched_ready:
            # 第一次点击：智能匹配参考图
            matched_ref_urls = []
            for item in self.image_history:
                if item["name"] in prompt:
                    matched_ref_urls.append(item["url"])
                    self.ctx.log(f"[系统日志] 智能匹配到参考图: [{item['name']}]\n")
            
            if not matched_ref_urls and self.video_ref_image_urls:
                matched_ref_urls = self.video_ref_image_urls
            
            self.pending_video_ref_urls = matched_ref_urls
            
            # 在界面上展示匹配到的图片供用户确认
            for widget in self.frame_vid_ref_inner.winfo_children(): widget.destroy()
            if matched_ref_urls:
                tk.Label(self.frame_vid_ref_inner, text="已智能匹配以下参考图，请确认后点击下方按钮生成：", bg=COLOR_PANEL, fg=COLOR_ACCENT, font=FONT_MAIN).pack(anchor="w", pady=5)
                
                # 核心修复：全部使用 pack 布局，避免与 grid 冲突导致崩溃
                img_container = tk.Frame(self.frame_vid_ref_inner, bg=COLOR_PANEL)
                img_container.pack(fill=tk.BOTH, expand=True)
                
                for i, url in enumerate(matched_ref_urls):
                    for item in self.image_history:
                        if item["url"] == url:
                            img = item["img"].copy()
                            img.thumbnail((150, 100))
                            tk_img = ImageTk.PhotoImage(img)
                            lbl = tk.Label(img_container, image=tk_img, bg=COLOR_PANEL)
                            lbl.image = tk_img
                            lbl.pack(side=tk.LEFT, padx=10, pady=10)
                            break
                            
                self.btn_gen_vid.config(text="✅ 确认并生成视频")
            else:
                tk.Label(self.frame_vid_ref_inner, text="未匹配到参考图\n(可直接生成纯文本视频，或手动选择图片后再次点击)", bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, font=FONT_MAIN, width=30, height=8).pack()
                self.btn_gen_vid.config(text="✅ 确认生成 (无参考图)")
            
            self.video_matched_ready = True
        else:
            # 第二次点击：确认并生成
            self.btn_gen_vid.config(state=tk.DISABLED, text="生成中...")
            self.label_vid_status.config(text="正在生成视频...")
            
            try: duration = int(self.combo_vid_duration.get())
            except: duration = 5
            
            self.agent.generate_video(prompt, self._get_api_config(), duration, self.combo_vid_ratio.get(), self.combo_vid_res.get(), self.pending_video_ref_urls)
            
            # 恢复初始状态
            self.video_matched_ready = False
            self.btn_gen_vid.config(text="🎬 生成视频 (智能匹配参考图)")

# ==========================================
# 程序入口
# ==========================================
def main():
    root = tk.Tk()
    root.title("CineMaster - AI 影视工业级分镜系统")
    root.geometry("1280x800")
    root.minsize(1100, 700)
    
    try:
        root.iconbitmap("app.ico")
    except:
        pass

    ctx = AppContext()
    agent = Agent(ctx)
    app = AppUI(root, ctx, agent)
    
    root.mainloop()

if __name__ == "__main__":
    main()
