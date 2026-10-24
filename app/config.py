"""配置。

取值顺序：**界面上填的用户设置 > 环境变量 > 默认值**。
所以开发时把密钥放环境变量、交付后让用户在设置界面里填，两种都成立。

界面可配的那些项不走模块常量，而是用模块级 __getattr__ 动态取，
这样用户在设置里改完立刻生效，不用重启。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .settings import DEFAULTS, SettingsStore

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MOCK = os.getenv("MOCK", "0").strip() == "1"

# 用户设置（data/settings.json），优先级高于环境变量
settings_store = SettingsStore(ROOT / "data" / "settings.json")
SETTINGS_PATH = ROOT / "data" / "settings.json"

# ---- 以下为不可在界面修改的常量 ----
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_TIMEOUT = float(os.getenv("CHAT_TIMEOUT", "25"))

ASR_MODEL = os.getenv("ASR_MODEL", "nova-2")
# 火山豆包：2.0 模型用 seedasr，1.0 用 bigasr。用错会直接 403。
VOLC_RESOURCE_ID = os.getenv("VOLC_RESOURCE_ID", "volc.seedasr.sauc.duration")
OPENAI_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "gpt-4o-transcribe")

# 时间兜底切分（毫秒）。0 = 关闭，纯按识别出的句号断句。
ASR_MAX_SPEECH_MS = int(os.getenv("ASR_MAX_SPEECH_MS", "0"))
ASR_KEYWORDS_MAX = int(os.getenv("ASR_KEYWORDS_MAX", "40"))

CHANNELS = 1
FRAME_MS = 100

SEG_MAX_LEN = 60
SEG_MAX_WAIT = 1.2
SEG_MIN_LEN = 10

TRANSLATE_DRAIN_TIMEOUT = float(os.getenv("TRANSLATE_DRAIN_TIMEOUT", "25"))

GLOSSARY_PATH = ROOT / "data" / "glossary.json"
HOTWORD_STORE = ROOT / "data" / "hotwords_custom.json"
PRESET_STORE = ROOT / "data" / "presets.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

DIRECTIONS = {
    "zh": {"dg_lang": "zh-CN", "target": "English", "pair": "zh2en"},
    "en": {"dg_lang": "en-US", "target": "Chinese", "pair": "en2zh"},
}

# 需要类型转换的那些
_COERCE = {
    "ASR_ENDPOINTING": int,
    "TRANSLATE_CONCURRENCY": int,
    "TRANSLATE_TIMEOUT": float,
    "ASR_KEYWORDS": lambda v: str(v).strip() == "1",
    "PINYIN_FIX": lambda v: str(v).strip() == "1",
}


def __getattr__(name: str):
    """界面可配项的动态取值。"""
    if name == "SAMPLE_RATE":
        # OpenAI Realtime 只收 24 kHz 及以上，其余引擎要 16 kHz
        return 24000 if settings_store.get("ASR_PROVIDER").lower() == "openai" else 16000
    if name in DEFAULTS:
        raw = settings_store.get(name)
        conv = _COERCE.get(name)
        if conv is not None:
            try:
                return conv(raw)
            except (TypeError, ValueError):
                return conv(DEFAULTS[name])
        return raw
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def missing_keys() -> list[str]:
    """当前引擎和翻译缺哪些密钥。"""
    missing = []
    if not settings_store.has("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    provider = settings_store.get("ASR_PROVIDER").lower()
    if provider == "volc" and not settings_store.has("VOLC_API_KEY"):
        missing.append("VOLC_API_KEY")
    if provider == "deepgram" and not settings_store.has("DEEPGRAM_API_KEY"):
        missing.append("DEEPGRAM_API_KEY")
    return missing


def mock_active() -> bool:
    """现在是不是在跑假数据。

    显式 MOCK=1 永远算；否则只要有密钥补齐了，就自动恢复真实模式——
    用户在设置里填完 key 应该立刻能用，不该逼他重启。
    """
    return MOCK or bool(missing_keys())


def validate() -> None:
    """启动检查。缺密钥不抛异常，降级到 MOCK 并给出提示。"""
    global MOCK
    if MOCK:
        print("[config] MOCK 模式：不调用任何外部 API")
        return

    missing = missing_keys()
    if missing:
        MOCK = True
        print()
        print("=" * 64)
        print(f"  缺少密钥：{', '.join(missing)}")
        print("  已自动切换到 MOCK 模式，界面能用，但字幕是假数据。")
        print()
        print("  三种填法，任选一种：")
        print("    1. 打开网页右上角的齿轮，在设置里填（推荐）")
        print("    2. 设环境变量后重启本窗口")
        print("    3. 复制 .env.example 为 .env 并填写")
        print("=" * 64)
        print()
