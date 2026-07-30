import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.study_intent import StudyAction
from models.question_set import SetManager
from ui.screens.topic_selection_screen import TopicSelectionScreen


_APP = QApplication.instance() or QApplication([])


class _SchedulingBank:
    def __init__(self):
        self.rows = {
            "q-cache-1": ("cache", "高速缓存", "medium"),
            "q-cache-2": ("cache", "高速缓存", "easy"),
            "q-io-1": ("io", "输入输出", "medium"),
            "q-process-1": ("process", "进程", "hard"),
        }
        self.requested_course_ids = []

    def scheduling_index(self, course_id=""):
        self.requested_course_ids.append(course_id)
        return dict(self.rows)

    def topic_index(self, course_id=""):
        return {
            question_id: (topic_id, topic_title)
            for question_id, (topic_id, topic_title, _difficulty)
            in self.rows.items()
        }


class StudySetupScreenTests(unittest.TestCase):
    def _screen(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        bank = _SchedulingBank()
        screen = TopicSelectionScreen(
            SetManager(tempdir.name),
            question_bank=bank,
        )
        self.addCleanup(screen.close)
        screen.set_current_course("course-os", "操作系统")
        return screen, bank

    def test_free_practice_uses_questions_without_requiring_a_saved_set(self):
        screen, bank = self._screen()
        started = []
        screen.study_start.connect(
            lambda intent, ids: started.append((intent, ids))
        )

        self.assertEqual("practice", screen.study_mode)
        self.assertFalse(hasattr(screen, "export_btn"))
        self.assertFalse(hasattr(screen, "rename_btn"))
        self.assertFalse(hasattr(screen, "regenerate_btn"))
        self.assertTrue(screen.start_btn.isEnabled())

        screen.question_count_input.setValue(3)
        screen.start_btn.click()

        self.assertEqual(["course-os"], bank.requested_course_ids[-1:])
        intent, question_ids = started[0]
        self.assertIs(StudyAction.CUSTOM_PRACTICE, intent.action)
        self.assertEqual("practice", intent.submission_mode)
        self.assertEqual(
            ["q-cache-1", "q-io-1", "q-process-1"],
            question_ids,
        )

    def test_mock_exam_is_an_inline_mode_not_a_start_dialog(self):
        screen, _bank = self._screen()
        started = []
        screen.study_start.connect(
            lambda intent, ids: started.append((intent, ids))
        )

        screen.mock_exam_mode_btn.click()
        screen.question_count_input.setValue(2)
        screen.start_btn.click()

        intent, question_ids = started[0]
        self.assertEqual("exam", screen.study_mode)
        self.assertEqual("exam", intent.submission_mode)
        self.assertEqual(2, len(question_ids))

    def test_scope_changes_refresh_a_user_facing_practice_preview(self):
        screen, _bank = self._screen()

        screen.question_count_input.setValue(6)

        self.assertFalse(screen.practice_preview_card.isHidden())
        self.assertIn("本次练习", screen.practice_preview_title.text())
        self.assertIn("4 题", screen.practice_preview_primary.text())
        self.assertIn("约 8 分钟", screen.practice_preview_primary.text())
        self.assertIn("高速缓存 2", screen.practice_preview_coverage.text())
        self.assertIn("还差 2 题", screen.practice_preview_gap.text())
        self.assertIn("补齐后约 12 分钟", screen.practice_preview_gap.text())

    def test_today_mode_routes_back_to_the_daily_plan(self):
        screen, _bank = self._screen()
        requested = []
        screen.today_mode_requested.connect(lambda: requested.append(True))

        screen.today_mode_btn.click()

        self.assertEqual([True], requested)


if __name__ == "__main__":
    unittest.main()
