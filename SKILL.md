---
name: 文档翻译
description: >
  将外语文档专业翻译为简体中文，输出排版精良的 PDF 文件。自动处理 EPUB、PDF、DOCX、
  HTML、Markdown 等多种输入格式。当用户要求翻译文档、文章、论文、书籍、合同、
  规范文件时触发此 skill。也适用于 "翻译"、"translate"、"汉化"、"中译"
  等关键词。翻译后自动生成 PDF，用户无需手动排版。
---

# 文档翻译 Skill — 自动提取 → 翻译 → PDF 输出

## 架构说明

本 skill 是翻译流水线的**大脑**，你（主 agent）是**双手**。skill 定义做什么、怎么做、以什么标准做；你负责调用工具执行每一步。整个流水线由 skill 驱动，你的职责是忠实地执行以下指令，不即兴发挥。

```
Skill (大脑)                    Agent (双手)
─────────────                  ─────────────
SKILL.md → 指令集        →    你按指令调用工具
scripts/extract.py       →    你执行 python 命令
翻译原则 + 术语规范       →    你以此约束翻译输出
并行编排规则              →    你按规则 spawn Agent
scripts/to_pdf.py        →    你执行 PDF 生成
```

---

## 完整流水线（必须严格按顺序执行）

### 步骤 0: 准备

1. 确定输入文件路径、输出目录
2. 创建临时工作目录：`<输入文件所在目录>/translate-tmp/`
3. 安装依赖：`pip install fpdf2`

### 步骤 1: 提取源文本

```bash
python "<skill-dir>/scripts/extract.py" "<输入文件路径>" "<临时目录>/source.txt"
```

其中 `<skill-dir>` = `C:\Users\31905\AppData\Roaming\CherryStudioEnterprise\users\90396fe058e469c5\Data\Skills\translate-doc`

### 步骤 2: 翻译（根据文档长度选择策略）

#### 2A. 短文档 (source.txt ≤ 15000 字符)

直接翻译全文，输出为 `<临时目录>/translation.md`。

#### 2B. 长文档 (source.txt > 15000 字符) — 并行翻译编排

**这是 skill 的核心编排能力。** 你必须按以下规则执行：

##### 2B-1: 分章

读取 source.txt，按自然章节边界（如 "Chapter", "Part", "第X章", 或 EPUB 的 `# CHAPTER` 标记）拆分。

- 每章作为一个独立翻译单元，保持完整，**不对章节内部再做切分**
- 章节数 ≤ 2: 逐个翻译
- 章节数 ≥ 3: 使用并行 Agent 翻译

##### 2B-2: 建立术语表

在翻译开始前，快速浏览全文（前 200 行），提取关键术语并建立**术语对照表**。此表供所有并行 Agent 共享，确保术语一致性。

##### 2B-3: 生成翻译提示词

对每个章节，生成如下结构的翻译提示词，包含完整上下文：

```
你是资深专业翻译。请将以下英文/外文章节翻译为简体中文。

## 翻译原则
- 信达雅：准确第一，通顺自然，文体匹配
- 不增不减：原文没有的内容不添加，原文有的不遗漏
- 术语精准：使用下方术语对照表
- 英文长句拆分为符合中文阅读节奏的短句
- 被动语态尽量转为主动语态
- 代码块、公式、URL 不翻译
- 人名、地名、产品名保持原文，首译括注中文

## 术语对照表（全书统一）
| 原文 | 译文 | 说明 |
|------|------|------|
| ... | ... | ... |

## 输出格式
使用 Markdown，标题层级与原文一致（# → ## → ###）。
每个章节翻译完成后立即返回，不要等所有章节完成。

## 待翻译章节
[章节内容]
```

##### 2B-4: 并行启动 Agent

**同时**启动多个 Agent（使用 Agent 工具，`subagent_type="general-purpose"`），每个 Agent 翻译一个章节。所有 Agent 调用放在**同一条消息**中以实现真正的并行执行。

示例：
```
# 同时启动 3 个 Agent（同一条消息中）
Agent(description="翻译第1章", prompt="<完整翻译提示词 + 第1章内容>")
Agent(description="翻译第2章", prompt="<完整翻译提示词 + 第2章内容>")
Agent(description="翻译第3章", prompt="<完整翻译提示词 + 第3章内容>")
```

##### 2B-5: 合并译文

等待所有 Agent 返回后，按顺序合并：
1. 文档标题 + 作者信息
2. 按章节顺序拼接译文
3. 文末追加**术语对照表**

输出为 `<临时目录>/translation.md`。

##### 2B-6: 全书术语一致性检查

合并后，通读全文，检查术语是否一致。同一原文术语在全书中的译法必须统一。

### 步骤 3: 生成 PDF

```bash
python "<skill-dir>/scripts/to_pdf.py" "<临时目录>/translation.md" "<输出目录>/<文档名>-中文翻译.pdf"
```

如果 PDF 生成失败：
- 中文字体缺失：告知用户安装 SimSun / SimHei 或 Noto Sans CJK
- 提供 Markdown 文件作为备选

### 步骤 4: 清理与交付

1. 报告最终 PDF 文件路径和页数
2. 删除 `<临时目录>/` 下的临时文件
3. 如果文档较长，附上简要的章节概览

---

## 扫描版 PDF 处理（OCR 流水线）

当输入 PDF 经 `extract.py` 提取后文本为空或 gibberish 时，说明这是**扫描版（图片型）PDF**，必须走 OCR 流水线。

### OCR 步骤 0: 检测 PDF 类型

```bash
python -c "
import PyPDF2
r = PyPDF2.PdfReader('<输入文件路径>')
# 检查前 3 页是否有文本
for i in range(min(3, len(r.pages))):
    t = r.pages[i].extract_text()
    print(f'Page {i+1}: {len(t) if t else 0} chars')
"
```

如果所有页文本长度为 0 → 扫描版 PDF → 继续 OCR 步骤 1。

### OCR 步骤 1: 安装 OCR 依赖

```bash
pip install pymupdf pytesseract pillow opencv-python requests
```

**Tesseract 后端**（本地，免费）还需安装 Tesseract-OCR + 中文语言包 (chi_sim)：
- Windows: `winget install UB-Mannheim.TesseractOCR`
- 语言包: 下载 `chi_sim.traineddata` 放入 tessdata 目录

**DashScope 后端**（云端 API，质量更高）需要阿里云 DashScope API Key：
- 前往 [DashScope 控制台](https://dashscope.console.aliyun.com/) 创建 API Key
- 设置环境变量: `export DASHSCOPE_API_KEY=sk-xxxx`
- 或通过命令行参数 `--api-key sk-xxxx` 传入

### OCR 步骤 2: 执行 OCR

**方式一: Tesseract 本地 OCR**（适合现代印刷体文档）

```bash
python "<skill-dir>/scripts/ocr.py" "<输入文件路径>" -o "<临时目录>/source.txt" -d 300
```

**方式二: DashScope 云端 OCR**（推荐，适合老旧印刷/手写/复杂排版）

```bash
python "<skill-dir>/scripts/ocr.py" "<输入文件路径>" \
  -o "<临时目录>/source.txt" \
  --backend dashscope \
  --api-key sk-xxxx \
  -d 150 -w 5
```

参数说明：
- `--backend`: `tesseract`（默认）或 `dashscope`
- `--api-key`: DashScope API Key（或设置环境变量 `DASHSCOPE_API_KEY`）
- `--model`: 模型名称（默认 `qwen-vl-max`）
- `-d DPI`: 渲染分辨率（Tesseract 默认 300，DashScope 默认 150）
- `-w N`: 并行数（Tesseract 默认自动，DashScope 默认 5）
- `--dry-run`: 先测试前 3 页质量

**后端选择建议:**
| 场景 | 推荐后端 | 原因 |
|------|---------|------|
| 现代印刷文档 | Tesseract | 免费、本地、速度快 |
| 老旧印刷/繁体 | DashScope | 视觉模型识别率远超 Tesseract |
| 手写/模糊文档 | DashScope | 视觉理解能力强 |
| 离线环境 | Tesseract | 无需网络 |
| 高精度要求 | DashScope | qwen-vl-max 识别准确率 95%+ |

### OCR 步骤 3: 判断是否需要翻译

读取 OCR 结果的前 500 字符，判断语言：
- **已是中文** → 跳过翻译，直接进入 PDF 生成（步骤 4）
- **外文** → 按正常翻译流水线处理（步骤 2）

对于中文扫描文档，OCR 输出可能含有噪点字符。在生成 PDF 前做基本清理：
- 移除明显的 OCR 乱码行（连续 3 个以上非中文字符且无意义）
- 合并被错误断开的段落

### OCR 步骤 4: 生成 PDF

OCR 输出的 `source.txt` 是纯文本格式（以 `===== 第 N 页 =====` 分隔），需先转换为 Markdown 再生成 PDF：

```bash
# 第一步: 将 OCR 文本转为 Markdown（添加标题 + 章节标记）
python -c "
import re
with open('<临时目录>/source.txt', 'r', encoding='utf-8') as f:
    text = f.read()
text = re.sub(r'\`\`\`(?:text)?\s*', '', text)  # 移除代码块标记
md = '# <文档标题>\n\n' + re.sub(r'={3,}\n第 (\d+) 页\n={3,}', r'## 第 \1 页', text)
with open('<临时目录>/source.md', 'w', encoding='utf-8') as f:
    f.write(md)
"

# 第二步: 生成 PDF
python "<skill-dir>/scripts/to_pdf.py" "<临时目录>/source.md" "<输出目录>/<文档名>.pdf"
```

---

## 脚本依赖

脚本位于 `<skill-dir>/scripts/` 目录:
- `extract.py` — 从 EPUB/HTML/Markdown/TXT 提取文本 (Python 标准库，零依赖)
- `ocr.py` — 扫描版 PDF 的 OCR 提取 (支持 Tesseract 本地 OCR + DashScope 云端 OCR)
- `to_pdf.py` — Markdown 转 PDF (需要 `fpdf2` 包 + 系统中文字体)

安装全部依赖:
```bash
pip install fpdf2 pymupdf pytesseract pillow opencv-python requests
```

- Tesseract 后端: 系统还需安装 Tesseract-OCR + 中文语言包 (chi_sim)
- DashScope 后端: 需设置 `DASHSCOPE_API_KEY` 环境变量或通过 `--api-key` 传入

### 1. 信 (Accuracy) — 准确第一
- **不增不减**：原文没有的内容绝不添加，原文有的内容绝不遗漏。不擅自做"解释性补充"。
- **术语精准**：技术术语使用行业公认的中文译法，不确定的术语保留英文原词并括注中文。
- **专有名词**：人名、公司名、产品名、地名保持原文，首译时括注中文。
- **数字与单位**：完整保留，包括小数点和单位符号。

### 2. 达 (Fluency) — 通顺自然
- 符合中文表达习惯，避免翻译腔。例如 "This allows users to..." → "用户可以..." 而非 "这允许用户去..."。
- 英文长句拆分为符合中文阅读节奏的短句，但不可改变原文逻辑关系。
- 被动语态尽量转为主动语态。
- 代词还原：英文的 it/this/that 在中文中还原为具体指代对象。

### 3. 雅 (Appropriateness) — 文体匹配
- **哲学著作**：概念精准、逻辑严密，关键术语全书统一。
- **技术文档**：简洁、客观、精确，术语统一。
- **学术论文**：严谨、逻辑清晰，保留引用格式。
- **商业文档**：专业、得体，符合商务中文习惯。
- **法律合同**：极度精确，关键条款必要时保留原文对照。

## 格式处理规则

### 必须保留
- 数学公式、代码块（内容不翻译，仅翻译注释）
- 表格结构、引用编号、脚注编号
- 链接 URL、图片引用路径

### 可以翻译
- 段落文字、表格中的文字内容
- 链接的显示文本（URL 不变）
- 图片的 alt 文本

### 不确定时
- 追加 `[译者注：...]` 说明歧义
- 原文有明显错误时追加 `[译者注：原文此处可能有误，...]`

## 译文 Markdown 结构

```markdown
# [文档标题]

**作者/来源信息**

---

## [章节标题]

[翻译内容...]
```

## 术语对照表格式

翻译完成后在文末附术语对照表：

```
| 原文 | 译文 | 说明 |
|------|------|------|
| term | 术语 | 领域/上下文 |
```

---
