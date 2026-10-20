"""把项目打包成 zip 发给组员，自动排除密钥和本机产物。

除了按名单排除，还会扫一遍内容：任何文件里出现像密钥的串就中止打包。
排除名单可能漏，内容扫描不会——这是最后一道闸。
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist"
OUT = OUT_DIR / "CC0015-发给组员.zip"

# 目录整棵跳过
EXCLUDE_DIRS = {
    ".venv", ".git", "logs", ".setup", ".tmp", "dist",
    "__pycache__", "data/raw",      # data/raw 是 2MB 的原始 PDF，组员用不上
}
# 单个文件跳过
EXCLUDE_FILES = {".env", "keys.txt"}

# 像密钥的东西：OpenAI 的 sk-、Deepgram 的 40 位十六进制
SUSPECT = re.compile(r"sk-[A-Za-z0-9_\-]{20,}|\b[a-f0-9]{40}\b")
SCAN_SUFFIX = {".py", ".md", ".json", ".txt", ".bat", ".js", ".html", ".css", ".env", ".example"}


def collect() -> tuple[list[Path], list[tuple[Path, str]]]:
    keep: list[Path] = []
    leaks: list[tuple[Path, str]] = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(ROOT)
        # 统一成 / 再比，否则 Windows 的 \ 跟名单里的 data/raw 对不上
        rel_str = rel.as_posix()
        if any(rel_str == d or rel_str.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        if rel.name in EXCLUDE_FILES or p.suffix == ".pyc":
            continue
        keep.append(rel)

        if p.suffix.lower() in SCAN_SUFFIX:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = SUSPECT.search(text)
            if m:
                # 只报位置，不回显密钥本身
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

    OUT_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(ROOT / rel, rel)

    size = OUT.stat().st_size / 1e6
    print(f"已生成：{OUT}  （{len(files)} 个文件，{size:.1f} MB）")
    print("\n包含：")
    for rel in sorted(files):
        print(f"  {rel}")
    print("\n不含：.env / keys.txt / .venv / logs / data/raw")
    print("组员解压后：双击 run.bat，密钥需自己设置（见 .env 里的说明）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
