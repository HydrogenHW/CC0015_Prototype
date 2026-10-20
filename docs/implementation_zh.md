# 中医课堂实时字幕系统
## 实现文档 v1.0

---

## 1. 系统概览

一个跑在本机的 Web 应用。后端是 Python 服务，负责音频转发、语音识别和翻译；前端是一个单页，在浏览器里打开，负责采集麦克风并把双语字幕画出来。

```
浏览器 (localhost:8000)
┌─────────────────────────────────┐
│ getUserMedia → AudioWorklet     │  16 kHz PCM
│            │                    │ ─────────┐
│            ▼                    │          │
│        WebSocket ───────────────┼──────────┤
│            ▲                    │          │
│            │  字幕 JSON          │          │
│     双栏字幕渲染                 │ ◄────────┤
└─────────────────────────────────┘          │
                                             ▼
                              ┌──────────────────────────┐
                              │  FastAPI   /ws           │
                              │    ├─ asr.py     Deepgram│
                              │    ├─ segmenter.py       │
                              │    ├─ glossary.py 267 条 │
                              │    └─ translate.py GPT   │
                              └──────────────────────────┘
```

启动后打开 `http://127.0.0.1:8000`，点「开始」，浏览器请求麦克风权限，字幕从下一句开始滚动。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn | 原生支持 WebSocket，异步友好 |
| 流式语音识别 | Deepgram（WebSocket 接口） | 中英文均支持，首字延迟约 300 ms |
| 翻译 | OpenAI `gpt-4o-mini` | 可接受术语表约束，支持结构化输出 |
| 前端 | 原生 HTML/CSS/JS | 无框架、无构建步骤 |
| 术语表 | 本地 JSON | 267 条，11 类 |

依赖清单：

```
fastapi
uvicorn[standard]
websockets
openai
python-dotenv
```

---

## 3. 文件结构

```
app/
├── server.py            FastAPI 入口，WebSocket 端点，串联所有模块
├── asr.py               Deepgram 流式客户端
├── segmenter.py         语义分句
├── glossary.py          术语加载与匹配
├── translate.py         翻译与术语约束
├── config.py            环境变量读取
└── static/
    ├── index.html       页面骨架
    ├── app.js           采集、连接、渲染
    ├── pcm-worklet.js   AudioWorklet 处理器
    └── style.css        样式
data/
└── glossary.json        术语表
requirements.txt
.env                    密钥（不提交）
run.bat                 一键启动
```

---

## 4. 消息协议

前后端只有一条 WebSocket 连接，消息分两类。

**浏览器 → 后端**

| 类型 | 格式 | 说明 |
|---|---|---|
| 音频 | 二进制帧 | 16 kHz、单声道、16-bit 小端 PCM，每帧 100 ms |
| 控制 | `{"type":"lang","value":"zh"}` | 切换翻译方向，`zh` 为中→英，`en` 为英→中 |
| 控制 | `{"type":"stop"}` | 结束本次会话 |

**后端 → 浏览器**

| 类型 | 格式 | 用途 |
|---|---|---|
| `interim` | `{"type":"interim","text":"..."}` | 识别中的临时结果，灰色显示，覆盖刷新 |
| `final` | `{"type":"final","src":"...","dst":"..."}` | 定稿双语句子，追加到字幕区 |
| `error` | `{"type":"error","message":"..."}` | 前端弹提示，不中断流 |

用 `interim` 占位、`final` 落定，是让字幕"看起来是实时的"的关键：用户能立刻看到文字在长出来，而翻译稍后补上。

---

## 5. 各模块实现

### 5.1 `config.py`

从 `.env` 读取两个密钥，缺失时直接抛错退出，避免跑到一半才失败。

```python
import os
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.environ["DEEPGRAM_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

ASR_MODEL = "nova-2"
TRANSLATE_MODEL = "gpt-4o-mini"
SAMPLE_RATE = 16000
```

### 5.2 `server.py`

核心是一个 `/ws` 端点。每来一个连接，同时起两个任务：

- **上行任务**：把浏览器发来的 PCM 原样转发给 Deepgram；
- **下行任务**：接收 Deepgram 的识别结果，interim 直接回推，final 则送去分句、翻译，再把双语结果回推。

两个任务用 `asyncio.gather` 并发，任一结束就收尾。

```python
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    dg = await DeepgramStream.connect(lang="en-US")
    try:
        await asyncio.gather(
            pump_upstream(ws, dg),      # 浏览器 → Deepgram
            pump_downstream(ws, dg),    # Deepgram → 浏览器（含翻译）
        )
    finally:
        await dg.close()
```

上行转发时注意：WebSocket 收到的二进制是 `bytes`，直接 `await dg.send(data)` 即可，不做解码——转换交给前面的前端。

### 5.3 `asr.py`

用 `websockets` 连 Deepgram，参数决定识别质量：

```python
URL = (
    "wss://api.deepgram.com/v1/listen"
    "?encoding=linear16"
    "&sample_rate=16000"
    "&channels=1"
    "&model=nova-2"
    f"&language={lang}"
    "&interim_results=true"
    "&endpointing=300"
    "&smart_format=true"
    "&punctuate=true"
)
HEADERS = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
```

几个参数值得说明：

- `endpointing=300`：静音 300 ms 判定一句话结束。太小会把词切碎，太大则字幕出得迟。
- `smart_format=true`：自动处理数字、标点，中医课上有大量数字（三、五、十二）和方剂剂量。
- `punctuate=true`：中文标点对分句很关键。

返回的消息形如：

```json
{"channel":{"alternatives":[{"transcript":"肝阳上亢","confidence":0.94}]},
 "is_final":false,"speech_final":false}
```

取 `transcript`，按 `is_final` 分流。

### 5.4 `segmenter.py`

Deepgram 的 final 往往是半句。直接送翻译会切断语义，中文语序尤其容易乱。因此加一层缓冲：

```python
class Segmenter:
    def __init__(self, max_wait=1.2, max_len=60):
        self.buf = ""
        self.since = time.monotonic()

    def feed(self, text):
        self.buf += text
        if self._complete() or self._too_long():
            out, self.buf = self.buf, ""
            return out
        return None

    def _complete(self):
        return self.buf.rstrip()[-1:] in "。！？.!?"

    def _too_long(self):
        return len(self.buf) >= self.max_len
```

两条触发条件：句末标点出现，或缓冲超过 60 字符。后者是保底——老师连讲不断句时，不能让字幕一直不出。

### 5.5 `glossary.py`

术语表在启动时载入，建好两个方向的索引，之后每次翻译只查命中的词，不遍历全表。

```python
class Glossary:
    def __init__(self, path, max_hits=8):
        raw = json.load(open(path, encoding="utf-8"))
        self._zh2en = {e["zh"]: e["en"] for e in raw}
        self._en2zh = {}
        for e in raw:
            self._en2zh.setdefault(e["en"].lower(), e["zh"])
        # 单字中文术语不参与匹配（理由见下）
        self._zh_keys = sorted((k for k in self._zh2en if len(k) > 1),
                               key=len, reverse=True)
        self._en_keys = sorted(self._en2zh, key=len, reverse=True)

    def match(self, text, direction="zh2en"):
        spans = self._spans_zh(text) if direction == "zh2en" else self._spans_en(text)
        spans.sort(key=lambda s: s[0])
        table = self._zh2en if direction == "zh2en" else self._en2zh
        return [(k, table[k]) for _, _, k in spans[: self.max_hits]]
```

匹配有两处细节，直接决定它能不能用：

**一、长词优先，且只取不重叠的最长匹配。**
`liver yang hyperactivity` 命中之后，其中的 `liver`、`yang` 不应再单独命中。

```python
def _overlaps(spans, start, end):
    return any(start < e and s < end for s, e, _ in spans)
```

不去重叠的话，`Qi and blood deficiency` 一句话就能吐出 5 条命中（qi / blood / deficiency / blood deficiency / qi and blood deficiency），`max_hits` 的 8 个名额会被短词吃光，真正需要注入的长术语反而挤不进去。实测修掉这个问题后，同一句话的命中从 5 条降到 1 条。

**二、单字中文术语不参与匹配。**
「表现」里的「表」、「实际」里的「实」，都会被朴素子串匹配误命中。而单字术语的注入价值本来就趋近于零——句子里单独出现一个「气」，模型自己就会译成 qi，不需要提醒。

这条是端到端测试里暴露出来的：mock 译文曾把「临床表现」改写成「临床 exterior 现」。它们仍留在表里供查阅，只是不当匹配键。

英文侧因为能用词边界（`\bliver\b`），不受此限。

### 5.6 `translate.py`

一次请求完成"按术语表翻译"：

```python
SYSTEM = (
    "你是中医课堂的实时翻译。把给定句子译成{target}。"
    "必须使用下列术语的指定译法，不得替换：\n{terms}\n"
    "只输出译文，不要解释。"
)
```

术语注入的格式：

```
肝阳上亢 → liver yang hyperactivity
气血两虚 → qi and blood deficiency
```

调用时设 `temperature=0`，保证同一术语每次译法一致——课堂上译法飘忽比译错更让人困惑。

超时保护：`asyncio.wait_for(..., timeout=3)`。超时就先把原文推给前端，译文后补或留空，不让字幕流卡住。

**翻译前先做同音纠错。** 嘈杂环境里 ASR 最典型的错误是同音替代（肝阳上亢 → 肝阳上抗）。这类错误有个好性质：读音没变。所以不需要问模型，直接用拼音就能把字认回来：

1. 术语表逐条转拼音建索引；
2. 待译句子转拼音后滑窗比对，命中即改回标准写法；
3. 全程本地完成，零延迟，纠正后的原文也回传前端显示。

实测：

| ASR 原文 | 纠正后 | 译文 |
|---|---|---|
| 肝阳上**抗**的临床表**显** | 肝阳上亢的临床表显 | liver yang hyperactivity |
| 患者气血两**需** | 患者气血两虚 | qi and blood deficiency |
| 针刺足三**理**可以健**皮** | 足三里 / 健脾 | Zusanli / strengthen spleen |

这一步的意义不只是改错字。**术语一旦被认错，强制译法就丢了**，翻译会退化成模型自由发挥——「气血两需」曾被译成 "requires both qi and blood"，语义完全反了。纠错把这条链重新接上。

此外，翻译提示词里也加入了隐式纠错要求（"静默修正明显的听错，只译不解释"），用来兜住术语表覆盖不到的部分。

### 5.7 前端

**页面骨架**（`index.html`）：顶栏放方向切换和开始/停止按钮，主体是字幕区，底部一行灰色状态。

**音频采集**（`app.js`）：

```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
});
const ctx = new AudioContext();
await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
const node = new AudioWorkletNode(ctx, "pcm-capture");
ctx.createMediaStreamSource(stream).connect(node);
```

`echoCancellation` 和 `noiseSuppression` 必须开——线下教室的空调声、投影仪风扇声会显著影响识别。

**（后来修正）** 这两项其实是可调的：浏览器自带的降噪是为通话设计的，会削掉语音里的弱成分，对识别不一定是好事。现在做成 URL 开关，方便同一句话反复对比：

```
?ns=0    关降噪      ?aec=0  关回声消除      ?agc=0  关自动增益
```

音频链路上另外加了一级 **80 Hz 高通**，切掉空调、投影仪的低频轰鸣。人声基频最低约 85 Hz，这一刀基本不伤语音，却能去掉噪声里能量最集中的一段。

**重采样**：浏览器采样率通常是 48 kHz，Deepgram 要 16 kHz。在主线程序里做 3:1 抽取取平均即可，语音频段足够：

```javascript
const ratio = ctx.sampleRate / 16000;   // 通常是 3
function downsample(input) {
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    let sum = 0;
    for (let j = 0; j < ratio; j++) sum += input[i * ratio + j] || 0;
    out[i] = sum / ratio;
  }
  return out;
}
```

累积到 1600 个样本（100 ms）后转 `Int16Array` 发送：

```javascript
const pcm16 = new Int16Array(out.length);
for (let i = 0; i < out.length; i++) {
  pcm16[i] = Math.max(-1, Math.min(1, out[i])) * 0x7fff;
}
ws.send(pcm16.buffer);
```

**渲染**：`interim` 用一个固定元素反复覆盖，`final` 则新建一行：

```javascript
function addLine(src, dst) {
  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `<div class="src"></div><div class="dst"></div>`;
  row.querySelector(".src").textContent = src;
  row.querySelector(".dst").textContent = dst;
  captions.appendChild(row);
  captions.scrollTop = captions.scrollHeight;
}
```

用 `textContent` 而非 `innerHTML` 写内容——ASR 与翻译结果都是外部数据，不可当 HTML 解析。

**断线重连**：`ws.onclose` 里延时 1 秒重连，并在状态栏提示。课堂演示时网络抖动不该让人以为程序崩了。

---

## 6. 配置与运行

`.env` 放在项目根目录：

```
DEEPGRAM_API_KEY=你的key
OPENAI_API_KEY=你的key
```

启动：

```bash
pip install -r requirements.txt
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

必须用 `127.0.0.1` 或 `localhost` 访问：浏览器只在安全上下文（HTTPS 或 localhost）下允许 `getUserMedia`，用局域网 IP 打开会拿不到麦克风。

---

## 7. 一周排期

| 天 | 工作 | 当天结束时可看到 |
|---|---|---|
| D1 | 装依赖，跑通 FastAPI，静态页能打开 | 空白字幕页 |
| D2 | 前端采集 + PCM 推流，后端转发 Deepgram | 屏幕上出现实时英文 interim |
| D3 | final 定稿、分句器、滚动字幕 | 英文单语字幕可连续滚动 |
| D4 | 接入翻译 + 术语表，双栏显示 | 双语字幕 |
| D5 | 中英双向切换、错误处理、断线重连 | 两个方向都能用 |
| D6 | 联调、测延迟、修 bug、录素材 | 稳定版本 |
| D7 | 录屏演示、整理文档 | 演示视频 |

**D2 是唯一的高风险节点**：如果这天结束时屏幕上还是没字，说明音频链路有问题，后面全都堆在这上面。建议 D1 就把 Deepgram 的密钥连通性单独测一遍，别等到 D2。

---

## 8. 调试与常见问题

| 现象 | 排查 |
|---|---|
| 点开始没反应 | 浏览器地址是否为 `127.0.0.1`；控制台有无 `NotAllowedError`（权限被拒） |
| 有 interim 但永远没有 final | `endpointing` 调小；确认音频帧在持续发送，不是发一次就停 |
| 字幕出得很慢 | 看 D6 的延迟测量：音频 100 ms + ASR 300 ms + 分句最长 1.2 s + 翻译 1 s |
| 翻译不出现，只有原文 | 后端日志看 OpenAI 是否超时；密钥额度是否用完 |
| 术语没被正确使用 | `glossary.json` 里的中文是否与文本完全一致；长词排序是否生效 |
| 断线后字幕停在原地 | `onclose` 重连逻辑是否触发；状态栏是否提示 |

延迟测量方法：前端在发送第一帧音频时记 `t0`，收到对应 `final` 时记 `t1`，打印差值。测 20 句取中位数，这个数字写进报告。

---

## 9. 术语表

`data/glossary.json` 共 267 条，按 11 类组织（基础理论、精气血津液神、脏腑、经络、病因病机、四诊八纲、证型、治法、方剂、穴位、一般用语）。

译法以 **WHO《西太平洋地区传统医学名词术语国际标准》（2007）** 为准。该标准的英文全文已用于逐条校验，267 条中 173 条（64.8%）在该标准正文中直接出现；其余条目为该标准未收录的组合，按同一命名规则给出。

术语在管线中的作用很直接：翻译前从句子中匹配出命中的术语，写入提示词并注明"必须使用"，翻译时以 `temperature=0` 执行，保证同一术语在整节课里译法一致。
