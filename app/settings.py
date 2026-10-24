"""用户设置：界面里改的那些东西。

取值优先级固定为：**用户设置 > 环境变量 > 默认值**。
这样开发时把密钥放环境变量、交付后让用户在界面里填，两种方式都成立。

config.py 通过模块级 __getattr__ 在这里取值，所以改动是**立即生效**的，
不用重启——除了识别引擎本身（连接建立后才读参数）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("settings")


# 界面上暴露哪些配置。group 会渲染成小标题，顺序即显示顺序。
# readonly 的项只显示当前值，不给改——先把模型参数锁死，
# 避免用户随手改坏，等明确了再放开。
SCHEMA = [
    {
        "group": "API 密钥", "group_en": "API keys",
        "items": [
            {"key": "VOLC_API_KEY", "type": "password",
             "label": "火山引擎（语音识别）", "label_en": "Volcengine (speech recognition)",
             "link": "https://console.volcengine.com/speech/new/setting/apikeys",
             "link_text": "控制台", "link_text_en": "Console"},
            {"key": "OPENAI_API_KEY", "type": "password",
             "label": "OpenAI（翻译）", "label_en": "OpenAI (translation)",
             "link": "https://platform.openai.com/api-keys",
             "link_text": "控制台", "link_text_en": "Console"},
            {"key": "DEEPSEEK_API_KEY", "type": "password",
             "label": "DeepSeek（术语助手）", "label_en": "DeepSeek (assistant)",
             "link": "https://platform.deepseek.com/api_keys",
             "link_text": "控制台", "link_text_en": "Console"},
        ],
    },
    {
        "group": "语音识别", "group_en": "Recognition",
        "items": [
            {"key": "ASR_PROVIDER", "type": "select", "readonly": True,
             "label": "识别引擎", "label_en": "Engine",
             "options": [["volc", "火山豆包", "Volcengine"], ["deepgram", "Deepgram", "Deepgram"]]},
            {"key": "ASR_ENDPOINTING", "type": "number", "readonly": True, "min": 300, "max": 5000,
             "label": "断句静音阈值（毫秒）", "label_en": "Silence threshold (ms)"},
            {"key": "ASR_KEYWORDS", "type": "select", "readonly": True,
             "label": "启用热词组", "label_en": "Use hotword sets",
             "options": [["1", "开", "On"], ["0", "关", "Off"]]},
            {"key": "PINYIN_FIX", "type": "select", "readonly": True,
             "label": "同音纠错", "label_en": "Homophone repair",
             "options": [["1", "开", "On"], ["0", "关", "Off"]]},
        ],
    },
    {
        "group": "翻译", "group_en": "Translation",
        "items": [
            {"key": "TRANSLATE_MODEL", "type": "text", "readonly": True,
             "label": "翻译模型", "label_en": "Model"},
            {"key": "TRANSLATE_CONCURRENCY", "type": "number", "readonly": True, "min": 1, "max": 8,
             "label": "并发路数", "label_en": "Parallel requests"},
            {"key": "TRANSLATE_TIMEOUT", "type": "number", "readonly": True, "min": 1, "max": 30,
             "label": "单句超时（秒）", "label_en": "Per-sentence timeout (s)"},
        ],
    },
    {
        "group": "术语助手", "group_en": "Assistant",
        "items": [
            {"key": "CHAT_MODEL", "type": "text", "readonly": True,
             "label": "助手模型", "label_en": "Model"},
        ],
    },
]

# 界面可配的键 → 默认值。没有环境变量也没有用户设置时用这个。
DEFAULTS = {
    "VOLC_API_KEY": "",
    "OPENAI_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "DEEPGRAM_API_KEY": "",
    "ASR_PROVIDER": "volc",
    "ASR_ENDPOINTING": "800",
    "ASR_KEYWORDS": "1",
    "PINYIN_FIX": "1",
    "TRANSLATE_MODEL": "gpt-4o-mini",
    "TRANSLATE_CONCURRENCY": "3",
    "TRANSLATE_TIMEOUT": "6.0",
    "CHAT_MODEL": "deepseek-chat",
}

SECRET_KEYS = {"VOLC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DEEPGRAM_API_KEY"}


class SettingsStore:
    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ 读
    def get(self, key: str, default: str | None = None) -> str:
        v = self._data.get(key)
        if v not in (None, ""):
            return str(v)
        env = os.getenv(key)
        if env not in (None, ""):
            return str(env)
        if default is not None:
            return default
        return DEFAULTS.get(key, "")

    def source_of(self, key: str) -> str:
        """这个值从哪来的：用户 / 环境变量 / 默认。界面用来提示。"""
        if self._data.get(key) not in (None, ""):
            return "user"
        if os.getenv(key) not in (None, ""):
            return "env"
        return "default"

    def has(self, key: str) -> bool:
        return bool(self.get(key))

    def public(self) -> dict:
        """给前端的状态：不返回明文密钥，只告诉有没有、从哪来。"""
        out = {}
        for key in DEFAULTS:
            if key in SECRET_KEYS:
                out[key] = {"set": self.has(key), "source": self.source_of(key)}
            else:
                out[key] = {"value": self.get(key), "source": self.source_of(key)}
        return out

    def schema(self) -> list:
        return SCHEMA

    # ------------------------------------------------------------------ 写
    def update(self, patch: dict) -> dict:
        changed = []
        for key, value in patch.items():
            if key not in DEFAULTS:
                continue
            v = "" if value is None else str(value).strip()
            if key in SECRET_KEYS and v.startswith("*"):
                continue                     # 前端回传的掩码值，跳过
            if self._data.get(key, "") == v:
                continue
            if v == "":
                self._data.pop(key, None)
            else:
                self._data[key] = v
            changed.append(key)
        if changed:
            self._save()
            log.info("设置已更新：%s", ", ".join(changed))
        return {"changed": changed}

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = {str(k): str(v) for k, v in raw.items() if v is not None}
            log.info("载入用户设置 %d 项", len(self._data))
        except Exception:
            log.warning("设置文件损坏，已忽略", exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            log.warning("设置保存失败", exc_info=True)
