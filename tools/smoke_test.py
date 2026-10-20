"""端到端冒烟测试：起服务 → 连 WebSocket → 收字幕 → 关掉。

跑的是 MOCK 模式，不碰任何外部 API，只验证
音频上行、识别流、分句、翻译、前端消息格式这条链路是通的。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = 8123
BASE = Path(__file__).resolve().parent.parent
VENDOR = BASE / "vendor"
if VENDOR.exists():  # 只在本机没有安装依赖时兜底
    sys.path.insert(0, str(VENDOR))


def wait_health(timeout=25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


async def run() -> int:
    import websockets

    seen_interim = seen_final = 0
    got_final_with_pair = False
    url = f"ws://127.0.0.1:{PORT}/ws?lang=zh"

    async with websockets.connect(url) as ws:
        async def pump_audio():
            # 送 100ms 的静音帧，模拟麦克风持续供数
            silence = b"\x00" * 3200
            for _ in range(60):
                await ws.send(silence)
                await asyncio.sleep(0.1)

        audio = asyncio.create_task(pump_audio())
        deadline = time.time() + 12
        try:
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg["type"] == "interim":
                    seen_interim += 1
                elif msg["type"] == "final":
                    seen_final += 1
                    if msg.get("src") and msg.get("dst"):
                        got_final_with_pair = True
                    if seen_final <= 3:
                        print(f"  final  src={msg['src']}")
                        print(f"         dst={msg['dst']}")
                if seen_final >= 2:
                    break
        finally:
            audio.cancel()

    print(f"\n[result] interim={seen_interim} final={seen_final}")
    ok = seen_interim > 0 and seen_final >= 1 and got_final_with_pair
    print("[result] PASS" if ok else "[result] FAIL")
    return 0 if ok else 1


def main() -> int:
    env = dict(os.environ)
    env["MOCK"] = "1"
    env["PYTHONPATH"] = str(BASE / "vendor")
    env["PYTHONIOENCODING"] = "utf-8"

    logpath = BASE / ".tmp" / "server.log"
    logpath.parent.mkdir(exist_ok=True)
    logfile = open(logpath, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=BASE, env=env,
        stdout=logfile, stderr=subprocess.STDOUT,
    )

    try:
        if not wait_health():
            print("[fail] 服务没起来，日志：")
            print(logpath.read_text(encoding="utf-8", errors="replace")[-3000:])
            return 1
        print("[ok] 服务已启动，开始收字幕…\n")
        return asyncio.run(run())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
