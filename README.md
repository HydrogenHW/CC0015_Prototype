# 中医课堂实时字幕

把课堂语音实时转成中英双语字幕，术语按 WHO 国际标准译法锁定。

在本机运行，浏览器打开 `http://127.0.0.1:8000` 即可使用。

---

## 快速开始

### 1. Python（已就绪）

Python 3.13.16 装在这台机器上了：

```
%LocalAppData%\Programs\Python\Python313
```

已加入用户 PATH，项目依赖也装在了 `.venv/` 里，**不需要再做什么**。

换机器或重装系统时，运行 `.setup\install_python.py` 可以按同样方式装回来
（官方 NuGet 包，解压即用，不需要管理员权限）。

### 2. 配置密钥

密钥放在 **Windows 用户环境变量**里，**不写进项目文件**——这样整个文件夹可以安全发给别人。

PowerShell 里执行一次（换成你自己的值）：

```powershell
[Environment]::SetEnvironmentVariable("DEEPGRAM_API_KEY", "你的key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的key", "User")
```

设完重开一个窗口才生效。

- Deepgram：<https://console.deepgram.com>，注册即送 200 美元额度，不需要信用卡
- OpenAI：<https://platform.openai.com/api-keys>

> **为什么不放 .env**：`.env` 是明文文件，打包发人或误提交时整份泄露。
> 现在项目里一个密钥都没有，`tools/pack_for_team.py` 打包前还会再扫一遍文件内容兜底。

### 3. 启动

双击 `run.bat`。首次运行会自动建虚拟环境并装依赖（几分钟），之后秒开。

浏览器会自动打开。点「开始」，允许麦克风权限，说话即有字幕。

> 手动启动（等价）：
> ```bash
> pip install -r requirements.txt
> python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
> ```

---

## 没有密钥？先用假数据看界面

在 `.env` 里加一行：

```
MOCK=1
```

此时不调用任何外部 API，识别和翻译都由本地假数据驱动，界面、滚动、术语匹配逻辑全部照常工作。适合先验收前端，或者演示当天 API 抽风时兜底。

---

## 分享给组员

```bash
python tools/pack_for_team.py
```

生成 `dist/CC0015-发给组员.zip`（约 0.2 MB，28 个文件），自动排除 `.env`、`keys.txt`、`.venv`、`logs`、原始 PDF。

打包前会扫描所有文件内容，发现疑似密钥就**中止打包**——排除名单可能漏，内容扫描不会。

组员拿到后：装 Python → 设自己的环境变量（或先用 `MOCK=1` 看界面）→ 双击 `run.bat`。

## 目录

```
app/
├── server.py            FastAPI 入口，WebSocket 桥接
├── asr.py               Deepgram 流式识别（含 Mock）
├── segmenter.py         语义分句
├── glossary.py          术语匹配（长词优先）
├── translate.py         翻译 + 术语约束
├── config.py            配置
└── static/              前端四件套
data/
└── glossary.json        267 条中英术语
docs/
├── implementation_zh.md 实现文档（中文）
└── implementation_en.md Implementation document (English)
tools/
├── build_glossary.py    从术语源重建 glossary.json
├── make_review.py       生成人工复核表
├── smoke_test.py        端到端冒烟测试（MOCK 模式）
└── fetch_deps.py        pip 装不上时的备用下载脚本
```

跑冒烟测试（不需要密钥）：

```bash
python tools/smoke_test.py
```

---

## 常见问题

**点开始没反应 / 没有麦克风权限**

地址必须是 `127.0.0.1` 或 `localhost`。用局域网 IP（`192.168.x.x`）打开时，浏览器出于安全策略不授予麦克风，且**不会报错**。

**有灰色文字但没有正式字幕**

说明识别在工作、分句没触发。正常说话说完整句即可；如果长时间不出，调小 `config.py` 里的 `SEG_MAX_WAIT`。

**字幕出得慢**

链路预算是 100 ms 缓冲 + 300 ms 识别 + 最长 1.2 s 分句 + 约 1 s 翻译。想更快就把 `SEG_MAX_WAIT` 调到 0.6。

**翻译不出现，只有原文**

看后端窗口日志。常见原因是 OpenAI 额度用完或密钥无效——程序会降级为只显示原文，不会中断。

**术语没被正确使用**

`glossary.json` 里的中文必须与识别文本完全一致（含标点差异）。识别把「肝阳上亢」听成「肝阳上抗」时匹配不到，这属于识别问题，不是术语表问题。

---

## 术语表

267 条，11 类，译法以 WHO《西太平洋地区传统医学名词术语国际标准》（2007）为准。

构建与校验过程见 `docs/implementation_zh.md` 第 9 节。待人工复核的清单在 `notes/glossary_review.md`。
