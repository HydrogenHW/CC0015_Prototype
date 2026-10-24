"""火山豆包流式 ASR 协议验证。

协议是从官方示例反推的：4 字节头 + 4 字节长度 + gzip payload。
  头: [0]=0x11(协议版本1|头长1) [1]=消息类型<<4|flags [2]=序列化<<4|压缩 [3]=0
  消息类型: 1=FULL_CLIENT_REQUEST(配置) 2=AUDIO_ONLY_REQUEST(音频)
  flags: 0=中间包 1=带序号 2=最后一包
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

import websockets

KEY = os.environ["VOLC_API_KEY"]
URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
RID = os.getenv("VOLC_RESOURCE_ID", "volc.seedasr.sauc.duration")

HDR_CLIENT = bytes([0x11, 0x10, 0x11, 0x00])   # 配置：JSON + gzip
HDR_AUDIO = bytes([0x11, 0x20, 0x01, 0x00])    # 音频：raw + gzip
HDR_AUDIO_LAST = bytes([0x11, 0x22, 0x01, 0x00])


def frame(header: bytes, payload: bytes) -> bytes:
    body = gzip.compress(payload)
    return header + struct.pack(">I", len(body)) + body


def parse(data: bytes) -> dict:
    if isinstance(data, str):
        data = data.encode("latin-1")
    msg_type = data[1] >> 4
    flags = data[1] & 0x0F
    compressed = (data[2] & 0x0F) == 0x01
    off = 4
    info: dict = {"type": msg_type, "flags": flags}

    if msg_type == 0x0F:  # 错误包
        code = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        size = struct.unpack(">I", data[off:off + 4])[0]; off += 4
        body = data[off:off + size]
        if compressed or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        info["error"] = (code, body.decode("utf-8", "replace"))
        return info

    if flags & 0x01:
        info["seq"] = struct.unpack(">i", data[off:off + 4])[0]; off += 4
    size = struct.unpack(">I", data[off:off + 4])[0]; off += 4
    body = data[off:off + size]
    if compressed and body:
        body = gzip.decompress(body)
    info["payload"] = json.loads(body) if body else {}
    return info


def resample_24k_to_16k(pcm: bytes) -> bytes:
    n = len(pcm) // 2
    s = struct.unpack(f"<{n}h", pcm[: n * 2])
    out = []
    i = 0
    while i + 2 < len(s):
        # 3 个输 2 个：取首尾平均
        out.append(s[i])
        out.append((s[i + 1] + s[i + 2]) // 2)
        i += 3
    return struct.pack(f"<{len(out)}h", *out)


CONFIG = {
    "user": {"uid": "cc0015"},
    "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
    "request": {
        "model_name": "bigmodel",
        "enable_punc": True,
        "enable_itn": True,
        "show_utterances": True,
        "result_type": "full",
        "end_window_size": 800,
    },
}


async def main() -> int:
    raw = Path(".tmp/tts.pcm").read_bytes()
    pcm = resample_24k_to_16k(raw)
    print(f"音频 {len(pcm)/2/16000:.1f} 秒（已重采样到 16 kHz）")

    headers = {
        "x-api-key": KEY,
        "X-Api-Resource-Id": RID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    t0 = time.time()
    finals: list[str] = []
    partials: list[str] = []

    async with websockets.connect(URL, additional_headers=headers, max_size=10_000_000) as ws:
        await ws.send(frame(HDR_CLIENT, json.dumps(CONFIG, ensure_ascii=False).encode()))
        ack = parse(await asyncio.wait_for(ws.recv(), timeout=10))
        print("配置回执:", ack.get("error") or ack.get("payload", {}).get("message", "ok"))

        chunk = 1600 * 2  # 100 ms
        for i in range(0, len(pcm), chunk):
            await ws.send(frame(HDR_AUDIO, pcm[i:i + chunk]))
            await asyncio.sleep(0.05)
        await ws.send(frame(HDR_AUDIO_LAST, b"\x00\x00"))

        try:
            async with asyncio.timeout(25):
                async for msg in ws:
                    r = parse(msg)
                    if "error" in r:
                        print("错误:", r["error"])
                        break
                    res = r.get("payload", {}).get("result")
                    if res:
                        text = res.get("text", "") if isinstance(res, dict) else ""
                        utts = res.get("utterances") or []
                        for u in utts:
                            if u.get("definite"):
                                finals.append(u.get("text", ""))
                                print(f"  [{time.time()-t0:5.2f}s] FINAL   {u.get('text','')}")
                            elif u.get("text"):
                                partials.append(u.get("text", ""))
                                print(f"  [{time.time()-t0:5.2f}s] partial {u.get('text','')[:40]}")
                        if text and not utts:
                            finals.append(text)
                    if r.get("flags", 0) & 0b0010:
                        break
        except (TimeoutError, asyncio.TimeoutError):
            print("(超时)")

    print(f"\n最终: {''.join(finals) or '(空)'}")
    print(f"耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
