import os
import platform
import sys
from uuid import uuid4

# 处理可能的torch导入错误（faster-whisper依赖导致的）
# 在导入streamlit之前设置环境变量，避免文件监视器检查torch模块
os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

import warnings
# 忽略torch相关的警告（faster-whisper依赖torch，可能导致启动时的警告）
warnings.filterwarnings("ignore", message=".*torch.*")
warnings.filterwarnings("ignore", message=".*__path__.*")
warnings.filterwarnings("ignore", message=".*Tried to instantiate class.*")
warnings.filterwarnings("ignore", category=RuntimeWarning)

import streamlit as st
from loguru import logger

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    print("******** sys.path ********")
    print(sys.path)
    print("")

# 导入项目配置和模型
try:
    from app.config import config
except Exception as e:
    logger.warning(f"导入配置时出现警告: {e}")
    # 如果导入失败，尝试延迟导入
    import importlib
    import app.config
    config = importlib.reload(app.config).config
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import llm, voice
from app.services import task as tm
from app.utils import utils

st.set_page_config(
    page_title="MoneyPrinterTurbo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        "Report a bug": "https://github.com/harry0703/MoneyPrinterTurbo/issues",
        "About": "# MoneyPrinterTurbo\nSimply provide a topic or keyword for a video, and it will "
        "automatically generate the video copy, video materials, video subtitles, "
        "and video background music before synthesizing a high-definition short "
        "video.\n\nhttps://github.com/harry0703/MoneyPrinterTurbo",
    },
)


streamlit_style = """
<style>
h1 {
    padding-top: 0 !important;
}
</style>
"""
st.markdown(streamlit_style, unsafe_allow_html=True)

# 定义资源目录
font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")
config_file = os.path.join(root_dir, "webui", ".streamlit", "webui.toml")
system_locale = utils.get_system_locale()


if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = config.ui.get("language", system_locale)

# 加载语言文件
locales = utils.load_locales(i18n_dir)

# 创建一个顶部栏，包含标题和语言选择
title_col, lang_col = st.columns([3, 1])

with title_col:
    st.title(f"MoneyPrinterTurbo v{config.project_version}")

with lang_col:
    display_languages = []
    selected_index = 0
    for i, code in enumerate(locales.keys()):
        display_languages.append(f"{code} - {locales[code].get('Language')}")
        if code == st.session_state.get("ui_language", ""):
            selected_index = i

    selected_language = st.selectbox(
        "Language / 语言",
        options=display_languages,
        index=selected_index,
        key="top_language_selector",
        label_visibility="collapsed",
    )
    if selected_language:
        code = selected_language.split(" - ")[0].strip()
        st.session_state["ui_language"] = code
        config.ui["language"] = code

support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "fr-FR",
    "vi-VN",
    "th-TH",
]


def get_all_fonts():
    """获取所有字体文件，并添加语言标记"""
    # 定义中文字体和英文字体
    chinese_fonts = [
        "STHeitiMedium.ttc",
        "MicrosoftYaHeiBold.ttc",
        "STHeitiLight.ttc",
        "SimHei.ttf",
        "SimSun.ttf",
        "PingFang.ttc",
        "SourceHanSans",  # 思源黑体
        "NotoSans",  # Noto字体系列
        "MicrosoftYaHei",
        "SimSun",
        "KaiTi",
        "LXGWWenKai",  # 霞鹜文楷（毛笔手写风格）
        "Zhudou",      # 江西拙楷
        "STXingkai",   # 华文行楷
        "SmileySans",  # 得意黑
    ]
    
    fonts = []
    font_display_names = {}
    
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                # 判断是否为中文字体
                is_chinese = any(cn_font.lower() in file.lower() for cn_font in chinese_fonts)
                
                if is_chinese:
                    display_name = f"🇨🇳 {file}"
                else:
                    display_name = f"🇬🇧 {file}"
                
                fonts.append(file)
                font_display_names[file] = display_name
    
    fonts.sort(key=lambda x: (not any(cn in x.lower() for cn in chinese_fonts), x))  # 中文字体排在前面
    return fonts, font_display_names


def get_all_songs():
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        sys = platform.system()
        path = os.path.join(root_dir, "storage", "tasks", task_id)
        if os.path.exists(path):
            if sys == "Windows":
                os.system(f"start {path}")
            if sys == "Darwin":
                os.system(f"open {path}")
    except Exception as e:
        logger.error(e)


def scroll_to_bottom():
    js = """
    <script>
        console.log("scroll_to_bottom");
        function scroll(dummy_var_to_force_repeat_execution){
            var sections = parent.document.querySelectorAll('section.main');
            console.log(sections);
            for(let index = 0; index<sections.length; index++) {
                sections[index].scrollTop = sections[index].scrollHeight;
            }
        }
        scroll(1);
    </script>
    """
    st.components.v1.html(js, height=0, width=0)


def init_log():
    logger.remove()
    _lvl = "DEBUG"

    def format_record(record):
        # 获取日志记录中的文件全路径
        file_path = record["file"].path
        # 将绝对路径转换为相对于项目根目录的路径
        relative_path = os.path.relpath(file_path, root_dir)
        # 更新记录中的文件路径
        record["file"].path = f"./{relative_path}"
        # 返回修改后的格式字符串
        # 您可以根据需要调整这里的格式
        record["message"] = record["message"].replace(root_dir, ".")

        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
    )


init_log()

locales = utils.load_locales(i18n_dir)


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)


# 创建基础设置折叠框
if not config.app.get("hide_config", False):
    with st.expander(tr("Basic Settings"), expanded=False):
        config_panels = st.columns(3)
        left_config_panel = config_panels[0]
        middle_config_panel = config_panels[1]
        right_config_panel = config_panels[2]

        # 左侧面板 - 日志设置
        with left_config_panel:
            # 是否隐藏配置面板
            hide_config = st.checkbox(
                tr("Hide Basic Settings"), value=config.app.get("hide_config", False)
            )
            config.app["hide_config"] = hide_config

            # 是否禁用日志显示
            hide_log = st.checkbox(
                tr("Hide Log"), value=config.ui.get("hide_log", False)
            )
            config.ui["hide_log"] = hide_log

        # 中间面板 - LLM 设置

        with middle_config_panel:
            st.write(tr("LLM Settings"))
            llm_providers = [
                "OpenAI",
                "Moonshot",
                "Azure",
                "Qwen",
                "DeepSeek",
                "Gemini",
                "Ollama",
                "G4f",
                "OneAPI",
                "Cloudflare",
                "ERNIE",
                "Pollinations",
            ]
            saved_llm_provider = config.app.get("llm_provider", "OpenAI").lower()
            saved_llm_provider_index = 0
            for i, provider in enumerate(llm_providers):
                if provider.lower() == saved_llm_provider:
                    saved_llm_provider_index = i
                    break

            llm_provider = st.selectbox(
                tr("LLM Provider"),
                options=llm_providers,
                index=saved_llm_provider_index,
            )
            llm_helper = st.container()
            llm_provider = llm_provider.lower()
            config.app["llm_provider"] = llm_provider

            llm_api_key = config.app.get(f"{llm_provider}_api_key", "")
            llm_secret_key = config.app.get(
                f"{llm_provider}_secret_key", ""
            )  # only for baidu ernie
            llm_base_url = config.app.get(f"{llm_provider}_base_url", "")
            llm_model_name = config.app.get(f"{llm_provider}_model_name", "")
            llm_account_id = config.app.get(f"{llm_provider}_account_id", "")

            tips = ""
            if llm_provider == "ollama":
                if not llm_model_name:
                    llm_model_name = "qwen:7b"
                if not llm_base_url:
                    llm_base_url = "http://localhost:11434/v1"

                with llm_helper:
                    tips = """
                            ##### Ollama配置说明
                            - **API Key**: 随便填写，比如 123
                            - **Base Url**: 一般为 http://localhost:11434/v1
                                - 如果 `MoneyPrinterTurbo` 和 `Ollama` **不在同一台机器上**，需要填写 `Ollama` 机器的IP地址
                                - 如果 `MoneyPrinterTurbo` 是 `Docker` 部署，建议填写 `http://host.docker.internal:11434/v1`
                            - **Model Name**: 使用 `ollama list` 查看，比如 `qwen:7b`
                            """

            if llm_provider == "openai":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### OpenAI 配置说明
                            > 需要VPN开启全局流量模式
                            - **API Key**: [点击到官网申请](https://platform.openai.com/api-keys)
                            - **Base Url**: 可以留空
                            - **Model Name**: 填写**有权限**的模型，[点击查看模型列表](https://platform.openai.com/settings/organization/limits)
                            """

            if llm_provider == "moonshot":
                if not llm_model_name:
                    llm_model_name = "moonshot-v1-8k"
                with llm_helper:
                    tips = """
                            ##### Moonshot 配置说明
                            - **API Key**: [点击到官网申请](https://platform.moonshot.cn/console/api-keys)
                            - **Base Url**: 固定为 https://api.moonshot.cn/v1
                            - **Model Name**: 比如 moonshot-v1-8k，[点击查看模型列表](https://platform.moonshot.cn/docs/intro#%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8)
                            """
            if llm_provider == "oneapi":
                if not llm_model_name:
                    llm_model_name = (
                        "claude-3-5-sonnet-20240620"  # 默认模型，可以根据需要调整
                    )
                with llm_helper:
                    tips = """
                        ##### OneAPI 配置说明
                        - **API Key**: 填写您的 OneAPI 密钥
                        - **Base Url**: 填写 OneAPI 的基础 URL
                        - **Model Name**: 填写您要使用的模型名称，例如 claude-3-5-sonnet-20240620
                        """

            if llm_provider == "qwen":
                if not llm_model_name:
                    llm_model_name = "qwen-max"
                with llm_helper:
                    tips = """
                            ##### 通义千问Qwen 配置说明
                            - **API Key**: [点击到官网申请](https://dashscope.console.aliyun.com/apiKey)
                            - **Base Url**: 留空
                            - **Model Name**: 比如 qwen-max，[点击查看模型列表](https://help.aliyun.com/zh/dashscope/developer-reference/model-introduction#3ef6d0bcf91wy)
                            """

            if llm_provider == "g4f":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                            ##### gpt4free 配置说明
                            > [GitHub开源项目](https://github.com/xtekky/gpt4free)，可以免费使用GPT模型，但是**稳定性较差**
                            - **API Key**: 随便填写，比如 123
                            - **Base Url**: 留空
                            - **Model Name**: 比如 gpt-3.5-turbo，[点击查看模型列表](https://github.com/xtekky/gpt4free/blob/main/g4f/models.py#L308)
                            """
            if llm_provider == "azure":
                with llm_helper:
                    tips = """
                            ##### Azure 配置说明
                            > [点击查看如何部署模型](https://learn.microsoft.com/zh-cn/azure/ai-services/openai/how-to/create-resource)
                            - **API Key**: [点击到Azure后台创建](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI)
                            - **Base Url**: 留空
                            - **Model Name**: 填写你实际的部署名
                            """

            if llm_provider == "gemini":
                if not llm_model_name:
                    llm_model_name = "gemini-1.0-pro"

                with llm_helper:
                    tips = """
                            ##### Gemini 配置说明
                            > 需要VPN开启全局流量模式
                            - **API Key**: [点击到官网申请](https://ai.google.dev/)
                            - **Base Url**: 留空
                            - **Model Name**: 比如 gemini-1.0-pro
                            """

            if llm_provider == "deepseek":
                if not llm_model_name:
                    llm_model_name = "deepseek-chat"
                if not llm_base_url:
                    llm_base_url = "https://api.deepseek.com"
                with llm_helper:
                    tips = """
                            ##### DeepSeek 配置说明
                            - **API Key**: [点击到官网申请](https://platform.deepseek.com/api_keys)
                            - **Base Url**: 固定为 https://api.deepseek.com
                            - **Model Name**: 固定为 deepseek-chat
                            """

            if llm_provider == "ernie":
                with llm_helper:
                    tips = """
                            ##### 百度文心一言 配置说明
                            - **API Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Secret Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                            - **Base Url**: 填写 **请求地址** [点击查看文档](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/jlil56u11#%E8%AF%B7%E6%B1%82%E8%AF%B4%E6%98%8E)
                            """

            if llm_provider == "pollinations":
                if not llm_model_name:
                    llm_model_name = "default"
                with llm_helper:
                    tips = """
                            ##### Pollinations AI Configuration
                            - **API Key**: Optional - Leave empty for public access
                            - **Base Url**: Default is https://text.pollinations.ai/openai
                            - **Model Name**: Use 'openai-fast' or specify a model name
                            """

            if tips and config.ui["language"] == "zh":
                st.warning(
                    "中国用户建议使用 **DeepSeek** 或 **Moonshot** 作为大模型提供商\n- 国内可直接访问，不需要VPN \n- 注册就送额度，基本够用"
                )
                st.info(tips)

            st_llm_api_key = st.text_input(
                tr("API Key"), value=llm_api_key, type="password"
            )
            st_llm_base_url = st.text_input(tr("Base Url"), value=llm_base_url)
            st_llm_model_name = ""
            if llm_provider != "ernie":
                st_llm_model_name = st.text_input(
                    tr("Model Name"),
                    value=llm_model_name,
                    key=f"{llm_provider}_model_name_input",
                )
                if st_llm_model_name:
                    config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            else:
                st_llm_model_name = None

            if st_llm_api_key:
                config.app[f"{llm_provider}_api_key"] = st_llm_api_key
            if st_llm_base_url:
                config.app[f"{llm_provider}_base_url"] = st_llm_base_url
            if st_llm_model_name:
                config.app[f"{llm_provider}_model_name"] = st_llm_model_name
            if llm_provider == "ernie":
                st_llm_secret_key = st.text_input(
                    tr("Secret Key"), value=llm_secret_key, type="password"
                )
                config.app[f"{llm_provider}_secret_key"] = st_llm_secret_key

            if llm_provider == "cloudflare":
                st_llm_account_id = st.text_input(
                    tr("Account ID"), value=llm_account_id
                )
                if st_llm_account_id:
                    config.app[f"{llm_provider}_account_id"] = st_llm_account_id

        # 右侧面板 - API 密钥设置
        with right_config_panel:

            def get_keys_from_config(cfg_key):
                api_keys = config.app.get(cfg_key, [])
                if isinstance(api_keys, str):
                    api_keys = [api_keys]
                api_key = ", ".join(api_keys)
                return api_key

            def save_keys_to_config(cfg_key, value):
                value = value.replace(" ", "")
                if value:
                    config.app[cfg_key] = value.split(",")

            st.write(tr("Video Source Settings"))

            pexels_api_key = get_keys_from_config("pexels_api_keys")
            pexels_api_key = st.text_input(
                tr("Pexels API Key"), value=pexels_api_key, type="password"
            )
            save_keys_to_config("pexels_api_keys", pexels_api_key)

            pixabay_api_key = get_keys_from_config("pixabay_api_keys")
            pixabay_api_key = st.text_input(
                tr("Pixabay API Key"), value=pixabay_api_key, type="password"
            )
            save_keys_to_config("pixabay_api_keys", pixabay_api_key)

llm_provider = config.app.get("llm_provider", "").lower()
panel = st.columns(3)
left_panel = panel[0]
middle_panel = panel[1]
right_panel = panel[2]

params = VideoParams(video_subject="")
uploaded_files = []

with left_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        params.video_subject = st.text_input(
            tr("Video Subject"),
            value=st.session_state["video_subject"],
            key="video_subject_input",
        ).strip()

        # 添加视频时长选择
        video_durations = [
            ("5秒", 5),
            ("10秒", 10),
            ("30秒", 30),
            ("1分钟", 60),
            ("3分钟", 180),
            ("5分钟", 300),
            ("10分钟", 600),
            ("20分钟", 1200),
            ("30分钟", 1800),
        ]
        
        # 获取保存的时长设置，默认为1分钟
        saved_duration = config.ui.get("video_duration", 60)
        saved_duration_index = 0
        for i, (_, duration) in enumerate(video_durations):
            if duration == saved_duration:
                saved_duration_index = i
                break
        
        selected_duration_index = st.selectbox(
            tr("Video Duration"),
            options=range(len(video_durations)),
            format_func=lambda x: video_durations[x][0],
            index=saved_duration_index,
        )
        selected_video_duration = video_durations[selected_duration_index][1]
        config.ui["video_duration"] = selected_video_duration

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        for code in support_locales:
            video_languages.append((code, code))

        selected_index = st.selectbox(
            tr("Script Language"),
            index=0,
            options=range(
                len(video_languages)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_languages[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_language = video_languages[selected_index][1]

        if st.button(
            tr("Generate Video Script and Keywords"), key="auto_generate_script"
        ):
            with st.spinner(tr("Generating Video Script and Keywords")):
                script = llm.generate_script(
                    video_subject=params.video_subject, 
                    language=params.video_language,
                    video_duration=selected_video_duration
                )
                terms = llm.generate_terms(params.video_subject, script)
                if "Error: " in script:
                    st.error(tr(script))
                elif "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_script"] = script
                    st.session_state["video_terms"] = ", ".join(terms)
        params.video_script = st.text_area(
            tr("Video Script"), value=st.session_state["video_script"], height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                if "Error: " in terms:
                    st.error(tr(terms))
                else:
                    st.session_state["video_terms"] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"), value=st.session_state["video_terms"]
        )

with middle_panel:
    with st.container(border=True):
        st.write(tr("Video Settings"))
        
        # 先选择视频比例，因为背景选择需要根据比例来决定
        video_aspect_ratios = [
            (tr("Portrait") + " (1080x1920)", VideoAspect.portrait.value),
            (tr("Portrait") + " 720p (720x1280)", VideoAspect.portrait_720p.value),
            (tr("Landscape") + " (1920x1080)", VideoAspect.landscape.value),
            (tr("Landscape") + " 720p (1280x720)", VideoAspect.landscape_720p.value),
        ]
        
        # 从配置中获取上次保存的比例
        saved_aspect = config.ui.get("video_aspect", VideoAspect.portrait.value)
        saved_aspect_index = 0
        for i, (_, aspect_val) in enumerate(video_aspect_ratios):
            if aspect_val == saved_aspect:
                saved_aspect_index = i
                break
        
        selected_aspect_index = st.selectbox(
            tr("Video Ratio"),
            options=range(len(video_aspect_ratios)),
            format_func=lambda x: video_aspect_ratios[x][0],
            index=saved_aspect_index,
        )
        params.video_aspect = VideoAspect(video_aspect_ratios[selected_aspect_index][1])
        # 保存到配置，以便背景选择可以使用
        config.ui["video_aspect"] = params.video_aspect.value
        
        # 现在 params.video_aspect 已经赋值，可以用于背景选择
        # 正确判断：检查是否包含 "9:16"（竖屏）
        is_portrait = "9:16" in str(params.video_aspect.value)
        
        video_concat_modes = [
            (tr("Sequential"), "sequential"),
            (tr("Random"), "random"),
        ]
        video_sources = [
            (tr("Pexels"), "pexels"),
            (tr("Pixabay"), "pixabay"),
            (tr("Local file"), "local"),
            (tr("TikTok"), "douyin"),
            (tr("Bilibili"), "bilibili"),
            (tr("Xiaohongshu"), "xiaohongshu"),
        ]

        saved_video_source_name = config.app.get("video_source", "pexels")
        saved_video_source_index = [v[1] for v in video_sources].index(
            saved_video_source_name
        )

        selected_index = st.selectbox(
            tr("Video Source"),
            options=range(len(video_sources)),
            format_func=lambda x: video_sources[x][0],
            index=saved_video_source_index,
        )
        params.video_source = video_sources[selected_index][1]
        config.app["video_source"] = params.video_source

        if params.video_source == "local":
            # 判断是否是古书卷轴主题（使用保存的配置）
            saved_theme = config.ui.get("video_theme", "modern_book")
            is_ancient_scroll = saved_theme == "ancient_scroll"
            
            if is_ancient_scroll:
                # 古书卷轴主题：提供默认背景选择
                from app.config.background_themes import get_background_names, get_background_path
                
                st.write("**" + tr("Background Source") + " 🖼️**")
                
                # 直接使用当前的 is_portrait（已经在前面根据 params.video_aspect 计算好了）
                # 添加调试信息确认比例
                st.info(f"🔍 当前视频比例: {params.video_aspect.value} | is_portrait={is_portrait}")
                
                # 背景来源选择
                bg_source_options = [(tr("Default Backgrounds"), "default"), (tr("Upload Custom"), "upload")]
                
                # 从 session_state 或配置中获取保存的选择
                saved_bg_source = st.session_state.get("bg_source", "default")
                saved_bg_source_index = 0 if saved_bg_source == "default" else 1
                
                bg_source_index = st.radio(
                    tr("Select Background Source"),
                    options=range(len(bg_source_options)),
                    format_func=lambda x: bg_source_options[x][0],
                    index=saved_bg_source_index,
                    horizontal=True,
                    key="bg_source_radio"
                )
                bg_source = bg_source_options[bg_source_index][1]
                st.session_state["bg_source"] = bg_source
                
                if bg_source == "default":
                    # 显示默认背景选择器
                    
                    # 检测视频比例是否变化，如果变化则重置背景选择
                    aspect_key = "portrait" if is_portrait else "landscape"
                    last_aspect_key = st.session_state.get("last_bg_aspect", aspect_key)
                    
                    if last_aspect_key != aspect_key:
                        # 视频比例变化，重置为默认背景
                        st.session_state["selected_bg_key"] = "ancient_paper_1"
                        st.session_state["last_bg_aspect"] = aspect_key
                        st.info(f"🔄 视频比例切换为{'📱 竖屏' if is_portrait else '📺 横屏'}，已重置为默认背景")
                    
                    # 获取当前比例的背景列表（必须在比例确定后获取）
                    bg_names = get_background_names(is_portrait=is_portrait)
                    
                    st.write(f"**{tr('Default Backgrounds')}** ({'📱 竖屏 9:16' if is_portrait else '📺 横屏 16:9'})")
                    
                    # 从 session_state 获取保存的选择
                    saved_bg_key = st.session_state.get("selected_bg_key", "ancient_paper_1")
                    saved_bg_index = 0
                    for i, (key, _, _) in enumerate(bg_names):
                        if key == saved_bg_key:
                            saved_bg_index = i
                            break
                    
                    # 使用动态 key 以便视频比例切换时重新渲染
                    selected_bg_index = st.selectbox(
                        tr("Select Background"),
                        options=range(len(bg_names)),
                        format_func=lambda x: f"{bg_names[x][1]} - {bg_names[x][2]}",
                        index=saved_bg_index,
                        key=f"default_background_select_{aspect_key}"  # 动态 key
                    )
                    
                    selected_bg_key = bg_names[selected_bg_index][0]
                    st.session_state["selected_bg_key"] = selected_bg_key
                    
                    # 重要：使用当前比例获取背景路径
                    bg_path = get_background_path(selected_bg_key, is_portrait=is_portrait)
                    
                    if bg_path:
                        # 显示紧凑的背景预览（缩小尺寸）
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            st.image(bg_path, caption=bg_names[selected_bg_index][1], width=200)
                        with col2:
                            st.caption(f"📐 比例: {'竖屏 1080x1920' if is_portrait else '横屏 1920x1080'}")
                            st.caption(f"🎨 主题: {bg_names[selected_bg_index][1]}")
                            st.caption(f"📝 说明: {bg_names[selected_bg_index][2]}")
                        
                        # 将背景添加到素材列表
                        from app.models.schema import MaterialInfo
                        m = MaterialInfo()
                        m.provider = "local"
                        m.url = bg_path
                        if not params.video_materials:
                            params.video_materials = []
                        params.video_materials = [m]  # 只使用一个背景
                    else:
                        st.warning(tr("Background file not found, please check resource directory"))
                else:
                    # 上传自定义背景
                    uploaded_files = st.file_uploader(
                        tr("Upload Custom Background"),
                        type=["jpg", "jpeg", "png"],
                        accept_multiple_files=False,
                        help=tr("Upload a custom background image (横屏: 1920x1080, 竖屏: 1080x1920)")
                    )
            else:
                # 非古书卷轴主题：普通文件上传
                uploaded_files = st.file_uploader(
                    "Upload Local Files",
                    type=["mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png"],
                    accept_multiple_files=True,
                )

        selected_index = st.selectbox(
            tr("Video Concat Mode"),
            index=1,
            options=range(
                len(video_concat_modes)
            ),  # Use the index as the internal option value
            format_func=lambda x: video_concat_modes[x][
                0
            ],  # The label is displayed to the user
        )
        params.video_concat_mode = VideoConcatMode(
            video_concat_modes[selected_index][1]
        )

        # 视频转场模式
        video_transition_modes = [
            (tr("None"), VideoTransitionMode.none.value),
            (tr("Shuffle"), VideoTransitionMode.shuffle.value),
            (tr("FadeIn"), VideoTransitionMode.fade_in.value),
            (tr("FadeOut"), VideoTransitionMode.fade_out.value),
            (tr("SlideIn"), VideoTransitionMode.slide_in.value),
            (tr("SlideOut"), VideoTransitionMode.slide_out.value),
        ]
        selected_index = st.selectbox(
            tr("Video Transition Mode"),
            options=range(len(video_transition_modes)),
            format_func=lambda x: video_transition_modes[x][0],
            index=0,
        )
        params.video_transition_mode = VideoTransitionMode(
            video_transition_modes[selected_index][1]
        )

        # 视频比例已经在前面选择过了，不需要重复

        params.video_clip_duration = st.selectbox(
            tr("Clip Duration"), options=[2, 3, 4, 5, 6, 7, 8, 9, 10], index=1
        )
        params.video_count = st.selectbox(
            tr("Number of Videos Generated Simultaneously"),
            options=[1, 2, 3, 4, 5],
            index=0,
        )
        
        # 缩放动画开关
        params.enable_video_animation = st.checkbox(
            tr("Enable Video Animation"),
            value=False,
            help=tr("Enable zoom animation effect (slower but more dynamic)"),
        )
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # 添加TTS服务器选择下拉框
        tts_servers = [
            ("azure-tts-v1", "Azure TTS V1 (免费)"),
            ("azure-tts-v2", "Azure TTS V2"),
            ("siliconflow", "SiliconFlow TTS"),
            ("gtts", "Google TTS (完全免费)"),
            ("pyttsx3", "Pyttsx3 (本地离线免费)"),
        ]

        # 获取保存的TTS服务器，默认为v1
        saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")
        saved_tts_server_index = 0
        for i, (server_value, _) in enumerate(tts_servers):
            if server_value == saved_tts_server:
                saved_tts_server_index = i
                break

        selected_tts_server_index = st.selectbox(
            tr("TTS Servers"),
            options=range(len(tts_servers)),
            format_func=lambda x: tts_servers[x][1],
            index=saved_tts_server_index,
        )

        selected_tts_server = tts_servers[selected_tts_server_index][0]
        config.ui["tts_server"] = selected_tts_server

        # 根据选择的TTS服务器获取声音列表
        filtered_voices = []

        if selected_tts_server == "siliconflow":
            # 获取硅基流动的声音列表
            filtered_voices = voice.get_siliconflow_voices()
        elif selected_tts_server == "gtts":
            # 获取gTTS的声音列表
            filtered_voices = voice.get_gtts_voices()
        elif selected_tts_server == "pyttsx3":
            # 获取pyttsx3的声音列表
            filtered_voices = voice.get_pyttsx3_voices()
        else:
            # 获取Azure的声音列表
            # 默认只显示中文语音（zh-CN），根据界面语言自动切换
            ui_language = st.session_state.get("ui_language", "zh")
            
            # 根据界面语言设置默认过滤语言
            if ui_language == "zh":
                default_filter = ["zh-CN"]  # 默认显示中文语音
            elif ui_language == "en":
                default_filter = ["en-US", "en-GB"]  # 英文显示美英语音
            else:
                default_filter = None  # 其他语言显示全部
            
            all_voices = voice.get_all_azure_voices(filter_locals=default_filter)

            # 根据选择的TTS服务器筛选声音
            for v in all_voices:
                if selected_tts_server == "azure-tts-v2":
                    # V2版本的声音名称中包含"v2"
                    if "V2" in v:
                        filtered_voices.append(v)
                else:
                    # V1版本的声音名称中不包含"v2"
                    if "V2" not in v:
                        filtered_voices.append(v)

        friendly_names = {
            v: v.replace("Female", tr("Female"))
            .replace("Male", tr("Male"))
            .replace("Neural", "")
            for v in filtered_voices
        }

        saved_voice_name = config.ui.get("voice_name", "")
        saved_voice_name_index = 0

        # 检查保存的声音是否在当前筛选的声音列表中
        if saved_voice_name in friendly_names:
            saved_voice_name_index = list(friendly_names.keys()).index(saved_voice_name)
        else:
            # 如果不在，则根据当前UI语言选择一个默认声音
            for i, v in enumerate(filtered_voices):
                if v.lower().startswith(st.session_state["ui_language"].lower()):
                    saved_voice_name_index = i
                    break

        # 如果没有找到匹配的声音，使用第一个声音
        if saved_voice_name_index >= len(friendly_names) and friendly_names:
            saved_voice_name_index = 0

        # 确保有声音可选
        if friendly_names:
            selected_friendly_name = st.selectbox(
                tr("Speech Synthesis"),
                options=list(friendly_names.values()),
                index=min(saved_voice_name_index, len(friendly_names) - 1)
                if friendly_names
                else 0,
            )

            voice_name = list(friendly_names.keys())[
                list(friendly_names.values()).index(selected_friendly_name)
            ]
            params.voice_name = voice_name
            config.ui["voice_name"] = voice_name
        else:
            # 如果没有声音可选，显示提示信息
            st.warning(
                tr(
                    "No voices available for the selected TTS server. Please select another server."
                )
            )
            params.voice_name = ""
            config.ui["voice_name"] = ""

        # 只有在有声音可选时才显示试听按钮
        if friendly_names and st.button(tr("Play Voice")):
            play_content = params.video_subject
            if not play_content:
                play_content = params.video_script
            if not play_content:
                play_content = tr("Voice Example")
            with st.spinner(tr("Synthesizing Voice")):
                temp_dir = utils.storage_dir("temp", create=True)
                audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")
                sub_maker = voice.tts(
                    text=play_content,
                    voice_name=voice_name,
                    voice_rate=params.voice_rate,
                    voice_file=audio_file,
                    voice_volume=params.voice_volume,
                )
                # if the voice file generation failed, try again with a default content.
                if not sub_maker:
                    play_content = "This is a example voice. if you hear this, the voice synthesis failed with the original content."
                    sub_maker = voice.tts(
                        text=play_content,
                        voice_name=voice_name,
                        voice_rate=params.voice_rate,
                        voice_file=audio_file,
                        voice_volume=params.voice_volume,
                    )

                if sub_maker and os.path.exists(audio_file):
                    st.audio(audio_file, format="audio/mp3")
                    if os.path.exists(audio_file):
                        os.remove(audio_file)

        # 当选择V2版本或者声音是V2声音时，显示服务区域和API key输入框
        if selected_tts_server == "azure-tts-v2" or (
            voice_name and voice.is_azure_v2_voice(voice_name)
        ):
            saved_azure_speech_region = config.azure.get("speech_region", "")
            saved_azure_speech_key = config.azure.get("speech_key", "")
            azure_speech_region = st.text_input(
                tr("Speech Region"),
                value=saved_azure_speech_region,
                key="azure_speech_region_input",
            )
            azure_speech_key = st.text_input(
                tr("Speech Key"),
                value=saved_azure_speech_key,
                type="password",
                key="azure_speech_key_input",
            )
            config.azure["speech_region"] = azure_speech_region
            config.azure["speech_key"] = azure_speech_key

        # 当选择硅基流动时，显示API key输入框和说明信息
        if selected_tts_server == "siliconflow" or (
            voice_name and voice.is_siliconflow_voice(voice_name)
        ):
            saved_siliconflow_api_key = config.siliconflow.get("api_key", "")

            siliconflow_api_key = st.text_input(
                tr("SiliconFlow API Key"),
                value=saved_siliconflow_api_key,
                type="password",
                key="siliconflow_api_key_input",
            )

            # 显示硅基流动的说明信息
            st.info(
                tr("SiliconFlow TTS Settings")
                + ":\n"
                + "- "
                + tr("Speed: Range [0.25, 4.0], default is 1.0")
                + "\n"
                + "- "
                + tr("Volume: Uses Speech Volume setting, default 1.0 maps to gain 0")
            )

            config.siliconflow["api_key"] = siliconflow_api_key

        # 当选择gTTS时，显示说明信息
        if selected_tts_server == "gtts":
            st.success(
                "🎉 **Google TTS (完全免费)**\n\n"
                + "✅ 无需API Key，完全免费使用\n"
                + "✅ 支持19种语言\n"
                + "✅ 声音自然流畅\n"
                + "⚠️ 需要网络连接\n"
                + "💡 如需调整语速，需安装 pydub 和 ffmpeg"
            )

        # 当选择pyttsx3时，显示说明信息
        if selected_tts_server == "pyttsx3":
            st.success(
                "💻 **Pyttsx3 (本地离线免费)**\n\n"
                + "✅ 完全离线，不需要网络连接\n"
                + "✅ 无需API Key，完全免费\n"
                + "✅ 使用系统内置声音\n"
                + "⚠️ 声音质量取决于系统\n"
                + "💡 Windows系统自带中文语音，macOS可Siri声音"
            )

        params.voice_volume = st.selectbox(
            tr("Speech Volume"),
            options=[0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0],
            index=2,
        )

        params.voice_rate = st.selectbox(
            tr("Speech Rate"),
            options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
            index=2,
        )

        bgm_options = [
            (tr("No Background Music"), ""),
            (tr("Random Background Music"), "random"),
            (tr("White Noise"), "white_noise"),
            (tr("Custom Background Music"), "custom"),
        ]
        selected_index = st.selectbox(
            tr("Background Music"),
            index=1,
            options=range(
                len(bgm_options)
            ),  # Use the index as the internal option value
            format_func=lambda x: bgm_options[x][
                0
            ],  # The label is displayed to the user
        )
        # Get the selected background music type
        params.bgm_type = bgm_options[selected_index][1]

        # Show or hide components based on the selection
        if params.bgm_type == "custom":
            custom_bgm_file = st.text_input(
                tr("Custom Background Music File"), key="custom_bgm_file_input"
            )
            if custom_bgm_file and os.path.exists(custom_bgm_file):
                params.bgm_file = custom_bgm_file
                # st.write(f":red[已选择自定义背景音乐]：**{custom_bgm_file}**")
        params.bgm_volume = st.selectbox(
            tr("Background Music Volume"),
            options=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            index=2,
        )

with right_panel:
    with st.container(border=True):
        st.write(tr("Subtitle Settings"))
        params.subtitle_enabled = st.checkbox(
            tr("Enable Subtitles"), 
            value=True,
            help="启用后将显示字幕，并应用下方的所有设置（主题、布局、字体、颜色、描边等）"
        )
        
        if not params.subtitle_enabled:
            st.warning("⚠️ 已禁用字幕，下方的所有字幕设置将不生效")
        
        # 视频主题选择
        video_themes = [
            (tr("Modern Book"), "modern_book"),       # 现代图书：标题在顶部，字幕横排底部
            (tr("Cinema"), "cinema"),                 # 电影模式：标题开头全屏3秒，字幕底部
            (tr("Ancient Scroll"), "ancient_scroll"), # 古书卷轴：标题右上角，字幕竖排高亮
            (tr("Minimal"), "minimal"),               # 简约模式：标题居中靠上，字幕底部
        ]
        saved_theme_index = 0  # 默认选择现代图书模式
        saved_theme = config.ui.get("video_theme", "modern_book")
        for i, (_, theme_value) in enumerate(video_themes):
            if theme_value == saved_theme:
                saved_theme_index = i
                break
        
        selected_theme_index = st.selectbox(
            tr("Video Theme"),
            options=range(len(video_themes)),
            index=saved_theme_index,
            format_func=lambda x: video_themes[x][0],
            help=tr("Choose theme style for title and subtitle display")
        )
        params.video_theme = video_themes[selected_theme_index][1]
        config.ui["video_theme"] = params.video_theme
        
        # 主题默认颜色配置
        theme_color_defaults = {
            "modern_book": {
                "text_fore_color": "#000000",  # 黑色字体（书页效果）
                "stroke_color": "#FFFFFF",     # 白色描边
            },
            "ancient_scroll": {
                "text_fore_color": "#FFD700",  # 金色字体（古卷效果）
                "stroke_color": "#8B4513",     # 棕色描边
            },
            "cinema": {
                "text_fore_color": "#FFFFFF",  # 白色字体（电影效果）
                "stroke_color": "#000000",     # 黑色描边
            },
            "minimal": {
                "text_fore_color": "#FFFFFF",  # 白色字体（简洁效果）
                "stroke_color": "#000000",     # 黑色描边
            },
        }
        
        # 初始化主题颜色状态（用于检测主题切换）
        if "current_theme" not in st.session_state:
            st.session_state.current_theme = params.video_theme
        
        # 检测主题是否切换
        theme_changed = st.session_state.current_theme != params.video_theme
        if theme_changed:
            st.session_state.current_theme = params.video_theme
            # 主题切换时，使用新主题的默认颜色
            theme_defaults = theme_color_defaults.get(params.video_theme, theme_color_defaults["minimal"])
            st.session_state.text_fore_color = theme_defaults["text_fore_color"]
            st.session_state.stroke_color = theme_defaults["stroke_color"]
            # 更新配置
            config.ui["text_fore_color"] = st.session_state.text_fore_color
            config.ui["stroke_color"] = st.session_state.stroke_color
            # 显示提示
            st.info(f"🎨 主题切换：字体颜色和描边颜色已更新为 {params.video_theme} 主题默认值")
        
        # 根据主题显示说明
        theme_descriptions = {
            "modern_book": tr("Modern Book: Title at top (book cover), horizontal subtitles at bottom (book pages)"),
            "cinema": tr("Cinema: Title fullscreen for 3s at start, subtitles at bottom"),
            "ancient_scroll": tr("Ancient Scroll: Vertical title at top-right, vertical subtitles with highlight effect"),
            "minimal": tr("Minimal: Title centered at top, subtitles at bottom"),
        }
        st.caption(theme_descriptions.get(params.video_theme, ""))
        
        # 古书卷轴主题：显示颜色主题选择
        if params.video_theme == "ancient_scroll":
            from app.config.subtitle_themes import get_all_theme_names, SUBTITLE_COLOR_THEMES
            
            st.write("**" + tr("Color Theme") + " 🎨**")
            
            # 获取所有主题
            all_themes = get_all_theme_names()
            theme_options = [name for key, name in all_themes]
            theme_keys = [key for key, name in all_themes]
            
            # 从配置中获取已保存的主题
            saved_color_theme = config.ui.get("subtitle_color_theme", "classic_gold")
            saved_theme_index = 0
            for i, key in enumerate(theme_keys):
                if key == saved_color_theme:
                    saved_theme_index = i
                    break
            
            selected_color_theme_index = st.selectbox(
                tr("Subtitle Color Theme"),
                options=range(len(theme_options)),
                index=saved_theme_index,
                format_func=lambda x: f"{theme_options[x]} - {SUBTITLE_COLOR_THEMES[theme_keys[x]]['description']}",
                help=tr("Choose color scheme for subtitle states: unread, reading, and read"),
                key="subtitle_color_theme_select"
            )
            
            params.subtitle_color_theme = theme_keys[selected_color_theme_index]
            config.ui["subtitle_color_theme"] = params.subtitle_color_theme
            
            # 显示颜色预览
            theme_config = SUBTITLE_COLOR_THEMES[params.subtitle_color_theme]
            st.markdown(f"""
            <div style="padding: 10px; border-radius: 5px; background: #f0f0f0;">
                <b>颜色预览:</b><br/>
                <span style="color: {theme_config['unread']['color']}; text-shadow: 1px 1px {theme_config['unread']['stroke']}; font-size: 16px;">■</span> 未读 ({theme_config['unread']['color']})<br/>
                <span style="color: {theme_config['reading']['color']}; text-shadow: 1px 1px {theme_config['reading']['stroke']}; font-size: 20px; font-weight: bold;">■</span> 正在读 ({theme_config['reading']['color']}, 放大)<br/>
                <span style="color: {theme_config['read']['color']}; text-shadow: 1px 1px {theme_config['read']['stroke']}; font-size: 16px;">■</span> 已读 ({theme_config['read']['color']})<br/>
                <span style="color: {theme_config['title']['color']}; text-shadow: 1px 1px {theme_config['title']['stroke']}; font-size: 18px; font-weight: bold;">■</span> 标题 ({theme_config['title']['color']})
            </div>
            """, unsafe_allow_html=True)
        else:
            # 其他主题使用默认颜色配置
            params.subtitle_color_theme = "classic_gold"
        
        # 🎨 主题布局预览
        st.write("**" + tr("Layout Preview") + "**")
        
        # 根据视频比例确定预览容器尺寸
        aspect = params.video_aspect
        if aspect == "9:16":  # 竖屏
            preview_width = 270
            preview_height = 480
        else:  # 16:9 横屏
            preview_width = 480
            preview_height = 270
        
        # 获取或初始化布局参数
        if "title_y_offset" not in st.session_state:
            st.session_state.title_y_offset = 0
        if "subtitle_y_offset" not in st.session_state:
            st.session_state.subtitle_y_offset = 0
        if "title_x_offset" not in st.session_state:
            st.session_state.title_x_offset = 0
        if "subtitle_x_offset" not in st.session_state:
            st.session_state.subtitle_x_offset = 0
        
        # 初始化边界参数（根据视频比例自适应）
        # 检测视频比例变化，重置字幕边界
        if "last_video_aspect" not in st.session_state:
            st.session_state.last_video_aspect = aspect
        
        aspect_changed = st.session_state.last_video_aspect != aspect
        if aspect_changed:
            st.session_state.last_video_aspect = aspect
            # 比例变化时，重置字幕边界为新比例的默认值
            if aspect == "9:16":  # 竖屏
                st.session_state.subtitle_left = 10
                st.session_state.subtitle_right = 70  # 竖屏70%
            else:  # 横屏
                st.session_state.subtitle_left = 18
                st.session_state.subtitle_right = 80  # 横屏80%
            # 重置标题位置
            st.session_state.title_left = 85
        
        if "title_top" not in st.session_state:
            st.session_state.title_top = 12  # 标题默认上边界（将基于此计算垂直居中）
        if "title_left" not in st.session_state:
            st.session_state.title_left = 85  # 标题默认左边界（85%）
        if "subtitle_top" not in st.session_state:
            st.session_state.subtitle_top = 12  # 字幕默认上边界
        if "subtitle_bottom" not in st.session_state:
            st.session_state.subtitle_bottom = 88  # 字幕默认下边界（88%，即距顶部88%）
        if "subtitle_left" not in st.session_state:
            # 根据视频比例设置默认值
            if aspect == "9:16":  # 竖屏
                st.session_state.subtitle_left = 10  # 字幕默认左边界（竖屏）
            else:  # 横屏
                st.session_state.subtitle_left = 18  # 字幕默认左边界（横屏）
        if "subtitle_right" not in st.session_state:
            # 根据视频比例设置默认值
            if aspect == "9:16":  # 竖屏
                st.session_state.subtitle_right = 70  # 字幕默认右边界（竖屏）70%）
            else:  # 横屏
                st.session_state.subtitle_right = 80  # 字幕默认右边界（横屏，80%）
        
        # 根据不同主题显示不同的布局调节选项
        if params.video_theme == "ancient_scroll":
            # 古书卷轴：支持水平和垂直位置调整
            # 根据视频比例显示不同的提示
            if aspect == "9:16":  # 竖屏
                layout_hint = tr("Ancient Scroll Layout: Title at 85% horizontal (centered vertically), Subtitle columns 10%-70% (Portrait)")
            else:  # 横屏
                layout_hint = tr("Ancient Scroll Layout: Title at 85% horizontal (centered vertically), Subtitle columns 18%-80%")
            st.caption("🎋 " + layout_hint)
            
            # 显示调节模式选择
            layout_mode = st.radio(
                "布局调节模式",
                ["偏移量模式", "精确边界模式"],
                horizontal=True,
                help="偏移量模式：在基础位置上微调。精确边界模式：直接设置精确边界位置"
            )
            
            if layout_mode == "偏移量模式":
                # 原有的偏移量模式
                # 水平位置调节
                col1, col2 = st.columns(2)
                with col1:
                    title_x_offset = st.slider(
                        tr("Title Horizontal Offset (%)"),
                        min_value=-10,
                        max_value=10,
                        value=st.session_state.title_x_offset,
                        step=1,
                        key="theme_title_x_offset",
                        help=tr("Adjust title horizontal position. Base position: 85%")
                    )
                    st.session_state.title_x_offset = title_x_offset
                
                with col2:
                    subtitle_x_offset = st.slider(
                        tr("Subtitle Horizontal Offset (%)"),
                        min_value=-10,
                        max_value=10,
                        value=st.session_state.subtitle_x_offset,
                        step=1,
                        key="theme_subtitle_x_offset",
                        help=tr("Adjust subtitle horizontal position. Base: 18%-80% (landscape) or 10%-70% (portrait)")
                    )
                    st.session_state.subtitle_x_offset = subtitle_x_offset
                
                # 垂直位置调节
                col3, col4 = st.columns(2)
                with col3:
                    title_offset = st.slider(
                        tr("Title Vertical Offset (%)"),
                        min_value=-20,
                        max_value=20,
                        value=st.session_state.title_y_offset,
                        step=5,
                        key="theme_title_offset",
                        help=tr("Adjust title vertical position. Base: vertically centered")
                    )
                    st.session_state.title_y_offset = title_offset
                
                with col4:
                    subtitle_offset = st.slider(
                        tr("Subtitle Vertical Offset (%)"),
                        min_value=-20,
                        max_value=20,
                        value=st.session_state.subtitle_y_offset,
                        step=5,
                        key="theme_subtitle_offset",
                        help=tr("Adjust subtitle vertical position. Base position: 12%")
                    )
                    st.session_state.subtitle_y_offset = subtitle_offset
                
                # 显示实际位置（根据视频比例）
                actual_title_x = 85 + title_x_offset
                if aspect == "9:16":  # 竖屏
                    actual_subtitle_left = 10 + subtitle_x_offset
                    actual_subtitle_right = 70 + subtitle_x_offset
                else:  # 横屏
                    actual_subtitle_left = 18 + subtitle_x_offset
                    actual_subtitle_right = 80 + subtitle_x_offset
                actual_subtitle_y = 12 + subtitle_offset
                st.info(
                    f"📍 {tr('Actual positions')}: "
                    f"{tr('Title')} ({actual_title_x}%, 垂直居中+{title_offset}%), "
                    f"{tr('Subtitle')} ({actual_subtitle_left}%-{actual_subtitle_right}%, {actual_subtitle_y}%)"
                )
                
                # 使用偏移量计算边界
                st.session_state.title_left = 85 + title_x_offset
                st.session_state.title_top = 12 + title_offset  # 注：实际使用时会基于此计算垂直居中
                if aspect == "9:16":  # 竖屏
                    st.session_state.subtitle_left = 10 + subtitle_x_offset
                    st.session_state.subtitle_right = 70 + subtitle_x_offset
                else:  # 横屏
                    st.session_state.subtitle_left = 18 + subtitle_x_offset
                    st.session_state.subtitle_right = 80 + subtitle_x_offset
                st.session_state.subtitle_top = 12 + subtitle_offset
                
            else:  # 精确边界模式
                st.caption("📏 直接设置边界位置（百分比）")
                
                # 标题边界设置
                st.markdown("**标题边界**")
                col1, col2 = st.columns(2)
                with col1:
                    title_left = st.slider(
                        "标题左边界 (%)",
                        min_value=70,
                        max_value=95,
                        value=st.session_state.title_left,
                        step=1,
                        key="title_left_boundary",
                        help="标题在视频中的水平位置（左边界，默认85%）"
                    )
                    st.session_state.title_left = title_left
                
                with col2:
                    title_top = st.slider(
                        "标题上边界 (%)",
                        min_value=0,
                        max_value=30,
                        value=st.session_state.title_top,
                        step=1,
                        key="title_top_boundary",
                        help="标题在视频中的垂直位置（上边界）"
                    )
                    st.session_state.title_top = title_top
                
                # 字幕边界设置
                st.markdown("**字幕边界**")
                col3, col4 = st.columns(2)
                with col3:
                    subtitle_left = st.slider(
                        "字幕左边界 (%)",
                        min_value=5,
                        max_value=50,
                        value=st.session_state.subtitle_left,
                        step=1,
                        key="subtitle_left_boundary",
                        help="字幕区域的左边界位置"
                    )
                    st.session_state.subtitle_left = subtitle_left
                
                with col4:
                    subtitle_right = st.slider(
                        "字幕右边界 (%)",
                        min_value=50,
                        max_value=85,
                        value=st.session_state.subtitle_right,
                        step=1,
                        key="subtitle_right_boundary",
                        help="字幕区域的右边界位置（横屏80%，竖屏70%，与85%的标题保持5%间距）"
                    )
                    st.session_state.subtitle_right = subtitle_right
                
                col5, col6 = st.columns(2)
                with col5:
                    subtitle_top = st.slider(
                        "字幕上边界 (%)",
                        min_value=0,
                        max_value=50,
                        value=st.session_state.subtitle_top,
                        step=1,
                        key="subtitle_top_boundary",
                        help="字幕区域的上边界位置（距离视频顶部的百分比）"
                    )
                    st.session_state.subtitle_top = subtitle_top
                
                with col6:
                    subtitle_bottom = st.slider(
                        "字幕下边界 (%)",
                        min_value=50,
                        max_value=100,
                        value=st.session_state.subtitle_bottom,
                        step=1,
                        key="subtitle_bottom_boundary",
                        help="字幕区域的下边界位置（距离视频顶部的百分比，建议不超过95%）"
                    )
                    st.session_state.subtitle_bottom = subtitle_bottom
                
                # 验证边界合理性
                if subtitle_left >= subtitle_right:
                    st.error("⚠️ 字幕左边界必须小于右边界")
                
                if subtitle_top >= subtitle_bottom:
                    st.error("⚠️ 字幕上边界必须小于下边界")
                
                if subtitle_right > st.session_state.title_left - 5:
                    st.warning("⚠️ 字幕右边界过近标题，可能重叠（建议预留至少5%间距）")
                
                if subtitle_bottom > 95:
                    st.warning("⚠️ 字幕下边界过低，可能超出视频范围（建议不超过95%）")
                
                # 显示当前设置
                subtitle_height = subtitle_bottom - subtitle_top
                st.info(
                    f"📍 当前边界: "
                    f"标题({title_left}%, {title_top}%), "
                    f"字幕区域({subtitle_left}%-{subtitle_right}%, {subtitle_top}%-{subtitle_bottom}%, 高度{subtitle_height}%)"
                )
                
                # 清零偏移量（精确模式不使用偏移）
                st.session_state.title_x_offset = 0
                st.session_state.title_y_offset = 0
                st.session_state.subtitle_x_offset = 0
                st.session_state.subtitle_y_offset = 0
        elif params.video_theme == "modern_book":
            st.caption("📖 " + tr("Modern Book Layout: Title at top 20%, Subtitle at bottom 65%"))
        elif params.video_theme == "cinema":
            st.caption("🎬 " + tr("Cinema Layout: Title fullscreen center, Subtitle at bottom 10%"))
        elif params.video_theme == "minimal":
            st.caption("✨ " + tr("Minimal Layout: Title at top 10%, Subtitle at bottom 15%"))
        
        # 生成预览HTML
        def generate_preview_html(theme, width, height, title_left=75, title_top=12, 
                                 subtitle_left=22, subtitle_right=65, subtitle_top=12, subtitle_bottom=88):
            """生成主题布局预览HTML
            
            Args:
                theme: 主题名称
                width, height: 预览容器尺寸
                title_left: 标题左边界（%）
                title_top: 标题上边界（%）
                subtitle_left: 字幕左边界（%）
                subtitle_right: 字幕右边界（%）
                subtitle_top: 字幕上边界（%）
                subtitle_bottom: 字幕下边界（%）
            """
            
            # 基础样式
            html = f"""
            <div style="
                width: {width}px;
                height: {height}px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                position: relative;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                margin: 10px auto;
            ">
            """
            
            if theme == "modern_book":
                # 现代图书：标题顶部，字幕底部横排
                title_y = 20
                subtitle_y = 65
                html += f"""
                <div style="
                    position: absolute;
                    top: {title_y}%;
                    left: 50%;
                    transform: translateX(-50%);
                    color: #000000;
                    background: rgba(255,255,255,0.9);
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 14px;
                    font-weight: bold;
                    white-space: nowrap;
                ">{tr("Video Title")}</div>
                <div style="
                    position: absolute;
                    top: {subtitle_y}%;
                    left: 10%;
                    right: 10%;
                    color: #000000;
                    background: rgba(255,255,255,0.85);
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 11px;
                    text-align: center;
                ">{tr("Subtitle text appears here")}</div>
                """
            
            elif theme == "cinema":
                # 电影模式：标题居中，字幕底部
                html += f"""
                <div style="
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    color: white;
                    font-size: 18px;
                    font-weight: bold;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
                    text-align: center;
                ">{tr("Video Title")}</div>
                <div style="
                    position: absolute;
                    bottom: 10%;
                    left: 10%;
                    right: 10%;
                    color: white;
                    background: rgba(0,0,0,0.6);
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 11px;
                    text-align: center;
                ">{tr("Subtitle text appears here")}</div>
                """
            
            elif theme == "ancient_scroll":
                # 古书卷轴：标题右侧垂直居中，字幕竖排多列（使用边界参数）
                subtitle_width = subtitle_right - subtitle_left
                subtitle_height = subtitle_bottom - subtitle_top
                html += f"""
                <div style="
                    position: absolute;
                    top: 50%;
                    left: {title_left}%;
                    transform: translateY(-50%);
                    writing-mode: vertical-rl;
                    color: #8B4513;
                    background: rgba(255,215,0,0.2);
                    padding: 8px 4px;
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: bold;
                    text-shadow: 1px 1px 2px rgba(255,215,0,0.5);
                ">{tr("Video Title")}</div>
                <div style="
                    position: absolute;
                    top: {subtitle_top}%;
                    left: {subtitle_left}%;
                    width: {subtitle_width}%;
                    height: {subtitle_height}%;
                    writing-mode: vertical-rl;
                    color: #FFD700;
                    font-size: 11px;
                    line-height: 1.8;
                    text-shadow: 1px 1px 2px rgba(139,69,19,0.8);
                    opacity: 0.9;
                    overflow: hidden;
                    border: 1px dashed rgba(255,215,0,0.3);
                ">{tr("Vertical subtitle text")}<br/>{tr("Multiple columns")}</div>
                <div style="
                    position: absolute;
                    top: 0;
                    left: {subtitle_left}%;
                    height: 100%;
                    width: 1px;
                    background: rgba(255,255,255,0.2);
                "></div>
                <div style="
                    position: absolute;
                    top: 0;
                    left: {subtitle_right}%;
                    height: 100%;
                    width: 1px;
                    background: rgba(255,255,255,0.2);
                "></div>
                <div style="
                    position: absolute;
                    top: {subtitle_top}%;
                    left: 0;
                    width: 100%;
                    height: 1px;
                    background: rgba(255,255,255,0.15);
                "></div>
                <div style="
                    position: absolute;
                    top: {subtitle_bottom}%;
                    left: 0;
                    width: 100%;
                    height: 1px;
                    background: rgba(255,255,255,0.15);
                "></div>
                <div style="
                    position: absolute;
                    top: 0;
                    left: {title_left}%;
                    height: 100%;
                    width: 1px;
                    background: rgba(255,215,0,0.3);
                "></div>
                """
            
            elif theme == "minimal":
                # 简约模式：标题顶部居中，字幕底部
                html += f"""
                <div style="
                    position: absolute;
                    top: 10%;
                    left: 50%;
                    transform: translateX(-50%);
                    color: white;
                    font-size: 16px;
                    font-weight: bold;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
                ">{tr("Video Title")}</div>
                <div style="
                    position: absolute;
                    bottom: 15%;
                    left: 10%;
                    right: 10%;
                    color: white;
                    font-size: 11px;
                    text-align: center;
                    text-shadow: 1px 1px 3px rgba(0,0,0,0.8);
                ">{tr("Subtitle text appears here")}</div>
                """
            
            html += "</div>"
            return html
        
        # 显示预览
        preview_html = generate_preview_html(
            params.video_theme,
            preview_width,
            preview_height,
            st.session_state.title_left,
            st.session_state.title_top,
            st.session_state.subtitle_left,
            st.session_state.subtitle_right,
            st.session_state.subtitle_top,
            st.session_state.subtitle_bottom
        )
        # 使用HTML容器确保正确渲染
        st.components.v1.html(preview_html, height=preview_height + 30, scrolling=False)
        
        # 保存边界参数到params（用于实际生成）
        if hasattr(params, '__dict__'):
            # 保存边界参数
            params.__dict__['title_left'] = st.session_state.title_left
            params.__dict__['title_top'] = st.session_state.title_top
            params.__dict__['subtitle_left'] = st.session_state.subtitle_left
            params.__dict__['subtitle_right'] = st.session_state.subtitle_right
            params.__dict__['subtitle_top'] = st.session_state.subtitle_top
            params.__dict__['subtitle_bottom'] = st.session_state.subtitle_bottom
            # 也保存偏移量参数（兼容性）
            params.__dict__['title_x_offset'] = st.session_state.title_x_offset
            params.__dict__['title_y_offset'] = st.session_state.title_y_offset
            params.__dict__['subtitle_x_offset'] = st.session_state.subtitle_x_offset
            params.__dict__['subtitle_y_offset'] = st.session_state.subtitle_y_offset
        
        font_names, font_display_names = get_all_fonts()
        
        # 默认字体优先级：毛笔手写体 > 黑体
        default_font_priority = [
            "LXGWWenKai-Regular.ttf",    # 霞鹜文楷（推荐）
            "LXGWWenKai-Bold.ttf",       # 霞鹜文楷粗体
            "Zhudou-Sans.ttf",           # 江西拙楷
            "STXingkai.ttf",             # 华文行楷
            "STHeitiMedium.ttc",         # 黑体（备选）
        ]
        
        # 尝试从优先级列表中找到第一个存在的字体
        default_font = "STHeitiMedium.ttc"  # 最后备选
        for font in default_font_priority:
            if font in font_names:
                default_font = font
                break
        
        saved_font_name = config.ui.get("font_name", default_font)
        saved_font_name_index = 0
        if saved_font_name in font_names:
            saved_font_name_index = font_names.index(saved_font_name)
        
        # 使用format_func显示带语言标记的字体名
        selected_font_index = st.selectbox(
            tr("Font"),
            options=range(len(font_names)),
            index=saved_font_name_index,
            format_func=lambda x: font_display_names[font_names[x]]
        )
        params.font_name = font_names[selected_font_index]
        config.ui["font_name"] = params.font_name

        subtitle_positions = [
            (tr("Top"), "top"),
            (tr("Center"), "center"),
            (tr("Bottom"), "bottom"),
            (tr("Bottom (20%)"), "bottom_20"),
            (tr("Custom"), "custom"),
        ]
        selected_index = st.selectbox(
            tr("Position"),
            index=3,  # 默认选择"底部（20%）"
            options=range(len(subtitle_positions)),
            format_func=lambda x: subtitle_positions[x][0],
        )
        params.subtitle_position = subtitle_positions[selected_index][1]

        if params.subtitle_position == "custom":
            custom_position = st.text_input(
                tr("Custom Position (% from top)"),
                value="70.0",
                key="custom_position_input",
            )
            try:
                params.custom_position = float(custom_position)
                if params.custom_position < 0 or params.custom_position > 100:
                    st.error(tr("Please enter a value between 0 and 100"))
            except ValueError:
                st.error(tr("Please enter a valid number"))

        font_cols = st.columns([0.3, 0.7])
        with font_cols[0]:
            # 初始化颜色状态（如果不存在）
            if "text_fore_color" not in st.session_state:
                # 使用当前主题的默认颜色
                theme_defaults = theme_color_defaults.get(params.video_theme, theme_color_defaults["minimal"])
                st.session_state.text_fore_color = config.ui.get("text_fore_color", theme_defaults["text_fore_color"])
            
            params.text_fore_color = st.color_picker(
                tr("Font Color"), 
                st.session_state.text_fore_color,
                help=f"字体颜色（当前主题默认：{theme_color_defaults.get(params.video_theme, {}).get('text_fore_color', '#FFFFFF')}）"
            )
            # 用户修改后保存
            if params.text_fore_color != st.session_state.text_fore_color:
                st.session_state.text_fore_color = params.text_fore_color
            config.ui["text_fore_color"] = params.text_fore_color

        with font_cols[1]:
            saved_font_size = config.ui.get("font_size", 60)
            params.font_size = st.slider(tr("Font Size"), 30, 100, saved_font_size)
            config.ui["font_size"] = params.font_size

        stroke_cols = st.columns([0.3, 0.7])
        with stroke_cols[0]:
            # 初始化描边颜色状态（如果不存在）
            if "stroke_color" not in st.session_state:
                # 使用当前主题的默认颜色
                theme_defaults = theme_color_defaults.get(params.video_theme, theme_color_defaults["minimal"])
                st.session_state.stroke_color = config.ui.get("stroke_color", theme_defaults["stroke_color"])
            
            params.stroke_color = st.color_picker(
                tr("Stroke Color"), 
                st.session_state.stroke_color,
                help=f"描边颜色（当前主题默认：{theme_color_defaults.get(params.video_theme, {}).get('stroke_color', '#000000')}）"
            )
            # 用户修改后保存
            if params.stroke_color != st.session_state.stroke_color:
                st.session_state.stroke_color = params.stroke_color
            config.ui["stroke_color"] = params.stroke_color
            
        with stroke_cols[1]:
            params.stroke_width = st.slider(tr("Stroke Width"), 0.0, 10.0, 1.5)

# 生成视频按钮：快速生成 和 标准生成
st.write("---")
st.write("**" + tr("Video Generation Mode") + "**")

# 模式对比说明
mode_comparison = st.expander(tr("📊 Mode Comparison & Instructions"), expanded=False)
with mode_comparison:
    col_fast, col_standard = st.columns(2)
    
    with col_fast:
        st.markdown("### ⚡ " + tr("Fast Mode"))
        st.markdown(f"""
        **{tr("Advantages")}:**
        - ⚡ {tr("Speed: 10-20x faster")}
        - 🚀 {tr("Uses FFmpeg stream copy (no re-encoding)")}
        - 💾 {tr("Lower CPU/GPU usage")}
        - 📦 {tr("Smaller file size")}
        
        **{tr("Limitations")}:**
        - ⚠️ {tr("Does not support video transition effects")}
        - ⚠️ {tr("Auto-fallback to standard mode if needed")}
        
        **{tr("Best For")}:**
        - 📹 {tr("Quick video creation")}
        - 🎯 {tr("Simple video transitions (none)")}
        - ⏱️ {tr("Time-sensitive projects")}
        """)
    
    with col_standard:
        st.markdown("### 🎬 " + tr("Standard Mode"))
        st.markdown(f"""
        **{tr("Advantages")}:**
        - ✨ {tr("Supports all transition effects")}
        - 🎨 {tr("Full MoviePy processing capabilities")}
        - 🔧 {tr("Maximum flexibility")}
        - 🎞️ {tr("Best quality control")}
        
        **{tr("Limitations")}:**
        - 🐢 {tr("Slower processing speed")}
        - 💻 {tr("Higher resource usage")}
        
        **{tr("Best For")}:**
        - 🎥 {tr("Professional video production")}
        - 🌟 {tr("Complex transitions and effects")}
        - 🎭 {tr("High-quality output requirements")}
        """)

button_cols = st.columns(2)

with button_cols[0]:
    fast_button = st.button(
        "⚡ " + tr("Fast Generation"),
        use_container_width=True,
        type="primary",
        help=tr("Use FFmpeg acceleration, 10-20x faster. Does not support transition effects.")
    )

with button_cols[1]:
    standard_button = st.button(
        "🎬 " + tr("Standard Generation"),
        use_container_width=True,
        help=tr("Full MoviePy processing, supports all effects but slower.")
    )

# 处理按钮点击
start_button = fast_button or standard_button
if start_button:
    # 设置生成模式
    if fast_button:
        params.enable_fast_mode = True
        st.success("⚡ " + tr("Fast Mode Selected") + " - " + tr("Expected 10-20x faster generation"))
        st.caption("🔸 " + tr("Using: FFmpeg concat + stream copy (no re-encoding)"))
        st.caption("💡 " + tr("Note: Will auto-switch to standard mode if transition effects are needed"))
    else:
        params.enable_fast_mode = False
        st.info("🎬 " + tr("Standard Mode Selected") + " - " + tr("Full processing with all features"))
        st.caption("🔸 " + tr("Using: MoviePy complete pipeline (supports all effects)"))
        st.caption("⏱️ " + tr("Note: Processing may take longer but offers maximum flexibility"))
    config.save_config()
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "local"]:
        st.error(tr("Please Select a Valid Video Source"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pexels" and not config.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pixabay" and not config.app.get("pixabay_api_keys", ""):
        st.error(tr("Please Enter the Pixabay API Key"))
        scroll_to_bottom()
        st.stop()

    if uploaded_files:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        for file in uploaded_files:
            file_path = os.path.join(local_videos_dir, f"{file.file_id}_{file.name}")
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
                m = MaterialInfo()
                m.provider = "local"
                m.url = file_path
                if not params.video_materials:
                    params.video_materials = []
                params.video_materials.append(m)

    log_container = st.empty()
    log_records = []

    def log_received(msg):
        if config.ui["hide_log"]:
            return
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))

    logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    result = tm.start(task_id=task_id, params=params)
    if not result or "videos" not in result:
        st.error(tr("Video Generation Failed"))
        logger.error(tr("Video Generation Failed"))
        scroll_to_bottom()
        st.stop()

    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception:
        pass

    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    scroll_to_bottom()

config.save_config()
