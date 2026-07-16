"""Resolve and verify source references attached to generated questions."""

from __future__ import annotations

from ai.question_plan import QuestionPlanItem


class GenerationSourceResolver:
    """Validate model refs against retrieved evidence and choose safe fallbacks."""

    def __init__(
        self,
        global_refs: list[dict] | None = None,
        refs_by_topic: dict[str, list[dict]] | None = None,
    ):
        self.global_refs = [dict(ref) for ref in (global_refs or []) if isinstance(ref, dict)]
        self.refs_by_topic = {
            str(topic): [dict(ref) for ref in refs if isinstance(ref, dict)]
            for topic, refs in (refs_by_topic or {}).items()
        }
        self.registry = _build_registry(self.global_refs, self.refs_by_topic)

    def resolve(
        self,
        qdata: dict,
        plan_item: QuestionPlanItem | None = None,
        plan_refs: list[dict] | None = None,
    ) -> tuple[list[dict], str, list[str]]:
        """Return trusted refs, resolution status, and rejected model evidence IDs."""
        refs = qdata.get("source_refs") if isinstance(qdata, dict) else None
        if isinstance(refs, list):
            sanitized = [sanitize_source_ref(ref) for ref in refs]
            sanitized = [ref for ref in sanitized if ref]
            if sanitized:
                valid_refs, invalid_ref_ids = self._validate_model_refs(
                    sanitized, plan_item
                )
                if valid_refs:
                    status = "valid_model_ref" if not invalid_ref_ids else "partial_model_ref"
                    return valid_refs, status, invalid_ref_ids
                fallback, _fallback_status = self._fallback_refs(plan_refs)
                return fallback, "invalid_model_ref", invalid_ref_ids
        fallback, fallback_status = self._fallback_refs(plan_refs)
        if fallback:
            return fallback, fallback_status, []
        return [], "", []

    def _fallback_refs(self, plan_refs: list[dict] | None) -> tuple[list[dict], str]:
        safe_plan_refs = [dict(ref) for ref in (plan_refs or []) if isinstance(ref, dict)]
        if safe_plan_refs:
            return safe_plan_refs[:1], "fallback_plan_evidence"
        if self.global_refs:
            return [dict(self.global_refs[0])], "fallback_global_evidence"
        return [], ""

    def _validate_model_refs(
        self,
        refs: list[dict],
        plan_item: QuestionPlanItem | None,
    ) -> tuple[list[dict], list[str]]:
        if not self.registry:
            return refs, []
        valid: list[dict] = []
        invalid_ids: list[str] = []
        allowed_chunk_ids = set(plan_item.evidence_chunk_ids if plan_item else [])
        for ref in refs:
            ref_id = _ref_id(ref)
            if not ref_id:
                invalid_ids.append("")
                continue
            registered = self.registry.get(ref_id)
            if registered is None:
                invalid_ids.append(ref_id)
                continue
            if (
                ref.get("source_kind") != "current_event"
                and allowed_chunk_ids
                and ref_id not in allowed_chunk_ids
            ):
                invalid_ids.append(ref_id)
                continue
            if not _matches_registered(ref, registered):
                invalid_ids.append(ref_id)
                continue
            valid.append(dict(registered))
        return valid, invalid_ids


def sanitize_source_ref(ref) -> dict:
    if not isinstance(ref, dict):
        return {}
    source_kind = str(ref.get("source_kind", "") or "").strip()
    candidate_id = str(ref.get("candidate_id", "") or "").strip()
    if source_kind == "current_event":
        if not candidate_id:
            return {}
        clean = {
            "source_kind": "current_event",
            "candidate_id": candidate_id,
            "url": str(ref.get("url", "") or "").strip(),
            "title": str(ref.get("title", "") or "").strip(),
            "domain": str(ref.get("domain", "") or "").strip(),
            "seen_at": str(ref.get("seen_at", "") or "").strip(),
            "retrieved_at": str(ref.get("retrieved_at", "") or "").strip(),
            "excerpt": _compact_excerpt(ref.get("excerpt", "")),
            "content_hash": str(ref.get("content_hash", "") or "").strip(),
            "review_status": str(ref.get("review_status", "") or "").strip(),
        }
        return {key: value for key, value in clean.items() if value not in ("", None)}
    chunk_id = str(ref.get("chunk_id", "") or "").strip()
    source_file = str(ref.get("source_file", "") or "").strip()
    if not chunk_id and not source_file:
        return {}
    page_or_slide = ref.get("page_or_slide")
    if page_or_slide is not None:
        try:
            page_or_slide = int(page_or_slide)
        except (TypeError, ValueError):
            page_or_slide = None
    clean = {
        "chunk_id": chunk_id,
        "source_file": source_file,
        "page_or_slide": page_or_slide,
        "heading": str(ref.get("heading", "") or "").strip(),
        "excerpt": _compact_excerpt(ref.get("excerpt", "")),
        "content_hash": str(ref.get("content_hash", "") or "").strip(),
    }
    return {key: value for key, value in clean.items() if value not in ("", None)}


def _build_registry(refs: list[dict], refs_by_topic: dict[str, list[dict]]) -> dict[str, dict]:
    registry: dict[str, dict] = {}
    for ref in refs:
        _register(registry, ref)
    for topic_refs in refs_by_topic.values():
        for ref in topic_refs:
            _register(registry, ref)
    return registry


def _register(registry: dict[str, dict], ref) -> None:
    clean = sanitize_source_ref(ref)
    ref_id = _ref_id(clean)
    if ref_id and ref_id not in registry:
        registry[ref_id] = clean


def _ref_id(ref: dict) -> str:
    if str(ref.get("source_kind", "") or "").strip() == "current_event":
        return str(ref.get("candidate_id", "") or "").strip()
    return str(ref.get("chunk_id", "") or "").strip()


def _matches_registered(ref: dict, registered: dict) -> bool:
    if registered.get("source_kind") == "current_event":
        return (
            ref.get("source_kind") == "current_event"
            and ref.get("candidate_id") == registered.get("candidate_id")
        )
    expected_file = str(registered.get("source_file") or "").strip()
    actual_file = str(ref.get("source_file") or "").strip()
    if actual_file and expected_file and actual_file != expected_file:
        return False
    expected_page = registered.get("page_or_slide")
    actual_page = ref.get("page_or_slide")
    return not (
        actual_page is not None
        and expected_page is not None
        and actual_page != expected_page
    )


def _compact_excerpt(value, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
