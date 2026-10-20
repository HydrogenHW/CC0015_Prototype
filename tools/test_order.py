"""验证 OrderedTranslator：并发翻译时字幕顺序必须跟提交顺序一致。

用假翻译器模拟「第一句很慢、后面很快」，检查输出是否仍然按序。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import server  # noqa: E402


class FakeClient:
    def __init__(self):
        self.out = []

    async def send(self, payload):
        self.out.append(payload)


async def slow_first(text, lang):
    if text.startswith("一"):
        await asyncio.sleep(1.0)      # 第一句故意慢
    else:
        await asyncio.sleep(0.05)
    return text, f"译文[{text}]"


async def main():
    server.translator.translate = slow_first  # 打桩

    client = FakeClient()
    out = server.OrderedTranslator(client, "zh", concurrency=3)

    sentences = ["一", "二", "三", "四", "五"]
    for s in sentences:
        out.submit(s)

    ok = await out.wait_idle(timeout=6)
    print("全部完成:", ok, "｜ 提交", out.submitted, "句，失败", out.failed, "句")

    got = [m["src"] for m in client.out]
    for m in client.out:
        print(f"  {m['src']} -> {m['dst']}")

    print()
    print("输出条数:", len(got), "/", len(sentences))
    print("顺序正确:", got == sentences)
    return 0 if (got == sentences and ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
