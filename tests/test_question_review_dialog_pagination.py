import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from models.course_project import CourseTopic
from models.question import Question
from core.language_manager import LanguageManager
from ui.dialogs.question_review_dialog import QuestionReviewDialog
from ui.widgets.question_form_editor import QuestionFormEditor
from utils.constants import Difficulty, QuestionType


_APP = QApplication.instance() or QApplication([])


def make_question(index: int) -> Question:
    return Question.create_new(
        QuestionType.MULTIPLE_CHOICE,
        Difficulty.MEDIUM,
        {
            "zh": {
                "stem": f"问题 {index}",
                "options": ["A", "B"],
                "explanation": "解释",
            },
            "en": {
                "stem": f"Question {index}",
                "options": ["A", "B"],
                "explanation": "Explanation",
            },
        },
        "A",
        "cache",
    )


class QuestionReviewDialogPaginationTests(unittest.TestCase):
    def test_review_dialog_reuses_shared_question_form_editor(self):
        dialog = QuestionReviewDialog([make_question(1)], page_size=10)
        self.addCleanup(dialog.close)

        self.assertIsInstance(dialog.form_editor, QuestionFormEditor)
        self.assertIs(
            dialog.form_editor,
            dialog.review_tabs.widget(1).findChild(QuestionFormEditor),
        )

    def test_review_dialog_separates_preview_edit_source_and_quality_tabs(self):
        question = make_question(1)
        question.metadata["source_ref_status"] = "invalid_model_ref"
        question.metadata["source_refs"] = [{
            "chunk_id": "source-0007",
            "source_file": "第21讲 Cache.pdf",
            "page_or_slide": 8,
        }]

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual(4, dialog.review_tabs.count())
        self.assertEqual(["预览", "编辑", "来源", "质量问题"], [
            dialog.review_tabs.tabText(index)
            for index in range(dialog.review_tabs.count())
        ])
        self.assertEqual(0, dialog.review_tabs.currentIndex())
        self.assertNotIn("Source Evidence", dialog.detail_editor.toPlainText())
        self.assertNotIn("Review Warnings", dialog.detail_editor.toPlainText())
        self.assertIn("第21讲 Cache.pdf", dialog.source_editor.toPlainText())
        self.assertIn("来源", dialog.quality_editor.toPlainText())

    def test_review_dialog_localizes_preview_and_tab_labels(self):
        language_manager = LanguageManager.instance()
        previous_language = language_manager.current
        self.addCleanup(language_manager.set_language, previous_language)
        language_manager.set_language("zh")
        dialog = QuestionReviewDialog([make_question(1)], page_size=10)
        self.addCleanup(dialog.close)

        self.assertIn("题型:", dialog.detail_editor.toPlainText())
        self.assertIn("知识点:", dialog.detail_editor.toPlainText())
        self.assertNotIn("Type:", dialog.detail_editor.toPlainText())

        language_manager.set_language("en")

        self.assertEqual("Preview", dialog.review_tabs.tabText(0))
        self.assertIn("Type:", dialog.detail_editor.toPlainText())

    def test_review_dialog_renders_only_current_page_for_large_batches(self):
        questions = [make_question(index) for index in range(25)]

        dialog = QuestionReviewDialog(questions, page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual(10, dialog.question_list.count())
        self.assertEqual([*range(10)], self._visible_question_indexes(dialog))
        self.assertIn("1 / 3", dialog.page_label.text())
        self.assertFalse(dialog.prev_page_btn.isEnabled())
        self.assertTrue(dialog.next_page_btn.isEnabled())

        dialog.next_page_btn.click()

        self.assertEqual(10, dialog.question_list.count())
        self.assertEqual([*range(10, 20)], self._visible_question_indexes(dialog))
        self.assertEqual(10, dialog._current_index)
        self.assertIn("2 / 3", dialog.page_label.text())
        self.assertTrue(dialog.prev_page_btn.isEnabled())
        self.assertTrue(dialog.next_page_btn.isEnabled())

        dialog.next_page_btn.click()

        self.assertEqual(5, dialog.question_list.count())
        self.assertEqual([*range(20, 25)], self._visible_question_indexes(dialog))
        self.assertIn("3 / 3", dialog.page_label.text())
        self.assertTrue(dialog.prev_page_btn.isEnabled())
        self.assertFalse(dialog.next_page_btn.isEnabled())

    def test_review_dialog_preserves_acceptance_state_across_pages(self):
        questions = [make_question(index) for index in range(12)]
        dialog = QuestionReviewDialog(questions, page_size=5)
        self.addCleanup(dialog.close)

        dialog.next_page_btn.click()
        self.assertEqual(5, dialog._current_index)

        dialog.reject_btn.click()
        self.assertNotIn(5, dialog._accepted)

        dialog.prev_page_btn.click()
        dialog.next_page_btn.click()

        self.assertNotIn(5, dialog._accepted)
        self.assertEqual([question.question_id for question in questions if question is not questions[5]],
                         [question.question_id for question in dialog.get_accepted_questions()])

        dialog.accept_all_btn.click()

        self.assertEqual([question.question_id for question in questions],
                         [question.question_id for question in dialog.get_accepted_questions()])

    def test_review_decisions_round_trip_as_pending_accepted_or_rejected(self):
        accepted = make_question(1)
        rejected = make_question(2)
        warning = make_question(3)
        warning.metadata["source_ref_status"] = "invalid_model_ref"

        dialog = QuestionReviewDialog([accepted, rejected, warning], page_size=10)
        self.addCleanup(dialog.close)

        dialog.question_list.setCurrentRow(1)
        dialog.reject_btn.click()

        state = dialog.get_review_state()

        self.assertEqual("accepted", state[accepted.question_id])
        self.assertEqual("rejected", state[rejected.question_id])
        self.assertEqual("pending", state[warning.question_id])

        restored = QuestionReviewDialog(
            [accepted, rejected, warning],
            page_size=10,
            review_state=state,
        )
        self.addCleanup(restored.close)

        self.assertEqual(state, restored.get_review_state())

    def test_review_dialog_displays_topic_title_not_internal_id(self):
        topic = CourseTopic(topic_id="interrupt_io", title="Interrupt-driven I/O")
        question = make_question(1)
        question.topic = topic

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        details = dialog.detail_editor.toPlainText()
        self.assertIn("知识点: Interrupt-driven I/O", details)
        self.assertNotIn("知识点: interrupt_io", details)

    def test_review_dialog_displays_source_refs_for_generated_question(self):
        question = make_question(1)
        question.metadata["source_refs"] = [
            {
                "chunk_id": "source-0007",
                "source_file": "第21讲 Cache.pdf",
                "page_or_slide": 8,
                "heading": "Cache Address Breakdown",
            }
        ]

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        details = dialog.source_editor.toPlainText()
        self.assertIn("第21讲 Cache.pdf", details)
        self.assertIn("页码/幻灯片 8", details)
        self.assertIn("source-0007", details)
        self.assertIn("Cache Address Breakdown", details)

    def test_review_dialog_requires_manual_acceptance_for_low_confidence_questions(self):
        good = make_question(1)
        good.metadata["source_ref_status"] = "valid_model_ref"
        good.metadata["source_refs"] = [{"chunk_id": "source-good"}]
        good.metadata["plan_match_status"] = "matched_by_plan_id"
        invalid_source = make_question(2)
        invalid_source.metadata["source_ref_status"] = "invalid_model_ref"
        shape_match = make_question(3)
        shape_match.metadata["plan_match_status"] = "matched_by_shape"
        missing_explanation = make_question(4)
        missing_explanation.bilingual["zh"]["explanation"] = ""
        missing_explanation.bilingual["en"]["explanation"] = ""

        dialog = QuestionReviewDialog(
            [good, invalid_source, shape_match, missing_explanation],
            page_size=10,
        )
        self.addCleanup(dialog.close)

        self.assertEqual({0}, dialog._accepted)
        self.assertEqual([good.question_id], [question.question_id for question in dialog.get_accepted_questions()])
        self.assertIn("⚠", dialog.question_list.item(1).text())
        self.assertIn("⚠", dialog.question_list.item(2).text())
        self.assertIn("⚠", dialog.question_list.item(3).text())

        dialog.question_list.setCurrentRow(1)
        details = dialog.quality_editor.toPlainText()
        self.assertIn("来源", details)

    def test_review_dialog_summarizes_source_coverage(self):
        exact = make_question(1)
        exact.metadata["source_ref_status"] = "valid_model_ref"
        exact.metadata["source_refs"] = [{"chunk_id": "source-exact"}]
        fallback = make_question(2)
        fallback.metadata["source_ref_status"] = "fallback_plan_evidence"
        fallback.metadata["source_refs"] = [{"chunk_id": "source-fallback"}]

        dialog = QuestionReviewDialog([exact, fallback, make_question(3)], page_size=10)
        self.addCleanup(dialog.close)

        self.assertIn("来源明确 1/3", dialog.source_coverage_label.text())
        self.assertIn("建议检查 2", dialog.source_coverage_label.text())

    def test_review_dialog_accept_all_excludes_weak_source_questions(self):
        exact = make_question(1)
        exact.metadata["source_ref_status"] = "valid_model_ref"
        exact.metadata["source_refs"] = [{"chunk_id": "source-exact"}]
        fallback = make_question(2)
        fallback.metadata["source_ref_status"] = "fallback_plan_evidence"
        fallback.metadata["source_refs"] = [{"chunk_id": "source-fallback"}]

        dialog = QuestionReviewDialog([exact, fallback], page_size=10)
        self.addCleanup(dialog.close)

        dialog.accept_all_btn.click()

        self.assertEqual([exact.question_id], [question.question_id for question in dialog.get_accepted_questions()])

    def test_review_dialog_accept_all_keeps_warning_questions_rejected(self):
        good = make_question(1)
        warning = make_question(2)
        warning.metadata["source_ref_status"] = "invalid_model_ref"
        dialog = QuestionReviewDialog([good, warning], page_size=10)
        self.addCleanup(dialog.close)

        dialog.accept_all_btn.click()

        self.assertEqual({0}, dialog._accepted)
        self.assertEqual([good.question_id], [question.question_id for question in dialog.get_accepted_questions()])

    def test_warning_only_review_can_save_after_rejecting_every_warning(self):
        warning = make_question(1)
        warning.metadata["source_ref_status"] = "invalid_model_ref"
        dialog = QuestionReviewDialog(
            [warning],
            page_size=10,
            allow_empty_accept=True,
        )
        self.addCleanup(dialog.close)
        self.assertEqual("保存审查结果", dialog.save_btn.text())

        with patch(
            "ui.dialogs.question_review_dialog.QMessageBox.warning",
        ) as warning_message, patch(
            "ui.dialogs.question_review_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog._on_save()

        warning_message.assert_not_called()
        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual([], dialog.get_accepted_questions())

    def test_review_dialog_accept_all_label_describes_safe_bulk_action(self):
        dialog = QuestionReviewDialog([make_question(1)], page_size=10)
        self.addCleanup(dialog.close)

        self.assertIn("无警告", dialog.accept_all_btn.text())

    def test_review_dialog_list_shows_short_warning_tags(self):
        invalid_source = make_question(1)
        invalid_source.metadata["source_ref_status"] = "invalid_model_ref"
        shape_match = make_question(2)
        shape_match.metadata["plan_match_status"] = "matched_by_shape"
        fallback_source = make_question(3)
        fallback_source.metadata["source_ref_status"] = "global_fallback"
        fallback_source.metadata["source_refs"] = [{"chunk_id": "source-fallback"}]

        dialog = QuestionReviewDialog(
            [invalid_source, shape_match, fallback_source],
            page_size=10,
        )
        self.addCleanup(dialog.close)

        self.assertIn("[无来源]", dialog.question_list.item(0).text())
        self.assertIn("[计划匹配弱]", dialog.question_list.item(1).text())
        self.assertIn("[兜底来源]", dialog.question_list.item(2).text())

    def test_review_dialog_apply_edits_does_not_accept_warning_question(self):
        warning = make_question(1)
        warning.metadata["plan_match_status"] = "matched_by_shape"
        dialog = QuestionReviewDialog([warning], page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual(set(), dialog._accepted)
        dialog.form_editor.zh_explanation_editor.setPlainText("补充后的解析仍需用户显式接受。")
        dialog.apply_edit_btn.click()

        self.assertEqual(set(), dialog._accepted)
        self.assertEqual("补充后的解析仍需用户显式接受。", warning.get_explanation("zh"))

    def test_review_dialog_preserves_pending_edits_when_switching_selection(self):
        first = make_question(1)
        second = make_question(2)
        dialog = QuestionReviewDialog([first, second], page_size=10)
        self.addCleanup(dialog.close)

        dialog.form_editor.zh_stem_editor.setPlainText("切题前未点应用的修改")
        dialog.question_list.setCurrentRow(1)

        self.assertEqual("切题前未点应用的修改", first.get_stem("zh"))
        self.assertEqual(1, dialog._current_index)

    def test_review_dialog_can_edit_current_question_before_accepting(self):
        question = make_question(1)
        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        editor = dialog.form_editor
        editor.zh_stem_editor.setPlainText("修改后的中文题干")
        editor.en_stem_editor.setPlainText("Edited English stem")
        for row, (zh, en) in enumerate((
            ("正确项", "Correct"),
            ("干扰项", "Distractor"),
            ("新干扰项", "New distractor"),
            ("另一干扰项", "Another distractor"),
        )):
            editor.choice_table.item(row, 1).setText(zh)
            editor.choice_table.item(row, 2).setText(en)
        editor.choice_answer_combo.setCurrentIndex(
            editor.choice_answer_combo.findData("C")
        )
        editor.zh_explanation_editor.setPlainText("修改后的中文解析")
        editor.en_explanation_editor.setPlainText("Edited English explanation")

        dialog.apply_edit_btn.click()

        accepted = dialog.get_accepted_questions()
        self.assertEqual(1, len(accepted))
        edited = accepted[0]
        self.assertEqual("修改后的中文题干", edited.get_stem("zh"))
        self.assertEqual("Edited English stem", edited.get_stem("en"))
        self.assertEqual(["A. 正确项", "B. 干扰项", "C. 新干扰项", "D. 另一干扰项"], edited.get_options("zh"))
        self.assertEqual(["A. Correct", "B. Distractor", "C. New distractor", "D. Another distractor"], edited.get_options("en"))
        self.assertEqual("C", edited.correct_answer)
        self.assertEqual("修改后的中文解析", edited.get_explanation("zh"))
        self.assertEqual("Edited English explanation", edited.get_explanation("en"))
        self.assertIn("修改后的中文题干", dialog.question_list.item(0).text())

    def test_review_dialog_shared_editor_can_convert_question_type(self):
        question = make_question(1)
        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)
        editor = dialog.form_editor

        editor.type_combo.setCurrentIndex(
            editor.type_combo.findData(QuestionType.SHORT_ANSWER.value)
        )
        editor.short_answer_editor.setPlainText("按关键机制给分的参考答案")
        dialog.apply_edit_btn.click()

        self.assertEqual(QuestionType.SHORT_ANSWER, question.type)
        self.assertEqual([], question.get_options("zh"))
        self.assertEqual("按关键机制给分的参考答案", question.correct_answer)

    def test_review_dialog_flags_lightweight_quality_warnings(self):
        long_correct = make_question(1)
        long_correct.bilingual["zh"]["options"] = [
            "A. 这是一个明显比其他干扰项长很多的正确答案，容易暴露答案",
            "B. 短项",
            "C. 短项",
            "D. 短项",
        ]
        long_correct.correct_answer = "A"
        imbalanced_explanation = make_question(2)
        imbalanced_explanation.bilingual["zh"]["explanation"] = "短"
        imbalanced_explanation.bilingual["en"]["explanation"] = (
            "This explanation is intentionally much longer than the Chinese explanation "
            "so the review dialog can warn about bilingual quality imbalance."
        )

        dialog = QuestionReviewDialog([long_correct, imbalanced_explanation], page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual(set(), dialog._accepted)
        self.assertIn("⚠", dialog.question_list.item(0).text())
        self.assertIn("⚠", dialog.question_list.item(1).text())

        dialog.question_list.setCurrentRow(0)
        self.assertIn("正确选项", dialog.quality_editor.toPlainText())
        dialog.question_list.setCurrentRow(1)
        self.assertIn("解析", dialog.quality_editor.toPlainText())

    def test_review_dialog_can_edit_topic_title_without_changing_stable_topic_id(self):
        question = make_question(1)
        original_topic_id = question.topic_id()
        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        editor = dialog.form_editor
        editor.topic_combo.setItemText(editor.topic_combo.currentIndex(), "进程调度")
        editor.difficulty_combo.setCurrentIndex(editor.difficulty_combo.findData("hard"))

        dialog.apply_edit_btn.click()

        edited = dialog.get_accepted_questions()[0]
        self.assertEqual(original_topic_id, edited.topic_id())
        self.assertEqual("进程调度", edited.metadata["topic_title"])
        self.assertEqual(Difficulty.HARD, edited.difficulty)
        self.assertIn("知识点: 进程调度", dialog.detail_editor.toPlainText())
        self.assertIn("难度: 困难", dialog.detail_editor.toPlainText())

    def test_review_dialog_preserves_fill_answer_list_when_editing_explanation(self):
        topic = CourseTopic(topic_id="cache_mapping", title="Cache Mapping")
        question = Question.create_new(
            QuestionType.FILL_IN_BLANK,
            Difficulty.MEDIUM,
            {
                "zh": {"stem": "____ 保存主存块。", "options": [], "explanation": "旧解析"},
                "en": {"stem": "____ stores memory blocks.", "options": [], "explanation": "Old explanation"},
            },
            ["cache line", "block"],
            topic,
        )

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        self.assertEqual("Cache Mapping", dialog.form_editor.topic_combo.currentText())
        dialog.form_editor.zh_explanation_editor.setPlainText("只修改解析，不应该改变答案结构。")
        dialog.apply_edit_btn.click()

        edited = dialog.get_accepted_questions()[0]
        self.assertEqual(["cache line", "block"], edited.correct_answer)
        self.assertEqual("cache_mapping", edited.topic_id())
        self.assertEqual("只修改解析，不应该改变答案结构。", edited.get_explanation("zh"))

    def test_review_dialog_preserves_matching_options_and_answer_when_editing_stem(self):
        question = Question.create_new(
            QuestionType.MATCHING,
            Difficulty.MEDIUM,
            {
                "zh": {
                    "stem": "配对 I/O 术语。",
                    "options": {
                        "left": [{"id": "left_1", "text": "DMA"}],
                        "right": [{"id": "right_1", "text": "直接内存访问"}],
                    },
                    "explanation": "DMA 与直接内存访问配对。",
                },
                "en": {
                    "stem": "Match I/O terms.",
                    "options": {
                        "left": [{"id": "left_1", "text": "DMA"}],
                        "right": [{"id": "right_1", "text": "Direct memory access"}],
                    },
                    "explanation": "DMA matches direct memory access.",
                },
            },
            [["left_1", "right_1"]],
            "input_output_improvements",
        )

        dialog = QuestionReviewDialog([question], page_size=10)
        self.addCleanup(dialog.close)

        dialog.form_editor.zh_stem_editor.setPlainText("配对 I/O 机制和含义。")
        dialog.apply_edit_btn.click()

        edited = dialog.get_accepted_questions()[0]
        self.assertIsInstance(edited.get_options("zh"), dict)
        self.assertEqual(
            {"left": [{"id": "left_1", "text": "DMA"}], "right": [{"id": "right_1", "text": "直接内存访问"}]},
            edited.get_options("zh"),
        )
        self.assertEqual([["left_1", "right_1"]], edited.correct_answer)
        self.assertEqual("配对 I/O 机制和含义。", edited.get_stem("zh"))

    def _visible_question_indexes(self, dialog: QuestionReviewDialog) -> list[int]:
        return [
            dialog.question_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.question_list.count())
        ]


if __name__ == "__main__":
    unittest.main()
