"""语义分句。

Deepgram 吐出的 final 常常是半句。直接丢给翻译，中文语序会被切碎，
译文读起来像机翻——因为确实是逐片翻的。

这里做一次缓冲，满足任一条件才放行：
  1. 句末标点  。！？.!?
  2. 长度超过 60 字（老师一口气讲很久时的兜底）
  3. 已积累到 10 字以上，且距上一个字节已经等了 1.2 秒

第 3 条是给连讲不断句的情况用的；没有它，字幕会长时间不出。
"""
from __future__ import annotations

import time

TERMINALS = "。！？.!?"


class Segmenter:
    def __init__(
        self,
        max_len: int = 60,
        max_wait: float = 1.2,
        min_len: int = 10,
    ):
        self.max_len = max_len
        self.max_wait = max_wait
        self.min_len = min_len
        self.buf = ""
        self._since = time.monotonic()

    def feed(self, text: str) -> str | None:
        """喂入一段识别文本，攒够一句就返回它，否则返回 None。"""
        if not text:
            return None
        if not self.buf:
            self._since = time.monotonic()
        self.buf += text

        now = time.monotonic()
        long_enough = len(self.buf) >= self.max_len
        waited = (
            len(self.buf) >= self.min_len
            and (now - self._since) >= self.max_wait
        )
        if self._complete() or long_enough or waited:
            out = self.buf.strip()
            self.buf = ""
            self._since = now
            return out or None
        return None

    def flush(self) -> str | None:
        """会话结束时把残留的半句也吐出去。"""
        out = self.buf.strip()
        self.buf = ""
        return out or None

    def _complete(self) -> bool:
        return bool(self.buf.rstrip()) and self.buf.rstrip()[-1] in TERMINALS
