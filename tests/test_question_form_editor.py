import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from models.course_project import CourseTopic
from models.question import Question
from core.language_manager import LanguageManager
from ui.widgets.question_form_editor import QuestionFormEditor


_APP = QApplication.instance() or QApplication([])


class QuestionFormEditorTests(unittest.TestCase):
    def test_editor_scrolls_instead_of_overflowing_short_windows(self):
        editor = QuestionFormEditor()

        self.assertTrue(editor.scroll_area.widgetResizable())
        self.assertIs(editor.scroll_area.widget(), editor.form_content)

    def test_language_switch_updates_structured_editor_labels(self):
        language_manager = LanguageManager.instance()
        previous_language = language_manager.current
        self.addCleanup(language_manager.set_language, previous_language)
        language_manager.set_language("zh")
        editor = QuestionFormEditor()
        self.assertEqual(
            "简单",
            editor.difficulty_combo.itemText(editor.difficulty_combo.findData("easy")),
        )

        language_manager.set_language("en")

        self.assertEqual("Type", editor.type_label.text())
        self.assertEqual("English", editor.language_tabs.tabText(1))
        self.assertEqual(
            "Easy",
            editor.difficulty_combo.itemText(editor.difficulty_combo.findData("easy")),
        )
        self.assertEqual("Add Pair", editor.add_matching_row_btn.text())
        self.assertEqual("Accepted answers", editor.fill_answers_label.text())

    def test_every_question_type_has_a_structured_answer_panel(self):
        editor = QuestionFormEditor()

        expected_panels = {
            "multiple_choice": editor.choice_panel,
            "scenario_choice": editor.choice_panel,
            "true_false": editor.true_false_panel,
            "matching": editor.matching_panel,
            "ordering": editor.ordering_panel,
            "fill_in_blank": editor.fill_panel,
            "short_answer": editor.short_answer_panel,
        }
        for question_type, expected_panel in expected_panels.items():
            with self.subTest(question_type=question_type):
                editor.type_combo.setCurrentIndex(editor.type_combo.findData(question_type))
                self.assertIs(editor.answer_stack.currentWidget(), expected_panel)

    def test_completed_structured_payloads_are_valid_for_every_question_type(self):
        editor = QuestionFormEditor()
        for question_type in (
            "multiple_choice",
            "scenario_choice",
            "true_false",
            "matching",
            "ordering",
            "fill_in_blank",
            "short_answer",
        ):
            with self.subTest(question_type=question_type):
                editor.start_new()
                editor.type_combo.setCurrentIndex(editor.type_combo.findData(question_type))
                editor.zh_stem_editor.setPlainText("中文题干")
                editor.zh_explanation_editor.setPlainText("中文解析")
                editor.en_stem_editor.setPlainText("English stem")
                editor.en_explanation_editor.setPlainText("English explanation")
                if question_type in {"multiple_choice", "scenario_choice"}:
                    for row in range(4):
                        editor.choice_table.item(row, 1).setText(f"中文选项 {row + 1}")
                        editor.choice_table.item(row, 2).setText(f"English option {row + 1}")
                elif question_type == "matching":
                    for column, value in enumerate(("左项", "Left", "右项", "Right"), start=1):
                        editor.matching_table.item(0, column).setText(value)
                elif question_type == "ordering":
                    editor.ordering_table.item(0, 1).setText("第一步")
                    editor.ordering_table.item(0, 2).setText("First step")
                elif question_type == "fill_in_blank":
                    editor.fill_answers_editor.setPlainText("答案")
                elif question_type == "short_answer":
                    editor.short_answer_editor.setPlainText("参考答案")

                payload = editor.to_payload()
                payload["question_id"] = f"q-{question_type}"

                self.assertEqual([], Question.from_dict(payload).validate())

    def test_round_trips_multiple_choice_payload_without_losing_metadata(self):
        editor = QuestionFormEditor()
        editor.set_topics([
            CourseTopic(topic_id="interrupt_io", title="中断驱动 I/O"),
        ])
        editor.load_payload({
            "question_id": "q-io-1",
            "type": "multiple_choice",
            "difficulty": "hard",
            "topic": "interrupt_io",
            "topic_id": "interrupt_io",
            "topic_title": "中断驱动 I/O",
            "subtopic": "interrupt lifecycle",
            "correct_answer": "C",
            "bilingual": {
                "zh": {
                    "stem": "CPU 何时收到完成通知？",
                    "options": ["A. 轮询前", "B. 发出命令时", "C. 设备中断时", "D. 永不"],
                    "explanation": "设备完成后通过中断通知 CPU。",
                },
                "en": {
                    "stem": "When is the CPU notified?",
                    "options": ["A. Before polling", "B. On issue", "C. On interrupt", "D. Never"],
                    "explanation": "The device interrupts the CPU after completion.",
                },
            },
            "metadata": {"source": "ai", "course_id": "course-a", "custom": 7},
        })

        editor.zh_stem_editor.setPlainText("设备完成后如何通知 CPU？")
        payload = editor.to_payload()

        self.assertEqual("q-io-1", payload["question_id"])
        self.assertEqual("multiple_choice", payload["type"])
        self.assertEqual("hard", payload["difficulty"])
        self.assertEqual("interrupt_io", payload["topic_id"])
        self.assertEqual("中断驱动 I/O", payload["topic_title"])
        self.assertEqual("C", payload["correct_answer"])
        self.assertEqual("设备完成后如何通知 CPU？", payload["bilingual"]["zh"]["stem"])
        self.assertEqual("A. Before polling", payload["bilingual"]["en"]["options"][0])
        self.assertEqual(7, payload["metadata"]["custom"])

    def test_scenario_choice_uses_the_choice_table_without_changing_type(self):
        editor = QuestionFormEditor()
        editor.start_new()
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("scenario_choice"))
        for row in range(4):
            editor.choice_table.item(row, 1).setText(f"情景选项 {row + 1}")
            editor.choice_table.item(row, 2).setText(f"Scenario option {row + 1}")
        editor.choice_answer_combo.setCurrentIndex(1)

        payload = editor.to_payload()

        self.assertEqual("scenario_choice", payload["type"])
        self.assertEqual("B", payload["correct_answer"])
        self.assertEqual("B. Scenario option 2", payload["bilingual"]["en"]["options"][1])

    def test_true_false_uses_fixed_bilingual_options_and_boolean_answer(self):
        editor = QuestionFormEditor()
        editor.start_new()
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("true_false"))
        editor.true_false_answer_combo.setCurrentIndex(
            editor.true_false_answer_combo.findData("false")
        )

        payload = editor.to_payload()

        self.assertEqual("true_false", payload["type"])
        self.assertEqual("false", payload["correct_answer"])
        self.assertEqual(["正确", "错误"], payload["bilingual"]["zh"]["options"])
        self.assertEqual(["True", "False"], payload["bilingual"]["en"]["options"])

    def test_matching_round_trip_preserves_stable_ids_and_row_pairing(self):
        editor = QuestionFormEditor()
        editor.load_payload({
            "question_id": "q-match",
            "type": "matching",
            "difficulty": "medium",
            "topic_id": "io",
            "correct_answer": [["left_dma", "right_direct"], ["left_irq", "right_signal"]],
            "bilingual": {
                "zh": {
                    "stem": "配对术语",
                    "options": {
                        "left": [
                            {"id": "left_dma", "text": "DMA"},
                            {"id": "left_irq", "text": "中断"},
                        ],
                        "right": [
                            {"id": "right_direct", "text": "直接内存访问"},
                            {"id": "right_signal", "text": "完成信号"},
                        ],
                    },
                    "explanation": "逐项配对。",
                },
                "en": {
                    "stem": "Match the terms",
                    "options": {
                        "left": [
                            {"id": "left_dma", "text": "DMA"},
                            {"id": "left_irq", "text": "Interrupt"},
                        ],
                        "right": [
                            {"id": "right_direct", "text": "Direct memory access"},
                            {"id": "right_signal", "text": "Completion signal"},
                        ],
                    },
                    "explanation": "Match each row.",
                },
            },
            "metadata": {"source": "ai"},
        })

        editor.matching_table.item(1, 2).setText("Interrupt request")
        payload = editor.to_payload()

        self.assertEqual("matching", payload["type"])
        self.assertEqual(
            [["left_dma", "right_direct"], ["left_irq", "right_signal"]],
            payload["correct_answer"],
        )
        self.assertEqual(
            "Interrupt request",
            payload["bilingual"]["en"]["options"]["left"][1]["text"],
        )
        self.assertEqual(
            "right_signal",
            payload["bilingual"]["zh"]["options"]["right"][1]["id"],
        )

    def test_ordering_table_order_defines_stable_correct_answer(self):
        editor = QuestionFormEditor()
        editor.load_payload({
            "question_id": "q-order",
            "type": "ordering",
            "difficulty": "easy",
            "topic_id": "pipeline",
            "correct_answer": ["fetch", "decode"],
            "bilingual": {
                "zh": {
                    "stem": "排序",
                    "options": [
                        {"id": "fetch", "text": "取指"},
                        {"id": "decode", "text": "译码"},
                    ],
                    "explanation": "先取指再译码。",
                },
                "en": {
                    "stem": "Order",
                    "options": [
                        {"id": "fetch", "text": "Fetch"},
                        {"id": "decode", "text": "Decode"},
                    ],
                    "explanation": "Fetch before decode.",
                },
            },
            "metadata": {},
        })

        editor.ordering_table.selectRow(1)
        editor.move_ordering_up_btn.click()
        payload = editor.to_payload()

        self.assertEqual(["decode", "fetch"], payload["correct_answer"])
        self.assertEqual("decode", payload["bilingual"]["zh"]["options"][0]["id"])
        self.assertEqual("Decode", payload["bilingual"]["en"]["options"][0]["text"])

    def test_fill_in_blank_edits_acceptable_answers_as_lines(self):
        editor = QuestionFormEditor()
        editor.load_payload({
            "question_id": "q-fill",
            "type": "fill_in_blank",
            "difficulty": "medium",
            "topic_id": "cpu",
            "correct_answer": ["central processing unit", "CPU"],
            "bilingual": {
                "zh": {"stem": "CPU 是 ____。", "options": [], "explanation": "处理器。"},
                "en": {"stem": "CPU means ____.", "options": [], "explanation": "Processor."},
            },
            "metadata": {},
        })

        editor.fill_answers_editor.setPlainText("central processing unit\nCPU\n中央处理器")
        payload = editor.to_payload()

        self.assertEqual("fill_in_blank", payload["type"])
        self.assertEqual(
            ["central processing unit", "CPU", "中央处理器"],
            payload["correct_answer"],
        )
        self.assertEqual([], payload["bilingual"]["zh"]["options"])

    def test_short_answer_edits_reference_answer_as_text(self):
        editor = QuestionFormEditor()
        editor.load_payload({
            "question_id": "q-short",
            "type": "short_answer",
            "difficulty": "hard",
            "topic_id": "io",
            "correct_answer": "中断允许 CPU 与设备并发工作。",
            "bilingual": {
                "zh": {"stem": "说明中断的作用。", "options": [], "explanation": "参考解析。"},
                "en": {"stem": "Explain interrupts.", "options": [], "explanation": "Reference explanation."},
            },
            "metadata": {},
        })

        editor.short_answer_editor.setPlainText("设备就绪后通知 CPU，减少忙等。")
        payload = editor.to_payload()

        self.assertEqual("short_answer", payload["type"])
        self.assertEqual("设备就绪后通知 CPU，减少忙等。", payload["correct_answer"])
        self.assertEqual([], payload["bilingual"]["en"]["options"])

    def test_dynamic_matching_and_ordering_rows_keep_unique_ids_after_deletion(self):
        editor = QuestionFormEditor()

        editor.add_matching_row_btn.click()
        editor.add_matching_row_btn.click()
        editor.matching_table.selectRow(1)
        editor.remove_matching_row_btn.click()
        editor.add_matching_row_btn.click()
        matching_ids = [
            editor.matching_table.item(row, 0).data(256)
            for row in range(editor.matching_table.rowCount())
        ]

        editor.add_ordering_row_btn.click()
        editor.add_ordering_row_btn.click()
        editor.ordering_table.selectRow(1)
        editor.remove_ordering_row_btn.click()
        editor.add_ordering_row_btn.click()
        ordering_ids = [
            editor.ordering_table.item(row, 0).text()
            for row in range(editor.ordering_table.rowCount())
        ]

        self.assertEqual(len(matching_ids), len(set(matching_ids)))
        self.assertEqual(len(ordering_ids), len(set(ordering_ids)))


if __name__ == "__main__":
    unittest.main()
