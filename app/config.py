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

ASR_MODEL = os.getenv("ASR_MODEL", "nova-2")
TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", "gpt-4o-mini")

# 识别引擎：openai（默认，走 OpenAI Realtime 转写）或 deepgram。
# Deepgram 的 key 曾因撤销而 401，OpenAI 这条线复用了已有的 key，
# 少一个供应商、少一个要来的密钥。
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "openai").strip().lower()

# OpenAI Realtime 转写模型。mini 更快更便宜，4o 更准。
OPENAI_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "gpt-4o-transcribe")

# 静音多久判定一句结束。太小会把词切碎、丢上下文，太大字幕出得慢。
ASR_ENDPOINTING = int(os.getenv("ASR_ENDPOINTING", "500"))

# 术语偏置：把术语表里的词喂给识别引擎，期望它更愿意听成这些词。
# 效果因引擎和语言而异，所以做成开关，方便 A/B 对比。
ASR_KEYWORDS = os.getenv("ASR_KEYWORDS", "0").strip() == "1"
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

TRANSLATE_TIMEOUT = 3.0

# 同时进行的翻译请求数。串行跑跟不上一堂课的语速，
# 但开太多会撞 OpenAI 的速率限制。
TRANSLATE_CONCURRENCY = int(os.getenv("TRANSLATE_CONCURRENCY", "3"))

# 停止录音后，等剩余句子翻完的最长时间（秒）。
# 太短会丢内容，太长会让人以为卡住了。
TRANSLATE_DRAIN_TIMEOUT = float(os.getenv("TRANSLATE_DRAIN_TIMEOUT", "25"))

GLOSSARY_PATH = ROOT / "data" / "glossary.json"
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

    missing = []
    if not DEEPGRAM_API_KEY:
        missing.append("DEEPGRAM_API_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        MOCK = True
        print()
        print("=" * 64)
        print(f"  缺少密钥：{', '.join(missing)}")
        print("  已自动切换到 MOCK 模式，界面能用，但字幕是假数据。")
        print()
        print("  要接真实识别与翻译：")
        print("    1. 复制 .env.example 为 .env")
        print("    2. 填入 Deepgram 和 OpenAI 的 key")
        print("    3. 重启本窗口")
        print("=" * 64)
        print()
