"""Versioned parsed-document checkpoints for resumable course imports."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.document_parser import ExtractedDocument
from utils.json_io import read_json, write_json


_SCHEMA_VERSION = 1
_MANIFEST_NAME = "checkpoint.json"


class CourseParseCheckpointStore:
    """Persist parsed source files without exposing incomplete course projects."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save_document(
        self,
        folder: str,
        *,
        operation: str,
        course_id: str,
        source_path: str | Path,
        document: ExtractedDocument,
    ) -> None:
        checkpoint_dir = self._prepare(folder, operation, course_id)
        source = Path(source_path).resolve()
        signature = _source_signature(source)
        if not signature:
            return
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "signature": signature,
            "document": _document_payload(document),
        }
        path = checkpoint_dir / _document_filename(source)
        if not write_json(str(path), payload):
            raise OSError(f"failed to save course parse checkpoint: {path}")

    def load_documents(
        self,
        folder: str,
        *,
        operation: str,
        course_id: str,
        source_paths: list[str | Path],
    ) -> dict[str, ExtractedDocument]:
        checkpoint_dir = self._checkpoint_dir(folder, operation, course_id)
        manifest = read_json(str(checkpoint_dir / _MANIFEST_NAME))
        if manifest != self._manifest(folder, operation, course_id):
            return {}
        documents: dict[str, ExtractedDocument] = {}
        for source_path in source_paths:
            source = Path(source_path).resolve()
            payload = read_json(str(checkpoint_dir / _document_filename(source)))
            if not isinstance(payload, dict):
                continue
            if payload.get("schema_version") != _SCHEMA_VERSION:
                continue
            signature = _source_signature(source)
            if not signature or payload.get("signature") != signature:
                continue
            document_payload = payload.get("document")
            if not isinstance(document_payload, dict):
                continue
            try:
                documents[str(source)] = _document_from_payload(document_payload)
            except (TypeError, ValueError):
                continue
        return documents

    def clear(self, folder: str, *, operation: str, course_id: str) -> None:
        """Remove one known checkpoint directory without recursive deletion."""
        checkpoint_dir = self._checkpoint_dir(folder, operation, course_id)
        root = self.root.resolve()
        resolved = checkpoint_dir.resolve()
        if resolved.parent != root or not resolved.exists():
            return
        for path in resolved.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
        try:
            resolved.rmdir()
        except OSError:
            pass

    def reusable_count(
        self,
        folder: str,
        *,
        operation: str,
        course_id: str,
        source_paths: list[str | Path],
    ) -> int:
        return len(self.load_documents(
            folder,
            operation=operation,
            course_id=course_id,
            source_paths=source_paths,
        ))

    def _prepare(self, folder: str, operation: str, course_id: str) -> Path:
        checkpoint_dir = self._checkpoint_dir(folder, operation, course_id)
        expected = self._manifest(folder, operation, course_id)
        current = read_json(str(checkpoint_dir / _MANIFEST_NAME))
        if current != expected:
            self.clear(folder, operation=operation, course_id=course_id)
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            if not write_json(str(checkpoint_dir / _MANIFEST_NAME), expected):
                raise OSError(f"failed to initialize course parse checkpoint: {checkpoint_dir}")
        return checkpoint_dir

    def _checkpoint_dir(self, folder: str, operation: str, course_id: str) -> Path:
        identity = "\0".join((
            str(Path(folder).resolve()).casefold(),
            str(operation or "").strip(),
            str(course_id or "").strip(),
        ))
        checkpoint_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.root / checkpoint_id

    @staticmethod
    def _manifest(folder: str, operation: str, course_id: str) -> dict:
        return {
            "schema_version": _SCHEMA_VERSION,
            "source_folder": str(Path(folder).resolve()),
            "operation": str(operation or "").strip(),
            "course_id": str(course_id or "").strip(),
        }


def _source_signature(path: Path) -> dict:
    try:
        stat = path.stat()
    except OSError:
        return {}
    return {
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _document_filename(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()
    return f"document-{digest[:24]}.json"


def _document_payload(document: ExtractedDocument) -> dict:
    return {
        "path": str(document.path or ""),
        "title": str(document.title or ""),
        "extension": str(document.extension or ""),
        "text": str(document.text or ""),
        "pages": [str(page or "") for page in document.pages or []],
        "warnings": [str(warning or "") for warning in document.warnings or []],
    }


def _document_from_payload(payload: dict) -> ExtractedDocument:
    pages = payload.get("pages", [])
    warnings = payload.get("warnings", [])
    if not isinstance(pages, list) or not isinstance(warnings, list):
        raise ValueError("invalid checkpoint document arrays")
    return ExtractedDocument(
        path=str(payload.get("path", "") or ""),
        title=str(payload.get("title", "") or ""),
        extension=str(payload.get("extension", "") or ""),
        text=str(payload.get("text", "") or ""),
        pages=[str(page or "") for page in pages],
        warnings=[str(warning or "") for warning in warnings],
    )
