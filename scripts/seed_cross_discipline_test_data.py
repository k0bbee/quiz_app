"""Materialize and audit the cross-discipline original-source acceptance pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import DATA_DIR
from core.cross_discipline_test_data import (
    audit_cross_discipline_data,
    seed_cross_discipline_data,
)


_GENERATED_CHILDREN = ("courses", "questions", "question_sets", "source_materials")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import cross-discipline course sources and create a runnable acceptance dataset."
    )
    parser.add_argument("--root", required=True, help="Isolated output data root.")
    parser.add_argument("--source-root", required=True, help="Folder containing the original course files.")
    parser.add_argument("--clean", action="store_true", help="Remove only generated children below --root first.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve()
    _validate_roots(root, source_root)
    if args.clean:
        _clean_generated_children(root)

    seeded = seed_cross_discipline_data(root, source_root=source_root)
    audit = audit_cross_discipline_data(root)
    payload = {
        "course_count": seeded.course_count,
        "question_count": audit.question_count,
        "question_set_count": audit.question_set_count,
        "course_ids": list(audit.course_ids),
        "questions_per_course": audit.questions_per_course,
        "sets_per_course": audit.sets_per_course,
        "question_types": [question_type.value for question_type in audit.question_types],
        "question_types_per_course": {
            course_id: [question_type.value for question_type in question_types]
            for course_id, question_types in audit.question_types_per_course.items()
        },
        "documents_per_course": audit.documents_per_course,
        "source_chunks_per_course": audit.source_chunks_per_course,
        "stale_question_refs": list(audit.stale_question_refs),
        "orphan_course_refs": list(audit.orphan_course_refs),
        "structurally_invalid_question_ids": list(audit.structurally_invalid_question_ids),
        "quality_issue_question_ids": list(audit.quality_issue_question_ids),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _validate_roots(root: Path, source_root: Path) -> None:
    protected = {PROJECT_ROOT.resolve(), Path(DATA_DIR).resolve(), source_root}
    if root in protected:
        raise ValueError("--root must be an isolated test-data directory, not the project, app data, or source root")
    if root in source_root.parents or source_root in root.parents:
        raise ValueError("--root and --source-root must not contain one another")


def _clean_generated_children(root: Path) -> None:
    for name in _GENERATED_CHILDREN:
        target = (root / name).resolve()
        if root != target.parent:
            raise ValueError(f"Refusing to clean path outside test root: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
