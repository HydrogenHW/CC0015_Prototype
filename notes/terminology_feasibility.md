# 中医术语表：可行性核查（2026-10-20）

## 目标

为"中英互译实时字幕"提供一份**中→英**的领域术语对照表，用于锁定译法。

## 核查结果

### ✅ 已获得：WHO 2007 国际标准正本

- 全名：*WHO International Standard Terminologies on Traditional Medicine in the Western Pacific Region*
- 获取路径：WHO IRIS `handle/10665/206952` 已下线，经 Wayback Machine 存档取得
- 文件：`data/raw/who_2007.pdf`（2.2 MB）
- 收录约 **3,952 条**术语（原文自述："commonly used terms ... estimated to be more than 4000, most of which are included"）
- 结构：`Code | Term(英) | Chinese(中) | Definition(英)`，8 大章（GENERAL / BASIC THEORIES / DIAGNOSTICS / THERAPEUTICS ...）

### ❌ 硬伤一：中文列无法用程序提取

PDF 的中文字体**没有 ToUnicode 映射**，所有 PDF 文本工具（pdftotext -layout / -table / -lineprinter）提取出的中文列都是空白。

已验证：全文仅 27 行含中文字符，且全是页码装饰符与英文人名，**不是术语本身**。

→ 结论：**这份 PDF 只能提供"英文标准译法"，提供不了"中文原文"**。要做中英对照，只能 OCR，或另找来源。

### ❌ 硬伤二：ISN 是商业出版物

- 全名：*International Standard Chinese-English: Basic Nomenclature of Chinese Medicine*（ISN）
- 世界中医药学会联合会编，人民卫生出版社 2008，ISBN 978-7-117-09356-9
- 收录 **6,526 条**，21 分类，含中文 + 拼音 + 英文 —— 这才是我原本想要的
- 但它是 Ovid 平台上的**付费图书**，无公开电子版

### 附带发现

- 该标准的编制主要参考书是谢竹藩《中医药常用名词术语英译》（中国中医药出版社 2004），同属付费出版物
- 国家标准 GB/T 20348-2006《中医基础理论术语》为纯中文，无英文对照
- 网上零散的中英对照表（术语在线、期刊附表等）条目不足百条，不成体系

## 结论

**"直接下载一份 4000 条中英对照表"这条路走不通。**

## 替代方案（推荐）

不要追求全量覆盖，改做**高频核心词表**：

| 做法 | 说明 |
|---|---|
| 规模 | 200–300 条，覆盖课堂实际出现频率 80%+ |
| 范围 | 阴阳五行 / 脏腑 / 气血津液 / 四诊 / 八纲 / 常用证型 / 常用方剂 / 常用穴位 |
| 生成 | 由 LLM 产出"中文→英文"候选（WHO 标准在网上被广泛引用，模型掌握良好） |
| 校验 | 用已获得的 WHO 英文术语集人工/程序交叉比对，确认译法落到标准用词上 |
| 审核 | 人工抽查 50 条，错误率控制在 5% 以内 |
| 工时 | 约 1 天 |

**这条路对 assignment 反而更有利**：术语表的构建方法本身就能写成一节（语料来源、抽取规则、校验流程、覆盖度），比"我下载了个表"有内容得多。

## 待办

- [ ] 确认 interviewee 的实际课堂用词（决定词表范围，比通用表更重要）
- [ ] 用 LLM 生成候选词表 200–300 条
- [ ] 与 WHO 英文术语集交叉校验
- [ ] 人工抽查并定稿为 `data/glossary.json`（双向索引）
