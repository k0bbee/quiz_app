"""Atomic persistence and progression for bounded daily study plans."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from models.daily_study_plan import DailyStudyPlan
from utils.json_io import read_json, write_json


_SCHEMA_VERSION = 1
_MAX_REMEDIATION_QUESTIONS = 5


class DailyStudyPlanStore:
    """Persist daily plan snapshots and advance them idempotently."""

    def __init__(self, filepath: str | Path):
        self._path = str(filepath)

    def get(self, plan_id: str) -> DailyStudyPlan | None:
        plan_id = str(plan_id or "").strip()
        if not plan_id:
            return None
        payload = self._load_payload()
        data = payload["plans"].get(plan_id)
        if not isinstance(data, dict):
            return None
        try:
            plan = DailyStudyPlan.from_dict(data)
        except (TypeError, ValueError):
            return None
        return plan if plan.plan_id == plan_id else None

    def get_or_create(
        self,
        *,
        plan_id: str,
        plan_date: str,
        course_id: str,
        queue,
        valid_question_ids,
    ) -> DailyStudyPlan:
        plan_id = str(plan_id or "").strip()
        if not plan_id:
            raise ValueError("plan_id is required")
        valid_ids = _normalized_ids(valid_question_ids)
        existing = self.get(plan_id)
        if existing is not None:
            reconciled = self._reconcile(existing, valid_ids, queue)
            if reconciled != existing:
                self._save(reconciled)
            return reconciled

        planned_ids = tuple(
            question_id
            for question_id in _normalized_ids(
                getattr(queue, "question_ids", ()) or ()
            )
            if question_id in valid_ids
        )
        planned_set = set(planned_ids)
        category_by_question = tuple(
            (
                str(getattr(entry, "question_id", "") or "").strip(),
                str(
                    getattr(
                        getattr(entry, "category", ""),
                        "value",
                        getattr(entry, "category", ""),
                    )
                    or ""
                ).strip(),
            )
            for entry in (getattr(queue, "entries", ()) or ())
            if str(getattr(entry, "question_id", "") or "").strip()
            in planned_set
        )
        plan = DailyStudyPlan(
            plan_id=plan_id,
            date=plan_date,
            course_id=course_id,
            planned_ids=planned_ids,
            completed_ids=(),
            pending_ids=planned_ids,
            remediation_ids=(),
            deferred_ids=(),
            category_by_question=category_by_question,
            backlog_count=int(
                getattr(queue, "backlog_count", len(planned_ids))
                or len(planned_ids)
            ),
            updated_at=_utc_now(),
        )
        self._save(plan)
        return plan

    def record_completion(
        self,
        plan_id: str,
        *,
        current_question_ids,
        answers,
    ) -> DailyStudyPlan:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(f"daily study plan not found: {plan_id}")

        answer_by_id = {
            question_id: answer
            for answer in (answers or ())
            if (
                question_id := str(
                    getattr(answer, "question_id", "") or ""
                ).strip()
            )
        }
        completed = list(plan.completed_ids)
        pending = list(plan.pending_ids)
        remediation = list(plan.remediation_ids)
        deferred = list(plan.deferred_ids)
        changed = False
        for question_id in _normalized_ids(current_question_ids):
            if question_id not in pending:
                continue
            changed = True
            was_remediation = question_id in remediation
            pending.remove(question_id)
            if was_remediation:
                remediation.remove(question_id)
            if question_id not in completed:
                completed.append(question_id)

            answer = answer_by_id.get(question_id)
            skipped = answer is None or bool(getattr(answer, "skipped", False))
            needs_remediation = (
                not skipped
                and (
                    not bool(getattr(answer, "is_correct", False))
                    or str(
                        getattr(answer, "confidence", "sure") or "sure"
                    ) == "unsure"
                )
            )
            if was_remediation:
                if needs_remediation or skipped:
                    _append_unique(deferred, question_id)
                continue
            if skipped:
                _append_unique(deferred, question_id)
            elif needs_remediation:
                if len(remediation) < _MAX_REMEDIATION_QUESTIONS:
                    remediation.append(question_id)
                    pending.append(question_id)
                else:
                    _append_unique(deferred, question_id)

        if not changed:
            return plan
        updated = replace(
            plan,
            completed_ids=tuple(completed),
            pending_ids=tuple(pending),
            remediation_ids=tuple(remediation),
            deferred_ids=tuple(deferred),
            updated_at=_utc_now(),
        )
        self._save(updated)
        return updated

    def clear(self) -> None:
        if not write_json(
            self._path,
            {"schema_version": _SCHEMA_VERSION, "plans": {}},
        ):
            raise OSError("failed to clear daily study plans")

    def _reconcile(
        self,
        plan: DailyStudyPlan,
        valid_ids: tuple[str, ...],
        queue,
    ) -> DailyStudyPlan:
        valid = set(valid_ids)
        updated = replace(
            plan,
            planned_ids=tuple(
                question_id
                for question_id in plan.planned_ids
                if question_id in valid
            ),
            completed_ids=tuple(
                question_id
                for question_id in plan.completed_ids
                if question_id in valid
            ),
            pending_ids=tuple(
                question_id
                for question_id in plan.pending_ids
                if question_id in valid
            ),
            remediation_ids=tuple(
                question_id
                for question_id in plan.remediation_ids
                if question_id in valid
            ),
            deferred_ids=tuple(
                question_id
                for question_id in plan.deferred_ids
                if question_id in valid
            ),
            category_by_question=tuple(
                row
                for row in plan.category_by_question
                if row[0] in valid
            ),
            backlog_count=int(
                getattr(queue, "backlog_count", plan.backlog_count)
                or plan.backlog_count
            ),
            updated_at=plan.updated_at,
        )
        if updated == plan:
            return plan
        return replace(updated, updated_at=_utc_now())

    def _save(self, plan: DailyStudyPlan) -> None:
        payload = self._load_payload()
        payload["plans"][plan.plan_id] = plan.to_dict()
        if not write_json(self._path, payload):
            raise OSError("failed to persist daily study plan")

    def _load_payload(self) -> dict:
        payload = read_json(self._path) or {}
        if not isinstance(payload, dict):
            payload = {}
        plans = payload.get("plans")
        if not isinstance(plans, dict):
            plans = {}
        return {
            "schema_version": _SCHEMA_VERSION,
            "plans": plans,
        }


def _normalized_ids(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        text
        for value in (values or ())
        if (text := str(value or "").strip())
    ))


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
