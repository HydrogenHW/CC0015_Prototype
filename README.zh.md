# 中医课堂实时字幕

把课堂语音实时转成中英双语字幕，术语按 WHO 国际标准译法锁定。

[English](README.md) | **中文**

---

## 要解决的问题

学中医的人，如果母语和授课语言不一致，会同时撞上两堵墙。

**速度。** 课堂是单向、连续、不可暂停的语流，跟不上就永久丢失。

**术语。** 通用翻译工具对中医词汇没有稳定对应。肝阳上亢、气血两虚、足三里，翻出来常常是字面直译，语义失真。

第二堵墙才是值得解决的。实时字幕已经是成熟商品，**准确跨语言传递中医概念**还不是。

## 怎么工作

```
浏览器 (localhost:8000)
  getUserMedia → AudioWorklet → 16 kHz PCM
        │
        ▼  WebSocket
  FastAPI ──► OpenAI 流式转写
        │           │
        │           ▼
        │        语义分句
        │           │
        │           ▼
        │     拼音同音纠错
        │           │
        │           ▼
        │   GPT-4o-mini + 术语表（temperature 0）
        │
        ▼
     双语字幕
```

四个关键设计：

**术语约束翻译。** 267 条人工整理的术语（11 类）作为强制译法注入提示词，翻译时 `temperature=0`。同一个术语在整节课里译法一致——一致比偶尔更贴切更重要。

**拼音同音纠错。** 嘈杂环境下 ASR 的典型错误是同音替代（肝阳上亢 → 肝阳上抗）。读音没变，所以本地用拼音就能把字认回来，零延迟。这一步很要紧：术语一认错，强制译法就丢了，翻译退化成模型瞎猜——「气血两需」曾被译成 "requires both qi and blood"，语义整个反了。

**并发翻译、顺序输出。** 串行翻译跟不上讲课速度，队列越积越长，停止时没翻完的全丢。现在三路并发，用序号加重排缓冲保证字幕顺序仍跟说话顺序一致。

**两段式字幕。** 临时结果灰色显示、反复覆盖；定稿才落成双语行。文字立刻出现，译文稍后补上。

实测端到端延迟 **1.5~2.2 秒**。

## 快速开始

### 环境要求

- Python 3.10+
- 麦克风（内置可用，外接效果明显更好）
- [OpenAI](https://platform.openai.com/api-keys) 账号 —— 识别和翻译都用它，**一个 key 就够**
- 可选：[Deepgram](https://console.deepgram.com)，只有切到 `ASR_PROVIDER=deepgram` 时才需要

> 本机已装好 Python 3.13.16（`%LocalAppData%\Programs\Python\Python313`，已加入用户 PATH），
> 依赖在 `.venv/` 里，直接跳到下一步。换机器时运行 `.setup\install_python.py`
> 可以按同样方式装回来（官方 NuGet 包，解压即用，不需要管理员权限）。

### 配置密钥

密钥放在**环境变量**里，不进仓库：

```powershell
[Environment]::SetEnvironmentVariable("DEEPGRAM_API_KEY", "你的key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的key", "User")
```

设完重开一个窗口生效。macOS/Linux 请写在 shell 配置里。

### 启动

**方式一：浏览器扩展（推荐，日常用这个）**

1. 双击 `start_service.vbs` —— 后台起服务，**不弹窗口**
2. 首次装扩展：Chrome 打开 `chrome://extensions` → 右上角开「开发者模式」→「加载已解压的扩展程序」→ 选本项目的 `extension/` 目录
3. 以后点工具栏那个图标即可打开字幕页

图标会先探一下服务是否活着：活着就开页面，没活着会给你一个说明页，而不是浏览器的「无法访问」。

想开机自动起服务，运行一次 `install_autostart.bat`（往启动文件夹放个快捷方式，随时可删）。

**方式二：run.bat（能看到日志，排查问题时用）**

双击 `run.bat`，会开一个带日志的窗口。浏览器打开 `http://127.0.0.1:8000`，点「开始」，允许麦克风。

> 手动启动（等价）：
> ```bash
> pip install -r requirements.txt
> python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
> ```

地址必须是 `127.0.0.1` 或 `localhost`。浏览器只在安全上下文下授予麦克风，用局域网 IP 打开会**静默失败**。

### 没有密钥？先用假数据看界面

在 `.env` 里写 `MOCK=1`。不调用任何外部 API，识别和翻译由本地假数据驱动，界面、滚动、分句、术语匹配全部照常。适合先验收前端，或演示当天 API 抽风时兜底。

## 目录

```
app/
├── server.py         FastAPI 入口、WebSocket 桥接、顺序化并发翻译
├── asr.py            OpenAI Realtime 转写（另含 Deepgram、Mock）
├── segmenter.py      语义分句
├── glossary.py       术语匹配（长词优先、去重叠）
├── pinyin_fix.py     同音纠错
├── translate.py      术语约束翻译
├── config.py         配置
└── static/           前端四件套
data/
└── glossary.json     267 条中英术语
docs/
├── implementation_zh.md  实现文档（中文）
└── implementation_en.md  Implementation document (English)
tools/
├── build_glossary.py  从术语源重建 glossary.json
├── make_review.py     生成人工复核表
├── smoke_test.py      端到端冒烟测试（不需要密钥）
├── test_order.py      并发翻译顺序测试
└── pack_for_team.py   安全打包给组员
extension/             Chrome 扩展（点图标打开字幕页）
start_service.vbs      静默启动后台服务（双击）
install_autostart.bat  设置开机自启
```

## 测试

不需要密钥：

```bash
python tools/smoke_test.py   # 端到端：进去语音，出来字幕
python tools/test_order.py   # 并发翻译仍然保持字幕顺序
```

## 分享给组员

```bash
python tools/pack_for_team.py
```

生成 `dist/CC0015-发给组员.zip`，自动排除 `.env`、`keys.txt`、`.venv`、`logs`、原始 PDF。打包前会扫描所有文件内容，发现疑似密钥就**中止**。

## 常见问题

**点开始没反应 / 没有麦克风权限**

地址必须是 `127.0.0.1` 或 `localhost`。局域网 IP 会被浏览器静默拒绝。

**有灰色文字但没有正式字幕**

识别在工作，分句没触发。转写会话用的是服务端 VAD，靠约 500 ms 静音判定一句结束，说话时自然停顿即可。若长时间不出，调小 `app/config.py` 里的 `SEG_MAX_WAIT`。

**字幕出得慢**

预算：100 ms 缓冲 + 约 300 ms 识别 + 最长 1.2 s 分句 + 约 1 s 翻译。把 `SEG_MAX_WAIT` 调到 0.6 可以牺牲上下文换速度。

**翻译不出现，只有原文**

看后端日志。常见原因是 OpenAI 额度用完或密钥无效——程序会降级为只显示原文，不中断。

**术语没被正确使用**

匹配是严格字符串比对。识别把「肝阳上亢」听成「肝阳上抗」时，拼音纠错应该会拦下来——看日志里有没有 `[纠字]` 那一行。

## 术语表

267 条，11 类：基础理论、精气血津液神、脏腑、经络、病因病机、四诊八纲、证型、治法、方剂、穴位、一般用语。

译法以 **WHO《西太平洋地区传统医学名词术语国际标准》（2007）** 为准。该标准英文全文已逐条校验，267 条中 173 条（64.8%）直接命中；其余为该标准未收录的组合，按同一命名规则给出。待人工复核的清单在 `notes/glossary_review.md`。

一处已知分歧：七情一组，WHO 2007 用 *thought / anxiety / sorrow*，通行教材（Wiseman 体系）用 *pensiveness / worry / grief*。本项目取 WHO 用法。

## 设计文档

- [`docs/implementation_zh.md`](docs/implementation_zh.md) —— 完整实现文档
- [`docs/implementation_en.md`](docs/implementation_en.md) —— 同一份文档的英文版
- [`notes/terminology_feasibility.md`](notes/terminology_feasibility.md) —— 术语表怎么来的、哪些拿不到
