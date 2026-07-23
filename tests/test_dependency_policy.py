import unittest
from pathlib import Path


class DependencyPolicyTests(unittest.TestCase):
    def test_pillow_floor_includes_2026_security_fixes(self):
        requirements = (
            Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        )
        pillow = next(
            line for line in requirements
            if line.lower().startswith("pillow")
        )
        self.assertEqual("Pillow>=12.3.0", pillow)


if __name__ == "__main__":
    unittest.main()
