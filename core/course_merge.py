"""Transactional merge of course identity and its linked user data."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from core.current_events import CurrentEventMaterialPack
from models.course_project import CourseProject, CourseTopic


@dataclass(frozen=True)
class CourseMergeResult:
    success: bool
    target_course_id: str
    source_course_ids: tuple[str, ...]
    question_count: int = 0
    question_set_count: int = 0
    past_exam_count: int = 0
    current_event_pack_count: int = 0
    error: str = ""
    rollback_errors: tuple[str, ...] = ()


def merge_courses(
    target_course_id: str,
    source_course_ids,
    *,
    course_manager,
    question_bank=None,
    set_manager=None,
    past_exam_manager=None,
    mastery_overrides=None,
    current_event_manager=None,
) -> CourseMergeResult:
    """Merge sources into one retained course, rolling back on any failure."""
    target_id = str(target_course_id or "").strip()
    source_ids = tuple(dict.fromkeys(
        str(course_id or "").strip()
        for course_id in (source_course_ids or ())
        if str(course_id or "").strip()
        and str(course_id or "").strip() != target_id
    ))
    base_result = {
        "target_course_id": target_id,
        "source_course_ids": source_ids,
    }
    target = course_manager.get(target_id) if target_id else None
    sources = [course_manager.get(course_id) for course_id in source_ids]
    if target is None:
        return CourseMergeResult(False, **base_result, error="Target course does not exist")
    if not source_ids:
        return CourseMergeResult(False, **base_result, error="Select at least one source course")
    if any(source is None for source in sources):
        return CourseMergeResult(False, **base_result, error="A source course no longer exists")

    original_projects = [deepcopy(target), *(deepcopy(source) for source in sources)]
    current = course_manager.current()
    current_before_id = str(getattr(current, "course_id", "") or "")
    questions = _linked_items(question_bank, source_ids)
    source_question_ids = {
        str(getattr(question, "question_id", "") or "")
        for question in questions
    }
    question_sets = []
    for question_set in _load_all(set_manager):
        set_course_id = _metadata_course_id(question_set)
        contains_source_question = bool(
            source_question_ids.intersection(
                getattr(question_set, "questions", ()) or ()
            )
        )
        if (
            set_course_id in source_ids
            or (not set_course_id and contains_source_question)
        ):
            question_sets.append(deepcopy(question_set))
    past_exams = [
        deepcopy(record)
        for record in _load_all(past_exam_manager)
        if str(getattr(record, "course_id", "") or "") in source_ids
    ]
    source_packs = [
        deepcopy(pack)
        for pack in _load_all(current_event_manager)
        if str(getattr(pack, "course_id", "") or "") in source_ids
    ]
    mastery_before = {}
    if mastery_overrides is not None:
        mastery_before = {
            course_id: set(mastery_overrides.mastered_topics(course_id))
            for course_id in (target_id, *source_ids)
        }

    merged = _merged_project(deepcopy(target), sources)
    migrated_questions = [
        _with_target_metadata(deepcopy(question), merged)
        for question in questions
    ]
    migrated_sets = [
        _with_target_metadata(deepcopy(question_set), merged)
        for question_set in question_sets
    ]
    migrated_exams = [
        replace(
            record,
            course_id=target_id,
            assignment_mode="manual",
            analysis_status="pending",
        )
        for record in past_exams
    ]
    migrated_packs = [
        CurrentEventMaterialPack.create(
            course_id=target_id,
            course_updated_at=merged.updated_at,
            query=pack.query,
            candidates=list(pack.candidates),
            selected_candidate_ids=list(pack.selected_candidate_ids),
            created_at=pack.created_at,
        )
        for pack in source_packs
    ]
    overwritten_packs = {}
    if current_event_manager is not None:
        for pack in migrated_packs:
            existing = current_event_manager.get(pack.pack_id)
            if existing is not None:
                overwritten_packs[pack.pack_id] = deepcopy(existing)

    try:
        _require(course_manager.save(merged, make_current=False), "save merged course")
        for question in migrated_questions:
            _require(question_bank.save(question), f"move question {question.question_id}")
        for question_set in migrated_sets:
            _require(set_manager.save(question_set), f"move question set {question_set.set_id}")
        for record in migrated_exams:
            _require(
                past_exam_manager.save_record(record),
                f"move historical exam {record.exam_id}",
            )
        if mastery_overrides is not None:
            combined_mastery = set().union(*mastery_before.values())
            replacements = {target_id: combined_mastery}
            replacements.update({course_id: set() for course_id in source_ids})
            _require(
                mastery_overrides.replace_course_topics(replacements),
                "move mastery overrides",
            )
        for pack in migrated_packs:
            _require(
                current_event_manager.save(pack),
                f"move current-event pack {pack.pack_id}",
            )
        for pack in source_packs:
            _require(
                current_event_manager.delete(pack.pack_id),
                f"remove old current-event pack {pack.pack_id}",
            )
        for course_id in source_ids:
            _require(course_manager.delete(course_id), f"delete source course {course_id}")
        if current_before_id in {target_id, *source_ids}:
            _require(course_manager.set_current(target_id), "activate merged course")
    except Exception as exc:
        rollback_errors = _rollback(
            projects=original_projects,
            current_before_id=current_before_id,
            questions=questions,
            question_sets=question_sets,
            past_exams=past_exams,
            mastery_before=mastery_before,
            source_packs=source_packs,
            migrated_packs=migrated_packs,
            overwritten_packs=overwritten_packs,
            course_manager=course_manager,
            question_bank=question_bank,
            set_manager=set_manager,
            past_exam_manager=past_exam_manager,
            mastery_overrides=mastery_overrides,
            current_event_manager=current_event_manager,
        )
        return CourseMergeResult(
            False,
            **base_result,
            error=str(exc),
            rollback_errors=tuple(rollback_errors),
        )

    return CourseMergeResult(
        True,
        **base_result,
        question_count=len(source_question_ids),
        question_set_count=len(question_sets),
        past_exam_count=len(past_exams),
        current_event_pack_count=len(migrated_packs),
    )


def _merged_project(target: CourseProject, sources: list[CourseProject]) -> CourseProject:
    target.topics = _merge_topics(target.topics, sources)
    target.documents = _merge_documents(target.documents, sources)
    sections = [str(target.summary_markdown or "").strip()]
    for source in sources:
        summary = str(source.summary_markdown or "").strip()
        if summary:
            sections.append(f"## {source.title}\n\n{summary}")
    target.summary_markdown = "\n\n".join(section for section in sections if section)
    target.updated_at = datetime.now(timezone.utc).isoformat()
    absorbed_ids = list(target.merged_course_ids)
    for source in sources:
        absorbed_ids.extend([source.course_id, *source.merged_course_ids])
    target.merged_course_ids = list(dict.fromkeys(
        course_id
        for course_id in absorbed_ids
        if course_id and course_id != target.course_id
    ))
    target.summary_source = "merged"
    target.summary_warning = ""
    target.generation_profile = {}
    target.generation_profile_source = "local"
    target.generation_profile_warning = ""
    if target.exam_scope_mode == "selected":
        target.exam_scope_topic_ids = [
            topic.topic_id
            for topic in target.topics
            if topic.topic_id in set(target.exam_scope_topic_ids)
        ]
    return target


def _merge_topics(
    target_topics: list[CourseTopic],
    sources: list[CourseProject],
) -> list[CourseTopic]:
    merged = [deepcopy(topic) for topic in target_topics]
    by_id = {topic.topic_id: topic for topic in merged}
    for source in sources:
        for incoming in source.topics:
            existing = by_id.get(incoming.topic_id)
            if existing is None:
                copied = deepcopy(incoming)
                merged.append(copied)
                by_id[copied.topic_id] = copied
                continue
            existing.keywords = _unique([*existing.keywords, *incoming.keywords])
            existing.source_files = _unique([
                *existing.source_files,
                *incoming.source_files,
            ])
            aliases = [*existing.aliases, *incoming.aliases]
            if incoming.title and incoming.title != existing.title:
                aliases.append(incoming.title)
            existing.aliases = _unique(aliases)
    return merged


def _merge_documents(target_documents: list[dict], sources) -> list[dict]:
    merged = [deepcopy(document) for document in target_documents]
    seen = {_document_key(document) for document in merged}
    for source in sources:
        for document in source.documents:
            key = _document_key(document)
            if key in seen:
                continue
            seen.add(key)
            merged.append(deepcopy(document))
    return merged


def _document_key(document) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, default=str)


def _with_target_metadata(item, target: CourseProject):
    metadata = dict(getattr(item, "metadata", {}) or {})
    metadata["course_id"] = target.course_id
    metadata["course_title"] = target.title
    metadata["course_updated_at"] = target.updated_at
    item.metadata = metadata
    return item


def _linked_items(manager, source_ids) -> list:
    return [
        deepcopy(item)
        for item in _load_all(manager)
        if _metadata_course_id(item) in source_ids
    ]


def _metadata_course_id(item) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    return str(metadata.get("course_id", "") or "") if isinstance(metadata, dict) else ""


def _load_all(manager) -> list:
    if manager is None:
        return []
    return list(manager.load_all())


def _rollback(
    *,
    projects,
    current_before_id,
    questions,
    question_sets,
    past_exams,
    mastery_before,
    source_packs,
    migrated_packs,
    overwritten_packs,
    course_manager,
    question_bank,
    set_manager,
    past_exam_manager,
    mastery_overrides,
    current_event_manager,
) -> list[str]:
    errors = []

    def restore(action, label):
        try:
            _require(action(), label)
        except Exception as rollback_error:
            errors.append(str(rollback_error))

    for project in projects:
        restore(
            lambda project=project: course_manager.save(
                deepcopy(project),
                make_current=False,
            ),
            f"restore course {project.course_id}",
        )
    for question in questions:
        restore(
            lambda question=question: question_bank.save(deepcopy(question)),
            f"restore question {question.question_id}",
        )
    for question_set in question_sets:
        restore(
            lambda question_set=question_set: set_manager.save(deepcopy(question_set)),
            f"restore question set {question_set.set_id}",
        )
    for record in past_exams:
        restore(
            lambda record=record: past_exam_manager.save_record(deepcopy(record)),
            f"restore historical exam {record.exam_id}",
        )
    if mastery_overrides is not None:
        restore(
            lambda: mastery_overrides.replace_course_topics(mastery_before),
            "restore mastery overrides",
        )
    if current_event_manager is not None:
        for pack in migrated_packs:
            restore(
                lambda pack=pack: current_event_manager.delete(pack.pack_id)
                if current_event_manager.get(pack.pack_id) is not None
                else True,
                f"remove migrated current-event pack {pack.pack_id}",
            )
        for pack in overwritten_packs.values():
            restore(
                lambda pack=pack: current_event_manager.save(deepcopy(pack)),
                f"restore existing current-event pack {pack.pack_id}",
            )
        for pack in source_packs:
            restore(
                lambda pack=pack: current_event_manager.save(deepcopy(pack)),
                f"restore source current-event pack {pack.pack_id}",
            )
    if current_before_id:
        restore(
            lambda: course_manager.set_current(current_before_id),
            f"restore current course {current_before_id}",
        )
    return errors


def _require(success, action: str) -> None:
    if not success:
        raise OSError(f"Failed to {action}")


def _unique(values) -> list[str]:
    return list(dict.fromkeys(
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    ))
