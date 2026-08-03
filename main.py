import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
import openai
import httpx
import threading
import json
import os
import hmac
import hashlib
import base64
import time
import uuid
import platform
import requests
from PIL import Image, ImageTk
import io
import subprocess
import re
import sys
import ctypes
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= macOS 应用数据目录 =================
# Finder 启动 .app 时工作目录不固定，配置和授权必须放在用户可写目录。
APP_DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "CineMaster")
os.makedirs(APP_DATA_DIR, exist_ok=True)
BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# ================= 高 DPI 适配 (必须放在最前面) =================
if platform.system() == 'Windows':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ================= 授权验证系统 =================
_OBFUSCATED_KEY = bytes([83, 116, 111, 114, 121, 98, 111, 97, 114, 100, 95, 50, 48, 50, 52, 95, 83, 117, 112, 101, 114, 95, 83, 101, 99, 114, 101, 116, 95, 75, 101, 121, 33, 64, 35])
SECRET_KEY = _OBFUSCATED_KEY.decode('utf-8')
LICENSE_FILE = os.path.join(APP_DATA_DIR, "license.dat")
BUNDLED_LICENSE_FILE = os.path.join(BUNDLE_DIR, "license.dat")
if not os.path.exists(LICENSE_FILE) and os.path.exists(BUNDLED_LICENSE_FILE):
    try:
        import shutil
        shutil.copy2(BUNDLED_LICENSE_FILE, LICENSE_FILE)
    except OSError:
        pass

def get_machine_code():
    mac = uuid.getnode()
    node = platform.node()
    processor = platform.processor()
    raw_str = f"{mac}-{node}-{processor}"
    md5_hash = hashlib.md5(raw_str.encode('utf-8')).hexdigest()[:16]
    return md5_hash.upper()

def validate_license(code, current_machine_code):
    try:
        decoded = base64.b64decode(code.encode('utf-8'))
        parts = decoded.split(b"||")
        if len(parts) != 2: return False, "激活码格式错误"
        msg_str, hmac_hash = parts
        expected_hmac = hmac.new(SECRET_KEY.encode('utf-8'), msg_str, hashlib.sha256).digest()
        if not hmac.compare_digest(hmac_hash, expected_hmac): return False, "激活码无效或被篡改"
        msg_parts = msg_str.decode('utf-8').split("|")
        if len(msg_parts) != 2: return False, "激活码数据损坏"
        lic_machine_code, expiry_str = msg_parts
        if lic_machine_code != current_machine_code: return False, "激活码与当前设备不匹配"
        expiry = int(expiry_str)
        if time.time() > expiry: return False, "激活码已过期"
        return True, "验证成功"
    except Exception as e:
        return False, f"解析错误：{str(e)}"

def check_license_on_start():
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            code = data.get("code")
            last_run = data.get("last_run", 0)
            if time.time() < last_run - 60: return False, "检测到系统时间异常回拨，授权失效！"
            valid, msg = validate_license(code, get_machine_code())
            if valid: return True, "验证成功"
            else: return False, msg
        except: pass
    return False, "未找到授权文件"

def save_license_and_time(code):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump({"code": code, "last_run": time.time()}, f)

def update_last_run_time():
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f: data = json.load(f)
            data["last_run"] = time.time()
            with open(LICENSE_FILE, "w", encoding="utf-8") as f: json.dump(data, f)
        except: pass

class ActivationDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("软件激活")
        self.geometry("450x350")
        self.resizable(False, False)
        self.grab_set()
        self.machine_code = get_machine_code()
        self.activated = False
        tk.Label(self, text="请将下方【机器码】发送给管理员获取激活码", font=("微软雅黑", 10, "bold")).pack(pady=(20, 5))
        frame_mc = tk.Frame(self)
        frame_mc.pack(pady=5)
        entry_mc = tk.Entry(frame_mc, width=25, font=("微软雅黑", 11, "bold"), justify='center', fg="blue")
        entry_mc.insert(0, self.machine_code)
        entry_mc.config(state='readonly')
        entry_mc.pack(side=tk.LEFT, padx=5)
        tk.Button(frame_mc, text="复制机器码", font=("微软雅黑", 9), command=self.copy_mc).pack(side=tk.LEFT)
        tk.Label(self, text="请输入激活码：", font=("微软雅黑", 10, "bold")).pack(pady=(15, 5))
        self.entry_code = tk.Entry(self, width=40, font=("微软雅黑", 10))
        self.entry_code.pack(pady=5)
        tk.Button(self, text="立即激活", font=("微软雅黑", 12, "bold"), bg="#4CAF50", fg="white", command=self.try_activate).pack(pady=15)

    def copy_mc(self):
        self.clipboard_clear()
        self.clipboard_append(self.machine_code)
        messagebox.showinfo("提示", "机器码已复制到剪贴板！", parent=self)

    def try_activate(self):
        code = self.entry_code.get().strip()
        if not code:
            messagebox.showwarning("提示", "请输入激活码！", parent=self)
            return
        valid, msg = validate_license(code, self.machine_code)
        if valid:
            save_license_and_time(code)
            self.activated = True
            messagebox.showinfo("成功", "激活成功！感谢您的使用。", parent=self)
            self.destroy()
        else:
            messagebox.showerror("激活失败", f"{msg}\n请检查您的激活码是否正确。", parent=self)

# ================= 配置文件处理 =================
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
BUNDLED_CONFIG_FILE = os.path.join(BUNDLE_DIR, "cinemaster_config.json")

def load_config():
    default_config = {
        "api_key": "", "base_url": "https://claw-open.feeling.ltd/api/v1/open", "model_name": "doubao-seed-2.0-lite",
        "media_api_key": "", "media_base_url": "https://claw-open.feeling.ltd/api/v1/open", 
        "img_model": "doubao-seedream-4.5", "vid_model": "doubao-seedance-2-0-260128"
    }
    config_source = CONFIG_FILE if os.path.exists(CONFIG_FILE) else BUNDLED_CONFIG_FILE
    if os.path.exists(config_source):
        try:
            with open(config_source, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
            return default_config
        except: pass
    return default_config

def save_config():
    config = {
        "api_key": entry_api_key.get().strip(), "base_url": entry_base_url.get().strip(), "model_name": combo_text_model.get().strip(),
        "media_api_key": entry_media_api_key.get().strip(), "media_base_url": entry_media_base_url.get().strip(), 
        "img_model": combo_img_model.get().strip(), "vid_model": combo_vid_model.get().strip()
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, ensure_ascii=False, indent=4)
    show_toast("配置已保存", "success")

# ================= 系统提示词区 =================
SYSTEM_PROMPT = """# 小说转分镜全链路自动化系统 (V4.0 动态运镜强化版)
你现在是集【顶级影视编剧】、【全资产大师V3.0】、【分镜大师V4.0(动态运镜强化版)】于一体的超级智能体。你的核心任务是：将用户输入的小说文本，精准、自动化地转化为符合影视工业标准的分集剧本、全类资产（角色/场景/道具）以及具备极强画面动感与光影连贯性的分镜资产。
# 绝对禁止事项（最高优先级）
1. 严禁生成任何示例、演示文本、占位符或与用户输入小说无关的内容。
2. 所有输出必须100%基于用户输入的小说文本进行转化，不得自行编造任何情节、人物或对话。
3. 当本设定被激活时，你的第一句话且只能是这句话：“系统设定已加载。请先告诉我单集目标时长是多少（可选1-3分钟）？确认时长后，请发送需要转化的小说文本。” 在收到用户的时长确认和小说文本前，绝对不得输出任何其他内容。
4. 严禁生成任何暴力、血腥、色情及违规描写，必须用温和的影视化语言进行转化，确保所有台词、动作描述及AI提示词符合安全规范。
# 核心执行规则
1. 台词与OS绝对保真：必须完整保留小说原文中的所有对话与旁白，不得删减、不得概括、不得改写。小说中的长篇大论也必须原封不动放入台词区。
2. 心理活动提取：将小说中角色的内心想法、心理描写，提取为剧本中的“内心OS（画外音）”，同样必须完整保留原文，不得改写。
3. 角色性格外化：在剧本正文写作时，必须根据【角色资产】中提取的“性格特点”，为角色添加符合其性格的微表情、肢体动作和语气提示，禁止在正文中直接使用形容词描述性格，而要转化为具体动作。
4. 视觉化改写与场景切换：小说中一旦发生地点或时间的变化，必须严格切换场景。场景刻画必须极致简化，仅用几个字点明环境特征，禁止任何光影、氛围的细致描写。
5. 资产一致性：在剧本和分镜中出现的角色形象、服装、道具，必须与前面生成的资产卡严格对应。
6. 分集与时长控制：1分钟剧本的台词/OS容量约为 150-200字。必须严格按照用户确认的单集时长截取小说内容生成本集剧本。
7. 分镜台词拆分铁律：台词必须完整保留。台词时长按正常人语速（约3-4字/秒）计算。单个分镜时长限制≤10s（即最多容纳约30-40字台词）。若台词超出单镜时长限制，必须自动拆分为多个分镜，分镜数量可无限增加，但台词绝不能删减。
8. 动态运镜设计：分镜必须详细描述机位运动轨迹、速度与起幅落幅，禁止大量使用纯固定镜头（除非为特殊情绪表达），需通过推拉摇移跟升降等动态运镜增加画面叙事张力。
9. 光影色调连贯性：光影与色调必须与剧情发展、场景空间物理逻辑严格匹配。相邻镜头之间的光源方向、色温、光比及整体色调必须保持视觉连贯；若发生时间流逝、开关灯或场景切换，必须在分镜中明确标注过渡状态（如“承接上镜冷光”、“过渡至暖黄”），严禁出现无逻辑的视觉突变。
10. 双语提示词强制输出：所有的角色、场景、道具、分镜资产，在输出【中文AI提示词】后，必须紧接输出对应的【英文AI提示词】。英文提示词必须是中文的精准翻译，使用半角逗号分隔关键词，去除冗余连接词，直接适配Midjourney/Stable Diffusion等AI绘图工具。
# 自动化链路执行流程
当用户发送小说文本后，系统必须按以下链路**一次性、全自动**完成单集的全部产出，中途不得停顿询问：
## 链路步骤一：剧本生成与基础角色提取
1. 提取并输出【剧本信息】与【A. 剧本基础角色资产】。
2. 紧接着直接开始按标准格式生成【B. 剧本正文】（第1集），从小说开头推进剧情。
3. 当本集台词与OS总字数达到该时长对应的上限时，立即停止生成后续剧情。
## 链路步骤二：全资产拆解 (全资产大师 V3.0)
剧本正文生成完毕后，自动接续执行：
1. 扫描刚生成的本集剧本，识别题材、时代、角色、场景、道具。
2. 生成【C. 角色资产】（500-800字中文提示词 + 对应英文提示词，含4区域布局段）。
3. 生成【D. 场景资产】（400-600字中文提示词 + 对应英文提示词，七层递进结构，含适配人物，画质尾缀）。
4. 生成【E. 道具资产】（200-400字中文提示词 + 对应英文提示词，四视图或单图，材质可触摸）。
## 链路步骤三：分镜资产生成 (全资产大师 V4.0 动态运镜强化版)
全资产拆解完毕后，自动接续执行：
1. 根据本集剧本正文，逐句拆解分镜。
2. 严格执行单镜≤10s限制，超长台词自动拆分。
3. 生成【F. 分镜资产】，包含景别、角度、焦段、构图、**运镜设计**、场景/角色调用、完整台词、**画面与视听细节(含光影连贯性说明)**、300-500字中文AI提示词及自检，以及对应的英文AI提示词。
## 链路步骤四：分镜图提示词生成 (纯净绘图版)
分镜资产生成完毕后，自动接续执行：
1. 根据已生成的分镜资产，提取每个镜头的核心画面。
2. 严格按照【G. 分镜图提示词规范】输出纯净的、专为AI绘图优化的中英文提示词，严禁出现运镜、音效等词汇。
## 链路步骤五：剪映剪辑指导方案生成
分镜图提示词生成完毕后，自动接续执行：
1. 根据生成的剧本和分镜，规划BGM、音效、转场和特效。
2. 严格按照【H. 剪映专业剪辑指导方案规范】输出结构化文本内容。
## 链路步骤六：循环与终止
当本集的剧本、全资产、分镜、分镜图提示词、剪映剪辑方案全部生成完毕后，在末尾提示：“第1集全链路资产生成完毕（本集时长约X分钟）。是否继续生成第2集？”
====================================================================
# 资产生成规范与输出格式
====================================================================
## A. 剧本基础角色资产格式
----- A. 剧本基础角色资产 -----
[角色1卡]
名称：[角色名称]
人物形象描述：[整体气质、身材体型、年龄段、走路姿态等宏观形象]
性格特点：[提取核心性格标签，如：偏执、懦弱但善良、冷酷等，并简述其行为逻辑倾向]
基础面容锚点：[提取不可改变的面部特征，如脸型、五官特点、特定疤痕或瞳色]
当前服装层次：[明确内外搭配、材质、破损或污渍状态，需与剧本时间线严格对应]
## B. 剧本正文格式
----- B. 剧本正文 -----
[格式要求：
1. 场景标记：用“○ ”开头，后接内景/外景 - 场景名称 - 日/夜。场景描述极致简化，仅几个字点明环境，禁止细致描写。
2. 动作描述：简练视觉化，直接描写角色动作。
3. 台词：以“△ ”开头，后接角色名及动作提示，下一行为完整台词原文。台词结束后必须空一行。
4. 内心OS：以“（OS）”开头，后接角色名，下一行为完整心理活动原文。OS结束后必须空一行。]
## C. 角色资产规范 (V3.0)
- 万能题材发型/造型规则：发型必须符合角色所处时代与身份（古装束发、民国烫卷、现代任意、赛博染色等），严禁穿越违和，必须细化结构。
- 万能服装系统：从内到外 + 腰部 + 下肢 + 足部六层结构。
- 角色概念表布局段（固定文本，必须原样嵌入提示词末尾）：
1. 主视觉区（上方）白底图：以"正面 + 侧面 + 背面"三个核心视角为主体。
2. 补充信息区（左侧）白底图：拆分出"面部特写（头部正立, 颈部垂直, 下颌线水平）"和"配色板"。
3. 局部细节区（底部）白底图：用小模块单独展示关键部件的设计。
4. 半身照比例照（右侧）：生成人物上半身图像，（头部正立, 颈部垂直, 下颌线水平）。
- 输出格式：
===== 角色 N · [角色名] =====
【中文AI提示词】（500-800字）
[时代/世界观] + [身份] + [性别年龄] + [全局参考风格] + [基础面容锚点完整描述] + [发式与头饰] + [服装从内到外六层] + [特殊状态] + [姿态：双手自然下垂，站姿自然，面容平静] + [角色概念表布局段原样嵌入] + [画质技术规范：8K超精细，材质纹理清晰可触，纯白底背景]
【英文AI提示词】
[将上述中文提示词精准翻译为英文，使用半角逗号分隔，去除冗余连接词，适配Midjourney/Stable Diffusion]
## D. 场景资产规范 (V3.0)
- 场景人物适配规则：每个场景必须包含适配场景类型的人物（如教室=学生，街道=行人），自然融入环境，严禁纯空镜（除非远景天际线或特写并标注“无人氛围镜”）。
- 七层递进结构：1.世界观定位 2.地理位置 3.主体建筑细节(含营造规范) 4.延伸空间与周边设施 5.自然与远景层次 6.光影与色彩系统 7.技术规格与风格参考。
- 画质技术尾缀（强制添加于末尾）：全场景色彩统一协调，禁止使用高饱和紫色、荧光色、霓虹色（除非题材本身为赛博朋克等强霓虹世界观，且需符合统一主色调），禁止出现与场景主色调冲突的刺眼配色。整体色调必须符合自然环境或建筑/工业材质的真实色彩关系。真人写实风格，电影画质，影视级真实材质，8K超精细，光影真实自然，物理准确的光照和阴影，材质纹理清晰可触。
- 输出格式：
【场景 N】场景名称
场景定位：[类型] | [室内外] | [时间] | [氛围]
【中文AI提示词】（400-600字）
[七层结构完整提示词，以全局尾缀结尾]
【英文AI提示词】
[将上述中文提示词精准翻译为英文，使用半角逗号分隔，去除冗余连接词，适配Midjourney/Stable Diffusion]
## E. 道具资产规范 (V3.0)
- 必填字段：道具名、分类、所属角色/场景、剧情功能、时代、尺寸、整体形制、材质构成(可触摸标准)、工艺与年代痕迹、装饰与纹样、功能细节、特殊状态。
- 构图要求：默认四视图（正面/背面/侧面/细节特写），可降级单图。禁止出现人物。
- 输出格式：
===== 道具资产卡 · [道具名] =====
[上述必填字段逐项列出]
【中文AI提示词】（200-400字）
[时代/世界观] + [道具类别] + [整体形制] + [主体材质与颜色] + [工艺与年代痕迹] + [装饰纹样与文字] + [功能细节] + [特殊状态] + [构图：四视图或单图] + [画质：白色/浅灰背景，柔和顶光，材质纹理清晰可触，8K超精细，电影级静物摄影]
【英文AI提示词】
[将上述中文提示词精准翻译为英文，使用半角逗号分隔，去除冗余连接词，适配Midjourney/Stable Diffusion]
## F. 分镜资产规范 (V4.0 动态运镜强化版)
----- F. 分镜资产 -----
===== 分镜 1 · [镜头标题/剧情简述] (时长：Xs，限制≤10s) =====
【分镜信息】
景别：[远景 / 全景 / 中景 / 近景 / 特写 / 大特写]
角度：[平视 / 仰视 / 俯视 / 荷兰角]
焦段：[广角(12-24mm) / 标准(35-50mm) / 长焦(85-200mm)]
构图：[三分法则 / 对称构图 / 框架构图 / 引导线构图 / 封闭或开放式构图]
运镜设计：[详细描述机位运动方式：如“手持跟拍”、“慢速横移”、“急推至特写”、“环绕拍摄”、“摇镜头跟随视线”等，需说明运动起点与终点、速度及节奏感]
场景：[调用D类场景名]
角色：[调用C类角色名]
台词：
[完整保留该镜头内所有角色台词，含旁白，不得删减、概括或改写。严格按3-4字/秒计算，超出10s必须拆分为下一个分镜]
【画面与视听细节】
画面内容：[具体动作、走位、道具互动及人物微表情]
景深层次：[焦内/焦外物体描述，虚化程度，焦点变换提示]
光影与色调：[光源方向、光比、色温、高光/阴影色彩参数、整体色调氛围。必须说明与上一镜头的衔接关系或向下一镜头的过渡逻辑]
渲染技术：[开启的特殊渲染功能，如光线追踪、毛发解算、SSS皮肤次表面散射、体积雾等]
人声与音效：[人声情绪及空间感、环境音、动作音效、特殊拟音]
【中文AI提示词】
[按顺序生成300-500字：景别与机位角度 + 动态运镜轨迹与速度 + 镜头焦段与构图法则 + 场景环境简述与连贯的光影氛围 + 出场角色及动作情绪 + 关键道具互动（如有） + 前景或背景细节 + 景深控制 + 画质技术尾缀]
*画质技术尾缀（强制添加于末尾）：真人写实风格，电影画质，影视级真实材质，8K超精细，物理准确的光照和阴影，材质纹理清晰可触，电影级调色，镜头光晕自然，画面极具叙事张力与电影感。
【英文AI提示词】
[将上述中文提示词精准翻译为英文，使用半角逗号分隔，去除冗余连接词，适配Midjourney/Stable Diffusion]
【自检】
□ 镜头语言明确
□ 运镜设计具体且具动感
□ 资产调用一致
□ 动作情绪具体
□ 光影色调与前后镜头衔接自然，无逻辑突变
□ 中英双语提示词均已输出且字数达标
□ 已附画质技术尾缀
□ 台词完整无删减
□ 台词时长未超出单镜10s限制

## G. 分镜图提示词规范 (V1.0 纯净绘图版)
在所有分镜资产输出完毕后，必须继续输出【G. 分镜图提示词】。这个板块专门用于AI绘图，必须去除所有运镜、时长、音效等非视觉词汇，只保留纯粹的静态画面描述。
----- G. 分镜图提示词 -----
===== 分镜 1 · [镜头标题/剧情简述] =====
【中文AI提示词】
[专为AI绘图模型生成300-500字的静态画面描述，严禁出现运镜、时长、音效等非视觉词汇。按以下顺序精准生成：
1. 画面主体描述：明确出场角色及其具体外貌、服装（必须与角色资产一致）、此刻的精准动作与生动面部表情。
2. 场景环境与道具：角色所处的具体环境细节、氛围、以及互动的关键道具。
3. 镜头语言与构图：景别、拍摄角度、焦段透视效果、画面构图方式。
4. 光影与色彩：主光源方向、光比软硬、色温、环境反光、整体色调氛围。
5. 景深控制：焦内清晰物体与焦外虚化程度。
6. 画质技术尾缀（强制添加于末尾）：真人写实风格，电影画质，影视级真实材质，8K超精细，物理准确的光照和阴影，材质纹理清晰可触，电影级调色，画面极具叙事张力与电影感。]
【英文AI提示词】
[将上述中文提示词精准翻译为英文，使用半角逗号分隔，去除冗余连接词，适配Midjourney/Stable Diffusion]

## G. 剪映专业剪辑指导方案规范 (V4.0)
在所有分镜输出完毕后，必须继续输出【剪映专业剪辑指导方案】。完全按照电影、短剧、AI漫剧的工业剪辑逻辑，提供可直接在剪映中操作的方案。排版必须严格采用以下结构化文本格式，禁止使用Markdown表格：

## 🎬 剪映专业剪辑指导方案

### 🎵 1. 分段式BGM与情绪节奏设计
[注意：严禁一首BGM贯通全局。必须根据剧本的场景切换、情绪转折或高潮爆发，将全集拆分为2-4个BGM段落。按以下格式依次列出每个段落：]

[BGM段落1 - 起幅/铺垫]
  - 对应剧情节点：[如：分镜1至分镜2，室外雨夜铺垫]
  - 情绪基调：[如：压抑/悬疑/低沉]
  - 推荐BGM搜索关键词：[如：悬疑 雨夜 大提琴 纯音乐]
  - 音量控制：[如：基础音量 -20dB，低沉底噪]
  - 起止与卡点建议：[如：雷声后0.5秒淡入，持续铺垫]

[BGM段落2 - 发展/转折]
  - 对应剧情节点：[如：分镜3，主角握紧玉佩准备推门]
  - 情绪基调：[如：紧张升级/节奏加快]
  - 推荐BGM搜索关键词：[如：紧张 鼓点 心跳 节奏感]
  - 音量控制：[如：音量提至 -15dB，鼓点渐强]
  - 起止与卡点建议：[如：与上一段BGM可通过0.5秒静音过渡，或直接交叉淡化；配合手部特写切入鼓点]

[BGM段落3 - 高潮/爆发]
  - 对应剧情节点：[如：分镜4，推门瞬间及进入古堡]
  - 情绪基调：[如：爆发/空灵/死寂]
  - 推荐BGM搜索关键词：[如：史诗 爆发 重低音 / 或 空灵 滴水声 悬疑]
  - 音量控制：[如：推门瞬间爆发至 -10dB，随后迅速衰减至 -25dB（音频闪避），让出空间给对白]
  - 起止与卡点建议：[如：推门动作卡重音点，对白时BGM压低，对白结束后BGM戛然而止只留环境音]

### 🔊 2. 关键音效设计
[音效1]
  - 对应镜头：[如：镜头X]
  - 音效分类：[如：环境音/转场音/动作音]
  - 剪映搜索关键词：[如：心跳声 紧张]
  - 音量：[如：-15dB]
  - 时长：[如：3s]
  - 剪辑逻辑与作用：[如：渲染内心紧张活动]
[至少列出3-5个关键音效，按此格式依次列出]

### ✂️ 3. 转场方案
[转场1]
  - 镜头衔接：[如：镜头X -> 镜头Y]
  - 转场类型：[如：叠化/黑场/运镜转场/无缝转场]
  - 剪映搜索关键词：[如：叠化]
  - 时长：[如：0.5s]
  - 剪辑逻辑说明：[如：时间流逝/情绪停顿/动作顺接]
[覆盖所有相邻镜头的切换点，按此格式依次列出]

### ✨ 4. 视觉特效与滤镜
[特效1]
  - 镜头/场景：[如：全局/镜头X]
  - 特效/滤镜类型：[如：调色滤镜/氛围特效/动感特效]
  - 剪映搜索关键词：[如：电影感 青橙]
  - 参数建议：[如：强度 60%]
  - 剪辑逻辑说明：[如：统一色调/增加梦幻感/强调冲击力]
[包含全局调色和局部特效，按此格式依次列出]

请确保搜索关键词是剪映素材库中容易搜到的常用词。

# 自动续写特别指令
由于你需要生成的内容非常长，可能会遇到单次输出字数上限被截断的情况。为了解决这个问题，请遵守以下规则：
1. 当你完成了所有要求的内容（剧本、资产、分镜、剪映剪辑方案全部生成完毕）后，必须在绝对末尾输出一个特殊标记：[ALL_DONE]
2. 如果你的输出在中间被截断，我会发送“继续”给你，你必须紧接着上次中断的地方继续输出，不要重复已经输出的内容，也不要说任何道歉或解释的话，直接输出剩余内容。"""
# ================= 核心逻辑区 =================
stop_flag = False
ui_buffer = []
line_buffer = ""
current_section = "script"

current_image_url = ""      
current_video_url = ""      
video_ref_image_urls = []   
video_ref_image_path = ""   
current_tk_img = None       
image_history = []          
video_history = []           
sb_ref_urls = []             # 存储分镜图匹配到的参考图URL
sb_image_urls = []           # 存储已生成的分镜图URL，供视频页调用
vid_gen_state = {"mode": None, "urls": []}  # 视频智能生成的状态管理

def safe_update_ui(callback):
    root.after(0, callback)

def flush_ui_buffer():
    global ui_buffer, line_buffer, current_section
    if ui_buffer:
        chunk = "".join(ui_buffer)
        ui_buffer.clear()
        chunk = chunk.replace("[ALL_DONE]", "")
        
        w_all = text_widgets["all"]
        w_all.config(state=tk.NORMAL)
        yview_all = w_all.yview()[1]
        w_all.insert(tk.END, chunk)
        if yview_all >= 0.95: w_all.see(tk.END)
        w_all.config(state=tk.DISABLED)
        
        line_buffer += chunk
        lines = line_buffer.split("\n")
        line_buffer = lines.pop() 
        
        for line in lines:
            if "===== 角色" in line: current_section = "character"
            elif "【场景" in line and "】" in line: current_section = "scene"
            elif "===== 道具资产卡" in line: current_section = "prop"
            elif "F. 分镜资产" in line: current_section = "storyboard"
            elif "G. 分镜图提示词" in line: current_section = "sb_prompt"
            elif "剪映专业剪辑指导方案" in line: current_section = "editing"
            
            w_target = text_widgets[current_section]
            w_target.config(state=tk.NORMAL)
            yview_target = w_target.yview()[1]
            w_target.insert(tk.END, line + "\n")
            if yview_target >= 0.95: w_target.see(tk.END)
            w_target.config(state=tk.DISABLED)
            
    root.after(100, flush_ui_buffer)

def generate_storyboard():
    global stop_flag, ui_buffer, line_buffer, current_section
    stop_flag = False
    ui_buffer.clear()
    line_buffer = ""
    current_section = "script"
    
    novel_text = text_input_novel.get("1.0", tk.END).strip()
    command_text = text_input_command.get("1.0", tk.END).strip()
    
    if not novel_text:
        show_toast("请输入小说文本", "warning")
        return
    
    user_input = ""
    if command_text:
        user_input += f"【用户附加指令/诉求】\n{command_text}\n\n"
    user_input += f"【小说文本】\n{novel_text}"
    
    api_key = entry_api_key.get().strip()
    base_url = entry_base_url.get().strip()
    model_name = combo_text_model.get().strip()
    
    if not api_key or not base_url or not model_name:
        show_toast("请先填写完整的文本模型 API 配置", "warning")
        return
    
    btn_generate.config(state=tk.DISABLED)
    btn_stop.config(state=tk.NORMAL)
    progress_bar.start()
    
    def clear_output():
        global line_buffer, current_section
        line_buffer = ""
        current_section = "script"
        for key in text_widgets:
            w = text_widgets[key]
            w.config(state=tk.NORMAL)
            w.delete("1.0", tk.END)
            if key == "all":
                w.insert(tk.END, f"[系统日志] 正在连接 API...\n")
                w.insert(tk.END, f"[系统日志] URL: {base_url}\n")
                w.insert(tk.END, f"[系统日志] 模型: {model_name}\n\n")
            w.config(state=tk.DISABLED)
        label_gen_time.config(text="本次生成耗时：计时中...")
        notebook.select(0)
    safe_update_ui(clear_output)
    
    threading.Thread(target=call_llm_api_with_continuation, args=(user_input, api_key, base_url, model_name), daemon=True).start()

def stop_generation():
    global stop_flag
    stop_flag = True

def call_llm_api_with_continuation(user_input, api_key, base_url, model_name):
    global stop_flag, ui_buffer
    start_time = time.time()
    try:
        timeout_config = httpx.Timeout(60.0, read=120.0)
        http_client = httpx.Client(timeout=timeout_config, trust_env=False)
        client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_config, http_client=http_client)
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ]
        max_loops = 15
        is_done = False
        
        for i in range(max_loops):
            if stop_flag: break
            if is_done: break
                
            retry_count = 0
            max_retries = 5
            chunk_content = ""
            stream = None
            first_chunk_received = False
            
            while retry_count < max_retries:
                try:
                    ui_buffer.append(f"[系统日志] 正在发起第 {i+1} 次请求...\n")
                    stream = client.chat.completions.create(
                        model=model_name, messages=messages, stream=True, temperature=0.7
                    )
                    for chunk in stream:
                        if stop_flag:
                            stream.close()
                            break
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta.content is not None:
                            text = delta.content
                            chunk_content += text
                            if not first_chunk_received:
                                first_chunk_received = True
                                ui_buffer.append("[系统日志] 已收到响应，正在生成内容...\n\n")
                            if "[ALL_DONE]" not in text:
                                ui_buffer.append(text)
                    break
                except Exception as conn_err:
                    err_str = str(conn_err).lower()
                    is_disconnect = "incomplete chunked read" in err_str or "peer closed" in err_str or "connection reset" in err_str
                    
                    if is_disconnect:
                        if chunk_content:
                            ui_buffer.append(f"\n[系统日志: 服务器中断连接，但已获取部分内容，将自动尝试续写...]\n")
                            break
                        else:
                            retry_count += 1
                            if retry_count >= max_retries:
                                raise Exception("服务器连续多次在开始时就断开连接，可能平台当前负载过高，请稍后再试或更换模型。")
                            ui_buffer.append(f"\n[系统日志: 服务器刚连接就断开，2秒后强制重试 ({retry_count}/{max_retries})...]\n")
                            time.sleep(2)
                    else:
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise conn_err
                        ui_buffer.append(f"\n[系统日志: 网络异常 ({str(conn_err)})，3秒后重试 ({retry_count}/{max_retries})...]\n")
                        time.sleep(3)
            
            if stop_flag: break
                
            if "[ALL_DONE]" in chunk_content:
                is_done = True
                break
                
            if chunk_content:
                messages.append({"role": "assistant", "content": chunk_content})
                messages.append({"role": "user", "content": "请严格接着上次未写完的内容继续输出，保持格式不变。如果已经全部输出完毕（包含剪映剪辑方案），请务必单独输出 [ALL_DONE] 标记。"})
                ui_buffer.append("\n\n[系统日志: 内容较长，正在自动续写...]\n\n")
            else:
                if not first_chunk_received and not is_done:
                    ui_buffer.append("\n\n[系统提示：API 未返回任何内容。请检查 API Key、Base URL 和模型名是否正确。]")
                else:
                    ui_buffer.append("\n\n[系统提示：API 返回为空，可能已生成完毕或被截断。]")
                break
                
        if stop_flag: ui_buffer.append("\n\n[系统提示：用户已手动停止生成。]")
        elif not is_done and not stop_flag and not first_chunk_received:
            ui_buffer.append("\n\n[系统提示：生成结束，但未获取到有效内容。]")
            
    except openai.APITimeoutError as te:
        ui_buffer.append("\n\n[系统提示：API 响应超时。服务端可能拥堵或网络不稳定，请稍后重试。]")
        safe_update_ui(lambda: show_toast("API 响应超时", "warning"))
    except Exception as e:
        ui_buffer.append(f"\n\n[生成失败] 错误信息：{str(e)}")
        safe_update_ui(lambda: show_toast("生成失败", "warning"))
    finally:
        elapsed_time = time.time() - start_time
        def reset_ui():
            btn_generate.config(state=tk.NORMAL)
            btn_stop.config(state=tk.DISABLED)
            progress_bar.stop()
            label_gen_time.config(text=f"本次生成耗时：{elapsed_time:.2f} 秒")
            if not stop_flag:
                show_toast("生成完毕", "success")
        safe_update_ui(reset_ui)

# ================= 媒体生成与下载逻辑 =================
def poll_task_result(base_url, headers, task_code, is_video=False):
    query_url = f"{base_url.rstrip('/')}/tasks/{task_code}"
    ui_buffer.append(f"[系统日志] 开始轮询任务: {task_code}\n")
    
    from urllib.parse import urlparse
    parsed_base = urlparse(base_url)
    domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    
    for i in range(120): 
        time.sleep(5)
        try:
            res = requests.get(query_url, headers=headers, timeout=30)
            if res.status_code != 200:
                ui_buffer.append(f"[系统日志: 轮询返回异常 HTTP {res.status_code}]\n")
                continue
                
            res_json = res.json()
            data = res_json.get("data", res_json) # 兼容有些平台没有 data 包裹
            status = str(data.get("status", res_json.get("status", ""))).upper()
            
            if i % 6 == 0:
                ui_buffer.append(f"[系统日志: 轮询中... 当前状态: {status}，原始返回: {str(res_json)[:300]}\n")
            
            if "SUCCESS" in status or "COMPLETE" in status or "DONE" in status or "SUCCEEDED" in status:
                url = None
                
                outputs = data.get("outputs", [])
                if outputs and isinstance(outputs, list) and len(outputs) > 0:
                    url = outputs[0].get("url")
                
                if not url:
                    if is_video:
                        url = data.get("videoUrl") or data.get("video_url") or data.get("url") or \
                              data.get("output", {}).get("video_url") or data.get("output", {}).get("url") or \
                              data.get("results", {}).get("videos", [{}])[0].get("url") or \
                              data.get("content", {}).get("video_url") or data.get("video")
                    else:
                        url = data.get("imageUrl") or data.get("image_url") or data.get("url") or \
                              data.get("output", {}).get("image_url") or data.get("output", {}).get("url") or \
                              data.get("results", {}).get("images", [{}])[0].get("url") or data.get("image")
                
                if url:
                    if url.startswith("//"):
                        url = "https:" + url
                    elif not (url.startswith("http://") or url.startswith("https://")):
                        if url.startswith("/"):
                            url = domain + url
                        else:
                            url = domain + "/" + url
                    return url
                else:
                    raw_str = json.dumps(data, ensure_ascii=False)
                    ui_buffer.append(f"[系统日志: 任务成功但未找到URL字段，原始返回: {raw_str}]\n")
                    raise Exception("任务成功但未找到URL，请查看全文展示页的日志")
                    
            elif "FAIL" in status or "ERROR" in status:
                raise Exception(f"任务失败: {data.get('error', {}).get('message', '未知错误')}")
                
        except Exception as e:
            ui_buffer.append(f"[系统日志: 轮询解析异常 {str(e)}]\n")
            if i > 10:
                raise Exception(f"轮询解析异常: {str(e)}")
            continue
            
    raise Exception("任务轮询超时 (10分钟)，请检查网络或稍后重试")

def poll_seedance_task(base_url, headers, task_id):
    query_url = f"{base_url.rstrip('/')}/contents/generations/tasks/{task_id}"
    ui_buffer.append(f"[系统日志] 开始轮询 Seedance 任务: {task_id}\n")
    
    for i in range(120): 
        time.sleep(5)
        try:
            res = requests.get(query_url, headers=headers, timeout=30)
            if res.status_code != 200:
                ui_buffer.append(f"[系统日志: 轮询返回异常 HTTP {res.status_code}]\n")
                continue
                
            res_json = res.json()
            status = str(res_json.get("status", "")).upper()
            
            if i % 6 == 0:
                ui_buffer.append(f"[系统日志: 轮询中... 当前状态: {status}]\n")
            
            if "SUCCEEDED" in status:
                video_url = res_json.get("content", {}).get("video_url")
                if video_url:
                    return video_url
                else:
                    raise Exception("任务成功但未找到 video_url")
            elif "FAILED" in status or "ERROR" in status:
                raise Exception(f"任务失败: {res_json.get('error', {}).get('message', '未知错误')}")
                
        except Exception as e:
            ui_buffer.append(f"[系统日志: 轮询解析异常 {str(e)}]\n")
            if i > 10:
                raise Exception(f"轮询解析异常: {str(e)}")
            continue
            
    raise Exception("任务轮询超时 (10分钟)，请检查网络或稍后重试")

def match_ref_for_storyboard():
    global sb_ref_urls
    if not image_history:
        show_toast("没有可用的历史图片", "warning")
        return
        
    # 获取分镜页的所有文本内容
    storyboard_text = text_widgets["storyboard"].get("1.0", tk.END)
    
    matched_urls = []
    matched_names = []
    
    # 遍历历史图片，如果图片名称出现在分镜文本中，则自动匹配
    for item in image_history:
        img_name = item.get("name", "")
        # 确保名称有效且在文本中出现
        if img_name and img_name != "自定义图片" and img_name in storyboard_text:
            if item["url"] not in matched_urls:
                matched_urls.append(item["url"])
                matched_names.append(img_name)
                
    if not matched_urls:
        show_toast("未在分镜提示词中匹配到相关参考图", "warning")
        sb_ref_urls = []
        label_sb_ref_status.config(text="未匹配到参考图", fg=COLOR_TEXT_DIM)
        return
        
    sb_ref_urls = matched_urls
    label_sb_ref_status.config(text=f"已智能匹配 {len(matched_urls)} 张参考图", fg=COLOR_SUCCESS)
    show_toast(f"已智能匹配: {', '.join(matched_names)}", "success")

def generate_all_assets():
    api_key = entry_media_api_key.get().strip()
    base_url = entry_media_base_url.get().strip()
    model_name = combo_img_model.get().strip()
    
    if not api_key or not base_url or not model_name:
        show_toast("请先填写完整的媒体 API 配置并拉取模型", "warning")
        return
        
    btn_gen_all_img.config(state=tk.DISABLED, text="资产生成中...")
    progress_bar.start()
    
    # 提取资产提示词
    asset_sections = ["character", "scene", "prop"]
    prompts = []
    names = []
    
    for sec in asset_sections:
        sec_content = text_widgets[sec].get("1.0", tk.END)
        # 使用正则一次性把标题和内容成对提取出来
        blocks = re.findall(r'(=====.*?=====|【场景\s*\d+】[^\n]*)(.*?)(?======.*?=====|【场景\s*\d+】|\Z)', sec_content, re.S)
        
        for title, block in blocks:
            # 1. 提取提示词（只取第一个匹配项，通常是中文，防止重复生成）
            prompt_match = re.search(r'【(中文|英文)AI提示词】\s*\n(.*?)(?=\n【|\n=====|\Z)', block, re.S)
            if not prompt_match: continue
            prompt_text = prompt_match.group(2).strip()
            if not prompt_text: continue
            
            # 2. 提取名称
            clean_title = title.replace("=====", "").strip()
            clean_title = re.sub(r'[\(（].*?[\)）]', '', clean_title).strip()
            parts = re.split(r'[·】：:\-—]', clean_title)
            name = parts[-1].strip() if parts else clean_title
            
            # 检查名字是否无效（如“角色 1”、“场景 1”、“道具 1”等）
            is_invalid = False
            if re.match(r'^(角色|场景|道具|资产卡|道具资产卡)\s*\d*$', name):
                is_invalid = True
            if not name:
                is_invalid = True
                
            if is_invalid:
                # 从正文找 "名称：xxx" 或 "道具名：xxx"
                name_match = re.search(r'(名称|道具名|场景名|角色名)[:：]\s*([^\n]+)', block)
                if name_match:
                    name = name_match.group(2).strip()
                else:
                    name = "未命名资产"
                    
            prompts.append(prompt_text)
            names.append(name)
            
    if not prompts:
        show_toast("未在角色/场景/道具页找到资产提示词", "warning")
        btn_gen_all_img.config(state=tk.NORMAL, text="一键并发生图")
        progress_bar.stop()
        return
        
    aspect_ratio = combo_img_ratio.get()
    resolution = combo_img_res.get()
    
    def generate_single(prompt_text, item_name):
        try:
            url = f"{base_url.rstrip('/')}/image/generations"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model_name, "prompt": prompt_text, "aspectRatio": aspect_ratio, "resolution": resolution}
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code != 200:
                ui_buffer.append(f"[系统日志: {item_name} 请求失败 {response.text[:200]}]\n")
                return None, f"HTTP {response.status_code}", item_name
            result = response.json()
            ui_buffer.append(f"[系统日志: {item_name} 提交成功，返回: {str(result)[:300]}]\n")
            
            task_code = result.get("data", {}).get("taskCode") or result.get("task_id") or result.get("id")
            direct_url = None
            if not task_code:
                if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                    direct_url = result["data"][0].get("url")
                elif "url" in result:
                    direct_url = result.get("url")
            
            if direct_url:
                img_url = direct_url
            elif task_code:
                ui_buffer.append(f"[系统日志: {item_name} 开始轮询任务: {task_code}]\n")
                img_url = poll_task_result(base_url, headers, task_code, is_video=False)
            else:
                return None, "未获取到URL", item_name
                
            if not img_url:
                ui_buffer.append(f"[系统日志: {item_name} 轮询结束，但未获取到URL]\n")
                return None, "轮询未返回URL", item_name
                
            ui_buffer.append(f"[系统日志: {item_name} 获取到图片URL，准备下载: {img_url}]\n")
            download_headers = {"User-Agent": "Mozilla/5.0", "Referer": base_url}
            img_response = requests.get(img_url, headers=download_headers, timeout=30)
            img_response.raise_for_status()
            pil_img = Image.open(io.BytesIO(img_response.content))
            return pil_img, img_url, item_name
        except Exception as e:
            ui_buffer.append(f"[系统日志: {item_name} 生成异常: {str(e)}]\n")
            return None, str(e), item_name

    def task():
        success_count = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_prompt = {executor.submit(generate_single, prompts[i], names[i]): prompts[i] for i in range(len(prompts))}
            for future in as_completed(future_to_prompt):
                pil_img, err_or_url, item_name = future.result()
                if pil_img:
                    success_count += 1
                    def update_ui(img=pil_img, url=err_or_url, name=item_name):
                        add_to_history(url, img, name)
                    safe_update_ui(update_ui)
                else:
                    ui_buffer.append(f"[系统日志: 资产图生成失败 - {err_or_url}]\n")
        safe_update_ui(lambda: show_toast(f"资产并发生成完毕，成功 {success_count}/{len(prompts)} 张", "success"))
        safe_update_ui(lambda: btn_gen_all_img.config(state=tk.NORMAL, text="一键并发生图"))
        safe_update_ui(lambda: progress_bar.stop())

    threading.Thread(target=task, daemon=True).start()
def generate_storyboard_image(use_ref=True):
    content = text_widgets["storyboard"].get("1.0", tk.END)
    
    prompts = []
    names = []
    # 使用正则一次性把标题和内容成对提取出来
    blocks = re.findall(r'(=====.*?=====)(.*?)(?======.*?=====|\Z)', content, re.S)
    
    for title, block in blocks:
        # 1. 提取提示词（只取第一个匹配项，防止重复生成）
        prompt_match = re.search(r'【(中文|英文)AI提示词】\s*\n(.*?)(?=\n【|\n=====|\Z)', block, re.S)
        if not prompt_match: continue
        prompt_text = prompt_match.group(2).strip()
        if not prompt_text: continue
        
        # 2. 提取名称
        clean_title = title.replace("=====", "").strip()
        clean_title = re.sub(r'[\(（].*?[\)）]', '', clean_title).strip()
        parts = re.split(r'[·】：:\-—]', clean_title)
        name = parts[-1].strip() if parts else clean_title
        
        is_invalid = False
        if re.match(r'^(分镜|分镜资产)\s*\d*$', name):
            is_invalid = True
        if not name:
            is_invalid = True
            
        if is_invalid:
            name_match = re.search(r'(名称|场景|角色|道具)[:：]\s*([^\n]+)', block)
            if name_match:
                name = name_match.group(2).strip()
            else:
                name = "未命名分镜"
                
        prompts.append(prompt_text)
        names.append(name)
        
    if not prompts:
        show_toast("未在分镜资产页找到提示词", "warning")
        return
        
    api_key = entry_media_api_key.get().strip()
    base_url = entry_media_base_url.get().strip()
    model_name = combo_img_model.get().strip()
    
    if not api_key or not base_url or not model_name:
        show_toast("请先填写完整的媒体 API 配置并拉取模型", "warning")
        return

    btn_gen_sb.config(state=tk.DISABLED, text="并发生成中...")
    aspect_ratio = combo_sb_ratio.get()
    resolution = combo_sb_res.get()
    progress_bar.start()
    
    def generate_single(prompt_text, item_name):
        try:
            url = f"{base_url.rstrip('/')}/image/generations"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model_name, 
                "prompt": prompt_text, 
                "aspectRatio": aspect_ratio, 
                "resolution": resolution
            }
            current_refs = sb_ref_urls if (use_ref and sb_ref_urls) else []
            if current_refs:
                payload["referenceImageUrls"] = current_refs
                
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code != 200:
                ui_buffer.append(f"[系统日志: {item_name} 请求失败 {response.text[:200]}]\n")
                return None, f"HTTP {response.status_code}", item_name
                
            result = response.json()
            ui_buffer.append(f"[系统日志: {item_name} 提交成功，返回: {str(result)[:300]}]\n")
            
            task_code = result.get("data", {}).get("taskCode") or result.get("task_id") or result.get("id")
            direct_url = None
            if not task_code:
                if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                    direct_url = result["data"][0].get("url")
                elif "url" in result:
                    direct_url = result.get("url")
                    
            if direct_url:
                img_url = direct_url
            elif task_code:
                ui_buffer.append(f"[系统日志: {item_name} 开始轮询任务: {task_code}]\n")
                img_url = poll_task_result(base_url, headers, task_code, is_video=False)
            else:
                return None, "未获取到URL", item_name
                
            if not img_url:
                ui_buffer.append(f"[系统日志: {item_name} 轮询结束，但未获取到URL]\n")
                return None, "轮询未返回URL", item_name
                
            ui_buffer.append(f"[系统日志: {item_name} 获取到图片URL，准备下载: {img_url}]\n")
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": base_url
            }
            img_response = requests.get(img_url, headers=download_headers, timeout=30)
            img_response.raise_for_status()
            pil_img = Image.open(io.BytesIO(img_response.content))
            return pil_img, img_url, item_name
        except Exception as e:
            ui_buffer.append(f"[系统日志: {item_name} 生成异常: {str(e)}]\n")
            return None, str(e), item_name

    def task():
        success_count = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_prompt = {executor.submit(generate_single, prompts[i], names[i]): prompts[i] for i in range(len(prompts))}
            for future in as_completed(future_to_prompt):
                pil_img, err_or_url, item_name = future.result()
                if pil_img:
                    success_count += 1
                    def update_ui(img=pil_img, url=err_or_url, name=item_name):
                        add_to_history(url, img, name)
                        sb_image_urls.append(url)
                    safe_update_ui(update_ui)
                else:
                    ui_buffer.append(f"[系统日志: 分镜图生成失败 - {err_or_url}]\n")
                    
        safe_update_ui(lambda: show_toast(f"并发生成完毕，成功 {success_count}/{len(prompts)} 张", "success"))
        safe_update_ui(lambda: btn_gen_sb.config(state=tk.NORMAL, text="生成分镜图"))
        safe_update_ui(lambda: progress_bar.stop())

    threading.Thread(target=task, daemon=True).start()

def show_large_image_by_url(url):
    for item in image_history:
        if item["url"] == url:
            show_large_image(image_history.index(item))
            return
    try:
        response = requests.get(url, timeout=30)
        pil_img = Image.open(io.BytesIO(response.content))
        top = tk.Toplevel(root)
        top.title("图片预览")
        top.configure(bg=COLOR_BG)
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        img = pil_img.copy()
        img.thumbnail((screen_w - 100, screen_h - 150))
        tk_img = ImageTk.PhotoImage(img)
        lbl = tk.Label(top, image=tk_img, bg=COLOR_BG)
        lbl.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        top.image = tk_img
    except:
        pass

def extract_latest_prompt():
    content = text_widgets["storyboard"].get("1.0", tk.END)
    matches_en = re.findall(r'【英文AI提示词】\n(.*?)(?=\n【|\n=====|\Z)', content, re.S)
    matches_cn = re.findall(r'【中文AI提示词】\n(.*?)(?=\n【英文|\n=====|\Z)', content, re.S)
    
    prompt = ""
    if matches_en: prompt = matches_en[-1].strip()
    elif matches_cn: prompt = matches_cn[-1].strip()
    
    if prompt:
        entry_img_prompt.delete("1.0", tk.END)
        entry_img_prompt.insert(tk.END, prompt)
        entry_vid_prompt.delete("1.0", tk.END)
        entry_vid_prompt.insert(tk.END, prompt)
        show_toast("提示词已提取", "success")
    else:
        show_toast("未找到分镜提示词", "warning")

def add_to_history(url, pil_img, name="生成的图片"):
    global image_history
    thumb = pil_img.copy()
    thumb.thumbnail((100, 60))
    tk_thumb = ImageTk.PhotoImage(thumb)
    image_history.append({"url": url, "img": pil_img, "tk_thumb": tk_thumb, "name": name})
    update_history_ui()

def delete_image_from_history(idx):
    if 0 <= idx < len(image_history):
        url_to_del = image_history[idx]["url"]
        del image_history[idx]
        if url_to_del in sb_image_urls:
            sb_image_urls.remove(url_to_del)
        update_history_ui()

def update_history_ui():
    global current_tk_img
    
    # 1. 更新图片生成页历史
    for widget in history_frame_inner.winfo_children():
        widget.destroy()
    for idx, item in enumerate(image_history):
        row = idx // 5
        col = idx % 5
        frame_item = tk.Frame(history_frame_inner, bg=COLOR_PANEL)
        frame_item.grid(row=row, column=col, padx=5, pady=5)
        lbl = tk.Label(frame_item, image=item["tk_thumb"], bg=COLOR_PANEL, cursor="hand2")
        lbl.pack()
        lbl.bind("<Button-1>", lambda e, i=idx: show_large_image(i))
        
        btn_del = tk.Button(frame_item, text="×", font=FONT_MAIN, bg=COLOR_BORDER, fg="white", relief=tk.FLAT, width=2, command=lambda i=idx: delete_image_from_history(i))
        btn_del.pack(pady=(2,0))
        
    # 2. 更新分镜图生成页历史 (横向排列)
    if 'sb_history_frame_inner' in globals():
        for widget in sb_history_frame_inner.winfo_children():
            widget.destroy()
        for idx, item in enumerate(image_history):
            frame_item = tk.Frame(sb_history_frame_inner, bg=COLOR_PANEL)
            frame_item.pack(side=tk.LEFT, padx=5, pady=5)
            lbl = tk.Label(frame_item, image=item["tk_thumb"], bg=COLOR_PANEL, cursor="hand2")
            lbl.pack()
            lbl.image = item["tk_thumb"] # 防止被垃圾回收
            lbl.bind("<Button-1>", lambda e, u=item["url"]: show_large_image_by_url(u))
            
            btn_del = tk.Button(frame_item, text="×", font=FONT_MAIN, bg=COLOR_BORDER, fg="white", relief=tk.FLAT, width=2, command=lambda i=idx: delete_image_from_history(i))
            btn_del.pack(pady=(2,0))

    # 3. 更新视频页列表
    listbox_vid_ref.delete(0, tk.END)
    for idx, item in enumerate(image_history):
        listbox_vid_ref.insert(tk.END, f"[{idx+1}] {item.get('name', '生成的图片')}")
        
    # 4. 更新分镜图页列表
    if 'listbox_sb_ref' in globals():
        listbox_sb_ref.delete(0, tk.END)
        for idx, item in enumerate(image_history):
            listbox_sb_ref.insert(tk.END, f"[{idx+1}] {item.get('name', '生成的图片')}")
        
    root.update_idletasks()
    root.update() # 强制立即刷新UI，实现生成一张展示一张

def show_large_image(idx):
    item = image_history[idx]
    top = tk.Toplevel(root)
    top.title(f"图片预览 - {idx+1}")
    top.configure(bg=COLOR_BG)
    
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    img = item["img"].copy()
    img.thumbnail((screen_w - 100, screen_h - 150))
    tk_img = ImageTk.PhotoImage(img)
    
    lbl = tk.Label(top, image=tk_img, bg=COLOR_BG)
    lbl.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    btn_download = tk.Button(top, text="下载此图片", font=FONT_MAIN, bg=COLOR_SUCCESS, fg="white", relief=tk.FLAT, 
                             command=lambda: download_specific_image(idx))
    btn_download.pack(pady=10)
    
    top.image = tk_img 

def download_specific_image(idx):
    item = image_history[idx]
    url = item["url"]
    file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG 图片", "*.png")], title="保存图片")
    if not file_path: return
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": entry_media_base_url.get().strip()
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(response.content)
        show_toast("图片已保存", "success")
    except Exception as e:
        messagebox.showerror("下载失败", f"错误详情: {str(e)}\n\n下载链接:\n{url}")

def on_vid_ref_select(event):
    global video_ref_image_urls, video_ref_image_path
    selected_indices = listbox_vid_ref.curselection()
    
    for widget in frame_vid_ref_inner.winfo_children():
        widget.destroy()
        
    if not selected_indices:
        video_ref_image_urls = []
        tk.Label(frame_vid_ref_inner, text="无参考图\n(从下方列表多选历史图片)", bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, font=FONT_MAIN, width=30, height=8).pack()
        return
        
    video_ref_image_urls = [image_history[i]["url"] for i in selected_indices]
    video_ref_image_path = "" 
    
    for i, idx in enumerate(selected_indices):
        row = i // 2
        col = i % 2
        img = image_history[idx]["img"].copy()
        img.thumbnail((120, 90))
        tk_img = ImageTk.PhotoImage(img)
        lbl = tk.Label(frame_vid_ref_inner, image=tk_img, bg=COLOR_PANEL)
        lbl.image = tk_img 
        lbl.grid(row=row, column=col, padx=5, pady=5)

def generate_image():
    global current_image_url, current_tk_img
    prompt = entry_img_prompt.get("1.0", tk.END).strip()
    if not prompt:
        show_toast("请输入提示词", "warning")
        return
        
    api_key = entry_media_api_key.get().strip()
    base_url = entry_media_base_url.get().strip()
    model_name = combo_img_model.get().strip()
    
    if not api_key or not base_url or not model_name:
        show_toast("请先填写完整的媒体 API 配置并拉取模型", "warning")
        return

    btn_gen_img.config(state=tk.DISABLED)
    btn_dl_img.config(state=tk.DISABLED)
    label_img_display.config(text="正在提交图片生成任务并轮询结果...", image="")
    progress_bar.start()
    
    try:
        url = f"{base_url.rstrip('/')}/image/generations"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        aspect_ratio = combo_img_ratio.get()
        resolution = combo_img_res.get()
        
        payload = {
            "model": model_name, 
            "prompt": prompt, 
            "aspectRatio": aspect_ratio, 
            "resolution": resolution
        }
        
        ui_buffer.append(f"[系统日志] 正在请求图片生成接口...\n")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            try:
                err_data = response.json()
                err_msg = err_data.get("error", {}).get("message") or err_data.get("message") or str(err_data)
            except:
                err_msg = response.text
            raise Exception(f"HTTP {response.status_code} - {err_msg}")
            
        result = response.json()
        ui_buffer.append(f"[系统日志] 接口返回数据: {str(result)[:500]}\n")
        
        task_code = result.get("data", {}).get("taskCode") or result.get("task_id") or result.get("id")
        direct_url = None
        
        if not task_code:
            if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                direct_url = result["data"][0].get("url") or result["data"][0].get("image_url")
            elif "data" in result and isinstance(result["data"], dict):
                direct_url = result["data"].get("url") or result["data"].get("image_url")
            elif "url" in result:
                direct_url = result.get("url")
            elif "image_url" in result:
                direct_url = result.get("image_url")
                
        if direct_url:
            current_image_url = direct_url
            ui_buffer.append(f"[系统日志] 获取到直接URL: {current_image_url}\n")
        elif task_code:
            ui_buffer.append(f"[系统日志] 获取到任务ID，开始轮询: {task_code}\n")
            current_image_url = poll_task_result(base_url, headers, task_code, is_video=False)
            ui_buffer.append(f"[系统日志] 轮询完成，获取到URL: {current_image_url}\n")
        else:
            raise Exception("未获取到图片任务 taskCode 或直接返回的 URL")
            
        if not current_image_url:
            raise Exception("任务完成但未找到图片URL")
            
        # 增加防盗链请求头下载图片
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": base_url
        }
        ui_buffer.append(f"[系统日志] 正在下载图片: {current_image_url}\n")
        img_response = requests.get(current_image_url, headers=download_headers, timeout=30)
        ui_buffer.append(f"[系统日志] 下载响应状态码: {img_response.status_code}\n")
        if img_response.status_code != 200:
            raise Exception(f"下载失败 HTTP {img_response.status_code}，可能被防盗链拦截")
        img_data = img_response.content
        pil_img = Image.open(io.BytesIO(img_data))
        
        display_img = pil_img.copy()
        if aspect_ratio == "9:16":
            display_img.thumbnail((225, 400))
        else:
            display_img.thumbnail((400, 225))
        current_tk_img = ImageTk.PhotoImage(display_img)
        label_img_display.config(image=current_tk_img, text="")
        
        add_to_history(current_image_url, pil_img, "自定义图片")
        
        btn_dl_img.config(state=tk.NORMAL)
        show_toast("图片生成成功", "success")
        
    except Exception as e:
        err_msg = str(e)
        label_img_display.config(text=f"生成失败: {err_msg}", image="")
        ui_buffer.append(f"\n[系统日志: 图片生成失败 - {err_msg}]\n")
        show_toast("图片生成失败，请查看全文展示页日志", "warning")
    finally:
        btn_gen_img.config(state=tk.NORMAL)
        progress_bar.stop()

def download_image():
    global current_image_url
    if not current_image_url:
        show_toast("请先生成图片", "warning")
        return
        
    file_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG 图片", "*.png")], title="保存图片")
    if not file_path: return
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": entry_media_base_url.get().strip()
        }
        response = requests.get(current_image_url, headers=headers, timeout=30)
        response.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(response.content)
        show_toast("图片已保存", "success")
    except Exception as e:
        messagebox.showerror("下载失败", f"错误详情: {str(e)}\n\n下载链接:\n{current_image_url}")

def upload_image_for_video():
    global video_ref_image_path, video_ref_image_urls
    file_path = filedialog.askopenfilename(filetypes=[("图片文件", "*.png *.jpg *.jpeg *.webp")], title="选择参考图")
    if not file_path: return
    
    video_ref_image_path = file_path
    video_ref_image_urls = [] 
    listbox_vid_ref.selection_clear(0, tk.END) 
    
    for widget in frame_vid_ref_inner.winfo_children():
        widget.destroy()
        
    try:
        img = Image.open(file_path)
        current_upload_img = img.copy()
        current_upload_img.thumbnail((300, 200))
        current_tk_img = ImageTk.PhotoImage(current_upload_img)
        lbl = tk.Label(frame_vid_ref_inner, image=current_tk_img, bg=COLOR_PANEL)
        lbl.image = current_tk_img
        lbl.pack()
        tk.Label(frame_vid_ref_inner, text="已上传本地图片\n(注意:平台可能不支持本地路径)", bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, font=FONT_MAIN).pack()
    except Exception as e:
        tk.Label(frame_vid_ref_inner, text=f"加载失败: {str(e)}", bg=COLOR_PANEL, fg=COLOR_DANGER, font=FONT_MAIN).pack()

def clear_video_ref_image():
    global video_ref_image_urls, video_ref_image_path
    video_ref_image_urls = []
    video_ref_image_path = ""
    listbox_vid_ref.selection_clear(0, tk.END)
    for widget in frame_vid_ref_inner.winfo_children():
        widget.destroy()
    tk.Label(frame_vid_ref_inner, text="无参考图\n(从下方列表多选历史图片)", bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, font=FONT_MAIN, width=30, height=8).pack()

def handle_smart_video_gen(match_type):
    global vid_gen_state
    # 如果当前模式就是这个，说明是第二次点击，执行生成
    if vid_gen_state["mode"] == match_type:
        # 恢复UI
        btn_smart_ref.config(text="智能匹配参考图", state=tk.NORMAL)
        btn_smart_sb.config(text="智能匹配分镜图", state=tk.NORMAL)
        vid_gen_state["mode"] = None
        
        # 开始生成
        threading.Thread(target=lambda: generate_video(force_ref_urls=vid_gen_state["urls"])).start()
        vid_gen_state["urls"] = [] # 清空，防止重复使用
    else:
        # 第一次点击，执行匹配
        matched_urls = []
        if match_type == "history":
            # 优先取用户选中的，如果没有则取全部历史
            selected_indices = listbox_vid_ref.curselection()
            if selected_indices:
                matched_urls = [image_history[i]["url"] for i in selected_indices]
            else:
                matched_urls = [item["url"] for item in image_history]
                
            btn_smart_ref.config(text="✅ 确认并生成视频")
            btn_smart_sb.config(state=tk.DISABLED)
        elif match_type == "storyboard":
            matched_urls = sb_image_urls.copy()
            btn_smart_sb.config(text="✅ 确认并生成视频")
            btn_smart_ref.config(state=tk.DISABLED)
            
        if not matched_urls:
            show_toast("未匹配到相关图片，请先生成图片", "warning")
            # 恢复UI
            btn_smart_ref.config(text="智能匹配参考图", state=tk.NORMAL)
            btn_smart_sb.config(text="智能匹配分镜图", state=tk.NORMAL)
            return
            
        vid_gen_state = {"mode": match_type, "urls": matched_urls}
        
        # 在右侧预览区展示匹配到的图片
        for widget in frame_vid_ref_inner.winfo_children():
            widget.destroy()
            
        for i, url in enumerate(matched_urls):
            # 找到对应的pil_img
            pil_img = None
            for item in image_history:
                if item["url"] == url:
                    pil_img = item["img"]
                    break
            if not pil_img: continue
            
            row = i // 2
            col = i % 2
            img = pil_img.copy()
            img.thumbnail((120, 90))
            tk_img = ImageTk.PhotoImage(img)
            lbl = tk.Label(frame_vid_ref_inner, image=tk_img, bg=COLOR_PANEL)
            lbl.image = tk_img 
            lbl.grid(row=row, column=col, padx=5, pady=5)
            
        show_toast(f"已匹配 {len(matched_urls)} 张图，确认无误后再次点击按钮生成", "info")
def generate_video(force_ref_urls=None):
    global current_video_url, video_ref_image_urls, video_ref_image_path
    prompt = entry_vid_prompt.get("1.0", tk.END).strip()
    
    api_key = entry_media_api_key.get().strip()
    base_url = entry_media_base_url.get().strip()
    model_name = combo_vid_model.get().strip()
    
    if not api_key or not base_url or not model_name:
        show_toast("请先填写完整的媒体 API 配置并拉取模型", "warning")
        return

    btn_gen_vid.config(state=tk.DISABLED)
    label_vid_status.config(text="正在提交视频生成任务...")
    progress_bar.start()
    
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        try:
            duration_val = int(combo_vid_duration.get())
        except:
            duration_val = 5
            
        aspect_ratio = combo_vid_ratio.get()
        resolution = combo_vid_res.get()
        
        is_seedance_model = "seedance-2" in model_name.lower()
        
        if is_seedance_model:
            ui_buffer.append(f"[系统日志] 识别到 Seedance 模型，使用官方专用接口\n")
            url = f"{base_url.rstrip('/')}/contents/generations/tasks"
            
            content_array = [{"type": "text", "text": prompt}]
            
            current_ref_urls = force_ref_urls if force_ref_urls else video_ref_image_urls
                
            if current_ref_urls:
                for img_url in current_ref_urls:
                    content_array.append({
                        "type": "image_url",
                        "image_url": {"url": img_url},
                        "role": "reference_image"
                    })
            elif video_ref_image_path:
                show_toast("该平台暂不支持本地路径，请使用图床URL", "warning")
                return
                
            payload = {
                "model": model_name, 
                "content": content_array,
                "generate_audio": True,
                "ratio": aspect_ratio,
                "duration": duration_val, 
                "resolution": resolution,
                "watermark": False
            }
            
            ui_buffer.append(f"[系统日志] 视频请求 URL: {url}\n")
            ui_buffer.append(f"[系统日志] 视频请求 Payload: {json.dumps(payload, ensure_ascii=False)[:500]}\n")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            ui_buffer.append(f"[系统日志] 视频平台返回状态码: {response.status_code}\n")
            ui_buffer.append(f"[系统日志] 视频平台返回内容: {response.text[:500]}\n")
            
            if response.status_code != 200:
                try:
                    err_data = response.json()
                    err_msg = err_data.get("error", {}).get("message") or err_data.get("message") or str(err_data)
                except:
                    err_msg = response.text
                raise Exception(f"HTTP {response.status_code} - {err_msg}")
                
            result = response.json()
            task_id = result.get("id")
            if not task_id:
                raise Exception("未获取到视频任务 id")
                
            current_video_url = poll_seedance_task(base_url, headers, task_id)
            
        else:
            ui_buffer.append(f"[系统日志] 识别为通用模型，使用标准视频接口\n")
            # 修复：使用复数 /videos/generations
            url = f"{base_url.rstrip('/')}/videos/generations"
            
            payload = {
                "model": model_name, 
                "prompt": prompt, 
                "mode": "text-only", 
                "duration": duration_val, 
                "aspectRatio": aspect_ratio, 
                "resolution": resolution,
                "generateAudio": True
            }
            
            current_ref_urls = force_ref_urls if force_ref_urls else video_ref_image_urls
                
            if current_ref_urls:
                payload["mode"] = "reference" 
                payload["referenceImageUrls"] = current_ref_urls
            elif video_ref_image_path:
                show_toast("该平台暂不支持本地路径，请使用图床URL", "warning")
                return
                
            ui_buffer.append(f"[系统日志] 视频请求 URL: {url}\n")
            ui_buffer.append(f"[系统日志] 视频请求 Payload: {json.dumps(payload, ensure_ascii=False)[:500]}\n")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            ui_buffer.append(f"[系统日志] 视频平台返回状态码: {response.status_code}\n")
            ui_buffer.append(f"[系统日志] 视频平台返回内容: {response.text[:500]}\n")
            
            if response.status_code != 200:
                try:
                    err_data = response.json()
                    err_msg = err_data.get("error", {}).get("message") or err_data.get("message") or str(err_data)
                except:
                    err_msg = response.text
                raise Exception(f"HTTP {response.status_code} - {err_msg}")
                
            result = response.json()
            task_code = result.get("data", {}).get("taskCode") or result.get("task_id") or result.get("id")
            if not task_code:
                raise Exception("未获取到视频任务 taskCode 或 id")
                
            current_video_url = poll_task_result(base_url, headers, task_code, is_video=True)
            
        if not current_video_url:
            raise Exception("任务完成但未找到视频URL")
            
        video_history.append(current_video_url)
        safe_update_ui(update_video_history_ui)
        
        label_vid_status.config(text="视频生成成功！可在下方历史记录中播放或下载。")
        show_toast("视频生成成功", "success")
        
    except Exception as e:
        label_vid_status.config(text=f"生成失败: {str(e)}")
        show_toast("视频生成失败，请查看全文展示页日志", "warning")
    finally:
        btn_gen_vid.config(state=tk.NORMAL)
        progress_bar.stop()

def delete_video_from_history(idx):
    if 0 <= idx < len(video_history):
        del video_history[idx]
        update_video_history_ui()

def update_video_history_ui():
    for widget in frame_vid_history_inner.winfo_children():
        widget.destroy()
        
    for idx, url in enumerate(video_history):
        row_frame = tk.Frame(frame_vid_history_inner, bg=COLOR_PANEL)
        row_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(row_frame, text=f"视频 {idx+1}", font=FONT_MAIN, fg=COLOR_TEXT, bg=COLOR_PANEL, width=8).pack(side=tk.LEFT, padx=5)
        
        btn_play = tk.Button(row_frame, text="播放", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white", relief=tk.FLAT, 
                             command=lambda u=url: threading.Thread(target=lambda: play_specific_video(u)).start())
        btn_play.pack(side=tk.LEFT, padx=5, ipady=2)
        
        btn_dl = tk.Button(row_frame, text="下载", font=FONT_MAIN, bg=COLOR_SUCCESS, fg="white", relief=tk.FLAT, 
                           command=lambda u=url: download_specific_video(u))
        btn_dl.pack(side=tk.LEFT, padx=5, ipady=2)
        
        btn_del = tk.Button(row_frame, text="删除", font=FONT_MAIN, bg=COLOR_BORDER, fg="white", relief=tk.FLAT, 
                            command=lambda i=idx: delete_video_from_history(i))
        btn_del.pack(side=tk.LEFT, padx=5, ipady=2)
        
    root.update_idletasks()

def download_specific_video(url):
    file_path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 视频", "*.mp4")], title="保存视频")
    if not file_path: return
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": entry_media_base_url.get().strip()
        }
        response = requests.get(url, headers=headers, timeout=60, stream=True)
        response.raise_for_status()
        
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        show_toast("视频已保存", "success")
    except Exception as e:
        messagebox.showerror("下载失败", f"错误详情: {str(e)}\n\n下载链接:\n{url}")

def play_specific_video(url):
    temp_dir = os.path.join(os.getenv('TMPDIR', '/tmp'), "CineMaster_Videos")
    os.makedirs(temp_dir, exist_ok=True)
    temp_file = os.path.join(temp_dir, f"video_{uuid.uuid4().hex}.mp4")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": entry_media_base_url.get().strip()
        }
        response = requests.get(url, headers=headers, timeout=60, stream=True)
        response.raise_for_status()
        
        with open(temp_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        if platform.system() == 'Windows':
            os.startfile(temp_file)
        elif platform.system() == 'Darwin':
            subprocess.call(['open', temp_file])
        else:
            subprocess.call(['xdg-open', temp_file])
    except Exception as e:
        safe_update_ui(lambda: show_toast("播放失败", "warning"))

# ================= 模型拉取与联动逻辑 =================
models_cache = {"image": [], "video": []}
def fetch_models():
    btn_fetch_text_models.config(state=tk.DISABLED, text="拉取中...")
    btn_fetch_models.config(state=tk.DISABLED, text="拉取中...")
    
    def task():
        text_api_key = entry_api_key.get().strip()
        text_base_url = entry_base_url.get().strip()
        
        if text_api_key and text_base_url:
            try:
                text_url = f"{text_base_url.rstrip('/')}/models"
                text_headers = {"Authorization": f"Bearer {text_api_key}"}
                ui_buffer.append(f"[系统日志] 正在拉取文本模型: {text_url}\n")
                
                text_res = requests.get(text_url, headers=text_headers, timeout=15)
                ui_buffer.append(f"[系统日志] 文本模型响应状态码: {text_res.status_code}\n")
                
                if text_res.status_code == 200:
                    text_res_json = text_res.json()
                    text_models = []
                    def _extract_text_models(obj):
                        if isinstance(obj, list):
                            for item in obj:
                                _extract_text_models(item)
                        elif isinstance(obj, dict):
                            m_id = obj.get("id") or obj.get("model") or obj.get("name") or obj.get("model_id") or ""
                            if m_id and str(m_id) not in text_models:
                                text_models.append(str(m_id))
                            for key in ["data", "models", "list", "items", "results"]:
                                if key in obj:
                                    _extract_text_models(obj[key])
                                    
                    _extract_text_models(text_res_json)
                    
                    if text_models:
                        def update_text_ui():
                            combo_text_model['values'] = text_models
                            if combo_text_model.get() not in text_models:
                                combo_text_model.set(text_models[0])
                        safe_update_ui(update_text_ui)
                        ui_buffer.append(f"[系统日志] 文本模型拉取成功，共 {len(text_models)} 个\n")
                    else:
                        err_msg = f"文本模型解析失败，原始数据: {str(text_res_json)[:200]}"
                        ui_buffer.append(f"[系统日志] {err_msg}\n")
                        safe_update_ui(lambda: messagebox.showwarning("文本模型", err_msg))
                else:
                    err_msg = f"文本模型拉取失败: HTTP {text_res.status_code}\n{text_res.text[:200]}"
                    ui_buffer.append(f"[系统日志] {err_msg}\n")
                    safe_update_ui(lambda: messagebox.showerror("文本模型", err_msg))
            except Exception as e:
                err_msg = f"文本模型拉取异常: {str(e)}"
                ui_buffer.append(f"[系统日志] {err_msg}\n")
                safe_update_ui(lambda: messagebox.showerror("文本模型", err_msg))

        api_key = entry_media_api_key.get().strip()
        base_url = entry_media_base_url.get().strip()
        
        if not api_key or not base_url:
            safe_update_ui(lambda: show_toast("请先填写媒体 API 配置", "warning"))
            safe_update_ui(lambda: btn_fetch_text_models.config(state=tk.NORMAL, text="拉取文本模型"))
            safe_update_ui(lambda: btn_fetch_models.config(state=tk.NORMAL, text="拉取媒体模型"))
            return
            
        try:
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            ui_buffer.append(f"[系统日志] 正在拉取媒体模型: {url}\n")
            res = requests.get(url, headers=headers, timeout=15)
            ui_buffer.append(f"[系统日志] 媒体模型响应状态码: {res.status_code}\n")
            
            if res.status_code != 200:
                err_msg = f"媒体模型拉取失败: HTTP {res.status_code}\n{res.text[:200]}"
                ui_buffer.append(f"[系统日志] {err_msg}\n")
                safe_update_ui(lambda: messagebox.showerror("媒体模型", err_msg))
                raise Exception(err_msg)
                
            res_json = res.json()
            
            img_models = []
            vid_models = []
            
            def _extract_media_models(obj):
                if isinstance(obj, list):
                    for item in obj:
                        _extract_media_models(item)
                elif isinstance(obj, dict):
                    model_id = obj.get("id") or obj.get("model") or obj.get("name") or obj.get("model_id") or ""
                    caps = obj.get("capabilities", {}) or obj.get("capability", {}) or obj.get("supported_modes", {})
                    
                    if model_id:
                        model_id = str(model_id)
                        if not caps:
                            if model_id not in img_models:
                                img_models.append(model_id)
                                models_cache["image"].append({
                                    "id": model_id,
                                    "ratios": ["16:9", "9:16", "1:1"],
                                    "resolutions": ["1k", "2k", "4k"]
                                })
                            if model_id not in vid_models:
                                vid_models.append(model_id)
                                models_cache["video"].append({
                                    "id": model_id,
                                    "ratios": ["16:9", "9:16", "1:1"],
                                    "resolutions": ["480p", "720p", "1080p"],
                                    "durations": [str(i) for i in range(4, 16)]
                                })
                        else:
                            if "image" in caps or "IMAGE" in caps:
                                if model_id not in img_models:
                                    img_models.append(model_id)
                                    cap_img = caps.get("image", caps.get("IMAGE", {}))
                                    models_cache["image"].append({
                                        "id": model_id,
                                        "ratios": cap_img.get("aspectRatios", cap_img.get("ratios", ["16:9", "9:16", "1:1"])),
                                        "resolutions": cap_img.get("resolutions", ["1k", "2k", "4k"])
                                    })
                            if "video" in caps or "VIDEO" in caps:
                                if model_id not in vid_models:
                                    vid_models.append(model_id)
                                    cap_vid = caps.get("video", caps.get("VIDEO", {}))
                                    models_cache["video"].append({
                                        "id": model_id,
                                        "ratios": cap_vid.get("aspectRatios", cap_vid.get("ratios", ["16:9", "9:16", "1:1"])),
                                        "resolutions": cap_vid.get("resolutions", ["480p", "720p", "1080p"]),
                                        "durations": cap_vid.get("durations", [str(i) for i in range(4, 16)])
                                    })
                                
                    for key in ["data", "models", "list", "items", "results"]:
                        if key in obj:
                            _extract_media_models(obj[key])
                            
            _extract_media_models(res_json)
                    
            def update_media_ui():
                combo_img_model['values'] = img_models
                combo_vid_model['values'] = vid_models
                if img_models: combo_img_model.set(img_models[0])
                if vid_models: combo_vid_model.set(vid_models[0])
                on_img_model_change(None)
                on_vid_model_change(None)
                show_toast(f"拉取成功: {len(combo_text_model['values'])}个文本, {len(img_models)}个图片, {len(vid_models)}个视频", "success")
            
            safe_update_ui(update_media_ui)
            ui_buffer.append(f"[系统日志] 媒体模型拉取成功: {len(img_models)}个图片, {len(vid_models)}个视频\n")
            
        except Exception as e:
            err_msg = f"媒体模型拉取异常: {str(e)}"
            ui_buffer.append(f"[系统日志] {err_msg}\n")
            safe_update_ui(lambda: messagebox.showerror("媒体模型", err_msg))
        finally:
            safe_update_ui(lambda: btn_fetch_text_models.config(state=tk.NORMAL, text="拉取文本模型"))
            safe_update_ui(lambda: btn_fetch_models.config(state=tk.NORMAL, text="拉取媒体模型"))

    threading.Thread(target=task, daemon=True).start()

def on_img_model_change(event):
    model_id = combo_img_model.get()
    for m in models_cache["image"]:
        if m["id"] == model_id:
            combo_img_ratio['values'] = m["ratios"]
            if m["ratios"]: combo_img_ratio.set(m["ratios"][0])
            combo_img_res['values'] = m["resolutions"]
            if m["resolutions"]: combo_img_res.set(m["resolutions"][0])
            break
    update_image_credits()

def on_vid_model_change(event):
    model_id = combo_vid_model.get()
    for m in models_cache["video"]:
        if m["id"] == model_id:
            combo_vid_ratio['values'] = m["ratios"]
            if m["ratios"]: combo_vid_ratio.set(m["ratios"][0])
            combo_vid_res['values'] = m["resolutions"]
            if m["resolutions"]: combo_vid_res.set(m["resolutions"][0])
            
            durations = m.get("durations", [])
            if durations:
                combo_vid_duration['values'] = durations
                combo_vid_duration.set(durations[0])
            break
    update_video_credits()

# ================= 积分预估系统 =================
def update_image_credits(event=None):
    res = combo_img_res.get()
    ratio = combo_img_ratio.get()
    
    base = 4
    res_mult = {"1k": 1, "2k": 2, "4k": 4, "8k": 8}.get(res, 1)
    ratio_mult = {"16:9": 1.2, "9:16": 1.0}.get(ratio, 1.0)
    
    credits = int(base * res_mult * ratio_mult)
    label_img_credits.config(text=f"预计消耗: {credits} 积分")

def update_video_credits(event=None):
    res = combo_vid_res.get()
    ratio = combo_vid_ratio.get()
    try:
        duration = int(combo_vid_duration.get())
    except:
        duration = 5
        
    base_per_sec = 5
    res_mult = {"480p": 1, "720p": 2, "1080p": 4, "2k": 8, "4k": 16, "8k": 32}.get(res, 4)
    ratio_mult = {"16:9": 1.2, "9:16": 1.0}.get(ratio, 1.0)
    
    credits = int(base_per_sec * duration * res_mult * ratio_mult)
    label_vid_credits.config(text=f"预计消耗: {credits} 积分")

# ================= Toast 通知系统 =================
def show_toast(message, msg_type="info"):
    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    
    if msg_type == "success":
        bg_color = "#34C759" 
        fg_color = "#FFFFFF"
    elif msg_type == "warning":
        bg_color = "#FF9500" 
        fg_color = "#FFFFFF"
    else:
        bg_color = "#333333"
        fg_color = "#FFFFFF"
        
    toast.configure(bg=bg_color)
    
    label = tk.Label(toast, text=message, font=("微软雅黑", 10, "bold"), bg=bg_color, fg=fg_color, padx=20, pady=10)
    label.pack()
    
    root.update_idletasks()
    x = root.winfo_x() + root.winfo_width() - 250 - 20
    y = root.winfo_y() + root.winfo_height() - 60 - 20
    toast.geometry(f"+{x}+{y}")
    
    toast.attributes("-alpha", 0.0)
    for i in range(11):
        toast.attributes("-alpha", i/10)
        toast.update()
        time.sleep(0.01)
        
    toast.after(2000, lambda: fade_out_toast(toast))

def fade_out_toast(toast):
    try:
        for i in range(10, -1, -1):
            toast.attributes("-alpha", i/10)
            toast.update()
            time.sleep(0.01)
        toast.destroy()
    except:
        pass

def copy_all_text():
    content = text_widgets["all"].get("1.0", tk.END)
    root.clipboard_clear()
    root.clipboard_append(content)
    show_toast("全文已复制到剪贴板", "success")
# ================= 界面布局区 =================
COLOR_BG = "#F0F2F5"          
COLOR_PANEL = "#FFFFFF"       
COLOR_INPUT = "#F5F7FA"       
COLOR_TEXT = "#333333"        
COLOR_TEXT_DIM = "#8E8E93"    
COLOR_ACCENT = "#007AFF"      
COLOR_ACCENT_DARK = "#005ECB" 
COLOR_DANGER = "#FF3B30"      
COLOR_SUCCESS = "#34C759"     
COLOR_BORDER = "#E0E0E0"      
COLOR_WATERMARK = "#E8E8E8"   
COLOR_CREDITS = "#FF9500"     

FONT_TITLE = ("PingFang SC", 13, "bold")
FONT_MAIN = ("PingFang SC", 11)
FONT_CODE = ("Menlo", 12)

def resource_path(relative_path):
    return os.path.join(BUNDLE_DIR, relative_path)

def bind_hover(widget, normal_bg, hover_bg):
    widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg))
    widget.bind("<Leave>", lambda e: widget.config(bg=normal_bg))

root = tk.Tk()
root.title("CineMaster - AI 影视工业级分镜系统")

screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
win_width = min(1280, screen_width - 100)
win_height = min(860, screen_height - 100)
root.geometry(f"{win_width}x{win_height}+50+50")
root.minsize(1024, 700)
root.configure(bg=COLOR_BG)
root.withdraw()

is_licensed, err_msg = check_license_on_start()
if not is_licensed:
    if err_msg and err_msg != "未找到授权文件":
        messagebox.showerror("授权错误", err_msg)
    dialog = ActivationDialog(root)
    root.wait_window(dialog)
    if not dialog.activated:
        root.destroy()
        exit()

update_last_run_time()
root.deiconify()

icon_path = resource_path("app.ico")
if os.path.exists(icon_path):
    try:
        # Mac 专用图标设置
        img_icon = Image.open(icon_path)
        tk_icon = ImageTk.PhotoImage(img_icon)
        root.iconphoto(True, tk_icon)
    except:
        pass

current_config = load_config()

canvas_watermark = tk.Canvas(root, bg=COLOR_BG, highlightthickness=0)
canvas_watermark.place(relx=0, rely=0, relwidth=1, relheight=1)

def draw_watermark(event=None):
    canvas_watermark.delete("all")
    w = canvas_watermark.winfo_width()
    h = canvas_watermark.winfo_height()
    for y in range(-100, h + 100, 150):
        for x in range(-200, w + 200, 300):
            canvas_watermark.create_text(x, y, text="CineMaster", angle=30, fill=COLOR_WATERMARK, font=("Arial", 24, "bold"))
canvas_watermark.bind("<Configure>", draw_watermark)

main_container = tk.Frame(root, bg=COLOR_BG)
main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
main_container.tkraise()

frame_header = tk.Frame(main_container, bg=COLOR_BG)
frame_header.pack(fill=tk.X, pady=(0, 5))

logo_path = resource_path("app.ico")
if os.path.exists(logo_path):
    img_logo = Image.open(logo_path).resize((32, 32), Image.Resampling.LANCZOS)
    tk_logo = ImageTk.PhotoImage(img_logo)
    tk.Label(frame_header, image=tk_logo, bg=COLOR_BG).pack(side=tk.LEFT, padx=(0, 10))

tk.Label(frame_header, text="CineMaster", font=("微软雅黑", 16, "bold"), fg=COLOR_ACCENT, bg=COLOR_BG).pack(side=tk.LEFT)
tk.Label(frame_header, text="| 全链路自动化影视生产力引擎", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_BG).pack(side=tk.LEFT, padx=10)

frame_config = tk.Frame(main_container, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_config.pack(fill=tk.X, pady=5)

def create_styled_entry(parent, **kwargs):
    return tk.Entry(parent, font=FONT_MAIN, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.FLAT, bd=5, **kwargs)

def create_styled_label(parent, text):
    return tk.Label(parent, text=text, font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)

frame_text_api = tk.Frame(frame_config, bg=COLOR_PANEL)
frame_text_api.pack(fill=tk.X, padx=10, pady=5)
create_styled_label(frame_text_api, "文本大模型 API").pack(anchor="w", pady=(2,5))

frame_text_grid = tk.Frame(frame_text_api, bg=COLOR_PANEL)
frame_text_grid.pack(fill=tk.X)

create_styled_label(frame_text_grid, "API Key:").grid(row=0, column=0, sticky="w", padx=5)
entry_api_key = create_styled_entry(frame_text_grid, width=30, show="*")
entry_api_key.grid(row=0, column=1, sticky="w", padx=5)

create_styled_label(frame_text_grid, "Base URL:").grid(row=0, column=2, sticky="w", padx=5)
entry_base_url = create_styled_entry(frame_text_grid, width=35)
entry_base_url.grid(row=0, column=3, sticky="w", padx=5)

create_styled_label(frame_text_grid, "模型名:").grid(row=0, column=4, sticky="w", padx=5)
combo_text_model = ttk.Combobox(frame_text_grid, width=18, font=FONT_MAIN)
combo_text_model.grid(row=0, column=5, sticky="w", padx=5)

btn_fetch_text_models = tk.Button(frame_text_grid, text="拉取文本模型", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white", relief=tk.FLAT, command=fetch_models)
btn_fetch_text_models.grid(row=0, column=6, sticky="w", padx=5, pady=2, ipady=3)
bind_hover(btn_fetch_text_models, COLOR_ACCENT_DARK, COLOR_ACCENT)

frame_media_api = tk.Frame(frame_config, bg=COLOR_PANEL)
frame_media_api.pack(fill=tk.X, padx=10, pady=5)
create_styled_label(frame_media_api, "媒体生成模型 API").pack(anchor="w", pady=(2,5))

frame_media_grid = tk.Frame(frame_media_api, bg=COLOR_PANEL)
frame_media_grid.pack(fill=tk.X)

create_styled_label(frame_media_grid, "API Key:").grid(row=0, column=0, sticky="w", padx=5)
entry_media_api_key = create_styled_entry(frame_media_grid, width=30, show="*")
entry_media_api_key.grid(row=0, column=1, sticky="w", padx=5)

create_styled_label(frame_media_grid, "Base URL:").grid(row=0, column=2, sticky="w", padx=5)
entry_media_base_url = create_styled_entry(frame_media_grid, width=35)
entry_media_base_url.grid(row=0, column=3, sticky="w", padx=5)

btn_fetch_models = tk.Button(frame_media_grid, text="拉取媒体模型", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white", relief=tk.FLAT, command=fetch_models)
btn_fetch_models.grid(row=0, column=4, sticky="w", padx=5, pady=2, ipady=3)
bind_hover(btn_fetch_models, COLOR_ACCENT_DARK, COLOR_ACCENT)

create_styled_label(frame_media_grid, "图片模型:").grid(row=0, column=5, sticky="w", padx=5)
combo_img_model = ttk.Combobox(frame_media_grid, width=15, font=FONT_MAIN)
combo_img_model.grid(row=0, column=6, sticky="w", padx=5)
combo_img_model.bind("<<ComboboxSelected>>", on_img_model_change)

create_styled_label(frame_media_grid, "视频模型:").grid(row=0, column=7, sticky="w", padx=5)
combo_vid_model = ttk.Combobox(frame_media_grid, width=15, font=FONT_MAIN)
combo_vid_model.grid(row=0, column=8, sticky="w", padx=5)
combo_vid_model.bind("<<ComboboxSelected>>", on_vid_model_change)

btn_save_config = tk.Button(frame_media_grid, text="保存配置", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, command=save_config)
btn_save_config.grid(row=0, column=9, sticky="w", padx=10, pady=2, ipady=3)
bind_hover(btn_save_config, COLOR_ACCENT, COLOR_ACCENT_DARK)

entry_api_key.insert(0, current_config["api_key"])
entry_base_url.insert(0, current_config["base_url"])
combo_text_model.set(current_config["model_name"])
entry_media_api_key.insert(0, current_config["media_api_key"])
entry_media_base_url.insert(0, current_config["media_base_url"])
combo_img_model.set(current_config["img_model"])
combo_vid_model.set(current_config["vid_model"])

frame_bottom_bar = tk.Frame(main_container, bg=COLOR_BG)
frame_bottom_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

frame_main = tk.PanedWindow(main_container, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg=COLOR_BG)
frame_main.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=5)

frame_left = tk.Frame(frame_main, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_main.add(frame_left, minsize=300, width=500)

paned_left = tk.PanedWindow(frame_left, orient=tk.VERTICAL, sashwidth=6, sashrelief=tk.RAISED, bg=COLOR_BG)
paned_left.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

frame_novel = tk.Frame(paned_left, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER, highlightthickness=1)
tk.Label(frame_novel, text="▼ 小说文本输入", font=FONT_TITLE, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w", padx=10, pady=5)
text_input_novel = scrolledtext.ScrolledText(frame_novel, wrap=tk.WORD, font=FONT_CODE, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.SOLID, bd=1, highlightbackground=COLOR_BORDER, highlightthickness=1)
text_input_novel.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
paned_left.add(frame_novel, minsize=100)

frame_command = tk.Frame(paned_left, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER, highlightthickness=1)
tk.Label(frame_command, text="▼ 附加指令/诉求", font=FONT_TITLE, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w", padx=10, pady=5)
text_input_command = scrolledtext.ScrolledText(frame_command, wrap=tk.WORD, font=FONT_CODE, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.SOLID, bd=1, highlightbackground=COLOR_BORDER, highlightthickness=1, height=5)
text_input_command.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
paned_left.add(frame_command, minsize=50)

btn_generate = tk.Button(frame_bottom_bar, text="▶ 开始转化", font=("微软雅黑", 12, "bold"), bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, command=generate_storyboard)
btn_generate.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5), ipady=5)
bind_hover(btn_generate, COLOR_ACCENT, COLOR_ACCENT_DARK)

btn_stop = tk.Button(frame_bottom_bar, text="■ 停止生成", font=("微软雅黑", 12, "bold"), bg=COLOR_DANGER, fg="white", relief=tk.FLAT, state=tk.DISABLED, command=stop_generation)
btn_stop.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0), ipady=5)
bind_hover(btn_stop, COLOR_DANGER, "#D63027")

frame_right = tk.Frame(frame_main, bg=COLOR_BG, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_main.add(frame_right, minsize=400)

style = ttk.Style()
style.theme_use('clam')
style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
style.configure("TNotebook.Tab", background=COLOR_PANEL, foreground=COLOR_TEXT_DIM, padding=[15, 5], font=FONT_MAIN)
style.map("TNotebook.Tab", background=[("selected", COLOR_ACCENT)], foreground=[("selected", "#FFFFFF")])
style.configure("TFrame", background=COLOR_PANEL)

notebook = ttk.Notebook(frame_right)
notebook.pack(fill=tk.BOTH, expand=True, pady=5)

text_widgets = {}
sections = [
    ("all", "全文展示"), ("script", "剧本正文"), ("character", "角色资产"),
    ("scene", "场景资产"), ("prop", "道具资产"), ("storyboard", "分镜资产"), 
    ("sb_prompt", "分镜图提示词"), ("editing", "剪辑方案")
]

for key, title in sections:
    frame_tab = tk.Frame(notebook, bg=COLOR_INPUT)
    notebook.add(frame_tab, text=title)
    if key == "all":
        btn_copy_all = tk.Button(frame_tab, text="一键复制全文", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=copy_all_text)
        btn_copy_all.pack(side=tk.TOP, anchor="e", padx=5, pady=5)
        bind_hover(btn_copy_all, COLOR_BORDER, "#D0D0D0")
    txt = scrolledtext.ScrolledText(frame_tab, wrap=tk.WORD, font=FONT_CODE, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.SOLID, bd=1, highlightbackground=COLOR_BORDER, highlightthickness=1)
    txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    text_widgets[key] = txt

# ==================== 图片生成页 ====================
frame_img = tk.Frame(notebook, bg=COLOR_INPUT)
notebook.add(frame_img, text="图片生成")

frame_img_top = tk.Frame(frame_img, bg=COLOR_INPUT, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_img_top.pack(fill=tk.X, pady=5, padx=5)
tk.Label(frame_img_top, text="提示词 (支持中英双语):", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", padx=5, pady=5)
entry_img_prompt = tk.Text(frame_img_top, height=4, font=FONT_CODE, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.SOLID, bd=1, highlightbackground=COLOR_BORDER, highlightthickness=1, wrap=tk.WORD)
entry_img_prompt.pack(fill=tk.X, padx=5, pady=5)

frame_img_settings = tk.Frame(frame_img, bg=COLOR_INPUT, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_img_settings.pack(fill=tk.X, pady=2, padx=5)
tk.Label(frame_img_settings, text="比例:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_img_ratio = ttk.Combobox(frame_img_settings, values=["16:9", "9:16"], width=6, state="readonly", font=FONT_MAIN)
combo_img_ratio.set("16:9")
combo_img_ratio.pack(side=tk.LEFT, padx=5)
combo_img_ratio.bind("<<ComboboxSelected>>", update_image_credits)

tk.Label(frame_img_settings, text="分辨率:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_img_res = ttk.Combobox(frame_img_settings, values=["1k", "2k", "4k", "8k"], width=6, state="readonly", font=FONT_MAIN)
combo_img_res.set("1k")
combo_img_res.pack(side=tk.LEFT, padx=5)
combo_img_res.bind("<<ComboboxSelected>>", update_image_credits)

label_img_credits = tk.Label(frame_img_settings, text="预计消耗: 4 积分", font=FONT_MAIN, fg=COLOR_CREDITS, bg=COLOR_INPUT)
label_img_credits.pack(side=tk.LEFT, padx=15)

frame_img_btns = tk.Frame(frame_img, bg=COLOR_INPUT)
frame_img_btns.pack(fill=tk.X, pady=5, padx=5)
btn_extract_prompt = tk.Button(frame_img_btns, text="提取提示词", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=extract_latest_prompt)
btn_extract_prompt.pack(side=tk.LEFT, padx=2, ipady=2)
bind_hover(btn_extract_prompt, COLOR_BORDER, "#D0D0D0")

btn_gen_img = tk.Button(frame_img_btns, text="生成图片", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, command=lambda: threading.Thread(target=generate_image).start())
btn_gen_img.pack(side=tk.LEFT, padx=2, ipady=2)
bind_hover(btn_gen_img, COLOR_ACCENT, COLOR_ACCENT_DARK)
btn_gen_all_img = tk.Button(frame_img_btns, text="一键并发生图", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white", relief=tk.FLAT, command=generate_all_assets)
btn_gen_all_img.pack(side=tk.LEFT, padx=2, ipady=2)
bind_hover(btn_gen_all_img, COLOR_ACCENT_DARK, COLOR_ACCENT)

btn_dl_img = tk.Button(frame_img_btns, text="下载当前图", font=FONT_MAIN, bg=COLOR_SUCCESS, fg="white", relief=tk.FLAT, state=tk.DISABLED, command=download_image)
btn_dl_img.pack(side=tk.LEFT, padx=2, ipady=2)

label_img_display = tk.Label(frame_img, text="", bg=COLOR_INPUT, fg=COLOR_TEXT_DIM, font=FONT_MAIN)

frame_img_history = tk.Frame(frame_img, bg=COLOR_INPUT)
frame_img_history.pack(fill=tk.BOTH, expand=True, pady=(5,0))

tk.Label(frame_img_history, text="▼ 历史记录 (横向滚动，点击放大，可删除)", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=2)

history_canvas = tk.Canvas(frame_img_history, bg=COLOR_PANEL, highlightthickness=0)
history_scroll = ttk.Scrollbar(frame_img_history, orient="horizontal", command=history_canvas.xview)
history_frame_inner = tk.Frame(history_canvas, bg=COLOR_PANEL)
history_frame_inner.bind("<Configure>", lambda e: history_canvas.configure(scrollregion=history_canvas.bbox("all")))
history_canvas.create_window((0, 0), window=history_frame_inner, anchor="nw")
history_canvas.configure(xscrollcommand=history_scroll.set)
history_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
history_scroll.pack(side=tk.BOTTOM, fill=tk.X)

# ==================== 分镜图生成页 ====================
frame_sb = tk.Frame(notebook, bg=COLOR_INPUT)
notebook.add(frame_sb, text="分镜图生成")

paned_sb_main = tk.PanedWindow(frame_sb, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg=COLOR_INPUT)
paned_sb_main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

# 左侧：提示词、参数、按钮、历史
frame_sb_left = tk.Frame(paned_sb_main, bg=COLOR_INPUT, highlightbackground=COLOR_BORDER, highlightthickness=1)
paned_sb_main.add(frame_sb_left, minsize=400)

frame_sb_top = tk.Frame(frame_sb_left, bg=COLOR_INPUT)
frame_sb_top.pack(fill=tk.X, pady=5, padx=5)
tk.Label(frame_sb_top, text="分镜提示词 (自动引用参考图，按序号命名):", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w")
entry_storyboard_prompt = tk.Text(frame_sb_top, height=4, font=FONT_CODE, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.SOLID, bd=1, highlightbackground=COLOR_BORDER, highlightthickness=1, wrap=tk.WORD)
entry_storyboard_prompt.pack(fill=tk.X, pady=2)

frame_sb_settings = tk.Frame(frame_sb_left, bg=COLOR_INPUT)
frame_sb_settings.pack(fill=tk.X, pady=2, padx=5)
tk.Label(frame_sb_settings, text="比例:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_sb_ratio = ttk.Combobox(frame_sb_settings, values=["16:9", "9:16"], width=6, state="readonly", font=FONT_MAIN)
combo_sb_ratio.set("16:9")
combo_sb_ratio.pack(side=tk.LEFT, padx=5)

tk.Label(frame_sb_settings, text="分辨率:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_sb_res = ttk.Combobox(frame_sb_settings, values=["1k", "2k", "4k", "8k"], width=6, state="readonly", font=FONT_MAIN)
combo_sb_res.set("1k")
combo_sb_res.pack(side=tk.LEFT, padx=5)

label_sb_credits = tk.Label(frame_sb_settings, text="预计消耗: 4 积分", font=FONT_MAIN, fg=COLOR_CREDITS, bg=COLOR_INPUT)
label_sb_credits.pack(side=tk.LEFT, padx=15)

frame_sb_btns = tk.Frame(frame_sb_left, bg=COLOR_INPUT)
frame_sb_btns.pack(fill=tk.X, pady=5, padx=5)

btn_match_ref = tk.Button(frame_sb_btns, text="一键匹配参考图", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=match_ref_for_storyboard)
btn_match_ref.pack(side=tk.LEFT, padx=2, ipady=2)
bind_hover(btn_match_ref, COLOR_BORDER, "#D0D0D0")

btn_gen_sb = tk.Button(frame_sb_btns, text="生成分镜图", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, command=lambda: threading.Thread(target=lambda: generate_storyboard_image(use_ref=True)).start())
btn_gen_sb.pack(side=tk.LEFT, padx=2, ipady=2)
bind_hover(btn_gen_sb, COLOR_ACCENT, COLOR_ACCENT_DARK)

label_sb_ref_status = tk.Label(frame_sb_btns, text="未匹配参考图", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT)
label_sb_ref_status.pack(side=tk.LEFT, padx=10)

frame_sb_history = tk.Frame(frame_sb_left, bg=COLOR_INPUT)
frame_sb_history.pack(fill=tk.BOTH, expand=True, pady=(5,0))

tk.Label(frame_sb_history, text="▼ 分镜历史记录 (横向滚动)", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=2)

sb_history_canvas = tk.Canvas(frame_sb_history, bg=COLOR_PANEL, highlightthickness=0)
sb_history_scroll = ttk.Scrollbar(frame_sb_history, orient="horizontal", command=sb_history_canvas.xview)
sb_history_frame_inner = tk.Frame(sb_history_canvas, bg=COLOR_PANEL)
sb_history_frame_inner.bind("<Configure>", lambda e: sb_history_canvas.configure(scrollregion=sb_history_canvas.bbox("all")))
sb_history_canvas.create_window((0, 0), window=sb_history_frame_inner, anchor="nw")
sb_history_canvas.configure(xscrollcommand=sb_history_scroll.set)
sb_history_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
sb_history_scroll.pack(side=tk.BOTTOM, fill=tk.X)

# 右侧：资产引用多选列表
frame_sb_right = tk.Frame(paned_sb_main, bg=COLOR_INPUT)
paned_sb_main.add(frame_sb_right, minsize=300)

tk.Label(frame_sb_right, text="选择历史图片作为参考:", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=5)

sb_listbox_frame = tk.Frame(frame_sb_right, bg=COLOR_INPUT)
sb_listbox_frame.pack(fill=tk.BOTH, expand=True, pady=2)
sb_listbox_scroll = ttk.Scrollbar(sb_listbox_frame, orient="vertical")
listbox_sb_ref = tk.Listbox(sb_listbox_frame, height=10, selectmode=tk.MULTIPLE, font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT, selectbackground=COLOR_ACCENT, selectforeground="white", relief=tk.FLAT, bd=2, highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_ACCENT)
sb_listbox_scroll.config(command=listbox_sb_ref.yview)
listbox_sb_ref.config(yscrollcommand=sb_listbox_scroll.set)
listbox_sb_ref.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
sb_listbox_scroll.pack(side=tk.RIGHT, fill=tk.Y)
# ==================== 视频生成页 (可拖拽缩放布局) ====================
frame_vid = tk.Frame(notebook, bg=COLOR_INPUT)
notebook.add(frame_vid, text="视频生成")

paned_vid_main = tk.PanedWindow(frame_vid, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg=COLOR_INPUT)
paned_vid_main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

# --- 左侧板块：设置区 + 视频历史记录 ---
frame_vid_left = tk.Frame(paned_vid_main, bg=COLOR_INPUT, highlightbackground=COLOR_BORDER, highlightthickness=1)
paned_vid_main.add(frame_vid_left, minsize=250) # 减小minsize允许向右拖拽

paned_vid_left_inner = tk.PanedWindow(frame_vid_left, orient=tk.VERTICAL, sashwidth=4, sashrelief=tk.FLAT, bg=COLOR_INPUT)
paned_vid_left_inner.pack(fill=tk.BOTH, expand=True)

# 设置区
frame_vid_settings = tk.Frame(paned_vid_left_inner, bg=COLOR_INPUT)
paned_vid_left_inner.add(frame_vid_settings, minsize=250)

tk.Label(frame_vid_settings, text="视频提示词:", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=5)
entry_vid_prompt = tk.Text(frame_vid_settings, height=5, font=FONT_CODE, bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT, relief=tk.FLAT, bd=5, wrap=tk.WORD)
entry_vid_prompt.pack(fill=tk.X, pady=2)

frame_vid_params = tk.Frame(frame_vid_settings, bg=COLOR_INPUT)
frame_vid_params.pack(fill=tk.X, pady=2)

tk.Label(frame_vid_params, text="时长:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_vid_duration = ttk.Combobox(frame_vid_params, values=[str(i) for i in range(4, 16)], width=4, state="readonly", font=FONT_MAIN)
combo_vid_duration.set("5")
combo_vid_duration.pack(side=tk.LEFT, padx=2)
combo_vid_duration.bind("<<ComboboxSelected>>", update_video_credits)

tk.Label(frame_vid_params, text="比例:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_vid_ratio = ttk.Combobox(frame_vid_params, values=["16:9", "9:16"], width=5, state="readonly", font=FONT_MAIN)
combo_vid_ratio.set("16:9")
combo_vid_ratio.pack(side=tk.LEFT, padx=2)
combo_vid_ratio.bind("<<ComboboxSelected>>", update_video_credits)

tk.Label(frame_vid_params, text="分辨率:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
combo_vid_res = ttk.Combobox(frame_vid_params, values=["480p", "720p", "1080p", "2k", "4k", "8k"], width=5, state="readonly", font=FONT_MAIN)
combo_vid_res.set("1080p")
combo_vid_res.pack(side=tk.LEFT, padx=2)
combo_vid_res.bind("<<ComboboxSelected>>", update_video_credits)

# 预估积分单独一行，防止被遮挡
label_vid_credits = tk.Label(frame_vid_settings, text="预计消耗: 24 积分", font=FONT_MAIN, fg=COLOR_CREDITS, bg=COLOR_INPUT)
label_vid_credits.pack(anchor="w", pady=(5,0))

# 智能生成按钮区
frame_vid_smart_btns = tk.Frame(frame_vid_settings, bg=COLOR_INPUT)
frame_vid_smart_btns.pack(fill=tk.X, pady=10)

btn_smart_ref = tk.Button(frame_vid_smart_btns, text="智能匹配参考图", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, command=lambda: handle_smart_video_gen("history"))
btn_smart_ref.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2, ipady=5)
bind_hover(btn_smart_ref, COLOR_ACCENT, COLOR_ACCENT_DARK)

btn_smart_sb = tk.Button(frame_vid_smart_btns, text="智能匹配分镜图", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white", relief=tk.FLAT, command=lambda: handle_smart_video_gen("storyboard"))
btn_smart_sb.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2, ipady=5)
bind_hover(btn_smart_sb, COLOR_ACCENT_DARK, COLOR_ACCENT)

btn_gen_vid = tk.Button(frame_vid_settings, text="▶ 生成视频", font=("微软雅黑", 11, "bold"), bg=COLOR_SUCCESS, fg="white", relief=tk.FLAT, command=lambda: threading.Thread(target=lambda: generate_video(), daemon=True).start())
btn_gen_vid.pack(fill=tk.X, pady=(10, 5), ipady=5)
bind_hover(btn_gen_vid, COLOR_SUCCESS, "#28A745")

label_vid_status = tk.Label(frame_vid_settings, text="等待生成...", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT)
label_vid_status.pack(anchor="w", pady=5)

# 视频历史记录区
frame_vid_history = tk.Frame(paned_vid_left_inner, bg=COLOR_INPUT)
paned_vid_left_inner.add(frame_vid_history, minsize=150)

tk.Label(frame_vid_history, text="▼ 视频历史记录", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=2)

history_vid_canvas = tk.Canvas(frame_vid_history, bg=COLOR_PANEL, highlightthickness=0)
history_vid_scroll = ttk.Scrollbar(frame_vid_history, orient="vertical", command=history_vid_canvas.yview)
frame_vid_history_inner = tk.Frame(history_vid_canvas, bg=COLOR_PANEL)
frame_vid_history_inner.bind("<Configure>", lambda e: history_vid_canvas.configure(scrollregion=history_vid_canvas.bbox("all")))
history_vid_canvas.create_window((0, 0), window=frame_vid_history_inner, anchor="nw")
history_vid_canvas.configure(yscrollcommand=history_vid_scroll.set)
history_vid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
history_vid_scroll.pack(side=tk.RIGHT, fill=tk.Y)

# --- 右侧板块：关联图片预览区 ---
frame_vid_right = tk.Frame(paned_vid_main, bg=COLOR_INPUT)
paned_vid_main.add(frame_vid_right, minsize=300) # 减小minsize允许向左拖拽

tk.Label(frame_vid_right, text="参考图设置 (按住 Ctrl 多选)", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=5)

ref_preview_canvas = tk.Canvas(frame_vid_right, bg=COLOR_PANEL, highlightthickness=0, height=200)
ref_preview_scroll = ttk.Scrollbar(frame_vid_right, orient="vertical", command=ref_preview_canvas.yview)
frame_vid_ref_inner = tk.Frame(ref_preview_canvas, bg=COLOR_PANEL)
frame_vid_ref_inner.bind("<Configure>", lambda e: ref_preview_canvas.configure(scrollregion=ref_preview_canvas.bbox("all")))
ref_preview_canvas.create_window((0, 0), window=frame_vid_ref_inner, anchor="nw")
ref_preview_canvas.configure(yscrollcommand=ref_preview_scroll.set)
ref_preview_canvas.pack(fill=tk.BOTH, expand=True, pady=5)
ref_preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)
tk.Label(frame_vid_ref_inner, text="无参考图\n(从下方列表多选历史图片)", bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, font=FONT_MAIN, width=30, height=8).pack()

tk.Label(frame_vid_right, text="选择历史图片:", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_INPUT).pack(anchor="w", pady=(10,2))

listbox_frame = tk.Frame(frame_vid_right, bg=COLOR_INPUT)
listbox_frame.pack(fill=tk.BOTH, expand=True, pady=2)
listbox_scroll = ttk.Scrollbar(listbox_frame, orient="vertical")
listbox_vid_ref = tk.Listbox(listbox_frame, height=5, selectmode=tk.MULTIPLE, font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT, selectbackground=COLOR_ACCENT, selectforeground="white", relief=tk.FLAT, bd=2, highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_ACCENT)
listbox_scroll.config(command=listbox_vid_ref.yview)
listbox_vid_ref.config(yscrollcommand=listbox_scroll.set)
listbox_vid_ref.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
listbox_scroll.pack(side=tk.RIGHT, fill=tk.Y)
listbox_vid_ref.bind("<<ListboxSelect>>", on_vid_ref_select)

frame_vid_ref_btns = tk.Frame(frame_vid_right, bg=COLOR_INPUT)
frame_vid_ref_btns.pack(fill=tk.X, pady=10)
btn_upload_ref = tk.Button(frame_vid_ref_btns, text="上传本地图片", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=upload_image_for_video)
btn_upload_ref.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2, ipady=2)
bind_hover(btn_upload_ref, COLOR_BORDER, "#D0D0D0")

btn_clear_ref = tk.Button(frame_vid_ref_btns, text="清除参考图", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=clear_video_ref_image)
btn_clear_ref.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2, ipady=2)
bind_hover(btn_clear_ref, COLOR_BORDER, "#D0D0D0")

# ==================== 底部状态栏 ====================
frame_footer = tk.Frame(main_container, bg=COLOR_PANEL, height=30, highlightbackground=COLOR_BORDER, highlightthickness=1)
frame_footer.pack(fill=tk.X, side=tk.BOTTOM)

label_gen_time = tk.Label(frame_footer, text="就绪", font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
label_gen_time.pack(side=tk.LEFT, padx=15, pady=5)

style.configure("Light.Horizontal.TProgressbar", troughcolor=COLOR_BG, background=COLOR_ACCENT, bordercolor=COLOR_BG, lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT)
progress_bar = ttk.Progressbar(frame_footer, style="Light.Horizontal.TProgressbar", mode='indeterminate', length=150)
progress_bar.pack(side=tk.RIGHT, padx=15, pady=8)

update_image_credits()
update_video_credits()

root.after(100, flush_ui_buffer)
root.mainloop()
