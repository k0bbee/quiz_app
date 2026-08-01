import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

from ai.batch_generator import GenerationWorker
from ai.generation_config import GenerationConfig
from ai.question_plan import QuestionPlanItem
from ai.exam_plan import ExamGenerationPlan
from ai.llm_client import LLMClient
from ai.generation_report import GenerationReport
from core.app_errors import AppError
from core.background_task_center import BackgroundTaskCenter, TaskStatus
from core import course_index
from core.question_set_builder import build_ai_question_set
from ui.dialogs.ai_generation_dialog import AIGenerationDialog
from ui.generation_workspace_controller import GenerationWorkspaceController
from ui.navigation import Route
from models.course_project import CourseProject, CourseTopic
from models.question import Question
from models.question_set import QuestionSet
from utils.constants import Difficulty, QuestionType, topic_value


_APP = QApplication.instance() or QApplication([])

class GenerationProfileFlowTests(unittest.TestCase):
    def test_dialog_can_prefill_from_existing_question_set(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process", "gpu"],
            )
            qset = QuestionSet(
                set_id="set-review",
                title={"zh": "复习", "en": "Review"},
                description={"zh": "", "en": ""},
                topics=["cache", "gpu"],
                difficulty=Difficulty.HARD,
                estimated_minutes=20,
                questions=["q1", "q2", "q3", "q4", "q5"],
            )

            dialog.configure_from_question_set(qset)

            self.assertEqual(dialog.count_spin.value(), 5)
            self.assertEqual(dialog.diff_combo.currentData(), "hard")
            checked = {
                dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(dialog.topic_list.count())
                if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
            }
            self.assertEqual({"cache", "gpu"}, checked)

    def test_dialog_exam_plan_round_trip_applies_all_controls(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            target = ExamGenerationPlan(
                question_count=22,
                difficulty="mixed",
                template="final_exam",
                selected_topics=("process",),
                question_type_weights={
                    "multiple_choice": 20,
                    "scenario_choice": 20,
                    "true_false": 20,
                    "fill_in_blank": 10,
                    "matching": 10,
                    "ordering": 10,
                    "short_answer": 10,
                },
                difficulty_weights={"easy": 10, "medium": 50, "hard": 40},
                topic_weights={"process": 100},
            )

            dialog.apply_exam_plan(target)
            rebuilt = dialog.build_exam_plan()

            self.assertEqual(target.to_dict(), rebuilt.to_dict())
            checked = {
                dialog.topic_list.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(dialog.topic_list.count())
                if dialog.topic_list.item(index).checkState() == Qt.CheckState.Checked
            }
            self.assertEqual({"process"}, checked)

    def test_exam_assistant_button_uses_descriptive_label_instead_of_jargon(self):
            from core.language_manager import LanguageManager

            lang_manager = LanguageManager.instance()
            previous_lang = lang_manager.current
            self.addCleanup(lang_manager.set_language, previous_lang)

            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )

            lang_manager.set_language("zh")
            self.assertNotIn("试卷助手", dialog.exam_assistant_btn.text())

            lang_manager.set_language("en")
            self.assertNotIn("Exam Assistant", dialog.exam_assistant_btn.text())

    def test_accepted_exam_assistant_plan_is_applied(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            target = ExamGenerationPlan(
                question_count=30,
                selected_topics=("cache",),
                topic_weights={"cache": 100},
            )

            with patch("ui.dialogs.exam_assistant_dialog.ExamAssistantDialog") as assistant_class:
                assistant = assistant_class.return_value
                assistant.exec.return_value = QDialog.DialogCode.Accepted
                assistant.get_confirmed_plan.return_value = target

                dialog._open_exam_assistant()

            self.assertEqual(30, dialog.count_spin.value())
            assistant_class.assert_called_once()

    def test_dialog_prefills_all_controls_from_course_generation_profile(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            profile = ExamGenerationPlan(
                question_count=26,
                difficulty="mixed",
                template="calculation_practice",
                selected_topics=("cache", "process"),
                question_type_weights={
                    "multiple_choice": 30,
                    "scenario_choice": 30,
                    "true_false": 10,
                    "fill_in_blank": 30,
                },
                difficulty_weights={"easy": 10, "medium": 40, "hard": 50},
                topic_weights={"cache": 70, "process": 30},
            )
            course = SimpleNamespace(generation_profile=profile.to_dict())

            applied = dialog.configure_from_course_profile(course)

            self.assertTrue(applied)
            self.assertEqual(profile.to_dict(), dialog.build_exam_plan().to_dict())

    def test_malformed_course_profile_keeps_current_controls_and_shows_error(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            before = dialog.build_exam_plan().to_dict()
            course = SimpleNamespace(
                generation_profile={"selected_topics": ["invented topic"]}
            )

            applied = dialog.configure_from_course_profile(course)

            self.assertFalse(applied)
            self.assertEqual(before, dialog.build_exam_plan().to_dict())
            self.assertIn("invented topic", dialog.status_label.text())

    def test_course_profile_legacy_topic_names_are_migrated_before_apply(self):
            from models.course_project import CourseTopic

            io_topic = CourseTopic(
                topic_id="input_output_improvements",
                title="Input Output Improvements",
                aliases=["input output improvements", "I/O 改进"],
            )
            vm_topic = CourseTopic(
                topic_id="virtual_memory_address_translation_and_page_replacement",
                title="Virtual Memory Address Translation and Page Replacement",
            )
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=[io_topic, vm_topic],
            )
            course = SimpleNamespace(
                topics=[io_topic, vm_topic],
                generation_profile={
                    "selected_topics": [
                        "input output improvements",
                        "Virtual Memory Address Translation and Page Replacement",
                    ],
                    "topic_weights": {
                        "input output improvements": 70,
                        "Virtual Memory Address Translation and Page Replacement": 30,
                    },
                },
            )

            applied = dialog.configure_from_course_profile(course)

            self.assertTrue(applied)
            plan = dialog.build_exam_plan()
            self.assertEqual(
                (
                    "input_output_improvements",
                    "virtual_memory_address_translation_and_page_replacement",
                ),
                plan.selected_topics,
            )
            self.assertEqual(70, plan.topic_weights["input_output_improvements"])
            self.assertEqual(
                30,
                plan.topic_weights["virtual_memory_address_translation_and_page_replacement"],
            )
            self.assertNotIn("无效", dialog.status_label.text())

    def test_course_profile_warning_detail_is_not_shown_in_generation_dialog_status(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache"],
            )
            profile = ExamGenerationPlan(
                question_count=12,
                selected_topics=("cache",),
                topic_weights={"cache": 100},
            )
            course = SimpleNamespace(
                generation_profile=profile.to_dict(),
                generation_profile_source="local",
                generation_profile_warning=(
                    "Course profile LLM request failed: "
                    "Anthropic API response did not contain a text block."
                ),
            )

            applied = dialog.configure_from_course_profile(course)

            self.assertTrue(applied)
            status = dialog.status_label.text()
            self.assertIn("本地回退", status)
            self.assertNotIn("Course profile LLM request failed", status)
            self.assertNotIn("Anthropic API response did not contain a text block", status)

    def test_question_set_history_overrides_course_profile_on_regeneration(self):
            dialog = AIGenerationDialog(
                "course content",
                {"ai_provider": "local_agent", "ai_base_url": "local-agent://auto", "ai_model": "codex"},
                available_topics=["cache", "process"],
            )
            course_profile = ExamGenerationPlan(
                question_count=20,
                selected_topics=("cache",),
                topic_weights={"cache": 100},
            )
            dialog.configure_from_course_profile(
                SimpleNamespace(generation_profile=course_profile.to_dict())
            )
            question_set = QuestionSet(
                set_id="set-history",
                title={"zh": "历史", "en": "History"},
                description={"zh": "", "en": ""},
                topics=["process"],
                difficulty=Difficulty.HARD,
                estimated_minutes=30,
                questions=[f"q-{index}" for index in range(18)],
                metadata={
                    "difficulty_mode": "hard",
                    "generation_template": "final_exam",
                    "question_type_weights": {
                        "multiple_choice": 40,
                        "scenario_choice": 40,
                        "true_false": 10,
                        "fill_in_blank": 10,
                    },
                    "difficulty_weights": {"easy": 10, "medium": 30, "hard": 60},
                    "topic_weights": {"process": 100},
                },
            )

            dialog.configure_from_question_set(question_set)
            rebuilt = dialog.build_exam_plan()

            self.assertEqual(18, rebuilt.question_count)
            self.assertEqual("final_exam", rebuilt.template)
            self.assertEqual(("process",), rebuilt.selected_topics)
            self.assertEqual(60, rebuilt.difficulty_weights["hard"])

    def test_main_generation_flow_applies_active_course_profile_before_opening(self):
            from core.language_manager import LanguageManager
            from ui.main_window import MainWindow

            class ForbiddenSecrets:
                def get_key(self):
                    raise AssertionError("local agent generation preflight must not read persisted API keys")

            settings = {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            }
            course = SimpleNamespace(
                course_id="course-cache",
                title="Cache",
                generation_profile={"question_count": 20},
            )
            task_center = object()
            workspace = Mock()
            workspace.generation_widget.return_value = None
            shell = SimpleNamespace(
                settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
                lang_manager=LanguageManager.instance(),
                course_context=SimpleNamespace(
                    generation_context=lambda: ("summary", ["cache"], course),
                ),
                task_center=task_center,
                _generation_workspace=workspace,
                SCREEN_GENERATION=8,
                navigate_to=Mock(return_value=True),
            )

            with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
                 patch("core.secrets_manager.SecretsManager.instance", return_value=ForbiddenSecrets()), \
                 patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
                GenerationWorkspaceController(shell).open()

            dialog_class.return_value.configure_from_course_profile.assert_called_once_with(course)
            dialog_class.return_value.exec.assert_not_called()
            workspace.show_generation_widget.assert_called_once()
            self.assertIs(task_center, dialog_class.call_args.kwargs["task_center"])

    def test_predicted_generation_prefills_reviewable_plan_after_course_defaults(self):
            from core.language_manager import LanguageManager
            from ui.main_window import MainWindow

            settings = {
                "ai_provider": "local_agent",
                "ai_base_url": "local-agent://auto",
                "ai_model": "codex",
            }
            course = SimpleNamespace(
                course_id="course-a",
                title="Systems",
                summary_markdown="summary",
                topics=[CourseTopic("io", "I/O")],
                generation_profile={"question_count": 10},
            )
            plan = ExamGenerationPlan(
                question_count=20,
                difficulty="mixed",
                template="final_exam",
                selected_topics=("io",),
                topic_weights={"io": 100},
            )
            prediction = SimpleNamespace(plan=plan, source_count=2, warnings=("short_answer",))
            workspace = Mock()
            workspace.generation_widget.return_value = None
            shell = SimpleNamespace(
                settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
                lang_manager=LanguageManager.instance(),
                course_context=SimpleNamespace(
                    generation_context=lambda: ("", [], None),
                ),
                _generation_workspace=workspace,
                SCREEN_GENERATION=8,
                navigate_to=Mock(return_value=True),
            )

            with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
                 patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog") as dialog_class:
                dialog = dialog_class.return_value

                GenerationWorkspaceController(shell).open(
                    course_override=course,
                    initial_plan=plan,
                    prediction=prediction,
                )

            dialog.configure_from_course_profile.assert_called_once_with(course)
            dialog.apply_exam_plan.assert_called_once_with(plan)
            dialog.set_draft_source.assert_called_once_with("manual")
            dialog.exec.assert_not_called()
            workspace.show_generation_widget.assert_called_once()
            dialog.set_title_input.setText.assert_called_once_with("Systems预测模拟卷")
            self.assertIn("2 份历史真题画像", dialog.status_label.setText.call_args.args[0])
            self.assertIn("不代表未来考题", dialog.status_label.setText.call_args.args[0])

    def test_main_generation_flow_rolls_back_questions_when_question_set_save_fails(self):
            from core.language_manager import LanguageManager
            from models.question import QuestionBank
            from models.question_set import SetManager
            from ui.main_window import MainWindow

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                question_bank = QuestionBank(str(root / "questions"))
                set_manager = SetManager(str(root / "sets"))
                question = Question.create_new(
                    qtype=QuestionType.MULTIPLE_CHOICE,
                    difficulty=Difficulty.MEDIUM,
                    bilingual={
                        "zh": {
                            "stem": "Cache 题",
                            "options": ["A. one", "B. two"],
                            "explanation": "解释说明足够完整。",
                        },
                        "en": {
                            "stem": "Cache question",
                            "options": ["A. one", "B. two"],
                            "explanation": "Explanation text with enough detail.",
                        },
                    },
                    correct_answer="A",
                    topic="cache",
                )
                settings = {
                    "ai_provider": "local_agent",
                    "ai_base_url": "local-agent://auto",
                    "ai_model": "codex",
                }
                class FakeDialog:
                    generated_questions = [question]
                    diff_combo = SimpleNamespace(currentData=lambda: "medium")

                    def __init__(self, *args, **kwargs):
                        self.accepted = Mock()
                        self.rejected = Mock()
                        self.show_save_error = Mock()
                        self.deleteLater = Mock()

                    def configure_from_course_profile(self, course_project):
                        pass

                    def _build_generation_config(self):
                        return GenerationConfig(topic_weights={"cache": 100})

                    def question_set_title(self):
                        return "AI 事务测试"

                workspace = Mock()
                workspace.generation_widget.return_value = None
                navigate_to = Mock(return_value=True)
                shell = SimpleNamespace(
                    settings_screen=SimpleNamespace(settings_snapshot=lambda: dict(settings)),
                    lang_manager=LanguageManager.instance(),
                    question_bank=question_bank,
                    set_manager=set_manager,
                    course_context=SimpleNamespace(
                        generation_context=lambda: ("summary", ["cache"], None),
                        question_bank_changed=Mock(),
                    ),
                    SCREEN_TOPIC_SELECTION=1,
                    SCREEN_GENERATION=8,
                    _generation_workspace=workspace,
                    navigate_to=navigate_to,
                )

                with patch("ui.generation_workspace_controller.ai_generation_settings_error", return_value=""), \
                     patch("ui.dialogs.ai_generation_dialog.AIGenerationDialog", FakeDialog), \
                     patch.object(set_manager, "save", return_value=False), \
                     patch("ui.generation_workspace_controller.QMessageBox.critical") as critical:
                    GenerationWorkspaceController(shell).open()
                    dialog = workspace.show_generation_widget.call_args.args[0]
                    dialog.accepted.connect.call_args.args[0]()

                critical.assert_not_called()
                dialog.show_save_error.assert_called_once()
                self.assertIsNone(question_bank.get(question.question_id))
                navigate_to.assert_called_once_with(
                    8,
                    allow_first_run_redirect=False,
                )
