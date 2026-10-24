"""运行时热词表：术语表打底，用户可以对话增删。

和 glossary.py 的分工：
  glossary  只读的 267 条中医术语，负责匹配和强制译法
  lexicon   给识别引擎的热词，可在运行时改

热词改完不会立刻影响正在跑的识别——火山的 corpus.hotwords 只在
建立连接时传一次。所以改动会标记 dirty，下次点「开始」时生效。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .glossary import Glossary

log = logging.getLogger("lexicon")


class Lexicon:
    def __init__(self, glossary: Glossary, store: Path | None = None):
        self._glossary = glossary
        self._store = store
        self._extra: list[str] = []
        self._removed: set[str] = set()
        self._load()

    # ------------------------------------------------------------------
    def hotwords(self, direction: str = "zh2en", limit: int = 40) -> list[str]:
        """给识别引擎用的词表。用户加的词排在前面，优先占名额。"""
        base = self._glossary.keywords_for(direction, limit=400)
        out: list[str] = []
        seen: set[str] = set()
        for word in self._extra + base:
            w = word.strip()
            if not w or w in self._removed or w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= limit:
                break
        return out

    def add(self, words: list[str]) -> list[str]:
        added = []
        for w in words:
            w = (w or "").strip()
            if not w or len(w) < 2:
                continue
            self._removed.discard(w)
            if w not in self._extra:
                self._extra.append(w)
                added.append(w)
        if added:
            self._save()
            log.info("热词新增 %d 个：%s", len(added), "、".join(added[:8]))
        return added

    def remove(self, words: list[str]) -> list[str]:
        removed = []
        for w in words:
            w = (w or "").strip()
            if not w:
                continue
            if w in self._extra:
                self._extra.remove(w)
            self._removed.add(w)
            removed.append(w)
        if removed:
            self._save()
            log.info("热词移除 %d 个：%s", len(removed), "、".join(removed[:8]))
        return removed

    def snapshot(self) -> dict:
        return {
            "custom": list(self._extra),
            "removed": sorted(self._removed),
            "total": len(self.hotwords()),
        }

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self._extra = [str(w) for w in data.get("custom", [])]
            self._removed = set(str(w) for w in data.get("removed", []))
            log.info("载入自定义热词 %d 个", len(self._extra))
        except Exception:
            log.warning("自定义热词文件读取失败，忽略", exc_info=True)

    def _save(self) -> None:
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            self._store.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            log.warning("自定义热词保存失败", exc_info=True)
