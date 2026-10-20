"""同音纠错：识别听错字时，靠拼音把术语认回来。

噪声环境里 ASR 最典型的错误是同音替代：「肝阳上亢」→「肝阳上抗」。
这类错误有个好性质——**读音没变**。所以只要把术语表和句子都转成拼音，
滑窗一比就能把字改回来，不需要请求任何模型，零延迟。

它只能修术语表里有的词，但这恰恰是最要紧的一批：
术语一旦认错，后面的强制译法就丢了，翻译只能靠模型自由发挥。
"""
from __future__ import annotations

from pypinyin import lazy_pinyin

from .glossary import Glossary


class HomophoneFixer:
    def __init__(self, glossary: Glossary, max_len: int = 8):
        self.table: dict[tuple[str, ...], str] = {}
        longest = 2
        for entry in glossary.entries:
            zh = entry["zh"]
            if len(zh) < 2:
                continue
            pys = lazy_pinyin(zh)
            if len(pys) != len(zh):      # 含非汉字，跳过
                continue
            self.table.setdefault(tuple(pys), zh)
            longest = max(longest, len(zh))
        self.max_len = min(max_len, longest)

    def correct(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """返回（纠正后的句子，[(原写法, 改成的术语), ...]）。"""
        if not text:
            return text, []
        chars = list(text)
        pys = lazy_pinyin(text)
        if len(pys) != len(chars):       # 结构对不上就不冒险
            return text, []

        out: list[str] = []
        hits: list[tuple[str, str]] = []
        i, n = 0, len(chars)
        while i < n:
            matched = False
            for length in range(min(self.max_len, n - i), 1, -1):
                zh = self.table.get(tuple(pys[i : i + length]))
                if zh:
                    seg = "".join(chars[i : i + length])
                    if seg != zh:
                        hits.append((seg, zh))
                    out.append(zh)
                    i += length
                    matched = True
                    break
            if not matched:
                out.append(chars[i])
                i += 1
        return "".join(out), hits
