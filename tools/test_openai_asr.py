"""验证 OpenAI GA Realtime transcription 能不能做流式中文转写。

步骤：TTS 造一段中文语音 → 走 Realtime 流式转写 → 打印事件。
只用来确认接口可用性与事件格式，不接进正式链路。
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import websockets
from openai import OpenAI

KEY = os.environ["OPENAI_API_KEY"]
TEXT = "今天我们讲肝阳上亢的临床表现，患者舌红少苔，脉弦细数。"


def make_audio() -> bytes:
    """用 TTS 生成 24 kHz 16-bit 单声道 PCM，正好是 Realtime 要的格式。"""
    client = OpenAI(api_key=KEY, timeout=60)
    out = Path(".tmp/tts_test.pcm")
    out.parent.mkdir(exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=TEXT,
        response_format="pcm",
    ) as resp:
        resp.stream_to_file(out)
    data = out.read_bytes()
    print(f"TTS 音频：{len(data)} 字节（约 {len(data)/2/24000:.1f} 秒）")
    return data


async def transcribe(pcm: bytes) -> None:
    url = "wss://api.openai.com/v1/realtime?intent=transcription"
    headers = {"Authorization": f"Bearer {KEY}"}

    async with websockets.connect(url, additional_headers=headers, open_timeout=20) as ws:
        first = json.loads(await ws.recv())
        print("会话已建立:", first.get("type"), "| 默认输入格式:",
              json.dumps(first.get("session", {}).get("audio", {}))[:200])

        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "transcription": {"model": "gpt-4o-transcribe", "language": "zh"},
                        "turn_detection": {"type": "server_vad", "silence_duration_ms": 500},
                    }
                },
            },
        }))

        # 每 100 ms 推一块
        chunk = 2400 * 2
        for i in range(0, len(pcm), chunk):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm[i : i + chunk]).decode(),
            }))
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        got: list[str] = []
        deadline = asyncio.get_event_loop().time() + 20
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                break
            t = msg.get("type", "")
            if "transcription" in t:
                if t.endswith(".delta"):
                    got.append(msg.get("delta", ""))
                elif t.endswith(".completed"):
                    got.append(msg.get("transcript", ""))
                print(f"  事件 {t}: {json.dumps(msg)[:180]}")
            elif t == "error":
                print("  !! error:", json.dumps(msg)[:300])

        print("\n最终转写:", "".join(got) or "(空)")


if __name__ == "__main__":
    asyncio.run(transcribe(make_audio()))
