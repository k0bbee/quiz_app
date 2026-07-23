# Security Policy

[简体中文](SECURITY.md) | [English](SECURITY.en.md)

## Supported versions

AI课程刷题软件 is currently developed as a rolling desktop application rather than a set of long-lived release branches.

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

## Data boundaries

- `.quizdata` bundles may contain private courses, questions, and progress and must not be attached to public vulnerability reports.
- Custom AI endpoints receive the configured credential and selected course context only after explicit local configuration. Requests do not follow redirects, and response bodies have a fixed limit.
- Local-agent execution is capability-constrained: tools, session persistence, and project loading are disabled, and the process runs in an isolated work directory. CLI agents without a verified no-tools mode are rejected, and output pipes are drained under a fixed budget.
- Symbolic links and resolved paths outside the selected course folder are not read. Course file count, total source bytes, Office members/pages, and extracted text all have resource budgets.
- Oversized, over-populated, or suspiciously compressed `.quizdata` bundles are rejected before application data is written.
