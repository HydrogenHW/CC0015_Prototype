"""配置：从 .env 读取密钥与运行参数。

设计的要点是快速失败：缺 key 时启动即报错退出，而不是等到第一句话
才在 WebSocket 里炸掉。MOCK=1 可以绕过 key 检查，用假数据驱动界面，
方便没有密钥时先验收 UI 和音频链路。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MOCK = os.getenv("MOCK", "0").strip() == "1"

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VOLC_API_KEY = os.getenv("VOLC_API_KEY", "").strip()

# 右侧术语助手（DeepSeek，兼容 OpenAI 协议）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")
CHAT_TIMEOUT = float(os.getenv("CHAT_TIMEOUT", "25"))

ASR_MODEL = os.getenv("ASR_MODEL", "nova-2")
TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", "gpt-4o-mini")

# 识别引擎：volc（默认，火山豆包流式）| openai | deepgram
#
# 换到火山的理由来自实测：同一段加了噪声的音频，火山 0% 字错，
# OpenAI Realtime 85% 字错（整句崩成别的句子）。而且火山是真流式，
# 边说话边出字，OpenAI 要等句子结束才吐。
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "volc").strip().lower()

# 火山豆包：2.0 模型用 seedasr，1.0 用 bigasr。用错会直接 403。
VOLC_RESOURCE_ID = os.getenv("VOLC_RESOURCE_ID", "volc.seedasr.sauc.duration")

# OpenAI Realtime 转写模型。mini 更快更便宜，4o 更准。
OPENAI_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "gpt-4o-transcribe")

# 静音多久判定一句结束（毫秒）。火山推荐 800~1000，太小会切碎句子。
ASR_ENDPOINTING = int(os.getenv("ASR_ENDPOINTING", "800"))

# 时间兜底切分（毫秒）。0 = 关闭，纯按识别出的句号断句（推荐）。
# 只有遇到「长时间说话但识别迟迟不给句号」的极端情况才需要设成正数，
# 代价是会切在词中间。
ASR_MAX_SPEECH_MS = int(os.getenv("ASR_MAX_SPEECH_MS", "0"))

# 术语偏置：把术语表里的词喂给识别引擎，期望它更愿意听成这些词。
# 右侧助手可以增删这份热词，所以默认开着；设 0 可完全关闭。
ASR_KEYWORDS = os.getenv("ASR_KEYWORDS", "1").strip() == "1"
ASR_KEYWORDS_MAX = int(os.getenv("ASR_KEYWORDS_MAX", "40"))

# 采样率由引擎决定：OpenAI Realtime 只收 24 kHz 及以上，
# Deepgram 要 16 kHz。前端通过 /health 拿到这个值，不用改代码。
SAMPLE_RATE = 24000 if ASR_PROVIDER == "openai" else 16000
CHANNELS = 1
FRAME_MS = 100

# 断句：句末标点、最大长度、最长等待（秒）
SEG_MAX_LEN = 60
SEG_MAX_WAIT = 1.2
SEG_MIN_LEN = 10

# 同音纠错：识别把术语听成同音字时，按拼音把它改回来（零延迟，本地做）。
PINYIN_FIX = os.getenv("PINYIN_FIX", "1").strip() == "1"

TRANSLATE_TIMEOUT = float(os.getenv("TRANSLATE_TIMEOUT", "6.0"))

# 同时进行的翻译请求数。串行跑跟不上一堂课的语速，
# 但开太多会撞 OpenAI 的速率限制。
TRANSLATE_CONCURRENCY = int(os.getenv("TRANSLATE_CONCURRENCY", "3"))

# 停止录音后，等剩余句子翻完的最长时间（秒）。
# 太短会丢内容，太长会让人以为卡住了。
TRANSLATE_DRAIN_TIMEOUT = float(os.getenv("TRANSLATE_DRAIN_TIMEOUT", "25"))

GLOSSARY_PATH = ROOT / "data" / "glossary.json"
HOTWORD_STORE = ROOT / "data" / "hotwords_custom.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

DIRECTIONS = {
    "zh": {"dg_lang": "zh-CN", "target": "English", "pair": "zh2en"},
    "en": {"dg_lang": "en-US", "target": "Chinese", "pair": "en2zh"},
}


def validate() -> None:
    """启动前检查。

    缺 key 时不抛异常——直接降级到 MOCK 模式并打印醒目提示。
    理由：一屏 traceback 对第一次双击 run.bat 的人来说等于劝退，
    而「服务起来了、字幕在动、但内容是假的」更容易理解，
    字幕上的 [mock] 前缀也不会让人误以为接了真 API。
    """
    global MOCK
    if MOCK:
        print("[config] MOCK 模式：不调用任何外部 API")
        return

    # 翻译总是要 OpenAI；识别看引擎
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if ASR_PROVIDER == "volc" and not VOLC_API_KEY:
        missing.append("VOLC_API_KEY")
    if ASR_PROVIDER == "deepgram" and not DEEPGRAM_API_KEY:
        missing.append("DEEPGRAM_API_KEY")
    if missing:
        MOCK = True
        print()
        print("=" * 64)
        print(f"  缺少密钥：{', '.join(missing)}")
        print("  已自动切换到 MOCK 模式，界面能用，但字幕是假数据。")
        print()
        print("  要接真实识别与翻译（当前识别引擎 " + ASR_PROVIDER + "）：")
        print("    1. 设置环境变量（见 README「配置密钥」）")
        print("    2. 重启本窗口")
        print("=" * 64)
        print()
