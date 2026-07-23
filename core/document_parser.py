"""Document extraction for course initialization.

Supported formats are intentionally handled with lightweight local parsers:
PPTX/DOCX through their zipped XML payloads, text/Markdown directly, and PDF
through pypdfium2.
"""

from __future__ import annotations

import os
import re
import hashlib
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from core.ocr_runtime import configure_pytesseract
from core.background_task import TaskControl


SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt", ".md"}


@dataclass
class ExtractedDocument:
    """Text extracted from one source document."""

    path: str
    title: str
    extension: str
    text: str = ""
    pages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\w+", self.text))


class DocumentParser:
    """Parse a folder of course files into plain text documents."""

    _MAX_FILE_CACHE_SIZE = 128
    _FILE_CACHE: dict[tuple[str, int, int], ExtractedDocument] = {}

    # Directories to skip during recursive scan (generated output, not source)
    _SKIP_DIRS = {"__pycache__", ".git", ".claude", "node_modules",
                  "data", "generated", ".venv", "venv", "env", ".idea", ".vscode"}
    _SKIP_FILE_PATTERNS = [
        r"^diff(?:[-_].*)?\.(md|txt)$",
        r"^results(?:[-_].*)?\.(md|txt)$",
        r"^details\.(md|txt)$",
        r"^course-.*_summary\.md$",
        r"^模拟卷_\d+\.md$",
        r"^quiz备选清单\.md$",
        r"^课程内容\.md$",
        r"^复习辅助\.md$",
    ]

    def parse_folder(
        self,
        folder: str,
        task: TaskControl | None = None,
        cached_documents: dict[str, ExtractedDocument] | None = None,
        on_document_parsed: Callable[[Path, ExtractedDocument], None] | None = None,
    ) -> list[ExtractedDocument]:
        """Parse supported files under a folder recursively.

        Automatically skips common generated-output directories (data/, __pycache__/,
        .git/, etc.) to avoid ingesting the app's own output.
        """
        root = Path(folder)
        paths = self.source_paths(folder)
        if task is not None:
            task.report("files_found", total=len(paths), detail=str(root))

        docs: list[ExtractedDocument] = []
        cached_documents = cached_documents or {}
        seen_fingerprints: set[str] = set()
        seen_signatures: list[set[str]] = []
        for index, path in enumerate(paths, start=1):
            cached = cached_documents.get(str(path.resolve()))
            if cached is not None:
                if task is not None:
                    task.report("reusing_file", index, len(paths), path.name)
                doc = _clone_document(cached)
            else:
                if task is not None:
                    task.report("parsing_file", index, len(paths), path.name)
                doc = self.parse_file(path, task=task)
                if on_document_parsed is not None:
                    on_document_parsed(path, _clone_document(doc))
            if _is_auxiliary_text_document(doc):
                continue
            fingerprint = _content_fingerprint(doc.text)
            if fingerprint:
                if fingerprint in seen_fingerprints:
                    continue
                signature = _content_signature(doc.text)
                if signature and _is_near_duplicate(signature, seen_signatures):
                    continue
                seen_fingerprints.add(fingerprint)
                if signature:
                    seen_signatures.append(signature)
            docs.append(doc)
        return docs

    def source_paths(self, folder: str) -> list[Path]:
        """Return supported source files in the same stable order used for parsing."""
        root = Path(folder)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        return [
            path
            for path in sorted(root.rglob("*"), key=_source_sort_key)
            if path.is_file()
            and not path.name.startswith("~$")
            and not self._should_skip_path(path, root=root)
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

    def _should_skip_path(self, path: Path, root: Path | None = None) -> bool:
        """Return True if a path is clearly generated output or app metadata."""
        parents = path.parents
        if root is not None:
            try:
                parents = path.relative_to(root).parents
            except ValueError:
                pass
        if any(p.name in self._SKIP_DIRS for p in parents):
            return True
        name = path.name.lower()
        return any(re.match(pattern, name, flags=re.IGNORECASE) for pattern in self._SKIP_FILE_PATTERNS)

    def parse_file(self, path: Path, task: TaskControl | None = None) -> ExtractedDocument:
        """Parse one supported file."""
        path = Path(path)
        ext = path.suffix.lower()
        title = path.stem
        cache_key = _file_cache_key(path)
        if task is not None:
            task.check_cancelled()
        if cache_key in self._FILE_CACHE:
            return _clone_document(self._FILE_CACHE[cache_key])

        from core.input_limits import MAX_DOCUMENT_BYTES
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            return ExtractedDocument(
                str(path), title, ext,
                warnings=[f"File exceeds size limit ({MAX_DOCUMENT_BYTES} bytes)"],
            )

        if ext in {".txt", ".md"}:
            doc = self._parse_text(path)
        elif ext == ".pptx":
            doc = self._parse_pptx(path, task=task)
        elif ext == ".docx":
            doc = self._parse_docx(path)
        elif ext == ".pdf":
            doc = self._parse_pdf(path, task=task)
        else:
            doc = ExtractedDocument(str(path), title, ext, warnings=[f"Unsupported file type: {ext}"])

        if ext in SUPPORTED_EXTENSIONS:
            self._FILE_CACHE[cache_key] = _clone_document(doc)
            _trim_file_cache(self._FILE_CACHE, self._MAX_FILE_CACHE_SIZE)
        return doc

    def _parse_text(self, path: Path) -> ExtractedDocument:
        from core.input_limits import MAX_DOCUMENT_BYTES
        with path.open("rb") as source:
            raw = source.read(MAX_DOCUMENT_BYTES + 1)
        warnings = []
        if len(raw) > MAX_DOCUMENT_BYTES:
            raw = raw[:MAX_DOCUMENT_BYTES]
            warnings.append(
                f"Text file grew beyond {MAX_DOCUMENT_BYTES} bytes while reading; truncated."
            )
        text, encoding = _decode_text_bytes(raw)
        text = _normalize_text(text)
        if encoding != "UTF-8":
            warnings.append(f"Text encoding fallback used: {encoding}")
        text = _clamp_text_length(text, warnings)
        return ExtractedDocument(
            str(path),
            path.stem,
            path.suffix.lower(),
            text=text,
            pages=[text] if text else [],
            warnings=warnings,
        )

    def _parse_pptx(self, path: Path, task: TaskControl | None = None) -> ExtractedDocument:
        from core.input_limits import (
            MAX_OFFICE_XML_ENTRY_BYTES,
            MAX_OFFICE_XML_TOTAL_BYTES,
        )

        pages: list[str] = []
        warnings: list[str] = []
        xml_total = 0
        text_total = 0
        try:
            with zipfile.ZipFile(path) as zf:
                slide_names = sorted(
                    [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
                    key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
                )
                for index, slide_name in enumerate(slide_names, start=1):
                    if task is not None:
                        task.report("parsing_page", index, len(slide_names), path.name)
                    info = zf.getinfo(slide_name)
                    if info.file_size > MAX_OFFICE_XML_ENTRY_BYTES:
                        warnings.append(
                            f"Slide XML {slide_name} size {info.file_size} exceeds limit; skipped"
                        )
                        continue
                    xml_total += info.file_size
                    if xml_total > MAX_OFFICE_XML_TOTAL_BYTES:
                        warnings.append("Cumulative Office XML size exceeded; stopping")
                        break
                    xml = _read_zip_member_bounded(
                        zf, info, MAX_OFFICE_XML_ENTRY_BYTES
                    )
                    from core.input_limits import MAX_EXTRACTED_TEXT_CHARS
                    page = _extract_xml_text(
                        xml,
                        max_chars=max(0, MAX_EXTRACTED_TEXT_CHARS - text_total),
                    )
                    page, text_total, truncated = _take_text_with_budget(
                        page, text_total, warnings, "PPTX"
                    )
                    if page:
                        pages.append(page)
                    if truncated:
                        break
        except Exception as exc:
            warnings.append(f"Failed to parse PPTX: {exc}")
        text = "\n\n".join(f"[Slide {i + 1}]\n{page}" for i, page in enumerate(pages))
        text = _clamp_text_length(text, warnings)
        return ExtractedDocument(str(path), path.stem, ".pptx", text, pages, warnings)

    def _parse_docx(self, path: Path) -> ExtractedDocument:
        from core.input_limits import (
            MAX_EXTRACTED_TEXT_CHARS,
            MAX_OFFICE_XML_ENTRY_BYTES,
        )

        warnings: list[str] = []
        paragraphs: list[str] = []
        try:
            with zipfile.ZipFile(path) as zf:
                info = zf.getinfo("word/document.xml")
                if info.file_size > MAX_OFFICE_XML_ENTRY_BYTES:
                    warnings.append(
                        f"DOCX XML size {info.file_size} exceeds limit"
                    )
                    return ExtractedDocument(
                        str(path), path.stem, ".docx", "",
                        warnings=warnings,
                    )
                xml = _read_zip_member_bounded(
                    zf, info, MAX_OFFICE_XML_ENTRY_BYTES
                )
                paragraphs, truncated = _extract_docx_paragraphs(
                    xml,
                    max_chars=MAX_EXTRACTED_TEXT_CHARS,
                )
                if truncated:
                    warnings.append(
                        "DOCX extracted text exceeded the character budget; truncated."
                    )
        except Exception as exc:
            warnings.append(f"Failed to parse DOCX: {exc}")
        text = _normalize_text("\n".join(paragraphs))
        text = _clamp_text_length(text, warnings)
        return ExtractedDocument(str(path), path.stem, ".docx", text, [text] if text else [], warnings)

    def _parse_pdf(self, path: Path, task: TaskControl | None = None) -> ExtractedDocument:
        warnings: list[str] = []
        pages: list[str] = []
        numbered_pages: list[tuple[int, str]] = []
        text_total = 0
        try:
            import pypdfium2 as pdfium  # type: ignore

            doc = pdfium.PdfDocument(str(path))
            try:
                from core.input_limits import MAX_PDF_PAGES
                total_pages = len(doc)
                if total_pages > MAX_PDF_PAGES:
                    warnings.append(
                        f"PDF has {total_pages} pages, exceeding limit "
                        f"of {MAX_PDF_PAGES}; only the first "
                        f"{MAX_PDF_PAGES} pages will be parsed."
                    )
                    total_pages = MAX_PDF_PAGES
                for i in range(total_pages):
                    page = doc[i]
                    if task is not None:
                        task.report("parsing_page", i + 1, total_pages, path.name)
                    try:
                        text_page = page.get_textpage()
                        try:
                            text = text_page.get_text_range().strip()
                        finally:
                            close_text_page = getattr(text_page, "close", None)
                            if callable(close_text_page):
                                close_text_page()
                        if text:
                            normalized = _normalize_text(text)
                            normalized, text_total, truncated = _take_text_with_budget(
                                normalized, text_total, warnings, "PDF"
                            )
                            if normalized:
                                pages.append(normalized)
                                numbered_pages.append((i + 1, normalized))
                            if truncated:
                                break
                        else:
                            warnings.append(f"Page {i + 1} has no extractable text")
                            ocr_text = _ocr_pdf_page(page, i + 1, warnings)
                            if ocr_text:
                                normalized = _normalize_text(ocr_text)
                                normalized, text_total, truncated = _take_text_with_budget(
                                    normalized, text_total, warnings, "PDF"
                                )
                                if normalized:
                                    pages.append(normalized)
                                    numbered_pages.append((i + 1, normalized))
                                if truncated:
                                    break
                    finally:
                        close_page = getattr(page, "close", None)
                        if callable(close_page):
                            close_page()
            finally:
                close_doc = getattr(doc, "close", None)
                if callable(close_doc):
                    close_doc()
        except ImportError:
            warnings.append("pypdfium2 is not installed; PDF text extraction is unavailable.")
        except Exception as exc:
            warnings.append(f"Failed to parse PDF: {exc}")
        text = "\n\n".join(
            f"[Page {page_number}]\n{page_text}"
            for page_number, page_text in numbered_pages
        )
        text = _normalize_text(text)
        text = _clamp_text_length(text, warnings)
        return ExtractedDocument(str(path), path.stem, ".pdf", text, pages, warnings)


def _extract_xml_text(xml_bytes: bytes, max_chars: int | None = None) -> str:
    """Extract all text nodes from Office XML."""
    root = ET.fromstring(xml_bytes)
    chunks = []
    total = 0
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            value = node.text
            if max_chars is not None:
                remaining = max_chars - total
                if remaining <= 0:
                    break
                value = value[:remaining]
            chunks.append(value)
            total += len(value)
    return _normalize_text("\n".join(chunks))


def _extract_docx_paragraphs(
    xml_bytes: bytes,
    max_chars: int | None = None,
) -> tuple[list[str], bool]:
    """Extract DOCX paragraph text in document order."""
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    total = 0
    truncated = False
    for para in root.iter():
        if not para.tag.endswith("}p"):
            continue
        chunks = []
        for node in para.iter():
            if node.tag.endswith("}t") and node.text:
                chunks.append(node.text)
        text = _normalize_text("".join(chunks))
        if text:
            if max_chars is not None:
                remaining = max_chars - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(text) > remaining:
                    text = text[:remaining]
                    truncated = True
            paragraphs.append(text)
            total += len(text)
            if truncated:
                break
    return paragraphs, truncated


def _read_zip_member_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limit: int,
) -> bytes:
    """Read at most *limit* bytes even if archive metadata changes."""
    with archive.open(info, "r") as member:
        data = member.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Office XML member {info.filename} exceeds {limit} bytes")
    return data


def _take_text_with_budget(
    text: str,
    used: int,
    warnings: list[str],
    source: str,
) -> tuple[str, int, bool]:
    """Return a text slice that fits the cumulative extraction budget."""
    from core.input_limits import MAX_EXTRACTED_TEXT_CHARS

    remaining = MAX_EXTRACTED_TEXT_CHARS - used
    if remaining <= 0:
        warnings.append(f"{source} extracted text budget reached; remaining pages skipped.")
        return "", used, True
    if len(text) > remaining:
        warnings.append(f"{source} extracted text budget reached; content truncated.")
        return text[:remaining], MAX_EXTRACTED_TEXT_CHARS, True
    return text, used + len(text), False


def _clamp_text_length(text: str, warnings: list[str]) -> str:
    """Truncate *text* with a warning when it exceeds the character budget."""
    from core.input_limits import MAX_EXTRACTED_TEXT_CHARS
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        warnings.append(
            f"Extracted text length {len(text)} exceeds limit "
            f"of {MAX_EXTRACTED_TEXT_CHARS}; truncated."
        )
        return text[:MAX_EXTRACTED_TEXT_CHARS]
    return text


def _normalize_text(text: str) -> str:
    """Normalize whitespace without destroying line-level structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_text_bytes(raw: bytes) -> tuple[str, str]:
    """Decode common course-note encodings without silently dropping bytes."""
    for codec, label in (
        ("utf-8-sig", "UTF-8"),
        ("gb18030", "GB18030"),
        ("cp1252", "Windows-1252"),
    ):
        try:
            return raw.decode(codec), label
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "UTF-8 with replacement characters"


def _source_sort_key(path: Path) -> tuple[int, str, str]:
    """Stable sort that keeps likely originals before copied duplicates."""
    lower = path.name.lower()
    duplicate_hint = 1 if re.search(r"\b(copy|副本|duplicate)\b", lower) else 0
    normalized = re.sub(r"\s*(copy|副本|duplicate)\s*", " ", lower)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return duplicate_hint, normalized, lower


def _file_cache_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def _clone_document(doc: ExtractedDocument) -> ExtractedDocument:
    return replace(doc, pages=list(doc.pages), warnings=list(doc.warnings))


def _trim_file_cache(cache: dict[tuple[str, int, int], ExtractedDocument], max_size: int) -> None:
    while len(cache) > max_size:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)


def _content_fingerprint(text: str) -> str:
    normalized = _fingerprint_text(text)
    if len(normalized) < 120:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _content_signature(text: str) -> set[str]:
    normalized = _fingerprint_text(text)
    tokens = normalized.split()
    if len(tokens) < 40:
        return set()
    return {" ".join(tokens[i:i + 8]) for i in range(0, max(0, len(tokens) - 7), 4)}


def _is_near_duplicate(signature: set[str], previous: list[set[str]]) -> bool:
    for old in previous:
        if not old:
            continue
        overlap = len(signature & old)
        smaller = min(len(signature), len(old))
        if smaller and overlap / smaller >= 0.82:
            return True
    return False


def _is_auxiliary_text_document(doc: ExtractedDocument) -> bool:
    """Detect local helper artifacts that are not source course materials."""
    if doc.extension not in {".md", ".txt"}:
        return False
    haystack = f"{Path(doc.path).name}\n{doc.title}\n{doc.text[:2000]}".lower()
    marker_groups = [
        ("出题标准",),
        ("干扰项", "批改"),
        ("评分要点",),
        ("辅助提示词",),
        ("课程内容整理标准",),
        ("已生成的课程笔记",),
        ("高频考点", "变式提示"),
        ("模拟卷", "高频核心概念"),
        ("最后 40 分钟", "优先级"),
        ("marking rubric",),
        ("grading feedback",),
        ("answer key",),
        ("prompt template",),
        ("study helper",),
        ("review helper",),
    ]
    return any(all(marker in haystack for marker in markers) for markers in marker_groups)


def _fingerprint_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\W+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _ocr_pdf_page(page, page_number: int, warnings: list[str]) -> str:
    """Best-effort OCR for image-only PDF pages; optional dependencies only."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as exc:
        warnings.append(
            f"OCR fallback unavailable for page {page_number}: install pytesseract and Pillow ({exc})"
        )
        return ""

    try:
        from core.input_limits import MAX_RENDER_PIXELS, OCR_PAGE_TIMEOUT_SECONDS

        # Check pixel budget BEFORE rendering to avoid allocating a giant bitmap.
        page_width = getattr(page, "get_width", lambda: 0)()
        page_height = getattr(page, "get_height", lambda: 0)()
        if page_width > 0 and page_height > 0:
            scaled_pixels = (page_width * 2) * (page_height * 2)
            if scaled_pixels > MAX_RENDER_PIXELS:
                warnings.append(
                    f"Page {page_number} estimated render size "
                    f"{page_width * 2}x{page_height * 2} "
                    f"exceeds pixel budget; OCR skipped."
                )
                return ""

        bitmap = page.render(scale=2)
        try:
            image = bitmap.to_pil().convert("RGB").copy()
        finally:
            close_bitmap = getattr(bitmap, "close", None)
            if callable(close_bitmap):
                close_bitmap()
        ocr_config = configure_pytesseract(pytesseract)
        text = pytesseract.image_to_string(
            image,
            lang="eng+chi_sim",
            config=ocr_config,
            timeout=OCR_PAGE_TIMEOUT_SECONDS,
        )
        if text.strip():
            warnings.append(f"Page {page_number} text recovered by OCR fallback")
            return text.strip()
        warnings.append(f"OCR fallback found no text on page {page_number}")
    except Exception as exc:
        warnings.append(f"OCR fallback failed on page {page_number}: {exc}")
    return ""
