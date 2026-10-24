"""热词预设：可命名、可切换的热词组。

一个预设就是一组词，中英混在一起也没关系——它代表的是「某个领域的
术语」，不是「某个语言方向的术语」。中医这个预设里既有「肝阳上亢」
也有 liver yang hyperactivity。

真正用的时候按当前方向筛一遍：中文识别只把中文词喂给引擎，
英文识别只喂英文词。所以切换语言时预设列表不该变，变的只是取词。

（早期版本按方向存了两套预设，用户新建的词在另一个方向看不到，
那个设计是错的，这里已经改掉并带迁移。）
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from .glossary import Glossary

log = logging.getLogger("presets")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


class PresetStore:
    def __init__(self, path: Path, glossary: Glossary):
        self._path = path
        self._glossary = glossary
        self._data: dict = {"version": 2, "active": "", "presets": []}
        self._load()

    # ------------------------------------------------------------------ 读
    def list(self) -> list[dict]:
        return [
            {"id": p["id"], "name": p["name"], "count": len(p["words"])}
            for p in self._data["presets"]
        ]

    def active_id(self) -> str:
        aid = self._data.get("active", "")
        if any(p["id"] == aid for p in self._data["presets"]):
            return aid
        return self._data["presets"][0]["id"] if self._data["presets"] else ""

    def active_name(self) -> str:
        for p in self._data["presets"]:
            if p["id"] == self.active_id():
                return p["name"]
        return ""

    def words_for(self, direction: str, limit: int = 40) -> list[str]:
        """当前预设里、适合这个方向的词。

        中文识别拿含汉字的，英文识别拿不含汉字的。这样一份预设两边都能用。
        """
        preset = self._active()
        if not preset:
            return []
        want_cjk = direction.startswith("zh")
        out = [w for w in preset["words"] if _has_cjk(w) == want_cjk]
        return out[:limit]

    def get(self, preset_id: str) -> dict | None:
        for p in self._data["presets"]:
            if p["id"] == preset_id:
                return p
        return None

    # ------------------------------------------------------------------ 写
    def create(self, name: str, words: list[str] | None = None) -> dict:
        name = (name or "").strip() or "未命名"
        preset = {"id": uuid.uuid4().hex[:10], "name": name, "words": list(words or [])}
        self._data["presets"].append(preset)
        self._data["active"] = preset["id"]
        self._save()
        log.info("新建预设 %s", name)
        return preset

    def rename(self, preset_id: str, name: str) -> bool:
        preset = self.get(preset_id)
        if not preset:
            return False
        preset["name"] = (name or "").strip() or preset["name"]
        self._save()
        return True

    def delete(self, preset_id: str) -> bool:
        if not self.get(preset_id):
            return False
        if len(self._data["presets"]) <= 1:
            return False          # 至少留一个，否则下拉框会空掉
        self._data["presets"] = [p for p in self._data["presets"] if p["id"] != preset_id]
        if self._data.get("active") == preset_id:
            self._data["active"] = self._data["presets"][0]["id"]
        self._save()
        log.info("删除预设 %s", preset_id)
        return True

    def activate(self, preset_id: str) -> bool:
        if not self.get(preset_id):
            return False
        self._data["active"] = preset_id
        self._save()
        return True

    def add_words(self, preset_id: str, words: list[str]) -> list[str]:
        preset = self.get(preset_id)
        if not preset:
            return []
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
        preset = self.get(preset_id)
        if not preset:
            return []
        removed = [w for w in words if w in preset["words"]]
        if removed:
            preset["words"] = [w for w in preset["words"] if w not in removed]
            self._save()
        return removed

    # ------------------------------------------------------------------ 持久化
    def _active(self) -> dict | None:
        return self.get(self.active_id())

    def _load(self) -> None:
        if not self._path.exists():
            self._seed()
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("预设文件损坏，改用默认", exc_info=True)
            self._seed()
            return

        if data.get("version") == 2 and isinstance(data.get("presets"), list):
            self._data = data
            log.info("载入预设 %d 个", len(data["presets"]))
            self._ensure_builtin()
            return

        self._migrate(data)

    def _migrate(self, old: dict) -> None:
        """把按方向存的两套旧预设合并成一套。"""
        merged: list[dict] = []
        index: dict[str, dict] = {}
        for direction in ("zh2en", "en2zh"):
            for p in (old.get("presets") or {}).get(direction, []):
                name = p.get("name") or "未命名"
                # 「中医」和「TCM」是同一领域，合并成一个
                key = "tcm" if name.lower() in ("中医", "tcm", "中医 / tcm") else name
                target = index.get(key)
                if target is None:
                    target = {"id": "tcm" if key == "tcm" else (p.get("id") or uuid.uuid4().hex[:10]),
                              "name": "中医 / TCM" if key == "tcm" else name, "words": []}
                    index[key] = target
                    merged.append(target)
                for w in p.get("words") or []:
                    if w not in target["words"]:
                        target["words"].append(w)

        if not merged:
            self._seed()
            return

        active_old = (old.get("active") or {}).get("zh2en", "")
        active = next((p["id"] for p in merged if p["id"] == active_old), merged[0]["id"])
        self._data = {"version": 2, "active": active, "presets": merged}
        self._save()
        log.info("旧格式预设已合并为 %d 个（双向共用）", len(merged))
        self._ensure_builtin()

    def _seed(self) -> None:
        from .builtin_presets import BUILTIN

        presets = []
        for item in BUILTIN:
            if item["id"] == "tcm":
                continue    # 中医由 _tcm_words 单独生成
            words = list(dict.fromkeys(item["zh"] + item["en"]))
            presets.append({"id": item["id"], "name": item["name"], "words": words})
        presets.insert(0, {"id": "tcm", "name": "中医 / TCM", "words": self._tcm_words()})
        self._data = {"version": 2, "active": "tcm", "presets": presets}
        self._save()
        log.info("初始化 %d 个内置预设", len(presets))

    def _tcm_words(self) -> list[str]:
        zh = [e["zh"] for e in self._glossary.entries if len(e["zh"]) > 1]
        en = [e["en"] for e in self._glossary.entries]
        return list(dict.fromkeys(zh + en))

    def _ensure_builtin(self) -> None:
        """老用户的 presets.json 里可能还没有新增的学科预设，补齐。"""
        from .builtin_presets import BUILTIN

        have = {p["id"] for p in self._data["presets"]}
        added = 0
        for item in BUILTIN:
            if item["id"] in have:
                continue
            words = self._tcm_words() if item["id"] == "tcm" else list(
                dict.fromkeys(item["zh"] + item["en"])
            )
            self._data["presets"].append(
                {"id": item["id"], "name": item["name"], "words": words}
            )
            added += 1
        if added:
            self._save()
            log.info("补充内置预设 %d 个", added)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            log.warning("预设保存失败", exc_info=True)
