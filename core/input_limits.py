"""Centralised resource-budget constants and error type for untrusted input.

Every constant is defined here so that all limits are reviewable in one file.
"""

from __future__ import annotations


class InputLimitError(ValueError):
    """Untrusted input exceeded a declared resource budget."""

    def __init__(self, code: str, message_zh: str, message_en: str):
        super().__init__(f"[{code}] {message_en}")
        self.code = code
        self.message_zh = message_zh
        self.message_en = message_en


# ── ZIP / archive budgets (used by app_data_bundle) ────────────────

MAX_BUNDLE_ARCHIVE_BYTES = 512 * 1024 * 1024    # 512 MiB compressed on disk
MAX_BUNDLE_MANIFEST_BYTES = 64 * 1024            # 64 KiB
MAX_BUNDLE_MEMBERS = 5_000
MAX_BUNDLE_ENTRY_BYTES = 256 * 1024 * 1024      # 256 MiB (matches MAX_DOCUMENT_BYTES)
MAX_BUNDLE_TOTAL_BYTES = 1024 * 1024 * 1024     # 1 GiB
MAX_ZIP_COMPRESSION_RATIO = 200  # advisory warning only — not a blocking gate

# ── Document budgets (used by document_parser & past_exam_importer) ─

MAX_DOCUMENT_BYTES = 256 * 1024 * 1024           # 256 MiB
MAX_COURSE_SOURCE_FILES = 2_000
MAX_COURSE_SOURCE_BYTES = 1024 * 1024 * 1024     # 1 GiB per initialization
MAX_OFFICE_ARCHIVE_MEMBERS = 10_000
MAX_OFFICE_XML_ENTRY_BYTES = 32 * 1024 * 1024    # 32 MiB
MAX_OFFICE_XML_TOTAL_BYTES = 256 * 1024 * 1024   # 256 MiB
MAX_PPTX_SLIDES = 2_000
MAX_PDF_PAGES = 2_000
MAX_RENDER_PIXELS = 40_000_000
MAX_EXTRACTED_TEXT_CHARS = 20_000_000
OCR_PAGE_TIMEOUT_SECONDS = 60
