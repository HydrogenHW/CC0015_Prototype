"""端到端验证：音频 → 识别 → 同音纠错 → 术语约束翻译 → 双语字幕。

采样率从 /health 读，适配当前识别引擎（火山 16 kHz / OpenAI 24 kHz）。
"""
import asyncio
import json
import os
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

PCM = Path(".tmp/tts.pcm")          # 24 kHz 源
BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000")
WS = BASE.replace("http", "ws") + "/ws?lang=zh"


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    n = len(pcm) // 2
    s = struct.unpack(f"<{n}h", pcm[: n * 2])
    ratio = src / dst
    out, i = [], 0.0
    while int(i) + 1 < len(s):
        out.append(s[int(i)])
        i += ratio
    return struct.pack(f"<{len(out)}h", *out)


async def main() -> int:
    rate = json.load(urllib.request.urlopen(f"{BASE}/health", timeout=5))["sampleRate"]
    pcm = PCM.read_bytes()
    if rate != 24000:
        pcm = resample(pcm, 24000, rate)
    print(f"音频 {len(pcm)/2/rate:.1f} 秒 @ {rate} Hz")

    chunk = int(rate * 0.1) * 2
    finals, errors, interims = [], [], 0
    t0 = time.time()

    async with websockets.connect(WS) as ws:
        async def pump():
            for i in range(0, len(pcm), chunk):
                await ws.send(pcm[i : i + chunk])
                await asyncio.sleep(0.095)
            silence = b"\x00" * chunk
            for _ in range(40):
                await ws.send(silence)
                await asyncio.sleep(0.095)
            await ws.send(json.dumps({"type": "stop"}))

        task = asyncio.create_task(pump())
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
            except asyncio.TimeoutError:
                if task.done():
                    break
                continue
            except websockets.ConnectionClosed:
                break
            msg = json.loads(raw)
            if msg["type"] == "interim":
                interims += 1
            elif msg["type"] == "final":
                finals.append(msg)
                print(f"  [{time.time()-t0:5.1f}s] {msg['src']}")
                print(f"            → {msg['dst'][:80]}")
            elif msg["type"] == "error":
                errors.append(msg)
            if len(finals) >= 2:
                break

    print(f"\ninterim {interims} 次｜final {len(finals)} 条｜error {len(errors)}")
    ok = len(finals) >= 1 and all(f.get("src") and f.get("dst") for f in finals) and not errors
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
