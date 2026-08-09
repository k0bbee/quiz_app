"""Create the distributable Windows portable ZIP from a PyInstaller onedir."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from config import APP_NAME  # noqa: E402 - repository script bootstrap


_LEGAL_FILES = ("LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md")
_ARCHIVE_PREFIX = "AI-Course-Quiz"
_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*\Z")


def package_windows_portable(
    *,
    project_root: Path,
    dist_root: Path,
    version: str,
) -> tuple[Path, Path]:
    """Add release notices and archive one clean PyInstaller onedir."""
    project_root = project_root.resolve()
    dist_root = dist_root.resolve()
    version = str(version).strip()
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid package version: {version!r}")
    package_dir = dist_root / APP_NAME
    executable = package_dir / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"portable executable not found: {executable}")

    data_dir = package_dir / "data"
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError(
            f"portable data directory is not empty: {data_dir}"
        )

    for name in _LEGAL_FILES:
        source = project_root / name
        if not source.is_file():
            raise FileNotFoundError(f"release notice not found: {source}")
        shutil.copy2(source, package_dir / name)

    data_dir.mkdir(exist_ok=True)

    archive = dist_root / f"{_ARCHIVE_PREFIX}-{version}-Windows-x64.zip"
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        bundle.writestr(f"{APP_NAME}/data/", b"")
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_dir).as_posix()
            bundle.write(path, f"{APP_NAME}/{relative}")

    checksum = archive.with_name(f"{archive.name}.sha256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive, checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_REPOSITORY_ROOT,
    )
    parser.add_argument("--dist-root", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    archive, checksum = package_windows_portable(
        project_root=args.project_root,
        dist_root=args.dist_root,
        version=str(args.version).strip(),
    )
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
