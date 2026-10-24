"""FastAPI 入口：静态页 + WebSocket 桥接。

一个连接 = 一个会话。会话内部三个任务：
  upstream   浏览器 PCM → Deepgram
  downstream Deepgram 结果 → interim 回推 / final 进分句
  worker     分句 → 翻译 → 回推

之所以把翻译单独放到 worker，是因为它要等 API（0.6~1s），
放在接收循环里会把 interim 一起堵住，字幕就不"实时"了。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, config
from .chat import ChatService
from .glossary import Glossary
from .lexicon import Lexicon
from .segmenter import Segmenter
from .translate import Translator

LOG_DIR = config.ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# pythonw.exe（无控制台）下 sys.stderr 是 None，直接挂 StreamHandler 会让
# logging 初始化抛异常——进程在 import 阶段就死，连文件日志都留不下。
_log_handlers: list[logging.Handler] = [
    logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
]
if sys.stderr is not None:
    _log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
)
log = logging.getLogger("app")

glossary = Glossary(config.GLOSSARY_PATH)
translator = Translator(glossary)
lexicon = Lexicon(glossary, config.HOTWORD_STORE)
assistant = ChatService(lexicon, glossary)


class ChatIn(BaseModel):
    message: str


class HotwordIn(BaseModel):
    add: list[str] = []
    remove: list[str] = []


class Client:
    """给 WebSocket 加一把锁——两个任务会并发往回写。"""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.lock = asyncio.Lock()
        self.closed = False

    async def send(self, payload: dict) -> None:
        if self.closed:
            return
        async with self.lock:
            try:
                await self.ws.send_json(payload)
            except Exception:
                self.closed = True

    async def close(self) -> None:
        self.closed = True
        try:
            await self.ws.close()
        except Exception:
            pass


def pick_lang(value: str | None) -> str:
    return value if value in config.DIRECTIONS else "en"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.validate()
    log.info("术语表：%s", glossary.summary())
    _engines = {"volc": f"火山豆包 {config.VOLC_RESOURCE_ID}",
                "openai": f"OpenAI {config.OPENAI_ASR_MODEL}",
                "deepgram": f"Deepgram {config.ASR_MODEL}"}
    log.info("翻译模型：%s ｜ 识别引擎：%s",
             config.TRANSLATE_MODEL, _engines.get(config.ASR_PROVIDER, config.ASR_PROVIDER))
    log.info("采集采样率：%d Hz ｜ endpointing=%dms ｜ 术语偏置=%s",
             config.SAMPLE_RATE, config.ASR_ENDPOINTING,
             "开" if config.ASR_KEYWORDS else "关")
    log.info("服务已就绪，用浏览器打开 run.bat 里给出的地址")
    yield


app = FastAPI(title="TCM Live Captions", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    # 前端靠这里拿到该用多大的采样率推流：
    # OpenAI Realtime 只收 24 kHz 及以上，Deepgram 要 16 kHz。
    return {
        "ok": True,
        "mock": config.MOCK,
        "glossary": len(glossary),
        "sampleRate": config.SAMPLE_RATE,
        "provider": config.ASR_PROVIDER,
        "hotwords": len(lexicon.hotwords()),
        "assistant": bool(config.DEEPSEEK_API_KEY),
    }


@app.post("/chat")
async def chat(payload: ChatIn):
    """右侧术语助手的对话入口。"""
    return await assistant.ask(payload.message)


@app.post("/chat/reset")
async def chat_reset():
    assistant.reset()
    return {"ok": True}


@app.get("/hotwords")
async def get_hotwords():
    return {"hotwords": lexicon.hotwords(), **lexicon.snapshot()}


@app.post("/hotwords")
async def set_hotwords(payload: HotwordIn):
    added = lexicon.add(payload.add)
    removed = lexicon.remove(payload.remove)
    return {
        "added": added,
        "removed": removed,
        "hotwords": lexicon.hotwords(),
        "note": "下一次点「开始」时生效",
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    client = Client(ws)
    lang = pick_lang(ws.query_params.get("lang", "en"))
    log.info("会话开始，方向=%s", lang)
    try:
        while True:
            nxt = await run_session(client, lang)
            if not nxt:
                break
            lang = nxt
            log.info("切换方向 → %s", lang)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("会话异常")
    finally:
        await client.close()
        log.info("会话结束")


async def run_session(client: Client, lang: str) -> str | None:
    """跑一次会话。返回新语言表示要切换方向，返回 None 表示结束。"""
    pair = config.DIRECTIONS[lang]["pair"]
    keywords = lexicon.hotwords(pair) if config.ASR_KEYWORDS else None
    stream = await asr.connect(config.DIRECTIONS[lang]["dg_lang"], keywords=keywords)
    segmenter = Segmenter(
        max_len=config.SEG_MAX_LEN,
        max_wait=config.SEG_MAX_WAIT,
        min_len=config.SEG_MIN_LEN,
    )
    ctx = {"stop": False, "next_lang": None}
    out = OrderedTranslator(client, lang, concurrency=config.TRANSLATE_CONCURRENCY)

    up = asyncio.create_task(pump_upstream(client, stream, ctx))
    down = asyncio.create_task(pump_downstream(client, stream, segmenter, out, ctx))

    try:
        await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        ctx["stop"] = True
        for task in (up, down):
            task.cancel()
        await asyncio.gather(up, down, return_exceptions=True)

        # 分句器里残留的半句也要翻，别丢
        tail = segmenter.flush()
        if tail:
            out.submit(tail)
        if out.submitted:
            await out.wait_idle(timeout=config.TRANSLATE_DRAIN_TIMEOUT)
            log.info("会话收尾：提交翻译 %d 句，其中 %d 句没拿到译文",
                     out.submitted, out.failed)
        await stream.close()

    return ctx["next_lang"]


async def pump_upstream(client: Client, stream, ctx: dict) -> None:
    """浏览器 → ASR。顺带处理控制消息。"""
    while not ctx["stop"]:
        try:
            msg = await client.ws.receive()
        except Exception:
            ctx["stop"] = True
            return

        if msg.get("type") == "websocket.disconnect":
            ctx["stop"] = True
            return

        data = msg.get("bytes")
        if data:
            try:
                await stream.send(data)
            except Exception:
                ctx["stop"] = True
                return
            continue

        text = msg.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            continue

        kind = payload.get("type")
        if kind == "lang":
            ctx["next_lang"] = pick_lang(payload.get("value"))
            ctx["stop"] = True
            return
        if kind == "stop":
            ctx["stop"] = True
            return


class OrderedTranslator:
    """并发翻译，按提交顺序输出。

    原来是串行的一句一译：每句等 API 0.6~1 s，老师说快一点队列就越积越长，
    后面全在排队，停止时来不及翻的直接丢。改成几路并发之后，
    还要保证字幕顺序跟说话顺序一致，所以用序号 + 重排缓冲：
    某句先翻完了也压着，等它前面的句子先上屏。
    """

    def __init__(self, client: Client, lang: str, concurrency: int = 3):
        self.client = client
        self.lang = lang
        self.sem = asyncio.Semaphore(concurrency)
        self._seq = 0
        self._next = 0
        self._buf: dict[int, tuple[str, str]] = {}
        self._lock = asyncio.Lock()
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self.submitted = 0
        self.failed = 0

    def submit(self, src: str) -> None:
        seq = self._seq
        self._seq += 1
        self.submitted += 1
        self._inflight += 1
        self._idle.clear()
        asyncio.create_task(self._work(seq, src))

    async def _work(self, seq: int, src: str) -> None:
        try:
            async with self.sem:
                src, dst = await translator.translate(src, self.lang)
        except Exception:
            log.exception("翻译异常")
            dst = ""
        if not dst:
            self.failed += 1

        async with self._lock:
            self._buf[seq] = (src, dst)
            while self._next in self._buf:
                s, d = self._buf.pop(self._next)
                self._next += 1
                await self.client.send({
                    "type": "final",
                    "src": s,
                    "dst": d,
                    "dir": self.lang,
                })
            self._inflight -= 1
            if self._inflight == 0:
                self._idle.set()

    async def wait_idle(self, timeout: float = 25.0) -> bool:
        """等所有在途翻译落地。超时返回 False。"""
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            log.warning("等待翻译完成超时，还有 %d 句没上屏", self._inflight)
            return False


async def pump_downstream(
    client: Client, stream, segmenter: Segmenter,
    out: OrderedTranslator, ctx: dict,
) -> None:
    """ASR → 前端。interim 立即回推，final 攒成句子后送去翻译。"""
    try:
        async for result in stream:
            if ctx["stop"]:
                break
            if not result.is_final:
                await client.send({"type": "interim", "text": result.text})
                continue
            sentence = segmenter.feed(result.text)
            if sentence:
                log.info("[句] %s", sentence[:60])
                out.submit(sentence)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("识别流出错")
        await client.send({"type": "error", "message": "识别连接中断"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=False)
