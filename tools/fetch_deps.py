"""把依赖 wheel 直接下下来解压到 vendor/，绕开 pip 的临时目录问题。

只用于本机验证跑得起来；正式使用时用户按 requirements.txt 正常 pip install。
"""
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename

VENDOR = Path("vendor")
TMP = Path(".tmp")
ROOTS = ["fastapi", "uvicorn", "websockets", "python-dotenv"]
UA = {"User-Agent": "Mozilla/5.0"}


def pick_wheel(name: str) -> tuple[str, str] | None:
    url = f"https://pypi.org/pypi/{name}/json"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        meta = json.load(r)
    valid = set(sys_tags())
    best = None
    for fname, files in meta["releases"].items():
        for f in files:
            if not f["filename"].endswith(".whl"):
                continue
            try:
                _, ver, _, tags = parse_wheel_filename(f["filename"])
            except Exception:
                continue
            if not (tags & valid):
                continue
            if ver.is_prerelease:
                continue
            if best is None or ver > best[0]:
                best = (ver, f["url"], f["filename"], f.get("digests", {}).get("sha256"))
    return best[1:] if best else None


def deps_of(url: str) -> list[str]:
    """从 wheel 的 METADATA 里读 Requires-Dist。"""
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        data = r.read()
    TMP.mkdir(exist_ok=True)
    path = TMP / "probe.whl"
    path.write_bytes(data)
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                for line in z.read(n).decode("utf-8", "replace").splitlines():
                    if line.startswith("Requires-Dist:"):
                        out.append(line.split(":", 1)[1].strip())
                break
    return out


def install(name: str) -> None:
    got = pick_wheel(name)
    if not got:
        print(f"  !! 没有可用的 wheel: {name}")
        return
    url, fname = got[0], got[1]
    if (VENDOR / canonicalize_name(name).replace("-", "_")).exists():
        return
    print(f"  - {name:22} {fname}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = r.read()
    TMP.mkdir(exist_ok=True)
    whl = TMP / fname
    whl.write_bytes(data)
    VENDOR.mkdir(exist_ok=True)
    with zipfile.ZipFile(whl) as z:
        z.extractall(VENDOR)
    whl.unlink(missing_ok=True)


def main() -> None:
    queue = list(ROOTS)
    seen: set[str] = set()
    while queue:
        name = queue.pop(0)
        key = canonicalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        print(f"[{len(seen):2}] {key}")
        try:
            install(key)
            got = pick_wheel(key)
            if not got:
                continue
            for spec in deps_of(got[0]):
                try:
                    req = Requirement(spec)
                except Exception:
                    continue
                if req.marker and req.marker.evaluate({"extra": ""}):
                    continue
                elif req.marker and not req.marker.evaluate({"extra": ""}):
                    continue
                queue.append(req.name)
        except Exception as exc:
            print(f"  !! {key}: {type(exc).__name__}: {exc}")

    print(f"\n完成：{len(seen)} 个包 -> {VENDOR}/")


if __name__ == "__main__":
    main()
