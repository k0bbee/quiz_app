import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from models.course_project import CourseProject, CourseProjectManager
from models.question import Question, QuestionBank
from models.question_set import QuestionSet, SetManager
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


class LibraryScreenTests(unittest.TestCase):
    def test_library_scope_has_no_unassigned_ui_scope(self):
        from core.library_scope import LibraryAssetScope, LibraryScopeKind

        self.assertFalse(hasattr(LibraryAssetScope, "unassigned"))
        self.assertFalse(hasattr(LibraryScopeKind, "UNASSIGNED"))

    @staticmethod
    def _project(course_id: str, title: str, *, status: str = "active"):
        return CourseProject(
            course_id=course_id,
            title=title,
            source_folder="",
            summary_markdown=f"# {title}",
            summary_path="",
            topics=[],
            documents=[],
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
            status=status,
        )

    @staticmethod
    def _question(question_id: str, course_id: str = ""):
        question = Question(
            question_id=question_id,
            type=QuestionType.TRUE_FALSE,
            difficulty=Difficulty.EASY,
            bilingual={
                "zh": {
                    "stem": question_id,
                    "options": ["正确", "错误"],
                    "explanation": "",
                },
                "en": {
                    "stem": question_id,
                    "options": ["True", "False"],
                    "explanation": "",
                },
            },
            correct_answer=True,
            topic="general",
        )
        if course_id:
            question.metadata["course_id"] = course_id
        return question

    @staticmethod
    def _visible_question_ids(screen) -> set[str]:
        model = screen.question_screen.question_table_model
        return {
            str(model.index(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(model.rowCount())
        }

    @staticmethod
    def _visible_set_ids(screen) -> set[str]:
        panel = screen.set_panel
        return {
            str(panel.set_list.item(row).data(panel.SET_ID_ROLE))
            for row in range(panel.set_list.count())
        }

    def test_library_separates_question_records_from_question_set_assets(self):
        from ui.screens.library_screen import LibraryScreen

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            set_manager = SetManager(str(root / "sets"))
            course_manager = CourseProjectManager(str(root / "courses"))
            course_manager.save(
                self._project("course-os", "Operating Systems"),
                make_current=True,
            )
            question_set = QuestionSet.create_new(
                title={"zh": "操作系统复习", "en": "OS Review"},
                description={"zh": "", "en": ""},
                topics=["io"],
                question_ids=["q-1"],
                difficulty=Difficulty.MEDIUM,
            )
            question_set.metadata["course_id"] = "course-os"
            set_manager.save(question_set)
            screen = LibraryScreen(
                QuestionBank(str(root / "questions")),
                set_manager=set_manager,
                course_manager=course_manager,
            )
            self.addCleanup(screen.close)

            screen.set_current_course("course-os")
            screen.refresh()

            self.assertEqual(2, screen.workspace_tabs.count())
            self.assertEqual("question_records", screen.workspace_tabs.widget(0).objectName())
            self.assertEqual("question_sets", screen.workspace_tabs.widget(1).objectName())
            self.assertTrue(screen.question_screen.page_header.isHidden())
            margins = screen.question_screen.layout().contentsMargins()
            self.assertEqual(
                (0, 0, 0, 0),
                (
                    margins.left(),
                    margins.top(),
                    margins.right(),
                    margins.bottom(),
                ),
            )
            self.assertEqual(1, screen.set_panel.set_list.count())
            self.assertEqual(
                question_set.set_id,
                screen.set_panel.set_list.item(0).data(
                    screen.set_panel.SET_ID_ROLE
                ),
            )
            for button in (
                screen.set_panel.rename_btn,
                screen.set_panel.export_btn,
                screen.set_panel.regenerate_btn,
                screen.set_panel.delete_btn,
            ):
                self.assertIsNotNone(button)

    def test_library_uses_current_course_as_the_only_visible_scope(self):
        from ui.screens.library_screen import LibraryScreen

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(str(root / "courses"))
            active = self._project("course-active", "Active Course")
            archived = self._project(
                "course-archived",
                "Archived Course",
                status="archived",
            )
            self.assertTrue(course_manager.save(active, make_current=True))
            self.assertTrue(course_manager.save(archived, make_current=False))
            question_bank = QuestionBank(str(root / "questions"))
            question_bank.save_many([
                self._question("q-active", active.course_id),
                self._question("q-archived", archived.course_id),
                self._question("q-unassigned"),
            ])
            set_manager = SetManager(str(root / "sets"))
            for set_id, course_id, question_id in (
                ("set-active", active.course_id, "q-active"),
                ("set-archived", archived.course_id, "q-archived"),
                ("set-unassigned", "", "q-unassigned"),
            ):
                question_set = QuestionSet.create_new(
                    title={"zh": set_id, "en": set_id},
                    description={"zh": "", "en": ""},
                    topics=["general"],
                    question_ids=[question_id],
                )
                question_set.set_id = set_id
                if course_id:
                    question_set.metadata["course_id"] = course_id
                set_manager.save(question_set)
            screen = LibraryScreen(
                question_bank,
                set_manager=set_manager,
                course_manager=course_manager,
            )
            self.addCleanup(screen.close)

            screen.set_current_course(active.course_id)

            self.assertFalse(hasattr(screen, "active_scope_btn"))
            self.assertFalse(hasattr(screen, "archived_scope_btn"))
            self.assertFalse(hasattr(screen, "unassigned_scope_btn"))
            self.assertFalse(hasattr(screen, "course_scope_combo"))
            self.assertEqual(active.course_id, screen.current_scope.course_id)
            self.assertEqual(
                {"q-active"},
                self._visible_question_ids(screen),
            )
            self.assertEqual(
                {"set-active"},
                self._visible_set_ids(screen),
            )

            screen.show_course_assets(archived.course_id)

            self.assertEqual(archived.course_id, screen.current_scope.course_id)
            self.assertEqual(
                {"q-archived"},
                self._visible_question_ids(screen),
            )
            self.assertEqual(
                {"set-archived"},
                self._visible_set_ids(screen),
            )

            self.assertIn(archived.title, screen.scope_label.text())

    def test_library_can_open_one_archived_course_directly(self):
        from ui.screens.library_screen import LibraryScreen

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            course_manager = CourseProjectManager(str(root / "courses"))
            archived = self._project(
                "course-archived",
                "Archived Course",
                status="archived",
            )
            self.assertTrue(course_manager.save(archived, make_current=False))
            screen = LibraryScreen(
                QuestionBank(str(root / "questions")),
                set_manager=SetManager(str(root / "sets")),
                course_manager=course_manager,
            )
            self.addCleanup(screen.close)

            screen.show_course_assets(archived.course_id)

            self.assertEqual(archived.course_id, screen.current_scope.course_id)
            self.assertIn(archived.title, screen.scope_label.text())


if __name__ == "__main__":
    unittest.main()
