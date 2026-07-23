import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _requirement_names() -> set[str]:
    names: set[str] = set()
    for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", line)
        if match:
            names.add(match.group(1).casefold())
    return names


class ThirdPartyNoticesTests(unittest.TestCase):
    def test_pdf_runtime_uses_liberal_licensed_pdfium_binding(self):
        notices = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        self.assertIn("pypdfium2", notices)
        self.assertIn("Apache-2.0", notices)
        self.assertIn("BSD-3-Clause", notices)
        self.assertNotIn("PyMuPDF", notices)
        self.assertNotIn("AGPL", notices)

    def test_notice_covers_every_direct_requirement(self):
        notice = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").casefold()

        missing = sorted(name for name in _requirement_names() if name not in notice)

        self.assertEqual([], missing)

    def test_copyright_statement_preserves_third_party_ownership(self):
        statement = (PROJECT_ROOT / "COPYRIGHT.md").read_text(encoding="utf-8")

        self.assertIn("AI课程刷题软件", statement)
        self.assertIn("GPL-3.0-only", statement)
        self.assertIn("不主张拥有第三方", statement)


if __name__ == "__main__":
    unittest.main()
