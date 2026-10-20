"""翻译：术语约束下的句级翻译。

一次请求做三件事：查出句子里命中的术语、把术语写成强制译法、拿到译文。
temperature=0 是刻意的——同一个术语在整节课里必须译法一致，
译法飘忽比译错更让人迷茫。
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import config
from .glossary import Glossary

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a simultaneous interpreter for a Traditional Chinese Medicine "
    "(TCM) lecture.\n"
    "The input is automatic speech recognition output from a noisy classroom. "
    "It commonly contains homophone errors (e.g. 肝阳上抗 for 肝阳上亢) and "
    "broken sentence boundaries.\n"
    "\n"
    "Silently repair obvious mis-hearings before translating. Use the "
    "mandatory glossary below as evidence for which term was intended. "
    "Only fix what is clearly a mis-hearing — never rewrite, summarise or "
    "paraphrase the meaning.\n"
    "\n"
    "Then translate the repaired sentence into {target}.\n"
    "Rules:\n"
    "- Output ONLY the translation. No explanation, no quotes, no pinyin.\n"
    "- Keep it natural and speakable, as captions for a live audience.\n"
    "TERM_RULES"
)

TERM_BLOCK = (
    "- The following renderings are mandatory. Use them exactly, "
    "even if you would normally translate the term differently:\n{terms}\n"
)


class Translator:
    def __init__(self, glossary: Glossary):
        self.glossary = glossary
        self._client = None
        from .pinyin_fix import HomophoneFixer

        self.fixer = HomophoneFixer(glossary)

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return self._client

    async def translate(self, text: str, direction: str = "zh") -> tuple[str, str]:
        """返回（纠正后的原文, 译文）。"""
        text = text.strip()
        if not text:
            return "", ""

        # 先按拼音把听错的术语改回来，再拿去匹配和翻译。
        # 纠正后的原文也返回给前端——用户看到的是「修好的那句话」。
        if direction == "zh" and config.PINYIN_FIX:
            fixed, hits = self.fixer.correct(text)
            if hits:
                log.info("[纠字] %s", "；".join(f"{a}→{b}" for a, b in hits))
            text = fixed

        if config.MOCK:
            return text, self._mock_translate(text, direction)

        target = config.DIRECTIONS[direction]["target"]
        pair = config.DIRECTIONS[direction]["pair"]
        hits = self.glossary.match(text, pair)

        if hits:
            terms = "\n".join(f"  {src} → {dst}" for src, dst in hits)
            term_rules = TERM_BLOCK.format(terms=terms)
        else:
            term_rules = ""

        system = SYSTEM.format(target=target).replace("TERM_RULES", term_rules)

        t0 = time.perf_counter()
        try:
            client = self._get_client()
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=config.TRANSLATE_MODEL,
                    temperature=0,
                    max_tokens=200,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                ),
                timeout=config.TRANSLATE_TIMEOUT,
            )
            out = (resp.choices[0].message.content or "").strip()
            dur = (time.perf_counter() - t0) * 1000
            if dur > 1500:
                log.warning("翻译偏慢 %.0fms：%s", dur, text[:30])
            return text, out
        except asyncio.TimeoutError:
            log.warning("翻译超时，先显示原文：%s", text[:40])
            return text, ""
        except Exception as exc:  # 网络、额度、鉴权等
            log.warning("翻译失败（%s）：%s", type(exc).__name__, text[:40])
            return text, ""

    # ------------------------------------------------------------------
    def _mock_translate(self, text: str, direction: str) -> str:
        """无密钥时的占位译文：把命中的术语按表替换，其余原样保留。

        目的不是像样，而是让界面、滚动、术语命中率这些都能被验证。
        """
        pair = config.DIRECTIONS[direction]["pair"]
        hits = self.glossary.match(text, pair)
        out = text
        for src, dst in hits:
            out = out.replace(src, dst)
        if not hits:
            return f"[mock] {out}"
        return f"[mock] {out}"
