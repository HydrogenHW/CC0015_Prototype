# TCM Lecture Live Captions

Real-time bilingual captions for Traditional Chinese Medicine lectures, with terminology locked to the WHO international standard.

**English** | [中文](README.zh.md)

---

## The problem

A student of Traditional Chinese Medicine whose first language differs from the language of instruction faces two barriers at once.

**Speed.** A lecture is a continuous, one-directional stream. Anything missed is lost.

**Terminology.** General-purpose translation tools have no stable rendering for TCM vocabulary. 肝阳上亢, 气血两虚 and 足三里 come out as literal glosses that carry little or no meaning.

The second barrier is the one worth solving. Live captioning is already a commodity; accurately carrying TCM concepts across languages is not.

## How it works

```
Browser (localhost:8000)
  getUserMedia → AudioWorklet → 16 kHz PCM
        │
        ▼  WebSocket
  FastAPI ──► OpenAI Realtime transcription
        │           │
        │           ▼
        │      sentence assembly
        │           │
        │           ▼
        │   pinyin homophone repair
        │           │
        │           ▼
        │   GPT-4o-mini + glossary (temperature 0)
        │
        ▼
  bilingual captions
```

Four ideas do the heavy lifting:

**Glossary-constrained translation.** 267 curated terms (11 categories) are injected into the prompt as mandatory renderings, and translation runs at `temperature=0`. A term is rendered identically for the whole lecture — consistency matters more than occasional variety.

**Pinyin homophone repair.** In a noisy room the characteristic ASR failure is homophone substitution (肝阳上亢 → 肝阳上抗). Pronunciation is unchanged, so pinyin recovers the characters locally, with zero added latency. This matters because a mis-recognised term silently loses its mandatory rendering, and translation degrades into improvisation — 气血两需 was once rendered "requires both qi and blood", inverting the meaning.

**Concurrent translation, ordered output.** Serial translation falls behind lecture pace, the queue grows, and whatever is unfinished at stop time is lost. Translation now runs three-wide, with sequence numbers and a reorder buffer so captions still appear in the order they were spoken.

**Two-stage captions.** Interim results appear greyed and get overwritten; finals commit to a bilingual row. Text shows up immediately while the translation lands a moment later.

Measured end-to-end latency: **1.5–2.2 s**.

## Quick start

### Requirements

- Python 3.10+
- A microphone (built-in is fine, external is much better)
- An [OpenAI](https://platform.openai.com/api-keys) account — used for both recognition and translation, so one key is enough
- Optional: [Deepgram](https://console.deepgram.com) if you switch `ASR_PROVIDER=deepgram`

### Configure API keys

Keys live in **environment variables**, never in the repo:

```powershell
[Environment]::SetEnvironmentVariable("DEEPGRAM_API_KEY", "your_key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your_key", "User")
```

Reopen your terminal afterwards. On macOS/Linux, export them in your shell profile instead.

### Run

**Option 1 — browser extension (recommended for daily use)**

1. Double-click `start_service.vbs` — starts the backend **with no console window**
2. First time only: open `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, pick the `extension/` folder
3. From then on, click the toolbar icon

The icon probes the service before opening anything. If it is not running you get an explanatory page instead of the browser's "can't reach this site".

To start the service at login, run `install_autostart.bat` once (it drops a shortcut in your Startup folder, trivially removable).

**Option 2 — `run.bat` (visible log, useful when debugging)**

Double-click `run.bat`, then open `http://127.0.0.1:8000`, press **开始**, and allow microphone access.

> Manual start:
> ```bash
> pip install -r requirements.txt
> python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
> ```

The address must be `127.0.0.1` or `localhost`. Browsers only grant microphone access in a secure context, and on a LAN IP they fail **silently**.

### No keys? Run on mock data

Set `MOCK=1` in `.env`. Nothing external is called; recognition and translation are driven by local fixtures. The UI, scrolling, sentence assembly and glossary matching all work normally — useful for reviewing the interface, or as a fallback if an API misbehaves during a demo.

## What is in the box

| Component | Notes |
|---|---|
| Streaming ASR | OpenAI `gpt-4o-transcribe` via Realtime API; `delta` → interim, `completed` → final |
| Translation | GPT-4o-mini, glossary-constrained, 3-way concurrent |
| Glossary | 267 terms, 11 categories, WHO ISTTM (2007) |
| Homophone repair | pypinyin, local, zero latency |
| Frontend | Plain HTML/CSS/JS, no build step |
| Audio | 80 Hz high-pass; browser noise suppression is switchable |

## Project structure

```
app/
├── server.py         FastAPI entry, WebSocket bridge, ordered translation
├── asr.py            OpenAI Realtime transcription (+ Deepgram, + mock)
├── segmenter.py      sentence assembly
├── glossary.py       longest-first, non-overlapping term matching
├── pinyin_fix.py     homophone repair
├── translate.py      translation with term constraints
├── config.py         configuration
└── static/           frontend
data/
└── glossary.json     267 zh↔en terms
docs/
├── implementation_zh.md
└── implementation_en.md
tools/
├── build_glossary.py  rebuild glossary.json
├── make_review.py     generate human-review sheet
├── smoke_test.py      end-to-end test, no keys needed
├── test_order.py      concurrent translation ordering test
└── pack_for_team.py   share-safe packaging
extension/             Chrome extension (one-click entry point)
start_service.vbs      silent backend launcher
install_autostart.bat  enable start-at-login
```

## Testing

No keys required:

```bash
python tools/smoke_test.py   # end-to-end: speech in, captions out
python tools/test_order.py   # concurrent translation keeps caption order
```

## FAQ

**Start does nothing / no microphone**

Check the address is `127.0.0.1` or `localhost`. A LAN IP is refused silently.

**Grey text appears but never commits**

Recognition works; sentence assembly has not fired. The transcription session uses server-side VAD, which finalises a sentence after ~500 ms of silence — pause naturally between sentences. If it still lags, lower `SEG_MAX_WAIT` in `app/config.py`.

**Captions feel slow**

Budget: 100 ms buffering + ~300 ms ASR + up to 1.2 s assembly + ~1 s translation. Lower `SEG_MAX_WAIT` to 0.6 to trade context for speed.

**Source text without translation**

The backend log will say why. The common cause is exhausted OpenAI quota or an invalid key; the pipeline degrades to source-only rather than stalling.

**Terms not applied**

Matching is exact against `data/glossary.json`. If ASR hears 肝阳上抗 the pinyin repair should catch it — check the log line `[纠字]` to confirm.

## Terminology

267 entries across 11 categories: foundational theory, essence-qi-blood-fluids, zang-fu organs, meridians, aetiology and pathology, diagnostics, patterns, treatment methods, formulas, acupoints, and general vocabulary.

Renderings follow the **WHO International Standard Terminologies on Traditional Medicine in the Western Pacific Region (2007)**. The standard's full English text was used to verify every entry; 173 of 267 (64.8%) appear verbatim. The rest are combinations the standard does not list, rendered under the same conventions. Entries awaiting human review are marked in `notes/glossary_review.md`.

One known divergence: for the seven emotions, WHO 2007 uses *thought / anxiety / sorrow*, while the widely taught Wiseman convention uses *pensiveness / worry / grief*. This project follows WHO.

## Design documents

- [`docs/implementation_en.md`](docs/implementation_en.md) — full implementation guide
- [`docs/implementation_zh.md`](docs/implementation_zh.md) — 同一份文档的中文版
- [`notes/terminology_feasibility.md`](notes/terminology_feasibility.md) — how the glossary was sourced and what could not be obtained
