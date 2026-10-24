"""火山豆包 vs OpenAI 流式 ASR 对比基准。

同一段音频分别过两个引擎，量三个指标：
  - 首字延迟：第一个可见文字出现的时间
  - 定稿时间：句子 final 的时间
  - 准确率：与参考文本的字级比对
"""
import asyncio
import gzip
import json
import os
import struct
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

VOLC_KEY = os.getenv("VOLC_API_KEY", "")
VOLC_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
VOLC_RID = "volc.seedasr.sauc.duration"

# ---------- 工具 ----------

def resample(pcm: bytes, src: int, dst: int) -> bytes:
    n = len(pcm) // 2
    s = struct.unpack(f"<{n}h", pcm[: n * 2])
    ratio = src / dst
    out = []
    i = 0.0
    while int(i) + 1 < len(s):
        j = int(i)
        out.append(s[j])
        i += ratio
    return struct.pack(f"<{len(out)}h", *out)


def frame(header: bytes, payload: bytes) -> bytes:
    body = gzip.compress(payload)
    return header + struct.pack(">I", len(body)) + body


def parse(data) -> dict:
    if isinstance(data, str):
        data = data.encode("latin-1")
    msg_type = data[1] >> 4
    flags = data[1] & 0x0F
    compressed = (data[2] & 0x0F) == 1
    off = 4
    if msg_type == 0x0F:
        code = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        size = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        body = data[off:off + size]
        if compressed or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return {"error": body.decode("utf-8", "replace")}
    if flags & 0x01:
        off += 4
    size = struct.unpack(">I", data[off:off + 4])[0]; off += 4
    body = data[off:off + size]
    if compressed and body:
        body = gzip.decompress(body)
    return {"payload": json.loads(body) if body else {}, "flags": flags}


def wer(ref: str, hyp: str) -> float:
    """字级编辑距离 / 参考长度。"""
    ref, hyp = list(ref), list(hyp)
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(len(ref), 1)


# ---------- 两个引擎 ----------

async def run_volc(pcm16k: bytes, ref: str) -> dict:
    hdr = {"x-api-key": VOLC_KEY, "X-Api-Resource-Id": VOLC_RID,
           "X-Api-Request-Id": str(uuid.uuid4()), "X-Api-Connect-Id": str(uuid.uuid4())}
    cfg = {"user": {"uid": "bench"},
           "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
           "request": {"model_name": "bigmodel", "enable_punc": True, "enable_itn": True,
                       "show_utterances": True, "result_type": "full", "end_window_size": 800}}
    t0 = time.time()
    first = None
    final = None
    async with websockets.connect(VOLC_URL, additional_headers=hdr, max_size=10_000_000) as ws:
        await ws.send(frame(bytes([0x11, 0x10, 0x11, 0x00]), json.dumps(cfg, ensure_ascii=False).encode()))
        await asyncio.wait_for(ws.recv(), timeout=10)

        chunk = 3200
        for i in range(0, len(pcm16k), chunk):
            await ws.send(frame(bytes([0x11, 0x20, 0x01, 0x00]), pcm16k[i:i + chunk]))
            await asyncio.sleep(0.05)
        await ws.send(frame(bytes([0x11, 0x22, 0x01, 0x00]), b"\x00\x00"))

        try:
            async with asyncio.timeout(20):
                async for msg in ws:
                    r = parse(msg)
                    if "error" in r:
                        break
                    res = r.get("payload", {}).get("result") or {}
                    for u in res.get("utterances") or []:
                        if u.get("text") and first is None:
                            first = time.time() - t0
                        if u.get("definite"):
                            final = (time.time() - t0, u.get("text", ""))
                    if final:
                        break
        except (TimeoutError, asyncio.TimeoutError):
            pass
    return {"first": first, "final": final, "name": "火山豆包"}


async def run_openai(pcm24k: bytes, ref: str) -> dict:
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY", "")
    url = "wss://api.openai.com/v1/realtime?intent=transcription"
    t0 = time.time()
    first = None
    final = None
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {key}"},
                                  max_size=16 * 1024 * 1024) as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)
        await ws.send(json.dumps({"type": "session.update", "session": {
            "type": "transcription",
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": {"model": "gpt-4o-transcribe", "language": "zh"},
                "turn_detection": {"type": "server_vad", "silence_duration_ms": 500},
            }}}}))
        chunk = 4800
        for i in range(0, len(pcm24k), chunk):
            await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                      "audio": __import__("base64").b64encode(pcm24k[i:i+chunk]).decode()}))
            await asyncio.sleep(0.05)
        for _ in range(30):  # 补静音让 VAD 收尾
            await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                      "audio": __import__("base64").b64encode(b"\x00" * chunk).decode()}))
            await asyncio.sleep(0.05)
        try:
            async with asyncio.timeout(20):
                async for raw in ws:
                    m = json.loads(raw)
                    t = m.get("type", "")
                    if t.endswith("transcription.delta") and first is None:
                        first = time.time() - t0
                    elif t.endswith("transcription.completed"):
                        final = (time.time() - t0, m.get("transcript", ""))
                        break
        except (TimeoutError, asyncio.TimeoutError):
            pass
    return {"first": first, "final": final, "name": "OpenAI"}


async def main():
    cases = [
        ("气血两虚的患者，舌淡脉细，治以益气养血。", ".tmp/tts.pcm"),
    ]
    for ref, path in cases:
        raw = Path(path).read_bytes()
        p24 = raw
        p16 = resample(raw, 24000, 16000)
        print(f"\n参考文本: {ref}")
        print(f"音频 {len(p24)/2/24000:.1f} 秒\n")

        r1 = await run_volc(p16, ref)
        r2 = await run_openai(p24, ref)

        for r in (r1, r2):
            text = r["final"][1] if r["final"] else ""
            print(f"{r['name']:8} 首字 {r['first'] or 0:.2f}s  "
                  f"定稿 {r['final'][0] if r['final'] else 0:.2f}s  "
                  f"字错率 {wer(ref, text):.1%}")
            print(f"          {text}")


if __name__ == "__main__":
    asyncio.run(main())
