# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Check Orbit CLI wheel and source archive metadata without installing them."""

from __future__ import annotations

import argparse
import email.parser
import posixpath
import re
import stat
import tarfile
from pathlib import Path
from zipfile import ZipFile

_EXPECTED_NAME = "orbit-cli"
_EXPECTED_VERSION = "0.1.0a1"
_EXPECTED_REQUIRES_PYTHON = {">=3.11,<3.15", "<3.15,>=3.11"}


def _safe_name(name: str) -> bool:
    """Return whether an archive path is relative and cannot escape its root."""
    normalized = posixpath.normpath(name)
    return not normalized.startswith("/") and ".." not in normalized.split("/")


def _metadata_errors(raw: bytes, source: Path) -> list[str]:
    """Validate required package identity and runtime metadata from an archive."""
    metadata = email.parser.BytesParser().parsebytes(raw)
    errors = []
    for key, value in {
        "Name": _EXPECTED_NAME,
        "Version": _EXPECTED_VERSION,
        "License-Expression": "Apache-2.0",
    }.items():
        if metadata.get(key) != value:
            errors.append(f"{source}: metadata {key!r} must be {value!r}")
    if metadata.get("Requires-Python") not in _EXPECTED_REQUIRES_PYTHON:
        errors.append(f"{source}: metadata must support Python 3.11 through 3.14")
    if not metadata.get("License-File"):
        errors.append(f"{source}: license metadata is missing")
    dependency_pattern = re.compile(r"^orbit-core(?:\s|[<>=!~;\[])", re.IGNORECASE)
    if not any(dependency_pattern.match(value) for value in metadata.get_all("Requires-Dist", [])):
        errors.append(f"{source}: runtime dependency on orbit-core is missing")
    return errors


def check_distribution(directory: Path) -> list[str]:
    """Return integrity errors for the wheel and source distribution in a directory."""
    errors: list[str] = []
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        return [f"expected exactly one wheel and one sdist in {directory}"]
    with ZipFile(wheels[0]) as wheel:
        members = wheel.infolist()
        if any(
            not _safe_name(member.filename)
            or ((member.external_attr >> 16) & 0o170000) == stat.S_IFLNK
            for member in members
        ):
            errors.append(f"{wheels[0]}: unsafe archive member")
        metadata = [member for member in members if member.filename.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            errors.append(f"{wheels[0]}: expected one METADATA file")
        else:
            errors.extend(_metadata_errors(wheel.read(metadata[0]), wheels[0]))
        names = {member.filename for member in members}
        for required in ("orbit_cli/__init__.py", "orbit_cli/py.typed"):
            if required not in names:
                errors.append(f"{wheels[0]}: missing {required}")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            errors.append(f"{wheels[0]}: missing packaged LICENSE")
        entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entry_points) != 1 or "orbit = orbit_cli.app:app" not in wheel.read(
            entry_points[0]
        ).decode("utf-8"):
            errors.append(f"{wheels[0]}: missing orbit console entry point")
    with tarfile.open(sdists[0]) as archive:
        members = archive.getmembers()
        if any(
            not _safe_name(member.name) or not (member.isfile() or member.isdir())
            for member in members
        ):
            errors.append(f"{sdists[0]}: unsafe archive member")
        metadata = [member for member in members if member.name.endswith("/PKG-INFO")]
        if len(metadata) != 1:
            errors.append(f"{sdists[0]}: expected one PKG-INFO file")
        else:
            source = archive.extractfile(metadata[0])
            if source is None:
                errors.append(f"{sdists[0]}: unable to read PKG-INFO")
            else:
                errors.extend(_metadata_errors(source.read(), sdists[0]))
        names = {member.name for member in members}
        if not any(name.endswith("/src/orbit_cli/py.typed") for name in names):
            errors.append(f"{sdists[0]}: missing PEP 561 typing marker")
        if not any(name.endswith("/LICENSE") for name in names):
            errors.append(f"{sdists[0]}: missing LICENSE")
    return errors


def main() -> int:
    """Run archive validation and return a process-compatible status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    errors = check_distribution(args.directory)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Package integrity checks passed for {args.directory}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
