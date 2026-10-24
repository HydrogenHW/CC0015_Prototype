"""端到端验证 OpenAI 转写接入后的完整链路。

发一段真实语音（24 kHz PCM）到本地 /ws，看能不能拿到双语字幕。
这是唯一能确认「识别→纠错→翻译」整条线都通的办法。
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

PCM = Path(".tmp/tts.pcm")
WS = os.getenv("WS_URL", "ws://127.0.0.1:8000/ws?lang=zh")


async def main() -> int:
    if not PCM.exists():
        print(f"找不到测试音频 {PCM}，先跑 tools/test_openai_asr.py 生成")
        return 1

    pcm = PCM.read_bytes()
    print(f"音频 {len(pcm)/2/24000:.1f} 秒，24 kHz")

    finals = []
    interims = 0
    errors = []

    async with websockets.connect(WS) as ws:
        async def pump():
            chunk = 2400 * 2  # 100 ms @ 24 kHz
            for i in range(0, len(pcm), chunk):
                await ws.send(pcm[i : i + chunk])
                await asyncio.sleep(0.095)
            # 关键：VAD 靠「静音」判定一句结束。真实麦克风会一直发静音帧，
            # 测试里必须自己补上，否则只会看到 speech_started，永远等不到定稿。
            silence = b"\x00" * chunk
            for _ in range(40):
                await ws.send(silence)
                await asyncio.sleep(0.095)
            await ws.send(json.dumps({"type": "stop"}))

        task = asyncio.create_task(pump())
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
            except asyncio.TimeoutError:
                if task.done():
                    break
                continue
            except websockets.ConnectionClosed:
                break
            msg = json.loads(raw)
            print("  <<", json.dumps(msg, ensure_ascii=False)[:180])
            if msg["type"] == "interim":
                interims += 1
            elif msg["type"] == "final":
                finals.append(msg)
                print(f"  [final] {msg['src']}")
                print(f"          → {msg['dst']}")
            elif msg["type"] == "error":
                errors.append(msg)
                print("  [error]", msg)
            if len(finals) >= 2:
                break

    print()
    print(f"interim 次数: {interims}")
    print(f"final 条数: {len(finals)}")
    print(f"error: {len(errors)}")
    ok = len(finals) >= 1 and all(f.get("src") and f.get("dst") for f in finals)
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
