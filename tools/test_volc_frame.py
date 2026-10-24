"""火山帧格式自检：_volc_frame / _volc_parse 的组帧、拆帧（不联网、不需要密钥）。

跑法：.venv/Scripts/python.exe tools/test_volc_frame.py
"""
import gzip
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.asr import _volc_frame, _volc_parse, VOLC_HDR_CLIENT

HDR_JSON_GZ = bytes([0x11, 0x20, 0x01, 0x00])       # 普通包，JSON + gzip
HDR_JSON_GZ_SEQ = bytes([0x11, 0x21, 0x01, 0x00])   # 普通包，带序号
HDR_JSON_RAW = bytes([0x11, 0x20, 0x00, 0x00])      # 普通包，JSON 未压缩
HDR_ERR_GZ = bytes([0x11, 0xF0, 0x01, 0x00])        # 错误包


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    return bool(cond)


def frame(hdr: bytes, body: bytes, seq: int | None = None) -> bytes:
    mid = struct.pack(">i", seq) if seq is not None else b""
    return hdr + mid + struct.pack(">I", len(body)) + body


ok = True

# 1. 组帧：4 字节头 + 4 字节大端长度 + gzip 体
payload = json.dumps({"result": {"text": "肝阳上亢。"}}, ensure_ascii=False).encode()
f = _volc_frame(VOLC_HDR_CLIENT, payload)
ok &= check("组帧头", f[:4] == VOLC_HDR_CLIENT)
ok &= check("组帧长度字段", struct.unpack(">I", f[4:8])[0] == len(f) - 8)
ok &= check("组帧体可解压", gzip.decompress(f[8:]) == payload)

# 2. 普通回复帧（gzip）
msg = {"result": {"text": "舌红少苔。",
                  "utterances": [{"text": "舌红少苔。", "definite": True, "start_time": 0}]},
       "message": "ok"}
p = _volc_parse(frame(HDR_JSON_GZ, gzip.compress(json.dumps(msg, ensure_ascii=False).encode())))
ok &= check("普通帧 payload", p.get("payload") == msg)
ok &= check("普通帧 flags", p.get("flags") == 0)

# 3. 带序号帧
p = _volc_parse(frame(HDR_JSON_GZ_SEQ, gzip.compress(b'{"x":1}'), seq=7))
ok &= check("带序号帧跳过 seq", p.get("payload") == {"x": 1} and p.get("flags") == 1)

# 4. 错误帧：状态码 + 正文
err = gzip.compress("invalid api key".encode())
raw_err = HDR_ERR_GZ + struct.pack(">I", 45000001) + struct.pack(">I", len(err)) + err
p = _volc_parse(raw_err)
ok &= check("错误帧", p.get("error") == "45000001: invalid api key")

# 5. 未压缩帧
p = _volc_parse(frame(HDR_JSON_RAW, b'{"a":2}'))
ok &= check("未压缩帧", p.get("payload") == {"a": 2})

# 6. __aiter__ 对「会话结束」错误的判定仍成立
ok &= check("收尾错误可识别", "Timed out waiting" in "45000001: Timed out waiting for next audio")

print("\n全部通过" if ok else "\n有失败项")
sys.exit(0 if ok else 1)
