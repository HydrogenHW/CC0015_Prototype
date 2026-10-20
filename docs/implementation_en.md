# Real-Time TCM Lecture Captions
## Implementation Document v1.0

---

## 1. Overview

A web application that runs entirely on the local machine. A Python service handles audio forwarding, speech recognition and translation; a single page in the browser captures the microphone and renders bilingual captions.

```
Browser (localhost:8000)
┌─────────────────────────────────┐
│ getUserMedia → AudioWorklet     │  16 kHz PCM
│            │                    │ ─────────┐
│            ▼                    │          │
│        WebSocket ───────────────┼──────────┤
│            ▲                    │          │
│            │  caption JSON      │          │
│      two-column captions        │ ◄────────┤
└─────────────────────────────────┘          │
                                             ▼
                              ┌──────────────────────────┐
                              │  FastAPI   /ws           │
                              │    ├─ asr.py     Deepgram│
                              │    ├─ segmenter.py       │
                              │    ├─ glossary.py 267    │
                              │    └─ translate.py GPT   │
                              └──────────────────────────┘
```

Open `http://127.0.0.1:8000`, press Start, grant microphone access, and captions begin scrolling from the next utterance.

---

## 2. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI + uvicorn | Native WebSocket support, async throughout |
| Streaming ASR | Deepgram (WebSocket API) | Chinese and English, ~300 ms to first token |
| Translation | OpenAI `gpt-4o-mini` | Accepts glossary constraints, structured output |
| Frontend | Plain HTML/CSS/JS | No framework, no build step |
| Glossary | Local JSON | 267 entries, 11 categories |

Dependencies:

```
fastapi
uvicorn[standard]
websockets
openai
python-dotenv
```

---

## 3. File Layout

```
app/
├── server.py            FastAPI entry point, WebSocket endpoint, wiring
├── asr.py               Deepgram streaming client
├── segmenter.py         Semantic sentence assembly
├── glossary.py          Term loading and matching
├── translate.py         Translation with term constraints
├── config.py            Environment loading
└── static/
    ├── index.html       Page skeleton
    ├── app.js           Capture, connection, rendering
    ├── pcm-worklet.js   AudioWorklet processor
    └── style.css        Styles
data/
└── glossary.json        Term list
requirements.txt
.env                     Secrets (never committed)
run.bat                  One-click launch
```

---

## 4. Message Protocol

A single WebSocket carries everything.

**Browser → backend**

| Kind | Format | Purpose |
|---|---|---|
| Audio | Binary frame | 16 kHz, mono, 16-bit little-endian PCM, 100 ms per frame |
| Control | `{"type":"lang","value":"zh"}` | Switch direction; `zh` = Chinese→English, `en` = English→Chinese |
| Control | `{"type":"stop"}` | End the session |

**Backend → browser**

| Type | Format | Purpose |
|---|---|---|
| `interim` | `{"type":"interim","text":"..."}` | Provisional text, greyed out, replaced on each update |
| `final` | `{"type":"final","src":"...","dst":"..."}` | Committed sentence pair, appended to the caption area |
| `error` | `{"type":"error","message":"..."}` | Raise a notice without breaking the stream |

The interim/final split is what makes the captions *feel* live: text appears immediately, the translation follows a moment later.

---

## 5. Module Implementation

### 5.1 `config.py`

Read both keys from `.env` and fail fast if either is missing, rather than dying halfway through a session.

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

The core is a single `/ws` endpoint. Each connection spawns two concurrent tasks:

- **Upstream**: forward browser PCM to Deepgram unchanged;
- **Downstream**: receive recognition results — push interim text straight back, and send finals through segmentation and translation before returning the pair.

Run them with `asyncio.gather`; when either finishes, close both.

```python
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    dg = await DeepgramStream.connect(lang="en-US")
    try:
        await asyncio.gather(
            pump_upstream(ws, dg),      # browser → Deepgram
            pump_downstream(ws, dg),    # Deepgram → browser (+ translation)
        )
    finally:
        await dg.close()
```

Because the browser already sends raw PCM, the upstream pump does no decoding — it forwards `bytes` directly.

### 5.3 `asr.py`

Connect to Deepgram over `websockets`. The query parameters determine recognition quality:

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

Three parameters deserve comment:

- `endpointing=300` — declare an utterance finished after 300 ms of silence. Lower fragments words; higher delays captions.
- `smart_format=true` — normalises numbers and formatting, which matters in a subject full of counted concepts (three, five, twelve).
- `punctuate=true` — Chinese punctuation is what the segmenter keys on.

Responses look like this:

```json
{"channel":{"alternatives":[{"transcript":"肝阳上亢","confidence":0.94}]},
 "is_final":false,"speech_final":false}
```

Read `transcript`, branch on `is_final`.

### 5.4 `segmenter.py`

Deepgram finals are often half-sentences. Translating them directly cuts meaning in half and scrambles Chinese word order. Add a buffer:

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

Two release conditions: terminal punctuation, or 60 characters. The second is the safety valve — a lecturer who never pauses must not stall the captions indefinitely.

### 5.5 `glossary.py`

Load once at startup, build both direction indexes, then look up only the terms present in each sentence.

```python
class Glossary:
    def __init__(self, path, max_hits=8):
        raw = json.load(open(path, encoding="utf-8"))
        self._zh2en = {e["zh"]: e["en"] for e in raw}
        self._en2zh = {}
        for e in raw:
            self._en2zh.setdefault(e["en"].lower(), e["zh"])
        # single-character Chinese terms are excluded as match keys
        self._zh_keys = sorted((k for k in self._zh2en if len(k) > 1),
                               key=len, reverse=True)
        self._en_keys = sorted(self._en2zh, key=len, reverse=True)

    def match(self, text, direction="zh2en"):
        spans = self._spans_zh(text) if direction == "zh2en" else self._spans_en(text)
        spans.sort(key=lambda s: s[0])
        table = self._zh2en if direction == "zh2en" else self._en2zh
        return [(k, table[k]) for _, _, k in spans[: self.max_hits]]
```

Two details decide whether the matching is usable.

**Longest first, keeping only non-overlapping matches.** Once `liver yang hyperactivity` matches, its constituent `liver` and `yang` must not match again.

```python
def _overlaps(spans, start, end):
    return any(start < e and s < end for s, e, _ in spans)
```

Without de-overlapping, the single sentence `Qi and blood deficiency` yields five hits (qi / blood / deficiency / blood deficiency / qi and blood deficiency) and exhausts the `max_hits` budget on fragments, crowding out the long term that actually needed injection. Measured after the fix, that sentence yields one hit instead of five.

**Single-character Chinese terms are excluded as keys.** 表 inside 表现 and 实 inside 实际 are picked up by naive substring matching, and a lone single character carries almost no injection value — the model renders a bare 气 as qi without being told. End-to-end testing surfaced this directly: the mock pipeline once rewrote 临床表现 as 临床 exterior 现. These entries stay in the table for reference; they are simply not match keys.

The English side does not need this restriction because it matches on word boundaries (`\bliver\b`).

### 5.6 `translate.py`

One request performs "translate under term constraints":

```python
SYSTEM = (
    "You translate TCM lecture speech into {target}. "
    "You must use the following renderings and may not substitute others:\n{terms}\n"
    "Output the translation only."
)
```

Injected terms look like:

```
肝阳上亢 → liver yang hyperactivity
气血两虚 → qi and blood deficiency
```

Use `temperature=0`. Consistency matters more than variety here — a term rendered two different ways in one lecture is more confusing than a mildly imperfect one rendered consistently.

Wrap the call in `asyncio.wait_for(..., timeout=3)`. On timeout, push the source text through and leave the translation to arrive late or not at all, rather than stalling the caption stream.

**Homophone repair runs before translation.** In a noisy room the characteristic ASR failure is homophone substitution (肝阳上亢 → 肝阳上抗). Such errors have a useful property: the pronunciation is unchanged. So no model is needed — pinyin alone recovers the characters:

1. Index every glossary entry by its pinyin;
2. Convert the incoming sentence to pinyin and slide a window over it, rewriting any match to the standard form;
3. Entirely local, zero added latency; the repaired source is sent to the front end too.

Measured:

| ASR output | Repaired | Translation |
|---|---|---|
| 肝阳上**抗**的临床表**显** | 肝阳上亢的临床表显 | liver yang hyperactivity |
| 患者气血两**需** | 患者气血两虚 | qi and blood deficiency |
| 针刺足三**理**可以健**皮** | 足三里 / 健脾 | Zusanli / strengthen spleen |

This matters beyond spelling. **Once a term is mis-recognised, its mandatory rendering is lost** and translation degrades into whatever the model improvises — 「气血两需」 was once rendered "requires both qi and blood", inverting the meaning. Repair reconnects the chain.

The translation prompt additionally asks the model to silently repair obvious mis-hearings, covering terms outside the glossary.

### 5.7 Frontend

**Skeleton** (`index.html`): a top bar with direction toggle and start/stop, a caption area, and a grey status line at the bottom.

**Capture** (`app.js`):

```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
});
const ctx = new AudioContext();
await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
const node = new AudioWorkletNode(ctx, "pcm-capture");
ctx.createMediaStreamSource(stream).connect(node);
```

`echoCancellation` and `noiseSuppression` should be on — air conditioning and projector fans in a real classroom measurably hurt recognition.

**(Later correction.)** Both are actually tunable, and not obviously beneficial: browser noise suppression is designed for telephony and removes weak speech components along with the noise. They are now URL switches for A/B comparison:

```
?ns=0    no suppression      ?aec=0  no echo cancellation      ?agc=0  no auto gain
```

The audio path also gained an **80 Hz high-pass** stage, cutting the low-frequency rumble of air conditioning and projectors. Human voice fundamentals start around 85 Hz, so the cut costs almost nothing while removing the most energy-dense band of noise.

**Resampling.** Browser context rate is usually 48 kHz; Deepgram wants 16 kHz. A 3:1 average in the main thread is sufficient for speech:

```javascript
const ratio = ctx.sampleRate / 16000;   // typically 3
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

Accumulate 1600 samples (100 ms), convert to `Int16Array`, send:

```javascript
const pcm16 = new Int16Array(out.length);
for (let i = 0; i < out.length; i++) {
  pcm16[i] = Math.max(-1, Math.min(1, out[i])) * 0x7fff;
}
ws.send(pcm16.buffer);
```

**Rendering.** Interim text overwrites one fixed element; finals append a row:

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

Write content with `textContent`, never `innerHTML` — both recognition output and translations are external data and must not be parsed as markup.

**Reconnection.** Retry after one second in `ws.onclose` and say so in the status line. A network hiccup during a demo should not look like a crash.

---

## 6. Configuration and Running

Place `.env` at the project root:

```
DEEPGRAM_API_KEY=your_key
OPENAI_API_KEY=your_key
```

Start:

```bash
pip install -r requirements.txt
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

Use `127.0.0.1` or `localhost`, never a LAN IP. Browsers only grant `getUserMedia` in a secure context — HTTPS or localhost — so a LAN address will silently fail to get a microphone.

---

## 7. One-Week Schedule

| Day | Work | Visible at end of day |
|---|---|---|
| D1 | Install dependencies, bring up FastAPI, serve the static page | Blank caption page |
| D2 | Capture + PCM streaming; backend forwards to Deepgram | Live English interim text on screen |
| D3 | Final results, segmenter, scrolling captions | Continuous monolingual captions |
| D4 | Translation and glossary, two-column layout | Bilingual captions |
| D5 | Direction toggle, error handling, reconnection | Both directions working |
| D6 | Integration, latency measurement, bug fixing | Stable build |
| D7 | Screen recording and documentation | Demo video |

**D2 is the only high-risk checkpoint.** If nothing appears on screen by the end of that day, the audio path is broken and everything downstream piles onto it. Test Deepgram connectivity on D1, in isolation, rather than discovering it on D2.

---

## 8. Debugging

| Symptom | Check |
|---|---|
| Start does nothing | Address must be `127.0.0.1`; look for `NotAllowedError` in the console (permission denied) |
| Interims appear, finals never do | Lower `endpointing`; confirm frames are sent continuously, not once |
| Captions feel slow | Account for 100 ms buffering + 300 ms ASR + up to 1.2 s segmentation + ~1 s translation |
| Source text appears without translation | Backend log for OpenAI timeouts; check quota |
| Terms not applied | Exact string match against `glossary.json`; confirm longest-first ordering is active |
| Captions freeze after a drop | Whether `onclose` retries; whether the status line updated |

Latency measurement: stamp `t0` when the first audio frame of a sentence is sent, `t1` when its `final` arrives, print the delta. Take the median of twenty sentences — that number goes into the report.

---

## 9. Glossary

`data/glossary.json` holds 267 entries in 11 categories: foundational theory, essence-qi-blood-fluids, zang-fu organs, meridians, aetiology and pathology, diagnostics, patterns, treatment methods, formulas, acupoints, and general vocabulary.

Renderings follow the **WHO International Standard Terminologies on Traditional Medicine in the Western Pacific Region (2007)**. The standard's full English text was used to verify every entry: 173 of 267 (64.8%) appear verbatim. The remainder are combinations the standard does not list, rendered under the same conventions.

The glossary acts in the pipeline in a single way: before translation, terms present in the sentence are matched out and written into the prompt as mandatory renderings; the translation runs at `temperature=0` so a given term is rendered identically throughout a lecture.
