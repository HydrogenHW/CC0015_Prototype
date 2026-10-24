"""流式语音识别。

两种实现，接口一致：
  DeepgramStream  真实识别（WebSocket）
  MockStream      无密钥时用的假数据，按仿真的节奏吐结果

统一成同一个异步迭代接口，server.py 不需要知道当前是哪一种。
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from . import config

log = logging.getLogger("asr")

DG_URL = "wss://api.deepgram.com/v1/listen"
OPENAI_RT_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
VOLC_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

# 火山自定义二进制帧：4 字节头 + 4 字节长度 + gzip payload
#   头[0]=0x11 (协议版本1|头长1)  头[1]=消息类型<<4|flags
#   头[2]=序列化<<4|压缩          头[3]=保留
#   消息类型 1=配置(JSON) 2=音频    flags 0=中间包 2=最后一包
VOLC_HDR_CLIENT = bytes([0x11, 0x10, 0x11, 0x00])
VOLC_HDR_AUDIO = bytes([0x11, 0x20, 0x01, 0x00])
VOLC_HDR_AUDIO_LAST = bytes([0x11, 0x22, 0x01, 0x00])


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
        # 已推入、但还没被 VAD 切分掉的音频时长（毫秒）。
        # 到 ASR_MAX_SPEECH_MS 就主动 commit 一刀，防止连讲不停时永不出字。
        self._pending_ms = 0.0

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

        seconds = len(data) / 2 / config.SAMPLE_RATE
        self._pending_ms += seconds * 1000
        if self._pending_ms >= config.ASR_MAX_SPEECH_MS:
            try:
                await self._sock.send(json.dumps({"type": "input_audio_buffer.commit"}))
                log.info("连讲超过 %.0f 秒，强制切分一次", self._pending_ms / 1000)
            except Exception:
                log.exception("强制 commit 失败")
            self._pending_ms = 0.0

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
                self._pending_ms = 0.0   # VAD 已经切过一刀，累计清零
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


def _volc_frame(header: bytes, payload: bytes) -> bytes:
    body = gzip.compress(payload)
    return header + struct.pack(">I", len(body)) + body


def _volc_parse(data) -> dict:
    if isinstance(data, str):
        data = data.encode("latin-1")
    msg_type = data[1] >> 4
    flags = data[1] & 0x0F
    compressed = (data[2] & 0x0F) == 0x01
    off = 4
    if msg_type == 0x0F:                       # 错误帧
        off += 4                               # status code
        size = struct.unpack(">I", data[off:off + 4])[0]
        off += 4
        body = data[off:off + size]
        if compressed or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return {"error": body.decode("utf-8", "replace")}
    if flags & 0x01:                           # 带序号
        off += 4
    size = struct.unpack(">I", data[off:off + 4])[0]
    off += 4
    body = data[off:off + size]
    if compressed and body:
        body = gzip.decompress(body)
    return {"payload": json.loads(body) if body else {}, "flags": flags}


class VolcengineStream:
    """火山豆包流式识别（2.0 模型）。

    选它而不是 OpenAI 的依据是实测：同一段加了噪声的音频，
    火山 0% 字错，OpenAI Realtime 85% 字错。而且它是真流式——
    说话过程中就逐字吐 partial，不必等整句结束。

    三个接入要点，错一个就连不上：
      1. X-Api-Resource-Id 必须与模型版本匹配，2.0 用 volc.seedasr.*，
         1.0 用 volc.bigasr.*，用错直接 403；
      2. 音频要 16 kHz（不是 OpenAI 的 24 kHz）；
      3. 认证只需要 x-api-key，不需要 AppID。
    """

    def __init__(self, sock, vad_ms: int):
        self._sock = sock
        self._vad_ms = vad_ms
        self._closed = False
        # 火山每次推送都带「到目前为止的全部 utterances」，必须自己去重，
        # 否则同一句会被反复当成新句子送进翻译区。
        self._seen: dict[float, float] = {}   # start_time → 首次见到的时间
        self._done: set[float] = set()        # 已定稿的 start_time
        self._cut_len: dict[float, int] = {}  # 被强制切分过时，已上屏的字数

    @classmethod
    async def connect(cls, lang: str, keywords: list[str] | None = None) -> "VolcengineStream":
        import websockets

        headers = {
            "x-api-key": config.VOLC_API_KEY,
            "X-Api-Resource-Id": config.VOLC_RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        sock = await websockets.connect(
            VOLC_URL, additional_headers=headers, max_size=10_000_000
        )
        self = cls(sock, config.ASR_ENDPOINTING)

        # 火山要求 end_window_size 在 [300, 5000]，推荐 800~1000。
        # 太小会把句子切碎，太大出字慢。
        vad_ms = min(max(config.ASR_ENDPOINTING, 300), 5000)
        request: dict = {
            "model_name": "bigmodel",
            "enable_punc": True,
            "enable_itn": True,
            "show_utterances": True,
            "result_type": "full",
            "end_window_size": vad_ms,
        }
        if keywords:
            # 术语热词：火山会把命中的词优先听成这些写法
            ctx = {"hotwords": [{"word": w} for w in keywords[:50]]}
            request["corpus"] = {"context": json.dumps(ctx, ensure_ascii=False)}

        cfg = {
            "user": {"uid": "tcm-live-captions"},
            "audio": {
                "format": "pcm", "codec": "raw",
                "rate": config.SAMPLE_RATE, "bits": 16, "channel": 1,
            },
            "request": request,
        }
        await sock.send(_volc_frame(VOLC_HDR_CLIENT, json.dumps(cfg, ensure_ascii=False).encode()))
        try:
            ack = _volc_parse(await asyncio.wait_for(sock.recv(), timeout=10))
            if ack.get("error"):
                log.error("火山配置被拒: %s", ack["error"])
        except (asyncio.TimeoutError, ValueError):
            log.warning("没等到火山配置回执，继续尝试")
        return self

    async def send(self, data: bytes) -> None:
        if self._closed or not data:
            return
        await self._sock.send(_volc_frame(VOLC_HDR_AUDIO, data))

    async def __aiter__(self) -> AsyncIterator[ASRResult]:
        async for raw in self._sock:
            if self._closed:
                break
            try:
                msg = _volc_parse(raw)
            except Exception:
                continue
            if msg.get("error"):
                err = str(msg["error"])
                # 会话收尾时火山会抱怨没有新音频，这是正常结束，不是故障
                if "Timed out waiting" in err or "session has ended" in err:
                    break
                log.error("火山识别错误: %s", err)
                continue
            result = msg.get("payload", {}).get("result") or {}
            now = time.monotonic()

            for utt in result.get("utterances") or []:
                text = (utt.get("text") or "").strip()
                if not text:
                    continue
                start = utt.get("start_time", 0) or 0
                if start in self._done:
                    continue                      # 这句已经上屏过，别再重复

                prev_len = self._cut_len.get(start, 0)

                if utt.get("definite"):
                    self._done.add(start)
                    rest = text[prev_len:].strip()
                    if rest:
                        yield ASRResult(text=rest, is_final=True)
                    else:
                        # 这句已经全部切走，发个空草稿把残留清掉
                        yield ASRResult(text="", is_final=False)
                    continue

                # 还没定稿。火山只在检测到静音时才给 definite，
                # 老师连着讲不停就永远不给——到时长就本地强制切一刀。
                # 只切「上次切分之后新增的部分」，否则长句后半段会被整段丢掉。
                first = self._seen.setdefault(start, now)
                if now - first >= config.ASR_MAX_SPEECH_MS / 1000:
                    rest = text[prev_len:].strip()
                    if len(rest) >= 8:
                        self._cut_len[start] = len(text)
                        self._seen[start] = now       # 计时重置，等下个窗口
                        log.info("连讲超过 %.0f 秒，强制切分：%s",
                                 config.ASR_MAX_SPEECH_MS / 1000, rest[:40])
                        yield ASRResult(text=rest, is_final=True)
                        continue
                    self._seen[start] = now

                # 草稿只显示「还没切走的部分」。如果这里发完整文本，
                # 已经上屏的那半句会继续赖在草稿区不消失。
                yield ASRResult(text=text[prev_len:], is_final=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._sock.send(_volc_frame(VOLC_HDR_AUDIO_LAST, b"\x00\x00"))
        except Exception:
            pass
        try:
            await self._sock.close()
        except Exception:
            pass


async def connect(lang: str, keywords: list[str] | None = None) -> ASRStream:
    """按当前配置返回真实或模拟的识别流。"""
    if config.MOCK:
        return MockStream(lang)  # type: ignore[return-value]
    if config.ASR_PROVIDER == "volc":
        return await VolcengineStream.connect(lang, keywords=keywords)
    if config.ASR_PROVIDER == "openai":
        return await OpenAITranscribeStream.connect(lang, keywords=keywords)
    return await DeepgramStream.connect(lang, keywords=keywords)
