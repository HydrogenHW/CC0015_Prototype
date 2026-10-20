"""Render the glossary as a human-review sheet grouped by category."""
import json
from collections import OrderedDict

CAT_ZH = OrderedDict([
    ("theory", "基础理论"), ("substance", "精气血津液神"), ("organ", "脏腑"),
    ("meridian", "经络"), ("pathology", "病因病机"), ("diagnosis", "四诊八纲"),
    ("pattern", "证型"), ("treatment", "治法"), ("formula", "方剂"),
    ("acupoint", "穴位"), ("general", "一般用语"),
])

g = json.load(open("data/glossary.json", encoding="utf-8"))
by = OrderedDict((k, []) for k in CAT_ZH)
for e in g:
    by.setdefault(e["category"], []).append(e)

tot = len(g)
hit = sum(1 for e in g if e["who_hit"])
lines = [
    "# 中医核心术语表（待人工复核）",
    "",
    f"- 条目数：**{tot}**",
    f"- 在 WHO ISTTM 2007 英文全文中直接命中：**{hit}**（{hit/tot*100:.1f}%）",
    "- 未命中 ≠ 错误：WHO 常把术语拆写在定义里，或不收录该组合。未命中项是**人工复核的靶子**。",
    "- 复核方法：逐条读「英文」一列，判断它是不是该中文词在国际文献里的标准译法；"
    "可疑的标 ❌ 并写下更好的译法。",
    "",
]

for cat, items in by.items():
    if not items:
        continue
    lines.append(f"## {CAT_ZH.get(cat, cat)}（{len(items)} 条）")
    lines.append("")
    lines.append("| 中文 | 英文 | WHO 命中 | 复核 |")
    lines.append("|---|---|:-:|:-:|")
    for e in items:
        mark = "✓" if e["who_hit"] else "—"
        lines.append(f"| {e['zh']} | {e['en']} | {mark} |  |")
    lines.append("")

lines += [
    "## 已知需要决策的地方",
    "",
    "1. **七情**：WHO 2007 用 joy / anger / **thought** / **anxiety** / **sorrow** / fear / fright；"
    "通行教材（Wiseman 体系）用 joy / anger / **pensiveness** / **worry** / **grief**。"
    "现在表里取的是 WHO 用法。若要更贴近学生教材，需改回通行译法。",
    "2. **三焦**：WHO 2007 作 **triple energizer**；2009 针灸标准与多数教材作 **sanjiao**。已取 WHO。",
    "3. **十二正经**：WHO 在正文中只写 `lung meridian` 这种简式，本表保留 "
    "`Hand-Taiyin Lung Meridian` 全称（信息更全，但不在 WHO 命中）。",
    "4. **穴位**：格式为 `Hegu (LI4)`，WHO 原文作 `hegu (LI4)` 小写，仅大小写差异。",
    "",
    "## 下一步",
    "",
    "- [ ] 组员按分类认领，逐条复核，把 ❌ 改掉",
    "- [ ] 用 interviewee 真实课堂录音补 20–50 条本表没有的词",
    "- [ ] 定稿后锁版本，作为翻译提示词里的术语约束",
]
open("notes/glossary_review.md", "w", encoding="utf-8").write("\n".join(lines))
print(f"[ok] {tot} terms, {hit} WHO hits -> notes/glossary_review.md")
for e in g[:3]:
    print("  sample:", e)
