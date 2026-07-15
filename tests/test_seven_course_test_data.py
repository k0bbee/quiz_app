from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.seven_course_test_data import (
    CROSS_DISCIPLINE_COURSE_IDS,
    CROSS_DISCIPLINE_SOURCES,
    _CourseSeed,
    _COURSES,
    _QuestionSeed,
    _build_question,
    audit_seven_course_data,
    seed_seven_course_data,
)
from core.course_index import attach_index_to_project, build_source_index
from models.course_project import CourseProject, CourseProjectManager, CourseTopic
from core.quiz_engine import QuizSession
from models.question import QuestionBank
from models.question_set import SetManager
from utils.constants import Difficulty, QuestionType


class SevenCourseTestDataTests(unittest.TestCase):
    def test_source_grounding_does_not_succeed_from_distractor_text_alone(self):
        project = CourseProject(
            course_id="test-course-grounding",
            title="Grounding",
            source_folder="",
            summary_markdown="",
            summary_path="",
            topics=[CourseTopic("supported_topic", "Supported Topic", ["absent concept"])],
            documents=[{
                "path": "grounding.md",
                "title": "grounding",
                "extension": ".md",
                "pages": ["Only distractor evidence appears in this source."],
            }],
            created_at="",
            updated_at="",
        )
        attach_index_to_project(project)
        question_seed = _QuestionSeed(
            type=QuestionType.MULTIPLE_CHOICE,
            topic_index=0,
            stem_zh="选择正确概念。",
            stem_en="Choose the correct concept.",
            options_zh=("正确概念", "干扰证据"),
            options_en=("Correct concept", "Distractor evidence"),
            answer="A",
            explanation_zh="正确概念与资料中的干扰词无关。",
            explanation_en="A separate principle justifies the correct concept.",
        )
        course_seed = _CourseSeed(
            slug="grounding",
            title="Grounding",
            source_name="grounding.md",
            topics=(("supported_topic", "Supported Topic", ("absent concept",)),),
            questions=(question_seed,),
        )

        with self.assertRaisesRegex(ValueError, "no source evidence"):
            _build_question(project, course_seed, question_seed, 1)

    @pytest.mark.full
    def test_seed_pack_builds_seven_runnable_cross_discipline_courses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "seven-course-data"
            source_root = Path(tmpdir) / "original-sources"
            self._write_original_sources(source_root)

            seeded = seed_seven_course_data(root, source_root=source_root)
            audit = audit_seven_course_data(root)

            self.assertEqual(10, seeded.course_count)
            self.assertEqual(set(CROSS_DISCIPLINE_COURSE_IDS), set(audit.course_ids))
            self.assertEqual(70, audit.question_count)
            self.assertEqual(10, audit.question_set_count)
            self.assertTrue(all(count == 7 for count in audit.questions_per_course.values()))
            self.assertTrue(all(count == 1 for count in audit.sets_per_course.values()))
            self.assertEqual(set(QuestionType), set(audit.question_types))
            self.assertTrue(
                all(set(types) == set(QuestionType) for types in audit.question_types_per_course.values())
            )
            self.assertEqual((), audit.stale_question_refs)
            self.assertEqual((), audit.orphan_course_refs)
            self.assertEqual((), audit.structurally_invalid_question_ids)
            self.assertEqual((), audit.quality_issue_question_ids)
            self.assertTrue(all(count >= 1 for count in audit.documents_per_course.values()))
            self.assertTrue(all(count >= 1 for count in audit.source_chunks_per_course.values()))

            question_bank = QuestionBank(str(root / "questions"))
            projects = {
                project.course_id: project
                for project in CourseProjectManager(str(root / "courses")).load_all()
            }
            expected_topics = {
                f"test-course-{course.slug}": {topic_id for topic_id, _title, _keywords in course.topics}
                for course in _COURSES
            }
            questions_by_course = {}
            for question in question_bank.load_all():
                course_id = question.metadata["course_id"]
                questions_by_course.setdefault(course_id, []).append(question)
                self.assertIn(question.topic_id(), expected_topics[course_id])
                self.assertEqual("verified", question.metadata.get("source_ref_status"))
                source_refs = question.metadata.get("source_refs")
                self.assertTrue(source_refs, question.question_id)
                chunk_ids = {
                    chunk["chunk_id"]
                    for chunk in build_source_index(projects[course_id])
                }
                self.assertIn(source_refs[0]["chunk_id"], chunk_ids)

            for course_id, topic_ids in expected_topics.items():
                self.assertEqual(topic_ids, {topic.topic_id for topic in projects[course_id].topics})
                self.assertEqual(topic_ids, {q.topic_id() for q in questions_by_course[course_id]})
                self.assertEqual(
                    set(Difficulty),
                    {question.difficulty for question in questions_by_course[course_id]},
                )
                profile = projects[course_id].generation_profile
                self.assertEqual(topic_ids, set(profile.get("selected_topics", [])))
                self.assertEqual(topic_ids, set(profile.get("topic_weights", {})))

            for question_set in SetManager(str(root / "question_sets")).load_all():
                questions = question_bank.get_many(
                    question_set.questions,
                    course_id=question_set.metadata["course_id"],
                )
                session = QuizSession()
                session.start(question_set, questions, language="zh")
                self.assertEqual(7, session.total_questions)
                self.assertIsNotNone(session.current_question)
                while session.current_question is not None:
                    question = session.current_question
                    if question.type == QuestionType.FILL_IN_BLANK:
                        answer = question.correct_answer[0]
                    elif question.type == QuestionType.SHORT_ANSWER:
                        answer = "已依据参考要点完成自评。"
                    else:
                        answer = question.correct_answer
                    session.submit_answer(
                        answer,
                        manual_is_correct=True if question.type == QuestionType.SHORT_ANSWER else None,
                    )
                    if not session.next_question():
                        break
                record = session.get_progress_record()
                self.assertIsNotNone(record)
                self.assertEqual("completed", record.status)
                self.assertEqual(7, record.summary.answered)
                self.assertEqual(7, record.summary.correct)

            repeated = seed_seven_course_data(root, source_root=source_root)
            repeated_audit = audit_seven_course_data(root)
            self.assertEqual(seeded, repeated)
            self.assertEqual(70, repeated_audit.question_count)
            self.assertEqual(10, repeated_audit.question_set_count)

    @pytest.mark.full
    def test_cli_clean_rebuild_prints_json_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "seven-course-runtime"
            source_root = Path(tmpdir) / "original-sources"
            self._write_original_sources(source_root)
            stale = root / "questions" / "stale.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}", encoding="utf-8")
            script = Path(__file__).parents[1] / "scripts" / "seed_seven_course_test_data.py"

            completed = subprocess.run(
                [
                    sys.executable, str(script),
                    "--root", str(root),
                    "--source-root", str(source_root),
                    "--clean",
                ],
                cwd=script.parents[1],
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(10, report["course_count"])
            self.assertEqual(70, report["question_count"])
            self.assertEqual(10, report["question_set_count"])
            self.assertEqual([], report["stale_question_refs"])
            self.assertFalse(stale.exists())

    @staticmethod
    def _write_original_sources(source_root: Path) -> None:
        source_root.mkdir(parents=True)
        course_by_slug = {course.slug: course for course in _COURSES}
        for slug, filenames in CROSS_DISCIPLINE_SOURCES.items():
            filename = filenames[-1]
            topic = slug.replace("-", " ")
            keywords = " ".join(
                keyword
                for _topic_id, _title, topic_keywords in course_by_slug[slug].topics
                for keyword in topic_keywords
            )
            sentences = [
                f"{topic} source section {index} explains {keywords}, their conditions, process, evidence, and limitations."
                for index in range(1, 18)
            ]
            (source_root / filename).write_text("\n".join(sentences), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
