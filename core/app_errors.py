"""Structured, localized application errors for user-facing UI messages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppError:
    """User-facing error with a stable code and localized guidance."""

    code: str
    severity: str
    title_zh: str
    title_en: str
    message_zh: str
    message_en: str
    action_zh: str = ""
    action_en: str = ""
    technical_detail: str = ""

    def title(self, lang: str) -> str:
        return self.title_zh if lang == "zh" else self.title_en

    def message(self, lang: str) -> str:
        return self.message_zh if lang == "zh" else self.message_en

    def action(self, lang: str) -> str:
        return self.action_zh if lang == "zh" else self.action_en

    def status_text(self, lang: str) -> str:
        return f"{self.title(lang)}: {self.message(lang)} [{self.code}]"

    def __str__(self) -> str:
        return f"{self.title_en}: {self.message_en} [{self.code}]"


def format_app_error(error: AppError, lang: str = "zh", include_detail: bool = True) -> str:
    """Format an AppError for dialogs and copyable user reports."""
    if lang == "zh":
        lines = [error.title("zh"), error.message("zh")]
        if error.action("zh"):
            lines.append(f"建议操作: {error.action('zh')}")
        lines.append(f"错误码: {error.code}")
        if include_detail and error.technical_detail:
            lines.append(f"技术详情: {error.technical_detail}")
        return "\n\n".join(lines)

    lines = [error.title("en"), error.message("en")]
    if error.action("en"):
        lines.append(f"Suggested action: {error.action('en')}")
    lines.append(f"Error code: {error.code}")
    if include_detail and error.technical_detail:
        lines.append(f"Details: {error.technical_detail}")
    return "\n\n".join(lines)


def coerce_app_error(
    value,
    *,
    default_code: str,
    title_zh: str,
    title_en: str,
    action_zh: str = "",
    action_en: str = "",
) -> AppError:
    """Convert legacy string errors into structured AppError values."""
    if isinstance(value, AppError):
        return value
    detail = str(value)
    return AppError(
        code=default_code,
        severity="error",
        title_zh=title_zh,
        title_en=title_en,
        message_zh=detail,
        message_en=detail,
        action_zh=action_zh,
        action_en=action_en,
        technical_detail=detail,
    )
