import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.past_exam_course_matcher import match_exam_to_courses
from core.past_exam_importer import PastExamImporter
from core.document_parser import ExtractedDocument
from core.input_limits import InputLimitError
from models.past_exam import PastExamContent, PastExamManager, PastExamRecord
from models.course_project import CourseTopic


class PastExamImportTests(unittest.TestCase):
    def test_oversized_source_is_rejected_before_hashing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "oversized.pdf"
            source.write_bytes(b"%PDF oversized")
            manager = PastExamManager(root / "past-exams")
            importer = PastExamImporter(manager, self._course_manager([]))

            with patch("core.input_limits.MAX_DOCUMENT_BYTES", 1), \
                 patch("core.past_exam_importer._sha256_file") as hash_file:
                with self.assertRaises(InputLimitError):
                    importer.import_file(source)

            hash_file.assert_not_called()

    def test_manager_round_trips_record_content_and_hash_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PastExamManager(tmpdir)
            record = PastExamRecord(
                exam_id="past-exam-a",
                title="2025 期末考试",
                source_filename="2025-final.pdf",
                source_path="source/2025-final.pdf",
                content_path="content.json",
                source_sha256="abc123",
                imported_at="2026-07-13T00:00:00+00:00",
                course_id="course-a",
                assignment_mode="manual",
                match_candidates=[{
                    "course_id": "course-a",
                    "course_title": "Computer Systems",
                    "score": 0.91,
                    "matched_terms": ["cache"],
                }],
                warnings=["Page 2 text recovered by OCR fallback"],
            )
            content = PastExamContent(
                text="[Page 1]\nCache mapping",
                pages=["Cache mapping"],
            )

            self.assertTrue(manager.save_record(record))
            self.assertTrue(manager.save_content(record.exam_id, content))

            loaded = manager.get(record.exam_id)
            loaded_content = manager.get_content(record.exam_id)
            self.assertEqual(record, loaded)
            self.assertEqual(content, loaded_content)
            self.assertEqual(record, manager.find_by_hash("abc123"))
            self.assertEqual([record], manager.load_all())
            self.assertEqual(
                (Path(tmpdir) / "past-exam-a" / "source" / "2025-final.pdf").resolve(),
                manager.resolve_source_path(record),
            )

            reassigned = manager.reassign_course(record.exam_id, "course-b")
            self.assertEqual("course-b", reassigned.course_id)
            self.assertEqual("manual", reassigned.assignment_mode)
            self.assertEqual(record.match_candidates, reassigned.match_candidates)
            self.assertEqual("course-b", manager.get(record.exam_id).course_id)

    def test_course_matcher_auto_assigns_only_a_clear_explainable_match(self):
        systems = SimpleNamespace(
            course_id="course-systems",
            title="Computer Systems",
            topics=[CourseTopic(
                topic_id="input_output",
                title="Input Output",
                keywords=["DMA", "interrupt", "polling"],
                aliases=["I/O"],
            )],
        )
        marxism = SimpleNamespace(
            course_id="course-marxism",
            title="马克思主义基本原理",
            topics=[CourseTopic(
                topic_id="dialectical_materialism",
                title="辩证唯物主义",
                keywords=["矛盾", "实践"],
            )],
        )

        result = match_exam_to_courses(
            "2025 Computer Systems I/O Final",
            "Explain interrupt-driven input output and compare DMA with polling.",
            [marxism, systems],
        )

        self.assertEqual("course-systems", result.assigned_course_id)
        self.assertEqual("course-systems", result.candidates[0].course_id)
        self.assertIn("dma", result.candidates[0].matched_terms)
        self.assertGreater(result.candidates[0].score, result.candidates[1].score)

    def test_course_matcher_keeps_close_candidates_unassigned(self):
        courses = [
            SimpleNamespace(
                course_id="calculus-a",
                title="Calculus A",
                topics=[CourseTopic("integral", "Integral", ["integration"])],
            ),
            SimpleNamespace(
                course_id="calculus-b",
                title="Calculus B",
                topics=[CourseTopic("integral", "Integral", ["integration"])],
            ),
        ]

        result = match_exam_to_courses(
            "Calculus Exam",
            "Compute the integral using integration by parts.",
            courses,
        )

        self.assertEqual("", result.assigned_course_id)
        self.assertEqual(2, len(result.candidates))
        self.assertAlmostEqual(result.candidates[0].score, result.candidates[1].score)

    def test_importer_persists_text_source_and_manual_course_assignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "2025-final.txt"
            source.write_text("1. Explain cache mapping.\n2. Compare DMA and interrupts.", encoding="utf-8")
            manager = PastExamManager(root / "past_exams")
            course = self._systems_course()
            course_manager = self._course_manager([course])

            result = PastExamImporter(manager, course_manager).import_file(
                source,
                title="2025 Final",
                manual_course_id=course.course_id,
            )

            self.assertFalse(result.duplicate)
            self.assertEqual(course.course_id, result.record.course_id)
            self.assertEqual("manual", result.record.assignment_mode)
            self.assertEqual("2025 Final", result.record.title)
            self.assertEqual(source.read_bytes(), manager.resolve_source_path(result.record).read_bytes())
            content = manager.get_content(result.record.exam_id)
            self.assertIn("cache mapping", content.text)
            self.assertEqual([content.text], content.pages)

    def test_importer_can_explicitly_leave_exam_unassigned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "exam.txt"
            source.write_text("DMA interrupt polling input output", encoding="utf-8")
            manager = PastExamManager(root / "past_exams")

            result = PastExamImporter(
                manager,
                self._course_manager([self._systems_course()]),
            ).import_file(
                source,
                title="Computer Systems I/O Exam",
                manual_course_id="",
            )

            self.assertEqual("", result.record.course_id)
            self.assertEqual("unassigned", result.record.assignment_mode)

    def test_importer_reuses_parser_ocr_output_and_auto_assigns_course(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "scan.pdf"
            source.write_bytes(b"fake-pdf")
            manager = PastExamManager(root / "past_exams")
            parser = Mock()
            parser.parse_file.return_value = ExtractedDocument(
                path=str(source),
                title="scan",
                extension=".pdf",
                text="[Page 1]\nDMA interrupt-driven input output",
                pages=["DMA interrupt-driven input output"],
                warnings=["Page 1 text recovered by OCR fallback"],
            )

            result = PastExamImporter(
                manager,
                self._course_manager([self._systems_course()]),
                parser=parser,
            ).import_file(source, title="Computer Systems I/O Exam")

            self.assertEqual("course-systems", result.record.course_id)
            self.assertEqual("auto", result.record.assignment_mode)
            self.assertIn("OCR fallback", result.record.warnings[0])
            self.assertEqual(
                ["DMA interrupt-driven input output"],
                manager.get_content(result.record.exam_id).pages,
            )

    def test_importer_detects_duplicate_hash_before_parsing_again(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "exam.txt"
            source.write_text("Question one", encoding="utf-8")
            manager = PastExamManager(root / "past_exams")
            parser = Mock()
            parser.parse_file.return_value = ExtractedDocument(
                str(source), "exam", ".txt", "Question one", ["Question one"]
            )
            importer = PastExamImporter(manager, self._course_manager([]), parser=parser)

            first = importer.import_file(source)
            second = importer.import_file(source)

            self.assertFalse(first.duplicate)
            self.assertTrue(second.duplicate)
            self.assertEqual(first.record.exam_id, second.record.exam_id)
            parser.parse_file.assert_called_once()

    def test_duplicate_import_honors_new_manual_course_choice_without_reparsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "exam.txt"
            source.write_text("Generic examination content", encoding="utf-8")
            manager = PastExamManager(root / "past_exams")
            parser = Mock()
            parser.parse_file.return_value = ExtractedDocument(
                str(source), "exam", ".txt", "Generic examination content", ["Generic examination content"]
            )
            importer = PastExamImporter(
                manager,
                self._course_manager([self._systems_course()]),
                parser=parser,
            )

            first = importer.import_file(source, manual_course_id="")
            second = importer.import_file(source, manual_course_id="course-systems")

            self.assertEqual("", first.record.course_id)
            self.assertTrue(second.duplicate)
            self.assertEqual("course-systems", second.record.course_id)
            self.assertEqual("manual", second.record.assignment_mode)
            parser.parse_file.assert_called_once()

    def test_importer_commit_failure_leaves_no_partial_exam_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "exam.txt"
            source.write_text("Question one", encoding="utf-8")
            manager = PastExamManager(root / "past_exams")
            importer = PastExamImporter(manager, self._course_manager([]))

            with patch("core.past_exam_importer.os.replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    importer.import_file(source)

            self.assertEqual([], manager.load_all())
            self.assertEqual([], list((root / "past_exams").iterdir()))

    @staticmethod
    def _systems_course():
        return SimpleNamespace(
            course_id="course-systems",
            title="Computer Systems",
            topics=[CourseTopic(
                topic_id="input_output",
                title="Input Output",
                keywords=["DMA", "interrupt", "polling"],
                aliases=["I/O"],
            )],
        )

    @staticmethod
    def _course_manager(courses):
        by_id = {course.course_id: course for course in courses}
        return SimpleNamespace(
            load_all=lambda: list(courses),
            get=lambda course_id: by_id.get(course_id),
        )


if __name__ == "__main__":
    unittest.main()
