"""术语表：加载、双向索引、长词优先匹配。

两个方向各有一次排序成本，放在构造时做，之后每次匹配只做子串/正则查找。

长词优先是硬要求：语文里 气 ⊂ 气虚 ⊂ 气血两虚，不按长度倒序排，
短词会先把长词切碎，翻译出来的东西就没法看了。
"""
from __future__ import annotations

import json
import re
from pathlib import Path


class Glossary:
    def __init__(self, path: str | Path, max_hits: int = 8):
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.path = path
        self.max_hits = max_hits
        self.entries = raw

        self._zh2en: dict[str, str] = {}
        self._en2zh: dict[str, str] = {}
        for e in raw:
            zh, en = e["zh"], e["en"]
            self._zh2en.setdefault(zh, en)
            self._en2zh.setdefault(en.lower(), zh)

        # 长词优先。单字中文术语（表/里/虚/实/气/血…）不参与匹配：
        # 「表现」里的表、「实际」里的实都会误命中，而单字术语的注入价值
        # 本来也接近于零——出现单个「气」时模型自己就会译成 qi。
        # 它们仍留在表里供查阅，只是不当匹配键。
        self._zh_keys = sorted(
            (k for k in self._zh2en if len(k) > 1), key=len, reverse=True
        )
        self._en_keys = sorted(
            (k for k in self._en2zh if len(k) > 1), key=len, reverse=True
        )
        # 英文用词边界，避免 qi 命中 qigong
        self._en_patterns = {
            k: re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE)
            for k in self._en_keys
        }

    def __len__(self) -> int:
        return len(self.entries)

    def match(self, text: str, direction: str = "zh2en") -> list[tuple[str, str]]:
        """返回 [(原文术语, 目标译法)]，按在句中出现的先后排列。

        只保留不重叠的最长匹配：`liver yang hyperactivity` 命中之后，
        其中的 liver / yang 不再单独命中——否则提示词里塞满冗余条目，
        max_hits 几个名额很快就被短词占光。
        """
        if not text:
            return []
        table = self._zh2en if direction == "zh2en" else self._en2zh
        spans = self._spans_zh(text) if direction == "zh2en" else self._spans_en(text)
        spans.sort(key=lambda s: s[0])
        return [(k, table[k]) for _, _, k in spans[: self.max_hits]]

    def _spans_zh(self, text: str) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        for k in self._zh_keys:
            start = 0
            while True:
                i = text.find(k, start)
                if i < 0:
                    break
                if not self._overlaps(spans, i, i + len(k)):
                    spans.append((i, i + len(k), k))
                start = i + len(k)
        return spans

    def _spans_en(self, text: str) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        for k in self._en_keys:
            for m in self._en_patterns[k].finditer(text):
                s, e = m.span()
                if not self._overlaps(spans, s, e):
                    spans.append((s, e, k))
        return spans

    @staticmethod
    def _overlaps(spans, start: int, end: int) -> bool:
        return any(start < e and s < end for s, e, _ in spans)

    def keywords_for(self, direction: str = "zh2en", limit: int = 40) -> list[str]:
        """给识别引擎做术语偏置用的词表（取源语言那一侧）。

        单字词不进去：偏置一个「气」对模型几乎没有意义，
        还会挤占名额。
        """
        if direction == "zh2en":
            words = [e["zh"] for e in self.entries if len(e["zh"]) > 1]
        else:
            words = [e["en"] for e in self.entries]
        return words[:limit]

    def summary(self) -> str:
        cats: dict[str, int] = {}
        for e in self.entries:
            cats[e["category"]] = cats.get(e["category"], 0) + 1
        head = ", ".join(f"{k}:{v}" for k, v in sorted(cats.items()))
        return f"{len(self.entries)} 条术语 ({head})"
