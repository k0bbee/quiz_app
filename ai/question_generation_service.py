"""Pure-Python preparation and validation for model-generated questions."""

from __future__ import annotations

import re

from ai.question_answer_leak import choice_stem_leaks_answer_keyword
from ai.question_payload_normalizer import normalize_raw_question
from utils.constants import QuestionType, topic_alias_values, topic_label


class QuestionGenerationService:
    """Normalize and validate raw LLM question payloads without Qt dependencies."""

    def __init__(self, topics: list | None = None):
        self.topics = list(topics or [])

    def prepare_raw_question(self, qdata) -> tuple[dict | None, str]:
        """Return a normalized payload with a canonical topic, or a rejection reason."""
        normalized = self.normalize_raw_question(qdata)
        ok, reason = self.validate_raw_question(normalized)
        if not ok:
            return None, reason
        prepared = dict(normalized)
        prepared["topic"] = self.normalize_topic(prepared.get("topic"))
        return prepared, ""

    def normalize_raw_question(self, qdata):
        return normalize_raw_question(qdata)

    def validate_raw_question(self, qdata: dict) -> tuple[bool, str]:
        """Validate raw model output before converting it to a Question."""
        if not isinstance(qdata, dict):
            return False, "question is not an object"

        qtype = qdata.get("type", QuestionType.MULTIPLE_CHOICE.value)
        try:
            question_type = QuestionType(qtype)
        except ValueError:
            return False, f"unknown question type: {qtype}"

        if self.normalize_topic(qdata.get("topic")) is None:
            return False, f"topic {qdata.get('topic')} was not selected"

        bilingual = qdata.get("bilingual", {})
        if not isinstance(bilingual, dict):
            return False, "bilingual content must be an object"
        for language in ("zh", "en"):
            content = bilingual.get(language, {})
            if not isinstance(content, dict):
                return False, f"{language} content must be an object"
            if not content.get("stem"):
                return False, f"missing {language} stem"
            explanation = content.get("explanation", "")
            if not explanation or len(explanation) < 20:
                return False, f"missing or weak {language} explanation"

        if question_type in {
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.SCENARIO_CHOICE,
            QuestionType.TRUE_FALSE,
        }:
            return _validate_choice_question(question_type, qdata, bilingual)
        if question_type == QuestionType.FILL_IN_BLANK:
            answer = qdata.get("correct_answer")
            if not isinstance(answer, list) or not answer:
                return False, "fill_in_blank answer must be a non-empty list"
        elif question_type == QuestionType.MATCHING:
            issue = _matching_issue(qdata, bilingual)
            if issue:
                return False, issue
        elif question_type == QuestionType.ORDERING:
            issue = _ordering_issue(qdata, bilingual)
            if issue:
                return False, issue
        elif question_type == QuestionType.SHORT_ANSWER:
            answer = str(qdata.get("correct_answer", "") or "").strip()
            if len(answer) < 10:
                return False, "short_answer must include a meaningful reference answer"
        return True, ""

    def normalize_topic(self, raw_topic):
        """Map model topic output to one of the selected topics."""
        if not self.topics:
            return str(raw_topic or "general")
        raw = str(raw_topic or "").strip().lower()
        raw_key = _topic_match_key(raw)
        selected = {
            value.lower(): topic
            for topic in self.topics
            for value in topic_alias_values(topic)
        }
        if raw in selected:
            return selected[raw]
        canonical_selected = {
            _topic_match_key(value): topic
            for topic in self.topics
            for value in topic_alias_values(topic) | {topic_label(topic)}
        }
        if raw_key in canonical_selected:
            return canonical_selected[raw_key]
        for topic in self.topics:
            for label in topic_alias_values(topic) | {topic_label(topic)}:
                if _topic_tokens_cover(raw_key, _topic_match_key(label)):
                    return topic
        return None


def _validate_choice_question(question_type: QuestionType, qdata: dict, bilingual: dict) -> tuple[bool, str]:
    answer = str(qdata.get("correct_answer", "")).strip()
    if question_type == QuestionType.TRUE_FALSE:
        if answer.lower() not in {"true", "false"}:
            return False, "true_false answer must be true/false"
        return True, ""
    if answer.upper() not in {"A", "B", "C", "D"}:
        return False, "choice answer must be A/B/C/D"
    for language in ("zh", "en"):
        options = bilingual.get(language, {}).get("options", [])
        if len(options) != 4:
            return False, f"{language} choice question must have 4 options"
    if choice_stem_leaks_answer_keyword(bilingual, answer):
        return False, "answer keyword leaked in choice stem"
    return True, ""


def _matching_issue(qdata: dict, bilingual: dict) -> str:
    for language in ("zh", "en"):
        options = bilingual.get(language, {}).get("options", {})
        if not isinstance(options, dict):
            return f"{language} matching options must contain left/right lists"
        left = options.get("left", [])
        right = options.get("right", [])
        if not left or len(left) != len(right):
            return f"{language} matching left/right options must be non-empty and equal length"
        if not all(_has_option_id(item) for item in left + right):
            return f"{language} matching options must have stable ids"
    answer = qdata.get("correct_answer")
    if not isinstance(answer, list) or not answer:
        return "matching answer must be a non-empty list of id pairs"
    if not all(isinstance(pair, (list, tuple)) and len(pair) == 2 for pair in answer):
        return "matching answer must contain pairs"
    return ""


def _ordering_issue(qdata: dict, bilingual: dict) -> str:
    for language in ("zh", "en"):
        options = bilingual.get(language, {}).get("options", [])
        if not isinstance(options, list) or not options:
            return f"{language} ordering options must be a non-empty list"
        if not all(_has_option_id(item) for item in options):
            return f"{language} ordering options must have stable ids"
    answer = qdata.get("correct_answer")
    if not isinstance(answer, list) or not answer:
        return "ordering answer must be a non-empty list of item ids"
    return ""


def _topic_match_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _topic_tokens_cover(raw_key: str, label_key: str) -> bool:
    raw_tokens = {token for token in raw_key.split() if len(token) >= 3}
    label_tokens = {token for token in label_key.split() if len(token) >= 3}
    if not raw_tokens or not label_tokens:
        return False
    return raw_tokens.issuperset(label_tokens) or label_tokens.issuperset(raw_tokens)


def _has_option_id(option) -> bool:
    return isinstance(option, dict) and bool(str(option.get("id", "") or "").strip())
