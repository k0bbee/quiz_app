import tempfile
import unittest
import inspect
from pathlib import Path

from core.background_task import TaskControl
from core.document_parser import DocumentParser, ExtractedDocument

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

            source.write_text("virtual memory changed " * 30, encoding="utf-8")
            stale = store.load_documents(
                str(source.parent),
                operation="initialize",
                course_id="",
                source_paths=[source],
            )

            self.assertEqual({}, stale)

    def test_document_parser_reuses_cached_files_and_parses_only_missing_sources(self):
        self.assertIn(
            "cached_documents",
            inspect.signature(DocumentParser.parse_folder).parameters,
        )
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


if __name__ == "__main__":
    unittest.main()
