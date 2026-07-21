"""Bilingual presentation policy for completed-session retry actions."""

from __future__ import annotations

from dataclasses import dataclass

from core.session_retry import SessionRetryMode


@dataclass(frozen=True)
class SessionRetryCopy:
    empty_title_zh: str
    empty_title_en: str
    empty_detail_zh: str
    empty_detail_en: str
    session_title_zh: str
    session_title_en: str


_COPY = {
    SessionRetryMode.INCORRECT: SessionRetryCopy(
        "全部正确！",
        "All Correct!",
        "你答对了所有题目！",
        "You answered all questions correctly!",
        "重做：错题",
        "Retry: Incorrect Questions",
    ),
    SessionRetryMode.UNSURE: SessionRetryCopy(
        "没有不确定题",
        "No Unsure Questions",
        "本次练习没有标记为不确定的题目。",
        "No questions were marked unsure in this session.",
        "重做：不确定题",
        "Retry: Unsure Questions",
    ),
    SessionRetryMode.REVIEW: SessionRetryCopy(
        "没有复查题",
        "No Review Questions",
        "本次练习没有标记为复查的题目。",
        "No questions were marked for review in this session.",
        "重做：复查题",
        "Retry: Review Questions",
    ),
}


def session_retry_copy(mode: SessionRetryMode) -> SessionRetryCopy:
    return _COPY[mode]
