"""Document extraction for course initialization.

Supported formats are intentionally handled with lightweight local parsers:
PPTX/DOCX through their zipped XML payloads, text/Markdown directly, and PDF
through PyMuPDF when it is installed.
"""

from __future__ import annotations

import os
import re
import hashlib
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from xml.etree import ElementTree as ET

from core.ocr_runtime import configure_pytesseract


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

    def parse_folder(self, folder: str) -> list[ExtractedDocument]:
        """Parse supported files under a folder recursively.

        Automatically skips common generated-output directories (data/, __pycache__/,
        .git/, etc.) to avoid ingesting the app's own output.
        """
        root = Path(folder)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")

        docs: list[ExtractedDocument] = []
        seen_fingerprints: set[str] = set()
        seen_signatures: list[set[str]] = []
        for path in sorted(root.rglob("*"), key=_source_sort_key):
            if not path.is_file():
                continue
            if path.name.startswith("~$"):
                continue
            if self._should_skip_path(path):
                continue
            ext = path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            doc = self.parse_file(path)
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

    def _should_skip_path(self, path: Path) -> bool:
        """Return True if a path is clearly generated output or app metadata."""
        if any(p.name in self._SKIP_DIRS for p in path.parents):
            return True
        name = path.name.lower()
        return any(re.match(pattern, name, flags=re.IGNORECASE) for pattern in self._SKIP_FILE_PATTERNS)

    def parse_file(self, path: Path) -> ExtractedDocument:
        """Parse one supported file."""
        path = Path(path)
        ext = path.suffix.lower()
        title = path.stem
        cache_key = _file_cache_key(path)
        if cache_key in self._FILE_CACHE:
            return _clone_document(self._FILE_CACHE[cache_key])

        if ext in {".txt", ".md"}:
            doc = self._parse_text(path)
        elif ext == ".pptx":
            doc = self._parse_pptx(path)
        elif ext == ".docx":
            doc = self._parse_docx(path)
        elif ext == ".pdf":
            doc = self._parse_pdf(path)
        else:
            doc = ExtractedDocument(str(path), title, ext, warnings=[f"Unsupported file type: {ext}"])

        if ext in SUPPORTED_EXTENSIONS:
            self._FILE_CACHE[cache_key] = _clone_document(doc)
            _trim_file_cache(self._FILE_CACHE, self._MAX_FILE_CACHE_SIZE)
        return doc

    def _parse_text(self, path: Path) -> ExtractedDocument:
        text = path.read_text(encoding="utf-8", errors="ignore")
        text = _normalize_text(text)
        return ExtractedDocument(str(path), path.stem, path.suffix.lower(), text=text, pages=[text])

    def _parse_pptx(self, path: Path) -> ExtractedDocument:
        pages: list[str] = []
        warnings: list[str] = []
        try:
            with zipfile.ZipFile(path) as zf:
                slide_names = sorted(
                    [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
                    key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
                )
                for slide_name in slide_names:
                    xml = zf.read(slide_name)
                    page = _extract_xml_text(xml)
                    if page:
                        pages.append(page)
        except Exception as exc:
            warnings.append(f"Failed to parse PPTX: {exc}")
        text = "\n\n".join(f"[Slide {i + 1}]\n{page}" for i, page in enumerate(pages))
        return ExtractedDocument(str(path), path.stem, ".pptx", _normalize_text(text), pages, warnings)

    def _parse_docx(self, path: Path) -> ExtractedDocument:
        warnings: list[str] = []
        paragraphs: list[str] = []
        try:
            with zipfile.ZipFile(path) as zf:
                xml = zf.read("word/document.xml")
                paragraphs = _extract_docx_paragraphs(xml)
        except Exception as exc:
            warnings.append(f"Failed to parse DOCX: {exc}")
        text = _normalize_text("\n".join(paragraphs))
        return ExtractedDocument(str(path), path.stem, ".docx", text, [text] if text else [], warnings)

    def _parse_pdf(self, path: Path) -> ExtractedDocument:
        warnings: list[str] = []
        pages: list[str] = []
        numbered_pages: list[tuple[int, str]] = []
        try:
            import fitz  # type: ignore

            with fitz.open(path) as doc:
                for i, page in enumerate(doc):
                    text = page.get_text("text").strip()
                    if text:
                        normalized = _normalize_text(text)
                        pages.append(normalized)
                        numbered_pages.append((i + 1, normalized))
                    else:
                        warnings.append(f"Page {i + 1} has no extractable text")
                        ocr_text = _ocr_pdf_page(page, i + 1, warnings)
                        if ocr_text:
                            normalized = _normalize_text(ocr_text)
                            pages.append(normalized)
                            numbered_pages.append((i + 1, normalized))
        except ImportError:
            warnings.append("PyMuPDF is not installed; PDF text extraction is unavailable.")
        except Exception as exc:
            warnings.append(f"Failed to parse PDF: {exc}")
        text = "\n\n".join(
            f"[Page {page_number}]\n{page_text}"
            for page_number, page_text in numbered_pages
        )
        return ExtractedDocument(str(path), path.stem, ".pdf", _normalize_text(text), pages, warnings)


def _extract_xml_text(xml_bytes: bytes) -> str:
    """Extract all text nodes from Office XML."""
    root = ET.fromstring(xml_bytes)
    chunks = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            chunks.append(node.text)
    return _normalize_text("\n".join(chunks))


def _extract_docx_paragraphs(xml_bytes: bytes) -> list[str]:
    """Extract DOCX paragraph text in document order."""
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for para in root.iter():
        if not para.tag.endswith("}p"):
            continue
        chunks = []
        for node in para.iter():
            if node.tag.endswith("}t") and node.text:
                chunks.append(node.text)
        text = _normalize_text("".join(chunks))
        if text:
            paragraphs.append(text)
    return paragraphs


def _normalize_text(text: str) -> str:
    """Normalize whitespace without destroying line-level structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        pix = page.get_pixmap(matrix=None, alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        ocr_config = configure_pytesseract(pytesseract)
        text = pytesseract.image_to_string(image, lang="eng+chi_sim", config=ocr_config)
        if text.strip():
            warnings.append(f"Page {page_number} text recovered by OCR fallback")
            return text.strip()
        warnings.append(f"OCR fallback found no text on page {page_number}")
    except Exception as exc:
        warnings.append(f"OCR fallback failed on page {page_number}: {exc}")
    return ""
