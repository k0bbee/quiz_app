import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.background_task import BackgroundTaskCancelled, TaskControl
from core.course_initializer import CourseInitializer
from core.document_parser import DocumentParser, ExtractedDocument
from models.course_project import CourseProjectManager

try:
    from core.course_parse_checkpoint import CourseParseCheckpointStore
except ImportError:
    CourseParseCheckpointStore = None


class CourseParseCheckpointTests(unittest.TestCase):
    def test_store_reuses_unchanged_document_and_rejects_changed_source(self):
        self.assertIsNotNone(CourseParseCheckpointStore)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "materials" / "lecture.txt"
            source.parent.mkdir()
            source.write_text("cache mapping " * 20, encoding="utf-8")
            store = CourseParseCheckpointStore(root / "checkpoints")
            document = ExtractedDocument(
                path=str(source),
                title="lecture",
                extension=".txt",
                text="parsed cache mapping",
                pages=["parsed cache mapping"],
            )

            store.save_document(
                str(source.parent),
                operation="initialize",
                course_id="",
                source_path=source,
                document=document,
            )

            cached = store.load_documents(
                str(source.parent),
                operation="initialize",
                course_id="",
                source_paths=[source],
            )
            self.assertEqual("parsed cache mapping", cached[str(source.resolve())].text)

            from core import course_parse_checkpoint as checkpoint_module
            with patch.object(
                checkpoint_module,
                "read_json",
                wraps=checkpoint_module.read_json,
            ) as reader:
                reusable = store.reusable_count(
                    str(source.parent),
                    operation="initialize",
                    course_id="",
                    source_paths=[source],
                )

            self.assertEqual(1, reusable)
            self.assertEqual(1, reader.call_count)

            source.write_text("virtual memory changed " * 30, encoding="utf-8")
            stale = store.load_documents(
                str(source.parent),
                operation="initialize",
                course_id="",
                source_paths=[source],
            )

            self.assertEqual({}, stale)

    def test_document_parser_reuses_cached_files_and_parses_only_missing_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("cache mapping " * 100, encoding="utf-8")
            second.write_text("process scheduling " * 100, encoding="utf-8")
            cached_first = ExtractedDocument(
                str(first), "first", ".txt", "cached first", ["cached first"], []
            )
            parsed_paths = []
            events = []

            parser = DocumentParser()
            original_parse_file = parser.parse_file

            def parse_file(path, task=None):
                parsed_paths.append(Path(path).name)
                return original_parse_file(path, task=task)

            parser.parse_file = parse_file
            documents = parser.parse_folder(
                str(root),
                task=TaskControl(events.append),
                cached_documents={str(first.resolve()): cached_first},
            )

            self.assertEqual(["second.txt"], parsed_paths)
            self.assertEqual(["cached first", ("process scheduling " * 100).strip()], [
                document.text for document in documents
            ])
            self.assertEqual(1, len([event for event in events if event.stage == "reusing_file"]))

    def test_initializer_resumes_parsed_files_after_interruption_and_clears_on_commit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "materials"
            source.mkdir()
            (source / "first.txt").write_text("cache mapping " * 100, encoding="utf-8")
            (source / "second.txt").write_text("process scheduling " * 100, encoding="utf-8")
            manager = CourseProjectManager(str(root / "projects"))
            store = CourseParseCheckpointStore(root / "checkpoints")
            first_events = []
            first_task = TaskControl()

            def interrupt_before_second(event):
                first_events.append(event)
                if event.stage == "parsing_file" and event.current == 2:
                    first_task.cancel()

            first_task = TaskControl(interrupt_before_second)
            first_initializer = CourseInitializer(manager, checkpoint_store=store)

            with self.assertRaises(BackgroundTaskCancelled):
                first_initializer.initialize(str(source), title="Systems", task=first_task)

            source_paths = first_initializer.parser.source_paths(str(source))
            cached = store.load_documents(
                str(source),
                operation="initialize",
                course_id="",
                source_paths=source_paths,
            )
            self.assertEqual([str((source / "first.txt").resolve())], list(cached))

            parsed_paths = []
            second_events = []
            second_initializer = CourseInitializer(manager, checkpoint_store=store)
            original_parse_file = second_initializer.parser.parse_file

            def count_parse(path, task=None):
                parsed_paths.append(Path(path).name)
                return original_parse_file(path, task=task)

            second_initializer.parser.parse_file = count_parse
            project = second_initializer.initialize(
                str(source),
                title="Systems",
                task=TaskControl(second_events.append),
            )

            self.assertEqual(["second.txt"], parsed_paths)
            self.assertEqual(project.course_id, manager.current().course_id)
            self.assertTrue(any(event.stage == "reusing_file" for event in second_events))
            self.assertEqual({}, store.load_documents(
                str(source),
                operation="initialize",
                course_id="",
                source_paths=source_paths,
            ))


if __name__ == "__main__":
    unittest.main()
