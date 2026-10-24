"""热词预设：一个学科一个 JSON 文件。

目录结构：
  data/presets/            内置预设，随发布分发，一个学科一个文件
  data/user_presets.json   用户自己建的（本机数据，不进版本库）
  data/presets_state.json  当前选中了哪个

一个预设就是一组词，中英混在一起也没关系——它代表的是「某个领域的
术语」，不是「某个语言方向的术语」。中医这个预设里既有「肝阳上亢」
也有 liver yang hyperactivity。真正用的时候按当前方向筛一遍。

内置预设只读（可以切换，不能改名删除）；用户自己建的可以随便改。
新增一个学科只要往 data/presets/ 里丢一个 json，不用动代码。
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

log = logging.getLogger("presets")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


class PresetStore:
    def __init__(self, builtin_dir: Path, user_path: Path, state_path: Path):
        self._builtin_dir = builtin_dir
        self._user_path = user_path
        self._state_path = state_path
        self._user: dict = {"presets": []}
        self._active = ""
        self._load_user()
        self._load_state()

    # ------------------------------------------------------------------ 读
    def _builtin(self) -> list[dict]:
        out = []
        if not self._builtin_dir.is_dir():
            return out
        for f in sorted(self._builtin_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                log.warning("预设文件损坏，跳过：%s", f.name, exc_info=True)
                continue
            if not d.get("id") or not d.get("name"):
                continue
            out.append({"id": d["id"], "name": d["name"],
                        "words": list(d.get("words") or []), "builtin": True})
        return out

    def all(self) -> list[dict]:
        builtin = self._builtin()
        used = {p["id"] for p in builtin}
        extra = [p for p in self._user.get("presets", []) if p["id"] not in used]
        return builtin + extra

    def list(self) -> list[dict]:
        return [{"id": p["id"], "name": p["name"], "count": len(p["words"]),
                 "builtin": p.get("builtin", False)} for p in self.all()]

    def get(self, preset_id: str) -> dict | None:
        for p in self.all():
            if p["id"] == preset_id:
                return p
        return None

    def active_id(self) -> str:
        items = self.all()
        if any(p["id"] == self._active for p in items):
            return self._active
        return items[0]["id"] if items else ""

    def active_name(self) -> str:
        p = self.get(self.active_id())
        return p["name"] if p else ""

    def words_for(self, direction: str, limit: int = 40) -> list[str]:
        """当前预设里、适合这个方向的词。中文识别拿含汉字的，英文拿不带的。"""
        preset = self.get(self.active_id())
        if not preset:
            return []
        want_cjk = direction.startswith("zh")
        out = [w for w in preset["words"] if _has_cjk(w) == want_cjk]
        return out[:limit]

    # ------------------------------------------------------------------ 写
    def create(self, name: str) -> dict:
        name = (name or "").strip() or "未命名"
        preset = {"id": uuid.uuid4().hex[:10], "name": name, "words": []}
        self._user.setdefault("presets", []).append(preset)
        self._active = preset["id"]
        self._save_user()
        self._save_state()
        log.info("新建预设 %s", name)
        return preset

    def rename(self, preset_id: str, name: str) -> bool:
        for p in self._user.get("presets", []):
            if p["id"] == preset_id:
                p["name"] = (name or "").strip() or p["name"]
                self._save_user()
                return True
        return False          # 内置预设不允许改名

    def delete(self, preset_id: str) -> bool:
        items = self._user.get("presets", [])
        if not any(p["id"] == preset_id for p in items):
            return False      # 内置不能删
        self._user["presets"] = [p for p in items if p["id"] != preset_id]
        if self._active == preset_id:
            self._active = self.active_id() or ""
        self._save_user()
        self._save_state()
        log.info("删除预设 %s", preset_id)
        return True

    def activate(self, preset_id: str) -> bool:
        if not self.get(preset_id):
            return False
        self._active = preset_id
        self._save_state()
        return True

    def add_words(self, preset_id: str, words: list[str]) -> list[str]:
        for p in self._user.get("presets", []):
            if p["id"] != preset_id:
                continue
            added = []
            for w in words:
                w = (w or "").strip()
                if len(w) >= 2 and w not in p["words"]:
                    p["words"].append(w)
                    added.append(w)
            if added:
                self._save_user()
            return added
        return []             # 内置预设不接收新词

    def remove_words(self, preset_id: str, words: list[str]) -> list[str]:
        for p in self._user.get("presets", []):
            if p["id"] != preset_id:
                continue
            removed = [w for w in words if w in p["words"]]
            if removed:
                p["words"] = [w for w in p["words"] if w not in removed]
                self._save_user()
            return removed
        return []

    # ------------------------------------------------------------------ 持久化
    def _load_user(self) -> None:
        if not self._user_path.exists():
            return
        try:
            self._user = json.loads(self._user_path.read_text(encoding="utf-8"))
            self._user.setdefault("presets", [])
            log.info("载入自定义预设 %d 个", len(self._user["presets"]))
        except Exception:
            log.warning("自定义预设文件损坏，已忽略", exc_info=True)

    def _save_user(self) -> None:
        try:
            self._user_path.parent.mkdir(parents=True, exist_ok=True)
            self._user_path.write_text(
                json.dumps(self._user, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            log.warning("自定义预设保存失败", exc_info=True)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            self._active = json.loads(self._state_path.read_text(encoding="utf-8")).get("active", "")
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"active": self._active}, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            log.warning("预设状态保存失败", exc_info=True)
