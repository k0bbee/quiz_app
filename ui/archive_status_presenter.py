"""Shared presentation policy for immutable progress archive states."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArchiveStatusView:
    badge: str = ""
    tooltip: str = ""
    notice: str = ""
    retry_unavailable: str = ""


def build_archive_status_view(
    status: str,
    *,
    missing_fields=(),
    snapshot_count: int = 0,
    answer_count: int = 0,
    language: str = "zh",
) -> ArchiveStatusView:
    """Return consistent list, detail and retry copy for one archive state."""
    normalized = str(status or "").strip().lower()
    zh = language == "zh"
    if normalized == "incomplete":
        labels = _missing_labels(missing_fields, language)
        missing_text = (
            ("；缺失：" if zh else "; missing: ") + "、".join(labels)
            if zh and labels
            else ("; missing: " + ", ".join(labels) if labels else "")
        )
        if zh:
            notice = (
                "残缺历史：已保留本次得分、作答结果和用时；"
                f"可复盘 {snapshot_count}/{answer_count} 道题。"
                f"{missing_text}"
            )
            return ArchiveStatusView(
                badge="【残缺】",
                tooltip=f"残缺历史：只能复盘已保存部分{missing_text}",
                notice=notice,
                retry_unavailable=(
                    "原题已不可用。这是一条残缺历史，只能查看已保存的部分内容，"
                    "无法重新练习。"
                ),
            )
        notice = (
            "Incomplete history: score, answers, and timing were preserved; "
            f"{snapshot_count}/{answer_count} question(s) can be reviewed"
            f"{missing_text}."
        )
        return ArchiveStatusView(
            badge="[Incomplete]",
            tooltip=f"Incomplete history: only saved content can be reviewed{missing_text}.",
            notice=notice,
            retry_unavailable=(
                "The original questions are unavailable. This is an incomplete "
                "history record; only saved content can be reviewed and it cannot "
                "be retried."
            ),
        )
    if normalized == "legacy":
        if zh:
            return ArchiveStatusView(
                badge="【待保护】",
                tooltip="这条旧历史尚未完成历史保护，当前题目不会冒充当时内容。",
                notice=(
                    "这是一条尚未完成保护的旧历史。已保存的分数和作答结果仍可查看，"
                    "但题干、答案或课程信息可能不完整。"
                ),
                retry_unavailable=(
                    "原题已不可用。这条旧历史尚未完成保护，只能查看已保存的信息，"
                    "无法重新练习。"
                ),
            )
        return ArchiveStatusView(
            badge="[Protection Pending]",
            tooltip=(
                "This legacy history has not been fully protected. Current question "
                "content will not be shown as historical content."
            ),
            notice=(
                "This legacy history has not been fully protected. Saved scores and "
                "answers remain visible, but question or course details may be incomplete."
            ),
            retry_unavailable=(
                "The original questions are unavailable. This legacy history is still "
                "awaiting protection and cannot be retried."
            ),
        )
    return ArchiveStatusView(
        retry_unavailable=(
            "该课程或题目集已删除。历史内容仍可复盘，但原题已不可用，无法重新练习。"
            if zh
            else "The course or question set was deleted. This archived result can "
            "be reviewed, but the original questions can no longer be retried."
        )
    )


def _missing_labels(missing_fields, language: str) -> list[str]:
    zh = language == "zh"
    labels: list[str] = []
    for raw_field in missing_fields or ():
        field = str(raw_field or "").strip()
        if (
            field == "question_snapshots"
            or field.startswith("question:")
            or field.startswith("snapshot:")
            or field.startswith("question_snapshots:")
        ):
            label = "题目复盘内容" if zh else "question review content"
        elif field == "set_title_snapshot":
            label = "题集名称" if zh else "question-set title"
        elif field == "course_title_snapshot":
            label = "课程名称" if zh else "course title"
        else:
            label = "部分历史字段" if zh else "some historical fields"
        if label not in labels:
            labels.append(label)
    return labels
