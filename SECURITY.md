# Security Policy

## Supported versions

AI课程刷题器 is currently developed as a rolling desktop application rather than a set of long-lived release branches.

| Version | Security fixes |
|---|---|
| Latest release | Supported |
| Current `main` branch | Supported |
| Older releases and commits | Not supported; reproduce against the latest version first |

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue, discussion, pull request, screenshot, log, or course-data sample.

Use the repository's **Security → Report a vulnerability** action to create a private GitHub security advisory. If private vulnerability reporting is not available, open a public issue titled `[Security contact request]` containing only a request for a private reporting channel. Do not include technical details, credentials, personal information, or proof-of-concept material in that issue.

A useful private report includes:

- The affected version or commit.
- The operating system and Python version.
- The affected component and required configuration.
- Reproduction steps with sanitized test data.
- The expected and observed security boundary.
- The likely impact and any known mitigations.
- A minimal proof of concept that contains no real API key, private course material, or personal data.

Reports will be acknowledged as soon as practical. The maintainer may request additional reproduction details, coordinate a fix and release, and credit the reporter if requested. Please allow time for remediation before public disclosure.

## Security-sensitive areas

Reports are especially useful when they involve:

- API-key storage, retrieval, migration, or accidental logging.
- Windows DPAPI or system-keyring fallback behavior.
- `.quizdata`, course, question-bank, or progress import path traversal and unsafe archive handling.
- Untrusted PDF, PPTX, DOCX, Markdown, JSON, or generated HTML content.
- Remote LLM endpoint validation, request routing, or credential exposure.
- Local CLI Agent command, argument, environment, stdin, or file-access boundaries.
- Unsafe file opening, source navigation, or URL handling.
- Cross-course data isolation, destructive deletion, or unintended export of private material.
- Dependency vulnerabilities with a demonstrated impact on this application.

## Out of scope

The following are normally not treated as vulnerabilities without a demonstrated security impact:

- Model hallucinations, low-quality generated questions, or inaccurate course summaries.
- Availability or behavior of third-party LLM and OCR services.
- Attacks that require a user to deliberately disable operating-system protections or modify the application source.
- Reports based only on automated scanner output without a reproducible application impact.
- Secrets or private documents that a user intentionally enters into an untrusted third-party endpoint.

## Handling sensitive test material

Use synthetic content whenever possible. Redact API keys, usernames, local paths, course documents, student records, and provider responses before sharing logs or screenshots. Never commit a live key or private course file as a regression fixture.

If a credential may have been exposed, revoke or rotate it immediately. Removing it from the latest commit is not sufficient when it exists in Git history.

## 安全问题报告（中文）

请不要在公开 Issue、Discussion、PR、截图或日志中披露漏洞细节。优先通过仓库 **Security → Report a vulnerability** 创建私密安全报告。如果该入口尚未启用，只创建标题为 `[Security contact request]` 的公开 Issue，请求私密联系方式；Issue 中不要包含复现步骤、密钥、个人信息、课件内容或攻击样例。

提交材料应尽量使用合成数据，并清除 API Key、用户名、本地路径、课程资料、学生记录和第三方服务响应。若怀疑密钥已经泄露，应立即在对应服务商处撤销或轮换；仅从最新提交中删除并不能清除 Git 历史中的密钥。
