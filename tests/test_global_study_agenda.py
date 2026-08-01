import unittest
from datetime import date
from types import SimpleNamespace

from core.global_study_agenda import build_global_study_agenda
from core.study_queue import StudyQueueCategory


class _QuestionBank:
    def __init__(self, rows):
        self.rows = rows

    def question_ids(self, *, course_id):
        return list(self.rows[course_id]["ids"])

    def scheduling_index(self, *, course_id):
        return dict(self.rows[course_id]["scheduling"])


class _CourseManager:
    def __init__(self, courses):
        self.courses = courses

    def load_all(self):
        return list(self.courses)


class _ExamGoals:
    def __init__(self, goals):
        self.goals = goals

    def get(self, course_id):
        return self.goals.get(course_id)


class _Mastery:
    def __init__(self, mastered):
        self.mastered = mastered

    def mastered_topics(self, course_id):
        return set(self.mastered.get(course_id, ()))


class _DailyPlanStore:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def get_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return self.plan


class GlobalStudyAgendaTests(unittest.TestCase):
    def test_orders_exam_and_actionable_courses_without_changing_current_course(self):
        courses = [
            SimpleNamespace(
                course_id="course-a",
                title="算法",
                exam_scope_mode="all",
                topics=[],
                generation_profile={},
            ),
            SimpleNamespace(
                course_id="course-b",
                title="操作系统",
                exam_scope_mode="all",
                topics=[],
                generation_profile={},
            ),
        ]
        question_bank = _QuestionBank({
            "course-a": {
                "ids": ["a-1"],
                "scheduling": {"a-1": ("sorting", "排序", "medium")},
            },
            "course-b": {
                "ids": ["b-1", "b-2"],
                "scheduling": {
                    "b-1": ("io", "输入输出", "medium"),
                    "b-2": ("io", "输入输出", "easy"),
                },
            },
        })
        records = [
            SimpleNamespace(
                status="completed",
                answers=[
                    SimpleNamespace(
                        question_id="b-1",
                        is_correct=False,
                        confidence="sure",
                        skipped=False,
                    )
                ],
                started_at="2026-07-31T09:00:00+08:00",
            )
        ]

        agenda = build_global_study_agenda(
            _CourseManager(courses),
            question_bank=question_bank,
            progress_records=records,
            exam_goal_store=_ExamGoals({
                "course-a": SimpleNamespace(
                    days_remaining=lambda _today: 20,
                ),
                "course-b": SimpleNamespace(
                    days_remaining=lambda _today: 5,
                ),
            }),
            reference_date=date(2026, 8, 1),
            current_course_id="course-a",
        )

        self.assertEqual(("course-b", "course-a"), agenda.course_ids)
        self.assertEqual(3, agenda.total_question_count)
        self.assertEqual(3, agenda.total_actionable_count)
        self.assertEqual("course-b", agenda.items[0].course_id)
        self.assertEqual("操作系统", agenda.items[0].title)
        self.assertGreaterEqual(agenda.items[0].incorrect_count, 1)
        self.assertEqual("course-a", agenda.current_course_id)

    def test_respects_exam_scope_and_mastered_topics(self):
        course = SimpleNamespace(
            course_id="course-a",
            title="课程 A",
            exam_scope_mode="selected",
            topics=[
                SimpleNamespace(topic_id="keep", title="保留"),
                SimpleNamespace(topic_id="drop", title="范围外"),
            ],
            exam_topics=lambda: [SimpleNamespace(topic_id="keep", title="保留")],
            generation_profile={},
        )
        agenda = build_global_study_agenda(
            _CourseManager([course]),
            question_bank=_QuestionBank({
                "course-a": {
                    "ids": ["q-keep", "q-drop", "q-mastered"],
                    "scheduling": {
                        "q-keep": ("keep", "保留", "medium"),
                        "q-drop": ("drop", "范围外", "medium"),
                        "q-mastered": ("keep", "保留", "hard"),
                    },
                }
            }),
            progress_records=[],
            mastery_overrides=_Mastery({"course-a": {"keep"}}),
        )

        item = agenda.items[0]
        self.assertEqual(0, item.total_question_count)
        self.assertEqual(0, item.total_actionable_count)

    def test_category_counts_are_exposed_as_plain_user_facing_values(self):
        course = SimpleNamespace(
            course_id="course-a",
            title="课程 A",
            exam_scope_mode="all",
            topics=[],
            generation_profile={},
        )
        agenda = build_global_study_agenda(
            _CourseManager([course]),
            question_bank=_QuestionBank({
                "course-a": {
                    "ids": ["q-1"],
                    "scheduling": {"q-1": ("io", "输入输出", "medium")},
                }
            }),
            progress_records=[],
        )

        item = agenda.items[0]
        self.assertIsInstance(item.category_counts, tuple)
        self.assertEqual(1, dict(item.category_counts).get(StudyQueueCategory.NEW.value))

    def test_reuses_persisted_daily_plan_state_for_remaining_counts(self):
        course = SimpleNamespace(
            course_id="course-a",
            title="课程 A",
            exam_scope_mode="all",
            topics=[],
            generation_profile={},
        )
        store = _DailyPlanStore(SimpleNamespace(
            plan_id="2026-08-01:course-a",
            pending_ids=("q-2", "q-3"),
            next_session=lambda: (("q-2",), ("q-3",)),
        ))

        agenda = build_global_study_agenda(
            _CourseManager([course]),
            question_bank=_QuestionBank({
                "course-a": {
                    "ids": ["q-1", "q-2", "q-3"],
                    "scheduling": {
                        "q-1": ("io", "输入输出", "medium"),
                        "q-2": ("io", "输入输出", "medium"),
                        "q-3": ("io", "输入输出", "easy"),
                    },
                }
            }),
            progress_records=[],
            daily_plan_store=store,
            reference_date=date(2026, 8, 1),
        )

        item = agenda.items[0]
        self.assertEqual("2026-08-01:course-a", item.plan_id)
        self.assertEqual(("q-2",), item.today_question_ids)
        self.assertEqual(("q-3",), item.remaining_question_ids)
        self.assertEqual(2, item.total_actionable_count)
        self.assertEqual(1, len(store.calls))


if __name__ == "__main__":
    unittest.main()
