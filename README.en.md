# AI课程刷题软件 (AI Course Quiz)

[简体中文](README.md) | [English](README.en.md)

A general-purpose **PyQt6** desktop application for turning course materials into structured study content and quizzes. It can import PPTX, PDF, DOCX, Markdown, and plain-text materials, infer stable course topics, generate bilingual questions with an LLM, track progress, and switch the entire interface between Chinese and English.

## Requirements

- Python 3.10+
- Python packages from `requirements.txt`, including PyQt6, requests, keyring, pypdfium2, Pillow, and pytesseract
- Optional: Tesseract OCR with the `eng` and `chi_sim` language packs for scanned PDFs

## Quick start

```bash
python -m pip install -r requirements.txt
python scripts/check_environment.py
python main.py
```

`requirements.txt` declares supported development floors. To reproduce the audited Windows release environment, install the exact lock instead:

```bash
python -m pip install -r requirements-release.txt
```

The environment checker never reads or prints API keys. It verifies Python and package versions, the keyring backend, the Windows DPAPI fallback, Tesseract and its language packs, and write access to `data/`. Missing startup requirements produce a non-zero exit code; missing optional OCR support produces a warning.

For machine-readable diagnostics:

```bash
python scripts/check_environment.py --json
```

## Typical workflow

1. **Import course materials** — Open Course Management and select a folder containing PPTX, PDF, DOCX, Markdown, or text files.
2. **Review the course summary and topics** — The application extracts document text, creates a summary, assigns stable topic IDs, and builds page- or slide-level source references.
3. **Choose the exam scope** — Use every topic or select only the topics relevant to the current exam.
4. **Review current-event materials** (optional) — Explicitly search a public news index, inspect source and course relevance, and select individual items; opening the dialog never starts a search.
5. **Generate questions** — Use course defaults, adjust question type/topic/difficulty weights, or describe the desired paper in natural language.
6. **Review generated questions** — Check bilingual content, answers, source evidence, plan matching, and quality warnings before accepting questions.
7. **Practice or simulate an exam** — Practice mode grades one question at a time; exam mode saves drafts and submits the whole paper at the end.
8. **Review progress** — Inspect accuracy, topic mastery, uncertain answers, marked questions, and prioritized incorrect-question review.

## Main capabilities

| Area | Capability |
|---|---|
| Home | A transparent next-action recommendation based on unfinished drafts, incorrect answers, weak topics, available question sets, and imported courses |
| Course management | Multi-file course import, safe cancellation, summaries, stable topics, course renaming, exam-scope configuration, and source navigation |
| Past exams | Import TXT/Markdown/PDF/DOCX/PPTX exams, apply OCR to scanned PDFs, assign a course, and build explainable exam profiles |
| Question generation | Stream accepted questions one at a time, validate plan slots and source references, accept additional instructions while generation is running, and safely preserve partial results on cancellation |
| Q&A review | Ask follow-up questions inside the selected course workspace using only the current exam scope, course summary, and original source evidence; requests remain cancellable and non-blocking |
| Current-event materials | Explicitly search and manually review public news candidates, including low-relevance results; only selected items enter generation, and review metadata remains attached to generated questions |
| Background tasks | Show long-running task stages and failures; Open Task Page only navigates, orphaned tasks become interrupted after restart, and Retry restores validated inputs only when recovery metadata is complete |
| Question types | Multiple choice, true/false, scenario choice, matching, ordering, fill-in-the-blank, and short answer |
| Question bank | Search and filter by set, topic, difficulty, and quality; create or edit every question type; multi-select and batch-delete questions |
| Question sets | Rename sets, select multiple topics, create random practice sets, regenerate questions, and export one or more mock exams as UTF-8 Markdown |
| Quiz sessions | Practice/exam modes, free previous/next navigation, paper preview on demand, uncertain/review markers, keyboard controls, and complete draft recovery |
| Progress | Course-scoped statistics, mastery overrides, prioritized review, topic actions, and full progress reset |
| Data portability | Export/import `.quizdata` packages containing courses, question banks, question sets, past-exam assets, drafts, progress, mastery overrides, and non-sensitive settings |
| Settings | Open the utility entry at the bottom of the sidebar in a separate window without replacing the current study workspace |
| Localization | Live Chinese/English UI switching with bilingual question content and explanations |

Course-folder imports skip symbolic links and resolved paths outside the selected folder. One import accepts at most 2,000 supported files and 1 GiB of source data; larger collections must be split before import.

## Weight configuration

Question type, difficulty, and topic values are relative weights. Users do not need to make them sum to 100. For example, raw topic weights of `100` and `80` become effective shares of approximately `56%` and `44%`.

The generation dialog only displays currently selected topics. Effective percentages update after confirmation, avoiding confusing live `old → new` displays while controls are still being edited.

All seven question types are supported. Matching, ordering, and short-answer questions are grouped as advanced types and default to zero weight so existing ordinary-generation profiles are not changed unexpectedly.

Short answers do not pretend to have reliable automatic semantic grading. Practice mode shows the submitted answer, reference answer, and explanation, then asks for self-assessment. Exam mode collects short-answer assessments after the paper is submitted.

## Course exam scope

Each course can use all inferred topics or a selected subset. The selection is stored with stable topic IDs, so renaming a topic does not lose the scope. Topics removed by a later summary regeneration are safely removed from the effective scope.

The scope constrains AI generation, past-exam prediction, home-page recommendations, and incorrect-question review. It does not delete or hide historical questions, sets, progress, or drafts.

## Q&A review

Select a course and switch the right-hand workspace directly between the course summary and Q&A review. This does not open a separate mode dialog or add another top-level navigation item. Answers reuse the current exam scope, stable topic IDs, and page-level source index. Questions that explicitly target an out-of-scope topic are rejected with an actionable scope message instead of silently introducing outside material.

The conversation keeps only recent context during the current application session. A failed question returns to the input field, stopping a request discards any late response, and the UI remains responsive while the provider is working. `Enter` sends; `Shift+Enter` inserts a new line. Remote providers receive the necessary in-scope summary, source excerpts, and recent turns only after the user sends a question.

## Quiz behavior

- Practice mode grades the current question without automatically advancing.
- Exam mode lets users move freely and submits drafts together at the end.
- Matching questions require every pair; unchanged default ordering receives a confirmation prompt.
- Questions may be marked **uncertain** or **review later**.
- The result screen distinguishes incorrect, skipped, uncertain-but-correct, and review-marked questions.
- Exiting an unfinished session saves its question order, position, submitted answers, draft input, mode, and markers.
- Keyboard shortcuts: `1-9` select an option, `Enter` activates the current primary action, and `Esc` exits.

## AI configuration

| Provider preset | Description |
|---|---|
| Anthropic | Native Messages API |
| OpenAI-compatible | Compatible endpoints such as DeepSeek or SiliconFlow |
| Local CLI Agent | Uses Claude CLI only in restricted no-tools mode; set `ANTHROPIC_API_KEY` before starting the app. Prompts are sent through stdin, while detected Codex CLIs are rejected because no verified no-tools boundary is available |

API key lookup order:

1. `QUIZ_APP_API_KEY` environment variable
2. System keyring
3. Windows DPAPI-encrypted local fallback
4. Current process memory only

The settings page never displays an existing key. An empty key field keeps the current key; replacing or clearing it requires an explicit action. Keys are not stored in `data/settings.json` and are excluded from `.quizdata` exports. Keyring failures are reported without displaying raw backend exception text. If cleanup of a legacy plaintext key cannot be written to disk after secure migration, the application explicitly reports the remaining plaintext risk.

Remote LLM endpoints must use `https://`. Plain `http://` is accepted only for `localhost`, `127.0.0.1`, or `::1`. URLs containing embedded credentials, missing a host, or using another protocol are rejected before any request is sent. LLM requests do not follow HTTP redirects, and response bodies are capped at 16 MiB so an abnormal endpoint cannot keep forwarding credentials/course content or consume unbounded memory.

The connection test sends only a minimal JSON probe. It does not include course materials, questions, progress, or the API key text, although a remote provider may still bill the small request.

### Generation and review

Generation advances through explicit plan slots. Each request accepts at most one qualified question for the current target, while a small candidate pool compensates for model drift. A question is accepted only after local checks for type, difficulty, topic, structure, source evidence, and plan matching.

Accepted questions appear immediately. Users can append instructions that apply to later requests, cancel safely, or keep partial accepted results. Truncated JSON output automatically retries with smaller candidate batches. Persistent truncation is reported as `GEN-AI-JSON-001`.

Source references returned by the model are checked against the current retrieved-evidence registry. Forged or unrelated IDs are rejected; trusted source statuses without actual source references are reported as quality errors.

### Natural-language exam assistant

The exam assistant converts instructions such as the following into a reviewable configuration patch:

```text
Create a 20-question final exam focused on cache and processes, with 40% hard questions.
Reduce true/false questions and change the total to 25.
```

Remote models may only return a restricted JSON patch. The application validates fields, limits, templates, course topics, and weights locally. Nothing changes until the user applies the patch.

For a Local CLI Agent, common Chinese and English instructions are interpreted with deterministic local rules so free text is not exposed to command or file tools.

## Supported course files

| Format | Handling |
|---|---|
| `.pptx` | Extract text per slide; at most 10,000 ZIP members and 2,000 slides per file |
| `.pdf` | Extract text per page and attempt OCR on pages without extractable text; at most the first 2,000 pages per file |
| `.docx` | Extract Word document content |
| `.txt` / `.md` | Read UTF-8 text and Markdown |

### OCR fallback

When a PDF page contains no extractable text, the application renders it with pypdfium2 and tries OCR through Pillow and pytesseract. Install Tesseract separately on Windows:

```powershell
winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
```

Then reopen the terminal and run:

```bash
python scripts/check_environment.py
tesseract --list-langs
```

Both `eng` and `chi_sim` are recommended for bilingual material. Language data may also be placed in the writable `data/tessdata/` directory. OCR warnings are preserved in the course project and summary without discarding successfully extracted pages.

Embedded images inside PPTX and DOCX files are not currently sent through OCR.

## Project layout

```text
quiz_app/
├── main.py              # Application entry point
├── config.py            # Paths and defaults
├── style.qss            # Shared UI theme
├── ai/                  # LLM clients, prompts, planning, generation pipeline
├── core/                # Parsing, grading, validation, tasks, progress, migration
├── models/              # Courses, questions, sets, sessions, progress
├── ui/                  # Screens, dialogs, and reusable widgets
├── scripts/             # Environment checks and maintenance tools
├── utils/               # JSON I/O, logging, constants
├── data/                # Local runtime data; ignored by Git
├── tests/               # Unit, integration, and Qt UI tests
└── requirements.txt
```

## Running tests

```bash
# Core tests suitable for CI or systems without PyQt6
python -m pytest -m "not qt" -q

# Qt/UI tests
python -m pytest -m qt -q

# Default regression suite (skips large fixture rebuilds and complete UI workflows)
python -m pytest tests/ -q

# Release validation, including tests marked as full
python -m pytest tests/ -q --run-full
```

`tests/conftest.py` identifies tests that import PyQt6 and marks them as `qt`. If PyQt6 is unavailable, those modules are skipped during collection so core tests can still run. Cross-discipline fixture rebuilds, CLI audits, and complete UI quiz workflows are marked as `full`; they are skipped by default and run only when `--run-full` is supplied.

## Security and privacy

- Do not commit API keys, private course materials, generated runtime data, or exported study packages.
- API keys are excluded from application-data exports.
- Imported course content is sent to a remote provider only when the user explicitly runs an AI operation configured for that provider.
- See [SECURITY.en.md](SECURITY.en.md) for private vulnerability reporting and the supported-version policy.

## License

This project is distributed under the [GNU General Public License v3.0 only](LICENSE).
See [COPYRIGHT.md](COPYRIGHT.md) for the boundary between project-original and third-party material, and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for direct dependencies and significant runtimes.
