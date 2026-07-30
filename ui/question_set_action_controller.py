"""Coordinate question-set export and in-place regeneration actions."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

from core.mock_exam_exporter import MockExamExporter
from core.question_set_regenerator import persist_regenerated_question_set
from ui.navigation import Route
from utils.constants import Difficulty
from utils.json_io import sanitize_filename_part


class QuestionSetActionController:
    """Own user-facing actions performed on question-set assets."""

    def __init__(
        self,
        host,
        *,
        file_dialog=QFileDialog,
        message_box=QMessageBox,
        exporter=MockExamExporter,
        regenerator=persist_regenerated_question_set,
    ) -> None:
        self.host = host
        self.file_dialog = file_dialog
        self.message_box = message_box
        self.exporter = exporter
        self.regenerator = regenerator

    def export_mock_exam(self, set_id: str) -> None:
        """Export one selected question set as a Markdown mock exam."""
        host = self.host
        gm = host.lang_manager.get_text
        question_set = host.set_manager.get(set_id)
        if not question_set:
            self.message_box.warning(
                host,
                gm("错误", "Error"),
                gm("未找到题目集。", "Question set not found."),
            )
            return

        questions = host.question_bank.get_many(question_set.questions)
        if not questions:
            self.message_box.warning(
                host,
                gm("错误", "Error"),
                gm(
                    "未找到该题目集的题目。",
                    "No questions found for this set.",
                ),
            )
            return

        filepath, _ = self.file_dialog.getSaveFileName(
            host,
            gm("导出模拟卷", "Export Mock Exam"),
            f"{question_set.set_id}_mock_exam.md",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not filepath:
            return

        try:
            written = self.exporter.write_markdown(
                filepath,
                question_set,
                questions,
                lang=host.lang_manager.current,
                include_answers=True,
            )
        except OSError as exc:
            self.message_box.critical(
                host,
                gm("导出失败", "Export Failed"),
                str(exc),
            )
            return

        self.message_box.information(
            host,
            gm("导出完成", "Export Complete"),
            gm(
                f"模拟卷已导出到:\n{written}",
                f"Mock exam exported to:\n{written}",
            ),
        )

    def export_mock_exams(self, set_ids: list[str]) -> None:
        """Export multiple selected question sets into one chosen folder."""
        host = self.host
        gm = host.lang_manager.get_text
        unique_set_ids = list(dict.fromkeys(set_ids))
        if not unique_set_ids:
            return
        if len(unique_set_ids) == 1:
            self.export_mock_exam(unique_set_ids[0])
            return

        folder = self.file_dialog.getExistingDirectory(
            host,
            gm("批量导出模拟卷", "Export Mock Exams"),
        )
        if not folder:
            return

        output_dir = Path(folder)
        written: list[Path] = []
        failures: list[str] = []
        for set_id in unique_set_ids:
            question_set = host.set_manager.get(set_id)
            if not question_set:
                failures.append(
                    gm(
                        f"{set_id}: 未找到题目集",
                        f"{set_id}: question set not found",
                    )
                )
                continue

            questions = host.question_bank.get_many(question_set.questions)
            if not questions:
                failures.append(
                    gm(
                        f"{set_id}: 未找到题目",
                        f"{set_id}: no questions found",
                    )
                )
                continue

            output_path = output_dir / (
                f"{sanitize_filename_part(question_set.set_id)}_mock_exam.md"
            )
            try:
                written.append(
                    self.exporter.write_markdown(
                        output_path,
                        question_set,
                        questions,
                        lang=host.lang_manager.current,
                        include_answers=True,
                    )
                )
            except OSError as exc:
                failures.append(f"{set_id}: {exc}")

        if written:
            preview = "\n".join(str(path) for path in written[:5])
            extra = (
                ""
                if len(written) <= 5
                else gm(
                    f"\n等 {len(written)} 份文件",
                    f"\nand {len(written)} files total",
                )
            )
            self.message_box.information(
                host,
                gm("导出完成", "Export Complete"),
                gm(
                    f"已导出模拟卷:\n{preview}{extra}",
                    f"Mock exams exported:\n{preview}{extra}",
                ),
            )
        if failures:
            self.message_box.warning(
                host,
                gm("部分导出失败", "Export Partially Failed"),
                "\n".join(failures),
            )

    def regenerate(self, set_id: str) -> None:
        """Regenerate one existing question set and replace it transactionally."""
        host = self.host
        if not host.history_protection.confirm_navigation(
            host.SCREEN_QUESTION_BANK
        ):
            return

        gm = host.lang_manager.get_text
        question_set = host.set_manager.get(set_id)
        if not question_set:
            self.message_box.warning(
                host,
                gm("错误", "Error"),
                gm("未找到题目集。", "Question set not found."),
            )
            return

        preparation = host._generation_controller().prepare(
            purpose="regenerate",
        )
        if preparation is None:
            return
        dialog = preparation.dialog
        course_project = preparation.course_project
        dialog.configure_from_question_set(question_set)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        questions = dialog.generated_questions
        if not questions:
            self.message_box.warning(
                host,
                gm("没有题目", "No Questions"),
                gm(
                    "未生成可保存的题目。",
                    "No generated questions to save.",
                ),
            )
            return

        selected_difficulty = dialog.diff_combo.currentData()
        difficulty = question_set.difficulty
        if selected_difficulty in {item.value for item in Difficulty}:
            difficulty = Difficulty(selected_difficulty)
        try:
            updated_set, saved, deleted = self.regenerator(
                host.question_bank,
                host.set_manager,
                host.progress_manager,
                question_set,
                questions,
                difficulty=difficulty,
                course_project=course_project,
            )
        except RuntimeError as exc:
            self.message_box.critical(
                host,
                gm("保存失败", "Save Failed"),
                str(exc),
            )
            return

        host.topic_screen.refresh()
        cleanup_note = gm(
            (
                f"\n已清理 {len(deleted)} 道无引用旧 AI 题目。"
                if deleted
                else ""
            ),
            (
                f"\nCleaned up {len(deleted)} unreferenced old AI question(s)."
                if deleted
                else ""
            ),
        )
        self.message_box.information(
            host,
            gm("已重新生成", "Regenerated"),
            gm(
                f"已保存 {saved} 道新题，并更新题目集：\n"
                f"{updated_set.get_title(host.lang_manager.current)}"
                f"{cleanup_note}",
                f"Saved {saved} new questions and updated question set:\n"
                f"{updated_set.get_title(host.lang_manager.current)}"
                f"{cleanup_note}",
            ),
        )
        host.navigate_route(Route.library("sets"))
