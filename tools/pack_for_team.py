"""打一个可分发的 release 包。

release 包只装「运行需要的东西」：应用代码、术语表、启动脚本、说明文档。
开发用的 docs / notes / tools、用户本机的配置和密钥、以及 2MB 的原始
PDF 都不进去。

除了按名单排除，还会扫一遍内容：任何文件里出现像密钥的串就中止打包。
排除名单可能漏，内容扫描不会——这是最后一道闸。
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.1"
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
    "data/settings.json",       # 用户设置，含密钥
    "data/user_presets.json",   # 用户自建的预设
    "data/presets_state.json",  # 当前选中项
}

# 像密钥的东西：OpenAI / DeepSeek 的 sk-、40 位十六进制
SUSPECT = re.compile(r"sk-[A-Za-z0-9_\-]{20,}|\b[a-f0-9]{40}\b")
SCAN_SUFFIX = {".py", ".md", ".json", ".txt", ".bat", ".ps1", ".js", ".html", ".css"}

# 包里必须有的东西，缺了说明打包逻辑漏了
REQUIRED = {
    "run.bat", "setup_python.ps1", "requirements.txt",
    "app/server.py", "app/static/index.html", "data/presets/00-tcm.json", "README.md",
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def self_check(zip_path: Path) -> list[str]:
    """把刚打好的包解压到临时目录，用当前解释器真跑一遍。

    为什么要真起一次：`py_compile` / `compileall` 只查语法，抓不到运行期的
    `NameError`——1.0.0 就是这么发出去的：包能打、能编译，一开麦就崩。
    这里走三步：编译整棵 app/ → 导入 app.server → MOCK 模式起服务连 /health。
    """
    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="lc-packcheck-"))
    env = {**os.environ, "MOCK": "1", "PYTHONUTF8": "1"}
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        root = tmp / f"LiveCaptions-{VERSION}"

        # 1) 语法：整棵 app/ 编一遍
        comp = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(root / "app")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if comp.returncode != 0:
            problems.append("编译失败：\n" + (comp.stdout + comp.stderr).strip()[-2000:])
            return problems

        # 2) 导入：模块级代码（日志初始化、术语表加载）能不能跑完
        imp = subprocess.run(
            [sys.executable, "-c", "import app.server"],
            cwd=root, env=env, timeout=90,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if imp.returncode != 0:
            problems.append("导入失败：\n" + (imp.stderr or imp.stdout).strip()[-2000:])
            return problems

        # 3) 起服务 + 连 /health：确认端口能听、健康检查能应答
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.server:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        healthy = False
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=2
                    ) as r:
                        if r.status == 200:
                            healthy = True
                            break
                except Exception:
                    time.sleep(0.4)
        finally:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
        if not healthy:
            log = out.decode("utf-8", "replace").strip()[-2000:]
            problems.append("MOCK 模式起服务没成功（/health 无应答）：\n" + log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


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

    print("\n自检：解压 → 编译 → 导入 → MOCK 起服务连 /health …")
    problems = self_check(OUT)
    if problems:
        print("!! 自检没过，这个包不能发：\n")
        for why in problems:
            print(why)
        OUT.unlink(missing_ok=True)
        print(f"\n已删除 {OUT.name}。修好再打一次，别上传半成品。")
        return 2
    print("自检通过：编译、导入、MOCK 起服务 + /health 都正常。")

    print("\n使用者解压后双击 run.bat 即可（缺 Python 会自动装便携版）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
