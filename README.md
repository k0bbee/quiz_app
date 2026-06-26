# Course Quiz Studio

基于 **PyQt6** 的通用课件导入与刷题桌面应用。支持从 PPTX/PDF/DOCX/Markdown 课件中提取主题、AI 生成双语题目、自然语言配置试卷、7 种题型自动判分、进度追踪和中英文切换。

## 环境要求

- Python 3.10+
- `requirements.txt` 中的 Python 依赖（PyQt6、requests、keyring、PyMuPDF、Pillow、pytesseract）
- Tesseract OCR 及 `eng`/`chi_sim` 语言包（可选，仅扫描版 PDF OCR 需要）

## 快速启动

```bash
python -m pip install -r requirements.txt
python scripts/check_environment.py
python main.py
```

`check_environment.py` 不读取或输出任何 API Key。它会检查 Python 版本、全部 Python 包、keyring backend、Windows DPAPI 回退、Tesseract/语言包和 `data/` 写权限。缺少启动必需项时返回非零退出码；缺少可选 Tesseract 时显示 `WARN`，其他功能仍可启动。启动应用后，也可以在 **设置 → 运行环境 → 检查环境** 查看同一份诊断和 OCR 补齐命令，或点击 **复制 OCR 修复命令** 直接把 Tesseract 安装与 `data/tessdata/` 语言包补齐提示复制到剪贴板。需要机器可读结果时使用：

```bash
python scripts/check_environment.py --json
```

## 使用流程

1. **导入课件** — 工具 → 课件管理 → 浏览，选择包含 pptx/pdf/docx/md/txt 的文件夹，自动解析生成课程摘要和主题列表
2. **AI 出题**（可选）— 每门课程会生成独立默认数量、主题、模板和权重；也可以手动调整或打开“试卷助手”，用自然语言继续修改
3. **开始练习** — 从题目集中选题，支持单选/判断/配对/排序/填空/简答/情景题
4. **查看进度** — 总览答题次数、正确率、按主题统计

## 功能

| 功能 | 说明 |
|---|---|
| 📚 **课件管理** | 导入任意课程文件夹，自动提取主题和摘要 |
| 📝 **题目集练习** | 按主题/难度筛选题目集，随机出题 |
| 🤖 **AI 出题** | 调用 LLM API 基于课件内容生成双语题目 |
| 💬 **试卷助手** | 用自然语言调整数量、主题、模板、题型和难度权重，确认后再应用 |
| 🧭 **课程默认配置** | 根据每门课程的主题和总结生成独立出题方案，打开出题窗口时自动预填 |
| 🎯 **错题复习** | 聚合所有历史错题，针对性重练 |
| 📊 **进度面板** | 总览练习统计、按主题正确率、近期记录 |
| 🗂 **题库管理** | 查看/编辑/新建/删除单道题目，支持分页搜索 |
| ⚙ **设置** | 中英文切换、API Key/模型/端点配置、练习默认题量/难度/计时器/出题模板、环境检查、进度导入导出 |
| 🌐 **双语切换** | 全界面实时中英切换，题目同时显示双语版本 |

## 答题界面

- 提交后**自动判分**（单选、判断、配对、排序、填空）
- 简答题标记为需人工审核
- 每题附带**中英双语解析**
- 练习中途**随时切换语言**
- 快捷键：`1-9` 选选项，`Enter` 提交/下一题，`Esc` 退出
- 退出时**自动保存草稿**，不丢失已答记录

## 目录结构

```
quiz_app/
├── main.py              # 入口
├── config.py            # 路径与默认配置
├── style.qss            # VS Code Dark 风格主题与语义控件样式
├── ai/                  # LLM 调用、提示词、批量生成
├── core/                # 判分引擎、状态机、文档解析、主题提取
├── models/              # 题目、题目集、进度、课程项目
├── ui/
│   ├── screens/         # 8 个页面（首页/选题/答题/结果/进度/设置/课件/题库）
│   ├── dialogs/         # AI出题对话框、题目审核对话框
│   └── widgets/         # 答题区、题目卡片、进度条等可复用组件
├── scripts/             # 环境自检等维护脚本
├── utils/               # JSON读写、日志、常量
├── data/                # 🚫 运行时数据（题库/进度/课程/设置）
├── tests/               # 单元测试
└── requirements.txt
```

## AI 配置

| 提供商预设 | 说明 |
|---|---|
| Anthropic | 原生 Messages API |
| OpenAI 兼容 | 硅基流动、DeepSeek 等第三方端点 |
| Local CLI Agent | 免 API Key，调用本地 claude/codex CLI |

API Key 读取优先级：环境变量 `QUIZ_APP_API_KEY` → 系统密钥环 → Windows DPAPI 加密存储。设置页不会回显已有密钥；空输入表示保持不变，只有输入新值才会更新，清除操作需要单独确认。

新密钥会立即进入当前应用会话，并优先持久化到系统密钥环。Windows 上没有可用 `keyring` 后端时，会自动写入 `data/.api_key.dpapi`；文件内容由 Windows DPAPI 加密并绑定当前系统用户，不能复制到其他用户或机器直接解密。仅在密钥环和 DPAPI 都不可用时才退化为当前会话存储。密钥不会自动写入 `data/settings.json`。程序仍可读取旧版本留下的明文字段用于迁移，但下一次显式更新或清除密钥会移除该字段。

可通过 `python scripts/check_environment.py` 查看当前 keyring backend。Windows 正常安装 `keyring` 后通常会显示 `keyring.backends.Windows.WinVaultKeyring`；如果该后端不可用，程序会自动使用 DPAPI，不需要重新输入密钥。

远程 LLM 端点必须使用 `https://`。只有 `localhost`、`127.0.0.1` 或 `::1` 上的本机兼容服务可以使用 `http://`；包含用户名/密码、缺少主机或使用其他协议的 URL 会在设置测试和实际请求前被拒绝。

点击设置页的“测试 AI 设置”会先做本地配置校验，再在后台向当前提供商发送一个最小 JSON 连接探测请求。探测请求不包含课程内容、题库、学习记录或 API Key 文本，只要求模型返回 `{"ok": true}`，用于确认端点、模型和密钥是否真实可用。远程提供商可能仍会把这次探测计入一次很小的请求/Token 消耗；测试过程中设置按钮会暂时禁用，完成后会在页面上显示成功或失败原因。

### 自然语言试卷助手

在“AI 出题”窗口点击“试卷助手…”即可输入连续要求，例如：

```text
出 20 道期末模拟题，cache 和 process 为主，困难题占 40%。
判断题少一点，题目总数改成 25 道。
```

助手不会把自由对话直接拼接到题目生成提示中。远程 LLM 只能返回受限 JSON 配置补丁，程序会在本地校验字段、数量范围、模板、课程主题和权重，并在右侧显示本轮差异；只有点击“应用配置”后才会写回出题参数。

为了避免本地 CLI 代理潜在的文件或命令工具接触自由文本，选择 `Local CLI Agent` 时，试卷助手使用本地确定性规则解析常见的中英文数量、难度、模板、主题和比例要求。题目生成本身仍可继续使用已选择的本地代理。

### 每门课程的默认出题配置

课程初始化和“重新生成总结”会同时更新该课程的默认出题档案，包括题目数量、整体难度、模板、默认知识点、题型权重、难度权重和知识点权重。配置了可用的远程 LLM 时，LLM 会基于课程主题和总结提出建议，程序再用本地白名单和范围规则校验后保存。

LLM 不可用、返回非法 JSON 或引用不存在的知识点时，不会阻止课程导入。程序会保存确定性的本地方案，并在完成提示和课程项目中记录回退原因。默认配置只负责预填，用户仍可在出题窗口手动修改；重新生成已有题目集时，该题目集自己的历史配置优先。

## 支持的文件格式

| 格式 | 说明 |
|---|---|
| `.pptx` | PowerPoint 幻灯片，按页提取文本 |
| `.pdf` | PDF 文本提取；无可提取文本的页面会尝试 OCR fallback |
| `.docx` | Word 文档 |
| `.txt` / `.md` | 纯文本/Markdown |

### OCR fallback 配置

PDF 页面没有可提取文本时，程序会用 `PyMuPDF` 渲染页面，再通过 `Pillow` 和 `pytesseract` 尝试 OCR。`requirements.txt` 会安装这些 Python 依赖，但还必须单独安装 **Tesseract OCR** 系统程序，并确保 `tesseract` 可执行文件位于 `PATH`。

Windows 推荐补齐入口：

```powershell
winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
```

如果使用 Chocolatey，可选：

```powershell
choco install tesseract
```

安装后重新打开终端或 VS Code，再运行 `python scripts/check_environment.py`。如果仍提示缺少 `chi_sim`，请在 Tesseract 安装器中补选 Chinese Simplified 语言数据，或从 Tesseract tessdata 来源补齐 `chi_sim.traineddata`。没有管理员权限写入 `C:\Program Files\Tesseract-OCR\tessdata` 时，也可以把 `eng.traineddata` 和 `chi_sim.traineddata` 放到本项目的 `data/tessdata/`；程序和环境检查会优先使用这个可写目录。

中英文课件需要安装 Tesseract 的 `eng` 和 `chi_sim` 语言包。可用以下命令确认：

```bash
tesseract --list-langs
```

当前 OCR fallback 面向扫描版或图片型 PDF 的空文本页；PPTX/DOCX 中的嵌入图片暂不执行 OCR。OCR 不可用或识别失败时，课程完成提示和课程总结会保留对应警告，其他成功解析的资料仍可继续使用。

## 常见环境问题

| 自检结果 | 影响与处理 |
|---|---|
| Python 包显示 `FAIL` | 运行 `python -m pip install -r requirements.txt`，再执行 `python -m pip check` |
| keyring backend 显示 `WARN` | Windows 会使用 DPAPI 加密文件；其他系统需配置可用 keyring 后端，否则密钥仅当前会话有效 |
| Tesseract OCR 显示 `WARN` | 仅扫描 PDF OCR 不可用；按自检输出的 `Fix:` 命令安装 Tesseract，或使用 `winget install -e --id UB-Mannheim.TesseractOCR` / `choco install tesseract`，并确保 `eng`、`chi_sim` 可在安装目录或 `data/tessdata/` 中找到 |
| data directory 显示 `FAIL` | 确保应用目录及 `data/` 对当前用户可写 |

## 运行测试

```bash
python -m pytest tests/ -v
```
