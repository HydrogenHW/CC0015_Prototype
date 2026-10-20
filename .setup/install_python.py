"""无管理员权限安装 Python。

Windows 的官方 exe 安装器要走 Windows Installer，即使 InstallAllUsers=0
也会因缺少提权而返回 0x80070005。NuGet 上的官方 python 包是完整发行版
（含 pip、venv、标准库），解压即用，不需要安装、不需要注册表写入、
不需要管理员。

目标目录：%LocalAppData%\\Programs\\Python\\Python313
其中 tools\\ 下就是完整的 Python 根目录。
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import winreg
import zipfile
from pathlib import Path

VERSION = "3.13.16"
URL = f"https://www.nuget.org/api/v2/package/python/{VERSION}"
TARGET = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Python" / "Python313"
SETUP = Path(__file__).resolve().parent
NUPKG = SETUP / f"python-{VERSION}.nupkg"


def download() -> None:
    if NUPKG.exists() and NUPKG.stat().st_size > 1_000_000:
        print(f"[1/5] 已有安装包 {NUPKG.name}")
        return
    print(f"[1/5] 下载 {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(NUPKG, "wb") as f:
        shutil.copyfileobj(r, f)
    print(f"      {NUPKG.stat().st_size / 1e6:.1f} MB")


def extract() -> None:
    print(f"[2/5] 解压到 {TARGET}")
    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(NUPKG) as z:
        z.extractall(TARGET)
    # nuget 包把文件放在 tools/ 下，提到根目录
    tools = TARGET / "tools"
    if tools.is_dir():
        for item in list(tools.iterdir()):
            dest = TARGET / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        tools.rmdir()
    if not (TARGET / "python.exe").exists():
        raise SystemExit("解压后找不到 python.exe，结构不符合预期")


def add_to_path() -> None:
    print("[3/5] 写入用户 PATH")
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    )
    try:
        cur, kind = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        cur, kind = "", winreg.REG_EXPAND_SZ
    parts = [p for p in cur.split(";") if p]
    if str(TARGET) not in parts:
        parts.append(str(TARGET))
        winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts))
    winreg.CloseKey(key)
    # 广播环境变化，让新开的窗口立刻生效
    try:
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x1A, 0, "Environment", 0x2, 3000, None
        )
    except Exception:
        pass


def verify() -> bool:
    print("[4/5] 验证")
    py = TARGET / "python.exe"
    ok = True
    for args in (["--version"], ["-m", "pip", "--version"], ["-m", "venv", "--help"]):
        r = subprocess.run([str(py), *args], capture_output=True, text=True)
        first = (r.stdout or r.stderr).strip().splitlines()
        line = first[0] if first else ""
        print(f"      python {' '.join(args):22} -> {line[:70]}")
        if r.returncode != 0:
            ok = False
    return ok


def main() -> int:
    download()
    extract()
    add_to_path()
    ok = verify()
    if ok:
        print(f"\n[5/5] 完成：{TARGET}")
        print("      新开一个命令行窗口后，python 命令即可使用。")
        return 0
    print("\n[!] 验证未通过，见上面的输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
