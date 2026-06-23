"""Safe interpretation of natural-language exam requirements."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from ai.exam_plan import (
    DIFFICULTY_WEIGHT_KEYS,
    QUESTION_TYPES,
    ExamGenerationPlan,
    ExamPlanPatch,
    ExamPlanValidationError,
    PlanChange,
    apply_exam_plan_patch,
    describe_plan_changes,
)


class ExamRequestError(ValueError):
    """A user-facing interpretation failure that leaves the plan unchanged."""


@dataclass(frozen=True)
class InterpretationResult:
    plan: ExamGenerationPlan
    assistant_message: str
    changes: tuple[PlanChange, ...]
    source: str


class ExamRequestInterpreter:
    """Convert a request into a validated patch without exposing generation prompts."""

    def __init__(self, available_topics: list[str], llm_client=None):
        self.available_topics = tuple(dict.fromkeys(str(topic).strip() for topic in available_topics if str(topic).strip()))
        self.llm_client = llm_client

    def interpret(
        self,
        request: str,
        current: ExamGenerationPlan,
    ) -> InterpretationResult:
        text = str(request or "").strip()
        if not text:
            raise ExamRequestError("请输入具体的试卷要求。")
        if len(text) > 4000:
            raise ExamRequestError("试卷要求过长，请缩短到 4000 个字符以内。")

        if self._can_use_remote_llm():
            patch = self._interpret_with_llm(text, current)
            source = "llm"
        else:
            patch = self._interpret_with_local_rules(text, current)
            source = "local_rules"

        try:
            plan = apply_exam_plan_patch(current, patch, self.available_topics)
        except ExamPlanValidationError as exc:
            raise ExamRequestError(str(exc)) from exc
        changes = tuple(describe_plan_changes(current, plan))
        message = patch.assistant_message or (
            "已更新试卷方案，请检查右侧变更。"
            if changes
            else "当前要求没有改变试卷方案。"
        )
        return InterpretationResult(plan, message, changes, source)

    def _can_use_remote_llm(self) -> bool:
        if self.llm_client is None:
            return False
        base_url = str(getattr(self.llm_client, "base_url", "")).lower()
        return base_url.startswith("https://") or base_url.startswith("http://")

    def _interpret_with_llm(
        self,
        request: str,
        current: ExamGenerationPlan,
    ) -> ExamPlanPatch:
        schema = {
            "assistant_message": "short confirmation or clarification",
            "question_count": "integer 3..60",
            "difficulty": "easy|medium|hard|mixed",
            "template": "quick_review|final_exam|calculation_practice",
            "selected_topics": list(self.available_topics),
            "question_type_weights": {key: "integer 0..100" for key in QUESTION_TYPES},
            "difficulty_weights": {key: "integer 0..100" for key in DIFFICULTY_WEIGHT_KEYS},
            "topic_weights": {"allowed_topic": "integer 0..100"},
        }
        system = (
            "You translate exam requirements into a strict JSON PATCH. "
            "Return one JSON object only. Omit unchanged fields. Never add fields. "
            "Do not produce questions, commands, paths, or prose outside JSON.\n"
            f"ALLOWED_FIELDS_AND_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
        )
        user = (
            f"AVAILABLE_TOPICS={json.dumps(self.available_topics, ensure_ascii=False)}\n"
            f"CURRENT_PLAN={json.dumps(current.to_dict(), ensure_ascii=False, sort_keys=True)}\n"
            f"USER_REQUIREMENT={request}"
        )
        try:
            data = self.llm_client.generate_with_json(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=1400,
                max_retries=1,
            )
        except Exception as exc:
            raise ExamRequestError(f"LLM 无法理解试卷要求：{exc}") from exc
        if data is None:
            detail = str(getattr(self.llm_client, "last_error", "") or "未返回有效 JSON")
            raise ExamRequestError(f"LLM 无法理解试卷要求：{detail}")
        try:
            return ExamPlanPatch.from_mapping(data)
        except ExamPlanValidationError as exc:
            raise ExamRequestError(f"LLM 返回的配置无效：{exc}") from exc

    def _interpret_with_local_rules(
        self,
        request: str,
        current: ExamGenerationPlan,
    ) -> ExamPlanPatch:
        lowered = request.casefold()
        data: dict[str, object] = {}

        count = _extract_count(lowered)
        if count is not None:
            data["question_count"] = count

        difficulty = _extract_overall_difficulty(lowered)
        if difficulty:
            data["difficulty"] = difficulty

        template = _extract_template(lowered)
        if template:
            data["template"] = template

        topics = _extract_topics(lowered, self.available_topics)
        if topics:
            data["selected_topics"] = topics

        question_percentages = _extract_percentages(
            lowered,
            {
                "multiple_choice": ("选择题", "multiple choice", "multiple-choice"),
                "scenario_choice": ("情境选择题", "场景题", "scenario choice", "scenario"),
                "true_false": ("判断题", "true false", "true/false", "true-false"),
                "fill_in_blank": ("填空题", "fill in the blank", "fill-in-the-blank"),
            },
        )
        qualitative = _extract_qualitative_question_weights(lowered, current)
        question_percentages.update(qualitative)
        if question_percentages:
            data["question_type_weights"] = _complete_percentages(
                current.question_type_weights,
                question_percentages,
                QUESTION_TYPES,
            )

        difficulty_percentages = _extract_percentages(
            lowered,
            {
                "easy": ("简单题", "基础题", "easy questions", "easy"),
                "medium": ("中等题", "medium questions", "medium"),
                "hard": ("困难题", "难题", "hard questions", "hard"),
            },
        )
        if difficulty_percentages:
            data["difficulty_weights"] = _complete_percentages(
                current.difficulty_weights,
                difficulty_percentages,
                DIFFICULTY_WEIGHT_KEYS,
            )

        if not data:
            raise ExamRequestError(
                "没有识别到具体修改。请说明题目数量、难度、模板、知识点或题型比例。"
            )
        data["assistant_message"] = "已按本地安全规则更新方案；你可以继续补充要求。"
        try:
            return ExamPlanPatch.from_mapping(data)
        except ExamPlanValidationError as exc:
            raise ExamRequestError(str(exc)) from exc


def _extract_count(text: str) -> int | None:
    patterns = (
        r"(?<!\d)(\d{1,2})\s*(?:道|题)(?!\s*占)",
        r"(?<!\d)(\d{1,2})\s*(?:questions?|items?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if 3 <= value <= 60:
                return value
            raise ExamRequestError("题目数量必须在 3 到 60 之间。")
    return None


def _extract_overall_difficulty(text: str) -> str | None:
    without_percentages = re.sub(r"(?:简单题|基础题|中等题|困难题|难题|easy|medium|hard)[^,，。;；]{0,8}\d{1,3}\s*%", "", text)
    rules = (
        ("mixed", (r"混合难度", r"难度混合", r"mixed difficulty")),
        ("hard", (r"整体.{0,3}困难", r"困难(?:的)?(?:试卷|模拟|考试)", r"\bhard\b")),
        ("easy", (r"整体.{0,3}(?:简单|基础)", r"\beasy\b")),
        ("medium", (r"整体.{0,3}中等", r"\bmedium\b")),
    )
    for value, patterns in rules:
        if any(re.search(pattern, without_percentages, re.IGNORECASE) for pattern in patterns):
            return value
    return None


def _extract_template(text: str) -> str | None:
    if re.search(r"期末|模拟卷|考试风格|final exam|exam style", text, re.IGNORECASE):
        return "final_exam"
    if re.search(r"计算|运算|calculation|numeric", text, re.IGNORECASE):
        return "calculation_practice"
    if re.search(r"快速复习|速记|quick review|rapid review", text, re.IGNORECASE):
        return "quick_review"
    return None


def _extract_topics(text: str, available_topics: tuple[str, ...]) -> list[str]:
    found = []
    for topic in available_topics:
        escaped = re.escape(topic.casefold())
        if topic.isascii():
            pattern = rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])"
        else:
            pattern = escaped
        if re.search(pattern, text, re.IGNORECASE):
            found.append(topic)
    return found


def _extract_percentages(text: str, aliases: dict[str, tuple[str, ...]]) -> dict[str, int]:
    result = {}
    for key, names in aliases.items():
        for name in names:
            pattern = rf"{re.escape(name)}\s*(?:占|为|[:：])?\s*(\d{{1,3}})\s*%"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                if value > 100:
                    raise ExamRequestError(f"{name} 比例不能超过 100%。")
                result[key] = value
                break
    return result


def _extract_qualitative_question_weights(
    text: str,
    current: ExamGenerationPlan,
) -> dict[str, int]:
    result = {}
    aliases = {
        "multiple_choice": ("选择题", "multiple choice", "multiple-choice"),
        "scenario_choice": ("情境选择题", "场景题", "scenario"),
        "true_false": ("判断题", "true false", "true/false", "true-false"),
        "fill_in_blank": ("填空题", "fill in the blank", "fill-in-the-blank"),
    }
    for key, names in aliases.items():
        for name in names:
            escaped = re.escape(name)
            if re.search(rf"(?:少一点|减少|降低|fewer|less)\s*{escaped}|{escaped}.{{0,8}}(?:少一点|减少|降低|fewer|less)", text, re.IGNORECASE):
                result[key] = max(0, current.question_type_weights[key] - 10)
                break
            if re.search(rf"(?:多一点|增加|提高|more)\s*{escaped}|{escaped}.{{0,8}}(?:多一点|增加|提高|more)", text, re.IGNORECASE):
                result[key] = min(100, current.question_type_weights[key] + 10)
                break
            if re.search(rf"(?:不要|去掉|无|no)\s*{escaped}|{escaped}.{{0,4}}(?:不要|去掉)", text, re.IGNORECASE):
                result[key] = 0
                break
    return result


def _complete_percentages(
    current,
    explicit: dict[str, int],
    ordered_keys: tuple[str, ...],
) -> dict[str, int]:
    specified_total = sum(explicit.values())
    if specified_total > 100:
        raise ExamRequestError("指定比例之和不能超过 100%。")
    remaining_keys = [key for key in ordered_keys if key not in explicit]
    if not remaining_keys:
        if specified_total != 100:
            raise ExamRequestError("完整比例之和必须等于 100%。")
        return dict(explicit)
    remaining = 100 - specified_total
    current_total = sum(current[key] for key in remaining_keys)
    if current_total <= 0:
        base = {key: 1 for key in remaining_keys}
        current_total = len(remaining_keys)
    else:
        base = {key: current[key] for key in remaining_keys}
    raw = {key: base[key] * remaining / current_total for key in remaining_keys}
    completed = {**explicit, **{key: int(raw[key]) for key in remaining_keys}}
    delta = 100 - sum(completed.values())
    ranked = sorted(
        remaining_keys,
        key=lambda key: (-(raw[key] - int(raw[key])), ordered_keys.index(key)),
    )
    for key in ranked[:delta]:
        completed[key] += 1
    return {key: completed[key] for key in ordered_keys}
