"""Grader: Auto-grading logic for each question type."""

from typing import Any

from utils.constants import QuestionType
from models.question import Question


class Grader:
    """Stateless grading functions for each question type."""

    @staticmethod
    def grade(question: Question, user_answer: Any) -> tuple[bool, object]:
        """Grade a user answer. Returns (is_correct, normalized_answer)."""
        qtype = question.type
        if qtype == QuestionType.MULTIPLE_CHOICE:
            return Grader.grade_multiple_choice(question, user_answer)
        elif qtype == QuestionType.SCENARIO_CHOICE:
            return Grader.grade_multiple_choice(question, user_answer)
        elif qtype == QuestionType.TRUE_FALSE:
            return Grader.grade_true_false(question, user_answer)
        elif qtype == QuestionType.MATCHING:
            return Grader.grade_matching(question, user_answer)
        elif qtype == QuestionType.ORDERING:
            return Grader.grade_ordering(question, user_answer)
        elif qtype == QuestionType.FILL_IN_BLANK:
            return Grader.grade_fill_in_blank(question, user_answer)
        elif qtype == QuestionType.SHORT_ANSWER:
            return Grader.grade_short_answer(question, user_answer)
        else:
            return False, user_answer

    @staticmethod
    def grade_multiple_choice(question: Question, user_answer: str) -> tuple[bool, str]:
        """Exact match on answer letter (case-insensitive)."""
        correct = str(question.correct_answer).strip().upper()
        user = str(user_answer).strip().upper() if user_answer else ""
        return user == correct, user

    @staticmethod
    def grade_true_false(question: Question, user_answer: str) -> tuple[bool, str]:
        """Exact match on 'true'/'false' (case-insensitive)."""
        correct = str(question.correct_answer).strip().lower()
        user = str(user_answer).strip().lower() if user_answer else ""
        return user == correct, user

    @staticmethod
    def grade_matching(question: Question, user_answer: list) -> tuple[bool, list]:
        """Check if all pairs match. Returns (all_correct, user_answer)."""
        if not isinstance(user_answer, list):
            return False, user_answer
        correct_pairs = question.correct_answer
        if not isinstance(correct_pairs, list):
            return False, user_answer

        # Guard: if correct_pairs is empty but type is matching, always False
        if len(correct_pairs) == 0:
            return False, user_answer

        # Guard: validate inner structure before converting to tuples
        if user_answer:
            for p in user_answer:
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    return False, user_answer
        option_map = _option_label_to_id_map(question)
        normalized_user = [
            [_normalize_option_answer_value(pair[0], option_map), _normalize_option_answer_value(pair[1], option_map)]
            for pair in user_answer
        ] if user_answer else []
        normalized_correct = [
            [_normalize_option_answer_value(pair[0], option_map), _normalize_option_answer_value(pair[1], option_map)]
            for pair in correct_pairs
        ]
        # Sort both for order-independent comparison
        user_sorted = sorted([tuple(p) for p in normalized_user]) if normalized_user else []
        correct_sorted = sorted([tuple(p) for p in normalized_correct])
        return user_sorted == correct_sorted, normalized_user

    @staticmethod
    def grade_ordering(question: Question, user_answer: list) -> tuple[bool, list]:
        """Check if the entire order matches exactly."""
        if not isinstance(user_answer, list):
            return False, user_answer
        correct_order = question.correct_answer
        if not isinstance(correct_order, list):
            return False, user_answer
        option_map = _option_label_to_id_map(question)
        normalized_user = [
            _normalize_option_answer_value(item, option_map)
            for item in user_answer
        ]
        normalized_correct = [
            _normalize_option_answer_value(item, option_map)
            for item in correct_order
        ]
        return normalized_user == normalized_correct, normalized_user

    @staticmethod
    def grade_fill_in_blank(question: Question, user_answer: str) -> tuple[bool, str]:
        """Fuzzy match: case-insensitive, whitespace-normalized.
        The correct_answer is a list of acceptable answers."""
        if not user_answer:
            return False, ""
        acceptable = question.correct_answer
        if isinstance(acceptable, list):
            user_normalized = str(user_answer).strip().lower()
            for ans in acceptable:
                if str(ans).strip().lower() == user_normalized:
                    return True, user_answer.strip()
            return False, user_answer.strip()
        # Single answer fallback
        return str(user_answer).strip().lower() == str(acceptable).strip().lower(), user_answer.strip()

    @staticmethod
    def grade_short_answer(question: Question, user_answer: str) -> tuple[bool, str]:
        """Short answer always requires manual review. Returns False with stored answer."""
        return False, user_answer if user_answer else ""


def _option_label_to_id_map(question: Question) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for content in (question.bilingual or {}).values():
        options = content.get("options", {}) if isinstance(content, dict) else {}
        for option in _iter_option_payloads(options):
            option_id = _option_id(option)
            for label in _option_labels(option):
                if label:
                    mapping.setdefault(label.strip().lower(), option_id)
            mapping.setdefault(option_id.strip().lower(), option_id)
    return mapping


def _iter_option_payloads(options):
    if isinstance(options, dict):
        for key in ("left", "right", "items"):
            for option in options.get(key, []) or []:
                yield option
    elif isinstance(options, list):
        for option in options:
            yield option


def _option_id(option) -> str:
    if isinstance(option, dict):
        for key in ("id", "value", "key"):
            value = option.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return _option_labels(option)[0]


def _option_labels(option) -> list[str]:
    if isinstance(option, dict):
        labels = []
        for key in ("text", "label", "title", "name", "zh", "en", "id", "value"):
            value = option.get(key)
            if value is not None and str(value).strip():
                labels.append(str(value).strip())
        return labels or [str(option)]
    return [str(option)]


def _normalize_option_answer_value(value, option_map: dict[str, str]) -> str:
    text = str(value or "").strip()
    return option_map.get(text.lower(), text)
