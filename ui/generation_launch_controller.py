"""Shared preparation for opening the AI generation dialog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ai.course_summary_factory import provider_requires_api_key
from ai.settings_validation import ai_generation_settings_error


class GenerationLaunchIssue(str, Enum):
    MISSING_COURSE_CONTENT = "missing_course_content"
    EMPTY_EXAM_SCOPE = "empty_exam_scope"
    INVALID_AI_SETTINGS = "invalid_ai_settings"


@dataclass(frozen=True)
class GenerationLaunchCopy:
    title_zh: str
    title_en: str
    detail_zh: str
    detail_en: str


def generation_launch_copy(
    issue: GenerationLaunchIssue,
    *,
    purpose: str,
) -> GenerationLaunchCopy:
    """Return stable bilingual copy for a generation preflight issue."""
    if issue == GenerationLaunchIssue.MISSING_COURSE_CONTENT:
        if purpose == "regenerate":
            return GenerationLaunchCopy(
                "缺少课程内容",
                "No Course Content",
                "请先导入课程资料并生成课程总结，然后再重新生成题目。",
                "Import course materials and generate a course summary before regenerating questions.",
            )
        return GenerationLaunchCopy(
            "缺少课程内容",
            "No Course Content",
            "尚未导入任何课程资料。请先通过「课程资料」页面导入课件文件夹（支持 pptx/pdf/docx/md/txt），\n系统将自动解析并生成课程摘要，之后即可使用 AI 出题功能。",
            "No course materials imported yet. Please go to Course Materials to import a folder\n(pptx/pdf/docx/md/txt). The system will parse and generate a summary for AI generation.",
        )
    if issue == GenerationLaunchIssue.EMPTY_EXAM_SCOPE:
        if purpose == "regenerate":
            return GenerationLaunchCopy(
                "考试范围为空",
                "Empty Exam Scope",
                "当前指定范围中的知识点已不存在。请到课程页重新设置考试范围后再重新生成题目。",
                "The topics in the selected scope no longer exist. Reset the exam scope on the Courses page before regenerating questions.",
            )
        return GenerationLaunchCopy(
            "考试范围为空",
            "Empty Exam Scope",
            "当前指定范围中的知识点已不存在。请到课程页重新设置考试范围后再出题。",
            "The topics in the selected scope no longer exist. Reset the exam scope on the Courses page before generating questions.",
        )
    return GenerationLaunchCopy(
        "AI 设置需要处理",
        "AI Settings Need Attention",
        "",
        "",
    )


@dataclass(frozen=True)
class GenerationDialogPreparation:
    dialog: object | None = None
    course_project: object | None = None
    issue: GenerationLaunchIssue | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.dialog is not None and self.issue is None


class GenerationLaunchController:
    """Resolve course/settings dependencies before the window opens a dialog."""

    def __init__(
        self,
        *,
        settings_provider: Callable[[], dict],
        course_context_provider: Callable[[], tuple[str, list, object]],
        task_center=None,
        api_key_required: Callable[[dict], bool] = provider_requires_api_key,
        settings_validator: Callable[[dict, str], str] = ai_generation_settings_error,
        secret_provider: Callable[[], str] | None = None,
        dialog_factory=None,
    ) -> None:
        self._settings_provider = settings_provider
        self._course_context_provider = course_context_provider
        self._task_center = task_center
        self._api_key_required = api_key_required
        self._settings_validator = settings_validator
        self._secret_provider = secret_provider or self._stored_api_key
        self._dialog_factory = dialog_factory

    def prepare(
        self,
        parent,
        *,
        course_override=None,
        allow_review_without_ai: bool = False,
    ) -> GenerationDialogPreparation:
        settings = self._settings_provider()
        course_content, available_topics, course_project = self._course_context(
            course_override
        )
        if not course_content:
            return GenerationDialogPreparation(
                course_project=course_project,
                issue=GenerationLaunchIssue.MISSING_COURSE_CONTENT,
            )
        if (
            course_project is not None
            and getattr(course_project, "exam_scope_mode", "all") == "selected"
            and not available_topics
        ):
            return GenerationDialogPreparation(
                course_project=course_project,
                issue=GenerationLaunchIssue.EMPTY_EXAM_SCOPE,
            )

        if not allow_review_without_ai:
            api_key = (
                self._secret_provider()
                if self._api_key_required(settings)
                else ""
            )
            settings_error = self._settings_validator(settings, api_key)
            if settings_error:
                return GenerationDialogPreparation(
                    course_project=course_project,
                    issue=GenerationLaunchIssue.INVALID_AI_SETTINGS,
                    message=settings_error,
                )

        dialog_type = self._dialog_factory or self._default_dialog_factory()
        dialog = dialog_type(
            course_content,
            settings,
            parent,
            available_topics=available_topics,
            course_project=course_project,
            task_center=self._task_center,
        )
        dialog.configure_from_course_profile(course_project)
        return GenerationDialogPreparation(
            dialog=dialog,
            course_project=course_project,
        )

    def _course_context(self, course_override) -> tuple[str, list, object]:
        if course_override is None:
            return self._course_context_provider()
        course_content = str(
            getattr(course_override, "summary_markdown", "") or ""
        )
        scoped_topics = getattr(course_override, "exam_topics", None)
        available_topics = list(
            scoped_topics()
            if callable(scoped_topics)
            else getattr(course_override, "topics", []) or []
        )
        return course_content, available_topics, course_override

    @staticmethod
    def _stored_api_key() -> str:
        from core.secrets_manager import SecretsManager

        return SecretsManager.instance().get_key()

    @staticmethod
    def _default_dialog_factory():
        from ui.dialogs.ai_generation_dialog import AIGenerationDialog

        return AIGenerationDialog
