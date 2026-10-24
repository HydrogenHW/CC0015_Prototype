"""打一个可分发的 release 包。

release 包只装「运行需要的东西」：应用代码、术语表、启动脚本、说明文档。
开发用的 docs / notes / tools、用户本机的配置和密钥、以及 2MB 的原始
PDF 都不进去。

除了按名单排除，还会扫一遍内容：任何文件里出现像密钥的串就中止打包。
排除名单可能漏，内容扫描不会——这是最后一道闸。
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"
OUT_DIR = ROOT / "dist"
OUT = OUT_DIR / f"LiveCaptions-{VERSION}.zip"

# 整棵跳过的目录
EXCLUDE_DIRS = {
    ".venv", ".git", "logs", ".tmp", "dist", "__pycache__",
    "data/raw",      # 2MB 原始 PDF，只是术语表的来源，运行用不上
    "docs",          # 实现文档，开发用
    "notes",         # 术语核查记录，开发用
    "tools",         # 维护脚本，开发用
}

# 单个文件跳过
EXCLUDE_FILES = {
    ".env",                 # 可能有密钥
    ".env.example",         # 密钥现在在设置界面填，这个模板没用了
    ".gitignore",           # 使用者不提交代码
    "keys.txt",
    "data/settings.json",   # 用户设置，含密钥
    "data/presets.json",    # 用户热词组，首次运行会自动重建
}

# 像密钥的东西：OpenAI / DeepSeek 的 sk-、40 位十六进制
SUSPECT = re.compile(r"sk-[A-Za-z0-9_\-]{20,}|\b[a-f0-9]{40}\b")
SCAN_SUFFIX = {".py", ".md", ".json", ".txt", ".bat", ".ps1", ".js", ".html", ".css"}

# 包里必须有的东西，缺了说明打包逻辑漏了
REQUIRED = {
    "run.bat", "setup_python.ps1", "requirements.txt",
    "app/server.py", "app/static/index.html", "data/glossary.json", "README.md",
}


def collect() -> tuple[list[Path], list[tuple[Path, str]]]:
    keep: list[Path] = []
    leaks: list[tuple[Path, str]] = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(ROOT)
        rel_str = rel.as_posix()   # 统一成 /，否则跟名单里的 data/raw 对不上
        if any(rel_str == d or rel_str.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        if rel_str in EXCLUDE_FILES or rel.name in EXCLUDE_FILES or p.suffix == ".pyc":
            continue
        keep.append(rel)

        if p.suffix.lower() in SCAN_SUFFIX:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = SUSPECT.search(text)
            if m:
                leaks.append((rel, f"疑似密钥（{m.group(0)[:4]}…，长度 {len(m.group(0))}）"))
    return keep, leaks


def main() -> int:
    files, leaks = collect()

    if leaks:
        print("!! 中止打包：以下文件里发现疑似密钥")
        for rel, why in leaks:
            print(f"   {rel}  —— {why}")
        print("\n把这些内容移出项目（或用环境变量），再重新打包。")
        return 1

    names = {rel.as_posix() for rel in files}
    missing = sorted(REQUIRED - names)
    if missing:
        print("!! 中止打包：缺少运行必需的文件")
        for m in missing:
            print(f"   {m}")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            # 统一放进一个顶层目录，解压后不会散落一地
            z.write(ROOT / rel, Path(f"LiveCaptions-{VERSION}") / rel)

    size = OUT.stat().st_size / 1024
    print(f"已生成：{OUT}")
    print(f"  {len(files)} 个文件，{size:.0f} KB\n")
    print("包内：")
    for rel in sorted(files, key=lambda x: x.as_posix()):
        print(f"  LiveCaptions-{VERSION}/{rel.as_posix()}")
    print("\n不含：密钥 / 用户设置 / 热词组 / .venv / logs / docs / notes / tools / data/raw")
    print("使用者解压后双击 run.bat 即可（缺 Python 会自动装便携版）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
