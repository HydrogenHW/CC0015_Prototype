# Live Captions

Real-time bilingual captions for lectures, running entirely on your own machine.

Speech goes in through the microphone, subtitles come out in two languages side by side. Built for Chinese↔English study, with terminology hotword sets for nine fields.

**English** | [中文](README.zh.md)

---

## Features

**Live bilingual captions** — original text on the left, translation on the right. Interim results appear greyed as you speak; finished sentences commit to a full row.

**Both directions** — Chinese→English or English→Chinese, switchable at any time. The interface language follows the direction: Chinese UI for Chinese→EN, English UI for EN→Chinese.

**Nine built-in terminology sets** — TCM, computer science, mathematics, physics, chemistry, biology, economics, law, medicine. Each holds 60–490 Chinese and English terms that nudge recognition toward domain vocabulary.

**Custom terminology sets** — create your own, name it, switch between them from the top bar.

**Terminology assistant** — a side panel that answers questions about translations and terms, and can add or remove hotwords on request.

**Homophone repair** — when recognition mishears a term as a homophone (肝阳上亢 → 肝阳上抗), pinyin matching restores the correct characters before translation.

## The interface

```
┌──────────────────────────────────────────────────────────────────┐
│ Live Captions [Chinese→EN│EN→Chinese]  Presets▾ + ⋯  Start  ▮    │
├───────────────────────────────────────────┬──────────────────────┤
│  原文 原句原文              译文 翻译结果    │  Terminology         │
│  ──────────────────────────────────────    │  ┌────────────────┐  │
│  原文 原句原文              译文 翻译结果    │  │ Q: 什么是…      │  │
│                                           │  │ A: …            │  │
│                                           │  └────────────────┘  │
│  ┌ 正在识别的草稿 ─────────────────────┐   │  [ ask about a… ]    │
├───────────────────────────────────────────┴──────────────────────┤
│ Space to start / stop                                            │
└──────────────────────────────────────────────────────────────────┘
```

- **Top bar** — translation direction, terminology set, start/stop, microphone level, status
- **Caption area** — completed sentence pairs, newest at the bottom; the greyed line below is what's currently being recognized
- **Side panel** — terminology assistant; drag the divider to resize (240–720px)

## Requirements

- Windows 10/11
- Python 3.10 or newer
- A microphone
- API keys: [Volcengine](https://console.volcengine.com/speech/new/setting/apikeys) (recognition), [OpenAI](https://platform.openai.com/api-keys) (translation), [DeepSeek](https://platform.deepseek.com/api_keys) (assistant, optional)

## Setup

### 1. Python

Install [Python 3.10+](https://www.python.org/downloads/), or run `.setup/install_python.py`, which installs it without admin rights.

### 2. API keys

Two ways — pick either.

**In the app** (recommended). Click the gear icon at the top-left, paste the keys, save. They are stored in `data/settings.json` on this machine.

**Environment variables** (handy during development):

```powershell
[Environment]::SetEnvironmentVariable("VOLC_API_KEY",     "your_key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY",   "your_key", "User")
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "your_key", "User")
```

Keys entered in the app always take priority. If a key is missing from both places, pressing Start shows a prompt with a link back to settings.

### 3. Start

Double-click **`run.bat`**.

On first run it creates a virtual environment and installs dependencies; afterwards it starts straight away. The browser opens by itself a few seconds later — keep the window open, since closing it stops the service.

## Using it

1. **Pick a direction** in the top bar — 中文→EN or EN→中文
2. **Pick a terminology set** — the default is TCM; switch if your subject differs
3. **Press Start** and allow microphone access
4. Speak. Interim text appears greyed; finished sentences commit as bilingual pairs
5. **Ask the assistant** anything about a translation or a term

Press Space to start or stop from anywhere (except while typing in the assistant box).

## Terminology sets

Nine are built in. Each set is shared by both directions — it holds Chinese and English terms together, and recognition only receives the ones matching the current direction.

**Create** — press `+` in the top bar, type a name, done. The new set becomes active.

**Manage** — press `⋯` to rename or delete. At least one set must remain.

**Add terms** — ask the assistant: *"add 链表 and hash table to the hotwords"*. Or `POST /hotwords` with `{"add": ["链表"]}`.

Changes take effect the next time you press Start, because the recognition engine receives hotwords when the connection opens.

## Assistant

The side panel answers questions about translations and terminology, and refuses anything else. It can change hotwords when asked — say *"把太阳伤寒加进热词"* and it calls the tool rather than just agreeing.

It remembers the last few turns, so follow-ups like *"what was that term again — add it"* work.

## Troubleshooting

**Start does nothing / no microphone**

The address must be `127.0.0.1` or `localhost`. A LAN IP is silently refused — browsers only grant microphone access in a secure context.

**Grey text but no committed captions**

Recognition works; the sentence boundary hasn't fired. The recognizer closes a sentence after ~800 ms of silence or when it emits a full stop. Pause naturally between sentences.

**Captions but no translation**

Check the backend window or `logs/app.log`. Usually an expired OpenAI key or exhausted quota — the pipeline degrades to source-only rather than stalling.

**Terms not recognized correctly**

Make sure the active terminology set covers your subject and that its terms match the current direction (Chinese terms for Chinese→EN). Search the log for `[纠字]` lines to see whether homophone repair fired.

**Page loads but nothing responds**

Press F12 and check the console. A JavaScript error at load time leaves the page looking fine while every control stays dead.

## Project layout

```
app/
├── server.py           FastAPI entry, WebSocket bridge, /chat and /presets endpoints
├── asr.py              Volcengine streaming ASR (+ OpenAI, Deepgram, mock)
├── segmenter.py        sentence assembly
├── glossary.py         term matching for translation constraints
├── pinyin_fix.py       homophone repair
├── presets.py          terminology set storage
├── builtin_presets.py  the nine built-in subject sets
├── chat.py             terminology assistant (DeepSeek + tool calling)
├── translate.py        translation with term constraints
└── static/             frontend (HTML/CSS/JS, no build step)
data/
├── glossary.json       267 TCM terms, bilingual
└── presets.json        terminology sets, generated locally
tools/                  tests and maintenance scripts
docs/                   implementation notes
```
