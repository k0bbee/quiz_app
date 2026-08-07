"""Shared, UI-independent quality checks for stored and generated questions."""

from __future__ import annotations

from dataclasses import dataclass

from models.question import Question


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message_zh: str
    message_en: str
    tag_zh: str
    tag_en: str
    repair_action: str = ""

    def message(self, language: str) -> str:
        return self.message_zh if language == "zh" else self.message_en

    def tag(self, language: str) -> str:
        return self.tag_zh if language == "zh" else self.tag_en


def validate_question_quality(question: Question) -> tuple[ValidationIssue, ...]:
    """Return deterministic review issues in stable display order."""
    issues: list[ValidationIssue] = []
    metadata = question.metadata or {}
    source_status = str(metadata.get("source_ref_status", "") or "").strip().lower()
    source_refs = metadata.get("source_refs")
    has_source_refs = isinstance(source_refs, list) and any(
        isinstance(ref, dict) and bool(ref) for ref in source_refs
    )
    if bool(metadata.get("import_review_required")):
        issues.append(ValidationIssue(
            "imported_text_review", "warning",
            "导入题目需人工核对", "Imported question requires manual review",
            "[导入待核对]", "[Imported Review]", "review_import",
        ))
    if source_status in {"invalid_model_ref", "missing"}:
        issues.append(ValidationIssue(
            "source_invalid", "warning",
            "来源无效或缺失", "Source invalid or missing",
            "[无来源]", "[No Source]", "replace_source",
        ))
    elif source_status and not has_source_refs:
        issues.append(ValidationIssue(
            "source_status_without_refs", "error",
            "来源状态与证据不一致", "Source status has no supporting evidence",
            "[来源异常]", "[Source Mismatch]", "replace_source",
        ))
    elif source_status in {"partial_model_ref", "fallback_plan_evidence"}:
        issues.append(ValidationIssue(
            "source_weak", "warning",
            "来源证据不完整或来自计划补全", "Source evidence is partial or plan-completed",
            "[来源较弱]", "[Weak Source]", "review_source",
        ))
    elif source_status in {"fallback_global_evidence", "global_fallback"}:
        issues.append(ValidationIssue(
            "source_global_fallback", "warning",
            "来源来自全局兜底", "Source uses global fallback",
            "[兜底来源]", "[Fallback]", "review_source",
        ))

    if str(metadata.get("plan_match_status", "") or "").strip().lower() == "matched_by_shape":
        issues.append(ValidationIssue(
            "plan_shape_match", "warning",
            "仅按形状匹配生成计划", "Plan matched by shape only",
            "[计划匹配弱]", "[Weak Plan]", "review_plan",
        ))

    zh_explanation = question.get_explanation("zh").strip()
    en_explanation = question.get_explanation("en").strip()
    if not zh_explanation and not en_explanation:
        issues.append(ValidationIssue(
            "explanation_missing", "warning",
            "缺少解析", "Missing explanation",
            "[缺解析]", "[No Explanation]", "edit_explanation",
        ))
    elif _has_imbalanced_explanations(zh_explanation, en_explanation):
        issues.append(ValidationIssue(
            "bilingual_explanation_imbalance", "warning",
            "中英文解析长度差异过大", "Bilingual explanation lengths differ greatly",
            "[解析失衡]", "[Explanation Imbalance]", "edit_explanation",
        ))
    if _has_overlong_correct_option(question):
        issues.append(ValidationIssue(
            "correct_option_length_bias", "warning",
            "正确选项明显长于干扰项", "Correct option is much longer than distractors",
            "[答案过长]", "[Long Answer]", "rebalance_options",
        ))
    return tuple(issues)


def _has_imbalanced_explanations(zh_explanation: str, en_explanation: str) -> bool:
    zh_len = _information_length(zh_explanation)
    en_len = _information_length(en_explanation)
    if min(zh_len, en_len) == 0:
        return False
    return max(zh_len, en_len) >= max(60, min(zh_len, en_len) * 4)


def _information_length(text: str) -> int:
    """Approximate comparable bilingual content length without tokenization."""
    return sum(2 if "\u3400" <= char <= "\u9fff" else 1 for char in text.strip())


def _has_overlong_correct_option(question: Question) -> bool:
    answer = str(question.correct_answer).strip().upper()
    if len(answer) != 1 or not answer.isalpha():
        return False
    index = ord(answer) - ord("A")
    for language in ("zh", "en"):
        options = question.get_options(language)
        if not options or index < 0 or index >= len(options):
            continue
        lengths = [len(str(option).strip()) for option in options]
        distractors = [length for item_index, length in enumerate(lengths) if item_index != index]
        if distractors and lengths[index] >= max(28, max(distractors) * 2):
            return True
    return False
