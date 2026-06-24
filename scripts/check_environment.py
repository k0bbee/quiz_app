"""Command-line environment check for Course Quiz Studio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.environment_check import collect_environment_report, format_environment_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Course Quiz Studio runtime dependencies.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = collect_environment_report(PROJECT_ROOT)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_environment_report(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
