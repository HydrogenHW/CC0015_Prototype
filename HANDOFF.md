# 交接文档

写给接手调试的人（或下一个对话）。读完这份应该能直接开工。

---

## 这是什么

一个本地运行的实时中英双语字幕工具。麦克风收音 → 流式识别 → 术语约束翻译 → 左右两栏字幕。右侧有术语助手，可以问译法/术语，也能让它改热词。

不是网页服务，是一台机器上跑给自己的工具。浏览器只是显示层。

**当前版本：1.0.1**（`git tag v1.0.1`，GitHub Release 有打包好的 zip）

> 1.0.0 有致命 bug（火山识别必崩，见坑 #12），已在 1.0.1 修复，别再发 1.0.0 那个包。

---

## 运行环境（本机）

| 项 | 值 |
|---|---|
| 服务地址 | `http://127.0.0.1:8000` |
| 启动方式 | 双击 `run.bat`（自动装依赖、起服务、6 秒后开浏览器） |
| Python | `%LOCALAPPDATA%\Programs\Python\Python313`（便携版，无需管理员） |
| 项目虚拟环境 | `.venv/`（依赖都在这） |
| 应用日志 | `logs/app.log`（我们自己的日志）<br>`logs/service.log`（uvicorn 的 stdout/stderr） |
| 用户设置 | `data/settings.json`（含明文密钥，已 gitignore） |
| 自定义预设 | `data/user_presets.json`（本机数据） |

**API 密钥**在 Windows **用户环境变量**里（不在项目文件里）：

```
VOLC_API_KEY      火山引擎，语音识别
OPENAI_API_KEY    OpenAI，翻译
DEEPSEEK_API_KEY  DeepSeek，术语助手
```

取值优先级：**设置界面 > 环境变量 > 默认值**。设置界面填的会覆盖环境变量。

---

## 架构

```
浏览器
  getUserMedia → AudioWorklet → 16 kHz PCM
        │
        ▼ WebSocket (/ws)
  FastAPI (app/server.py)
        │
        ├─► 火山豆包流式识别 (app/asr.py)
        │        │ partial / definite
        │        ▼
        │   按句号分句 (app/asr.py)
        │        │
        │        ▼
        │   拼音同音纠错 (app/pinyin_fix.py)
        │        │
        │        ▼
        │   GPT-4o-mini + 术语约束 (app/translate.py)
        │
        └─► 双语字幕推回前端
```

翻译是**三路并发 + 序号重排**，保证字幕顺序跟说话顺序一致（`OrderedTranslator`）。

---

## 文件职责

```
app/
├── server.py       FastAPI 入口、WebSocket 桥接、/chat /presets /settings 接口
├── asr.py          火山流式识别（另有 Deepgram、Mock）；分句逻辑也在这
├── presets.py      热词预设：扫描 data/presets/ 目录 + 用户自定义
├── glossary.py     从 00-tcm.json 读中英对照表，做术语匹配
├── pinyin_fix.py   同音纠错（肝阳上抗 → 肝阳上亢）
├── segmenter.py    句子拼装（Deepgram/Mock 路径用）
├── translate.py    术语约束翻译
├── chat.py         术语助手（DeepSeek + function calling）
├── settings.py     设置存储、schema、密钥取值优先级
├── config.py       配置；可配项走模块级 __getattr__ 动态取值
└── static/         前端四件套（原生 JS，无构建）

data/presets/       9 个学科热词组，一科一个 json，文件名前缀定顺序
  00-tcm.json       中医（唯一自带 glossary 中英对照的）
  01-cs.json ... 08-med.json

tools/              测试与维护脚本（不随 release 分发）
docs/               实现文档
notes/              术语来源核查记录
```

---

## 已经踩过的坑

这些每一条都实际浪费过时间，改动时注意别踩回去。

### 1. `.bat` 文件必须纯 ASCII

cmd.exe 按系统代码页解析 `.bat`，UTF-8 中文会**撕裂命令行**，报一堆「'xx' 不是内部或外部命令」。

中文提示写在 README 或 Python 日志里。

### 2. `pythonw.exe` 下 `sys.stderr` 是 `None`

`logging.basicConfig(handlers=[StreamHandler(), ...])` 会直接抛异常，进程在 import 阶段就死，连文件日志都留不下。现象是"双击没反应、日志也空"。

现在的写法是：只在 `sys.stderr is not None` 时才挂 StreamHandler。

### 3. 隐藏窗口里 stdout/stderr 句柄不可用

即使换成 `python.exe`，只要输出不重定向、进程藏在隐藏窗口里，uvicorn 一样起不来。输出**必须**重定向到文件。

### 4. 火山的 `X-Api-Resource-Id` 必须匹配模型版本

```
2.0 模型 → volc.seedasr.sauc.duration   ← 当前用的
1.0 模型 → volc.bigasr.sauc.duration
```

用错直接 403，没有任何提示说明原因。认证只需要 `x-api-key`，不需要 AppID。

### 5. 火山每次推送都带「到目前为止的全部 utterances」

不做去重的话，同一句会被反复当成新句子送进翻译区——表现是草稿区的内容循环出现在正式字幕里。

现在是按 `start_time` 去重。

### 6. 火山只在检测到静音时才给 `definite`

老师连着讲不停就永远不断句。现在改成：**识别到句末标点（。！？）就切**，`definite` 只作兜底。

时间兜底（`ASR_MAX_SPEECH_MS`）默认关闭。

### 7. flex 子项的 `min-width` 默认是 `auto`

字幕区长句子会把 `.stage` 的最小宽度顶大，把右侧助手面板**挤出视口**。必须显式 `min-width: 0`。

### 8. I18N 表里不能引用 `t()`

做完批量替换后，`I18N` 对象内部的几个值被写成了 `t("...")`，等于表在定义过程中查自己。`let T` 还没执行，直接 TDZ 报错（`Cannot access 'T' before initialization`），整个 IIFE 在顶部就崩了——页面看着正常，但**所有按钮都没反应**。

### 9. 动态文案不能挂 `data-i18n`

状态栏是动态的（录音中/已停止/重连中…），曾给它挂了 `data-i18n="status_idle"`，而表里的键叫 `st_idle`。对不上，`t()` 原样返回键名，切到英文就显示成 `status_idle`。

现在 `setStatus(key, kind, ...args)` 接收 key 并记在 `state` 里，切语言时重算。

### 10. 浏览器会缓存静态资源

改了 CSS/JS 后对方看不到变化，多半是缓存。`index.html` 里的引用带版本号（`?v=11`），改动后**必须**把版本号加一。

### 11. 官方 Python 安装器在无管理员权限的机器上装不上

返回 `0x80070005`。改用 NuGet 包（zip，含 pip 和 venv），解压即用。见 `setup_python.ps1`。

### 12. 删一个类时，别把它紧邻的私有函数一起带走

`7fb06dd 删掉 OpenAI 语音识别` 切掉 `OpenAITranscribeStream` 整个类时，把紧跟在它后面、
给火山用的 `_volc_frame` / `_volc_parse` 一起删了，调用点还留着。结果是**每次开麦都**

```
NameError: name '_volc_frame' is not defined
```

**现象不是报错弹窗，而是状态栏在「录音中 ↔ 重连中」之间每秒横跳**：前端连上就被踢，
旧代码又固定 1 秒重连，于是永远循环。日志里是一秒一条 `ERROR 会话异常`。

`v1.0.0` 的 tag 在这个提交之后，所以那个 release zip 里也是坏的——**1.0.1 修好了并重新打过包**。
`pack_for_team.py` 现在会在打包后自己解压、编译、用 MOCK 起一次服务连 `/health`，
这类「包能打出来但跑不起来」的问题会在打包那一步就被挡下，不会再发出去。

现在两个函数在 `app/asr.py`（`MockStream` 之后、`VolcengineStream` 之前）。改完先跑：

```bash
.venv/Scripts/python.exe tools/test_volc_frame.py    # 帧格式自检，不联网、不需要密钥
```

### 13. 重连要有退避，而且「连上就清零」是错的

修上面那个 bug 时顺手改了前端策略（`app/static/app.js`）：

- 退避 1s→2s→4s→8s→15s，连败 6 次（第 7 次断开）就停手：停止录音、松开麦克风、
  状态显示「后端连接已断开」，弹一个带「重试」的提示条。
- **连接要稳定活过 8 秒才把失败计数清零**（`RETRY_STABLE_MS`）。原来是 `onopen`
  里直接清零——「连上就被后端踢掉」会被当成成功，退避永远回到 1 秒。
- 手动点「开始」时也清零一次，否则上一轮放弃留下的计数会让这一次一断开就直接判死。
- 后端 `ws_endpoint` 现在会把异常作为 `{"type":"error","message":"..."}` 先推给前端，
  页面上能看到 `NameError: ...` 这类真话，而不是只有一个 `断开(1011)`。

---

## 目前已知的问题

以下都是**没有完全解决**或**没有充分验证**的，调试时优先看这些：

### 断句质量依赖火山的标点

现在是"识别到句号就切"。但标点是火山自己加的，不完全可控：一段 20 秒的语音它可能只给 2 个句号，也可能一个都不给（那就等 `definite` 兜底）。

**只用人声 TTS 音频验证过，没在真实课堂录音上测过。**

### 强制切分的取舍没调过

`ASR_MAX_SPEECH_MS` 默认 0（关闭）。设成 5000 会切出「治以。」这类碎片；8000 效果尚可但仍是硬切。这个数值没有针对真实语料调优。

### 热词上限 40

`ASR_KEYWORDS_MAX = 40`，`words_for()` 也按 40 截断。中医预设 491 个词，实际只有 40 个进引擎。哪些词该优先（按词频？按预设顺序？）没有设计过。

### 内置预设不能加词

助手改热词只能写进**用户自建**的预设，内置的（`data/presets/*.json`）是只读的。想给中医加词，要么先复制一份新的，要么直接改 json 文件。

### 前端没有自动化测试

只有 DOM 桩能验证"加载不报错"，交互逻辑全部靠手测。

### 只用合成语音验证过

准确率、延迟、断句都是拿 TTS 音频测的。真实麦克风、远场、口音、噪声下的表现没有系统性数据。

---

## 调试工具

### 日志

```bash
tail -f logs/app.log      # 应用日志：分句、翻译耗时、纠错命中、预设加载
tail -f logs/service.log  # uvicorn：启动错误、请求记录
```

应用日志里几个有用的标记：

- `[句] xxx` —— 一句识别定稿
- `[纠字] a→b` —— 同音纠错触发
- `翻译偏慢 Nms` —— 超过 1.5 秒
- `连讲超过 N 秒，强制切分` —— 时间兜底

### DOM 桩（前端排错神器）

```bash
node .tmp/dom_probe.js
```

用最小 DOM 桩把整个 `app.js` 跑一遍。**页面能加载但按钮全死**这类问题，它五秒就能定位到哪一行报错。

这个文件在 `.tmp/`（gitignore），可能已经不在了。要重建的话：给 `document` / `window` / `fetch` / `WebSocket` 做几个 no-op 桩，用 `vm.runInContext` 执行 `app.js`。

### 测试脚本

```bash
python tools/smoke_test.py   # MOCK 模式端到端，不需要任何密钥
python tools/e2e.py          # 真实链路：发音频 → 收双语字幕（BASE_URL 可改端口）
python tools/test_order.py   # 并发翻译的顺序保证
python tools/test_volc_asr.py # 火山协议直连测试
python tools/test_volc_frame.py # 火山帧格式自检（离线，改 asr.py 后先跑这个）
```

### 前端

按 F12 看 Console。红色报错第一行通常就是答案。

---

## 改动流程

1. 改完跑这三样：
   ```bash
   .venv/Scripts/python.exe -m py_compile app/*.py
   node --check app/static/app.js
   node .tmp/dom_probe.js        # 有的话
   ```
2. 改了静态资源就把 `index.html` 里的 `?v=N` 加一
3. **不要硬编码密钥**，一律走 `config` / `settings`
4. `.bat` / `.ps1` 里不写中文
5. 服务重启：双击 `run.bat`，或者手动
   ```bash
   .venv/Scripts/python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8000
   ```

---

## 注意事项

- **改动先不要 commit**，等确认稳定了再说
- 打包发布用 `python tools/pack_for_team.py`，它会扫内容、发现疑似密钥就中止
- `.env` 那套已经废弃了（密钥在设置界面填），文件还在但没用了
