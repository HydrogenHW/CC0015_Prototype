"""热词预设：可命名、可切换的热词组，按翻译方向分开管理。

中医那 267 条术语只是「中医」这一个预设的内容。用户可以为
法律、计算机、生物之类的领域各建一个预设，切过去识别引擎就按
那个领域的词做偏置。

为什么按方向分开：中文课和英文课的热词长得不一样（一个要「肝阳上亢」，
一个要 liver yang hyperactivity），共用一份没有意义。
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from .glossary import Glossary

log = logging.getLogger("presets")

DIRECTIONS = ("zh2en", "en2zh")


class PresetStore:
    def __init__(self, path: Path, glossary: Glossary):
        self._path = path
        self._glossary = glossary
        self._data: dict = {"version": 1, "active": {}, "presets": {}}
        self._load()

    # ------------------------------------------------------------------ 读
    def list(self, direction: str) -> list[dict]:
        items = self._data["presets"].get(direction, [])
        return [{"id": p["id"], "name": p["name"], "count": len(p["words"])} for p in items]

    def active_id(self, direction: str) -> str:
        items = self._data["presets"].get(direction, [])
        aid = self._data["active"].get(direction)
        if any(p["id"] == aid for p in items):
            return aid
        return items[0]["id"] if items else ""

    def active_name(self, direction: str) -> str:
        aid = self.active_id(direction)
        for p in self._data["presets"].get(direction, []):
            if p["id"] == aid:
                return p["name"]
        return ""

    def words(self, direction: str, limit: int = 40) -> list[str]:
        """当前预设的热词，截断到引擎能接受的条数。"""
        aid = self.active_id(direction)
        for p in self._data["presets"].get(direction, []):
            if p["id"] == aid:
                return p["words"][:limit]
        return []

    def get(self, preset_id: str) -> tuple[str, dict] | None:
        for direction in DIRECTIONS:
            for p in self._data["presets"].get(direction, []):
                if p["id"] == preset_id:
                    return direction, p
        return None

    # ------------------------------------------------------------------ 写
    def create(self, direction: str, name: str) -> dict:
        name = (name or "").strip() or "未命名"
        preset = {"id": uuid.uuid4().hex[:10], "name": name, "words": []}
        self._data["presets"].setdefault(direction, []).append(preset)
        self._data["active"][direction] = preset["id"]
        self._save()
        log.info("新建预设 [%s] %s", direction, name)
        return preset

    def rename(self, preset_id: str, name: str) -> bool:
        found = self.get(preset_id)
        if not found:
            return False
        _, preset = found
        preset["name"] = (name or "").strip() or preset["name"]
        self._save()
        return True

    def delete(self, preset_id: str) -> bool:
        found = self.get(preset_id)
        if not found:
            return False
        direction = found[0]
        items = self._data["presets"][direction]
        if len(items) <= 1:
            return False          # 至少留一个，否则下拉框会空掉
        self._data["presets"][direction] = [p for p in items if p["id"] != preset_id]
        if self._data["active"].get(direction) == preset_id:
            self._data["active"][direction] = self._data["presets"][direction][0]["id"]
        self._save()
        log.info("删除预设 %s", preset_id)
        return True

    def activate(self, preset_id: str) -> bool:
        found = self.get(preset_id)
        if not found:
            return False
        self._data["active"][found[0]] = preset_id
        self._save()
        return True

    def add_words(self, preset_id: str, words: list[str]) -> list[str]:
        found = self.get(preset_id)
        if not found:
            return []
        _, preset = found
        added = []
        for w in words:
            w = (w or "").strip()
            if len(w) >= 2 and w not in preset["words"]:
                preset["words"].append(w)
                added.append(w)
        if added:
            self._save()
        return added

    def remove_words(self, preset_id: str, words: list[str]) -> list[str]:
        found = self.get(preset_id)
        if not found:
            return []
        _, preset = found
        removed = [w for w in words if w in preset["words"]]
        if removed:
            preset["words"] = [w for w in preset["words"] if w not in removed]
            self._save()
        return removed

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                log.info("载入预设：中文→EN %d 个，EN→中文 %d 个",
                         len(self._data["presets"].get("zh2en", [])),
                         len(self._data["presets"].get("en2zh", [])))
                return
            except Exception:
                log.warning("预设文件损坏，改用默认", exc_info=True)
        self._seed()

    def _seed(self) -> None:
        """首次运行：为两个方向各建一个「中医」预设。"""
        zh = [e["zh"] for e in self._glossary.entries if len(e["zh"]) > 1]
        en = [e["en"] for e in self._glossary.entries]
        self._data = {
            "version": 1,
            "active": {},
            "presets": {
                "zh2en": [{"id": "tcm-zh", "name": "中医", "words": zh}],
                "en2zh": [{"id": "tcm-en", "name": "TCM", "words": en}],
            },
        }
        self._data["active"] = {"zh2en": "tcm-zh", "en2zh": "tcm-en"}
        self._save()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            log.warning("预设保存失败", exc_info=True)
