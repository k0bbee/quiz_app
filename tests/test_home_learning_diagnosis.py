import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.study_intent import StudyAction
from ui.screens.home_screen import HomeScreen


_APP = QApplication.instance() or QApplication([])


class _QuestionBank:
    def __init__(self):
        self.rows = {
            "q-cache-1": ("cache", "高速缓存", "medium"),
            "q-cache-2": ("cache", "高速缓存", "easy"),
            "q-io-1": ("io", "输入输出", "medium"),
            "q-io-2": ("io", "输入输出", "hard"),
        }

    def question_ids(self, course_id=""):
        return list(self.rows)

    def count(self, course_id=""):
        return len(self.rows)

    def topic_index(self, course_id=""):
        return {
            question_id: (topic_id, title)
            for question_id, (topic_id, title, _difficulty) in self.rows.items()
        }

    def scheduling_index(self, course_id=""):
        return dict(self.rows)


class _ProgressManager:
    def __init__(self):
        self.records = [SimpleNamespace(
            status="completed",
            answers=[
                self._answer("q-cache-1", False),
                self._answer("q-cache-2", True),
                self._answer("q-io-1", False, confidence="unsure"),
                self._answer("q-io-2", False),
            ],
        )]

    def load_all(self):
        return list(self.records)

    def get_aggregated_stats(self, question_ids=None, *, records=None):
        return {
            "total_sessions": 1,
            "total_questions": 4,
            "overall_accuracy": 25.0,
        }

    @staticmethod
    def _answer(question_id, is_correct, *, confidence="sure"):
        return SimpleNamespace(
            question_id=question_id,
            is_correct=is_correct,
            confidence=confidence,
            skipped=False,
        )


class HomeLearningDiagnosisTests(unittest.TestCase):
    def test_home_without_learning_data_keeps_the_diagnosis_area_compact(self):
        screen = HomeScreen()
        self.addCleanup(screen.close)

        self.assertIn("学习重点", screen.diagnosis_title.text())
        self.assertTrue(screen.diagnosis_label.isHidden())

    def test_home_shows_two_explainable_focus_topics_beside_the_daily_action(self):
        screen = HomeScreen(_ProgressManager(), _QuestionBank())
        self.addCleanup(screen.close)

        screen.set_current_course("course-os", "操作系统")

        self.assertIn("当前需要巩固", screen.diagnosis_title.text())
        self.assertIn("输入输出", screen.diagnosis_label.text())
        self.assertIn("错误 2", screen.diagnosis_label.text())
        self.assertIn("高速缓存", screen.diagnosis_label.text())
        self.assertFalse(screen.diagnosis_label.isHidden())

    def test_home_focus_topic_is_a_direct_learning_action(self):
        screen = HomeScreen(_ProgressManager(), _QuestionBank())
        self.addCleanup(screen.close)
        requests = []
        screen.study_requested.connect(requests.append)

        screen.set_current_course("course-os", "操作系统")

        self.assertFalse(screen.focus_action_buttons[0].isHidden())
        self.assertIn("输入输出", screen.focus_action_buttons[0].text())
        screen.focus_action_buttons[0].click()

        self.assertEqual(1, len(requests))
        self.assertIs(StudyAction.PRACTICE_TOPIC, requests[0].action)
        self.assertEqual(("io",), requests[0].topic_ids)
        self.assertEqual("home_focus", requests[0].source)

    def test_home_does_not_expose_exam_goal_state(self):
        screen = HomeScreen(_ProgressManager(), _QuestionBank())
        self.addCleanup(screen.close)

        screen.set_current_course("course-os", "操作系统")

        self.assertFalse(hasattr(screen, "exam_goal_store"))
        self.assertNotIn("距考试", screen.next_step_label.text())


if __name__ == "__main__":
    unittest.main()
