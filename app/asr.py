"""流式语音识别。

两种实现，接口一致：
  DeepgramStream  真实识别（WebSocket）
  MockStream      无密钥时用的假数据，按仿真的节奏吐结果

统一成同一个异步迭代接口，server.py 不需要知道当前是哪一种。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from . import config

log = logging.getLogger("asr")

DG_URL = "wss://api.deepgram.com/v1/listen"
OPENAI_RT_URL = "wss://api.openai.com/v1/realtime?intent=transcription"


@dataclass
class ASRResult:
    text: str
    is_final: bool


class ASRStream(Protocol):
    async def send(self, data: bytes) -> None: ...
    def __aiter__(self) -> AsyncIterator[ASRResult]: ...
    async def close(self) -> None: ...


class DeepgramStream:
    """Deepgram 实时识别。

    参数里三个关键项：
      endpointing=300   静音 300ms 判定一句结束
      smart_format      数字/格式规整（中医课数字很多）
      punctuate         标点，分句器要靠它
    """

    def __init__(self, sock):
        self._sock = sock
        self._closed = False

    @classmethod
    async def connect(cls, lang: str, keywords: list[str] | None = None) -> "DeepgramStream":
        import websockets
        from urllib.parse import quote

        url = (
            f"{DG_URL}?encoding=linear16"
            f"&sample_rate={config.SAMPLE_RATE}"
            f"&channels={config.CHANNELS}"
            f"&model={config.ASR_MODEL}"
            f"&language={lang}"
            "&interim_results=true"
            f"&endpointing={config.ASR_ENDPOINTING}"
            "&smart_format=true"
            "&punctuate=true"
        )
        if keywords:
            # Deepgram 的术语偏置：重复参数，权重 2 表示加强
            extra = "&".join(
                f"keywords={quote(k)}:2" for k in keywords[: config.ASR_KEYWORDS_MAX]
            )
            url = f"{url}&{extra}"

        headers = {"Authorization": f"Token {config.DEEPGRAM_API_KEY}"}
        try:
            sock = await websockets.connect(url, additional_headers=headers)
        except TypeError:  # 旧版 websockets 用 extra_headers
            sock = await websockets.connect(url, extra_headers=headers)
        return cls(sock)

    async def send(self, data: bytes) -> None:
        if self._closed:
            return
        await self._sock.send(data)

    async def __aiter__(self) -> AsyncIterator[ASRResult]:
        async for raw in self._sock:
            if self._closed:
                break
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if msg.get("type") != "Results":
                continue
            alts = msg.get("channel", {}).get("alternatives") or [{}]
            text = (alts[0].get("transcript") or "").strip()
            if not text:
                continue
            yield ASRResult(text=text, is_final=bool(msg.get("is_final")))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._sock.close()
        except Exception:
            pass


MOCK_ZH = [
    "今天我们讲肝阳上亢的临床表现。",
    "患者常见眩晕、头痛、耳鸣。",
    "舌红少苔，脉弦细数。",
    "治法是平肝潜阳。",
    "可以用天麻钩藤饮加减。",
    "针灸取太冲、太溪、风池。",
    "气血两虚的患者要注意补益。",
    "足三里是强壮要穴。",
]

MOCK_EN = [
    "Today we discuss liver yang hyperactivity.",
    "The patient presents with dizziness and headache.",
    "The tongue is red with little coating.",
    "The treatment principle is to calm the liver and subdue yang.",
    "Acupuncture points are Taichong, Taixi and Fengchi.",
    "Qi and blood deficiency needs tonification.",
]


class MockStream:
    """没有密钥时的假识别流：节奏照真实情况走，用来验收界面与链路。"""

    def __init__(self, lang: str):
        self._sentences = MOCK_ZH if lang.startswith("zh") else MOCK_EN
        self._queue: asyncio.Queue[ASRResult | None] = asyncio.Queue()
        self._task = asyncio.create_task(self._produce())

    async def _produce(self) -> None:
        i = 0
        try:
            while True:
                sentence = self._sentences[i % len(self._sentences)]
                i += 1
                n = len(sentence)
                for step in (1, 2, 3):
                    await asyncio.sleep(0.45)
                    await self._queue.put(
                        ASRResult(sentence[: max(1, n * step // 3)], False)
                    )
                await asyncio.sleep(0.35)
                await self._queue.put(ASRResult(sentence, True))
                await asyncio.sleep(0.7)
        except asyncio.CancelledError:
            pass

    async def send(self, data: bytes) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[ASRResult]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self._queue.put(None)


class OpenAITranscribeStream:
    """OpenAI GA Realtime 转写（/v1/realtime?intent=transcription）。

    事件模型刚好对上两段式字幕：
      ...transcription.delta      逐字增量  → interim
      ...transcription.completed  整句定稿  → final

    两个坑已经踩过，写在这里免得再踩：
      1. 旧文档里的 `OpenAI-Beta: realtime=v1` 头已经停用，带上会直接 400；
      2. 采样率低于 24 kHz 会被拒（integer_below_min_value），
         所以前端必须按 24 kHz 推流，别沿用 Deepgram 的 16 kHz。
    """

    def __init__(self, sock, model: str, lang: str, vad_ms: int):
        self._sock = sock
        self._model = model
        self._lang = lang
        self._vad_ms = vad_ms
        self._cur = ""
        self._closed = False

    @classmethod
    async def connect(cls, lang: str, keywords: list[str] | None = None) -> "OpenAITranscribeStream":
        import websockets

        headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
        sock = await websockets.connect(
            OPENAI_RT_URL, additional_headers=headers, max_size=16 * 1024 * 1024
        )
        # "zh-CN" / "en-US" → "zh" / "en"
        short = (lang or "zh").split("-")[0].lower()
        self = cls(sock, config.OPENAI_ASR_MODEL, short, config.ASR_ENDPOINTING)

        # 必须先收掉 session.created，再发 session.update。
        # 顺序反了 update 会被服务端无声忽略，表现为「连上了但永远没有结果」。
        try:
            first = json.loads(await asyncio.wait_for(sock.recv(), timeout=10))
            if first.get("type") == "error":
                log.error("转写会话建立失败: %s", json.dumps(first)[:300])
        except (asyncio.TimeoutError, ValueError):
            log.warning("没等到 session.created，继续尝试配置")

        await self._configure()
        return self

    async def _configure(self) -> None:
        await self._sock.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                        "transcription": {"model": self._model, "language": self._lang},
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": self._vad_ms,
                        },
                    }
                },
            },
        }))

    async def send(self, data: bytes) -> None:
        if self._closed:
            return
        await self._sock.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(data).decode(),
        }))

    async def __aiter__(self) -> AsyncIterator[ASRResult]:
        async for raw in self._sock:
            if self._closed:
                break
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            kind = msg.get("type", "")

            if kind.endswith("input_audio_transcription.delta"):
                self._cur += msg.get("delta", "")
                if self._cur.strip():
                    yield ASRResult(text=self._cur, is_final=False)
            elif kind.endswith("input_audio_transcription.completed"):
                text = (msg.get("transcript") or self._cur).strip()
                self._cur = ""
                if text:
                    yield ASRResult(text=text, is_final=True)
            elif kind.endswith("input_audio_transcription.failed"):
                log.warning("转写失败: %s", json.dumps(msg)[:200])
                self._cur = ""
            elif kind == "error":
                # 单个事件出错不掀桌子，把原因留在日志里继续跑
                log.error("OpenAI 转写出错: %s", json.dumps(msg)[:300])

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._sock.close()
        except Exception:
            pass


async def connect(lang: str, keywords: list[str] | None = None) -> ASRStream:
    """按当前配置返回真实或模拟的识别流。"""
    if config.MOCK:
        return MockStream(lang)  # type: ignore[return-value]
    if config.ASR_PROVIDER == "openai":
        return await OpenAITranscribeStream.connect(lang, keywords=keywords)
    return await DeepgramStream.connect(lang, keywords=keywords)
