# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import datetime as dt
from importlib import resources

SCHEMAS_ROOT = resources.files("prow.stix") / "_schemas"


def test_version_txt_parses() -> None:
    text = (SCHEMAS_ROOT / "version.txt").read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    assert len(lines) == 2, f"version.txt must have exactly two lines, got {len(lines)}"

    commit_line, date_line = lines
    assert commit_line.startswith("commit: "), commit_line
    sha = commit_line.removeprefix("commit: ").strip()
    assert len(sha) == 40, f"expected full 40-char SHA, got {sha!r}"
    assert all(c in "0123456789abcdef" for c in sha), sha

    assert date_line.startswith("date: "), date_line
    date_str = date_line.removeprefix("date: ").strip()
    dt.date.fromisoformat(date_str)


def test_2_1_subdirectories_exist() -> None:
    root_2_1 = SCHEMAS_ROOT / "2.1"
    assert root_2_1.is_dir()
    present = {child.name for child in root_2_1.iterdir() if child.is_dir()}
    expected = {"common", "observables", "sdos", "sros"}
    missing = expected - present
    assert not missing, f"missing schema subdirs: {missing}"


def test_representative_schema_files_present() -> None:
    cases = [
        ("sdos", "indicator.json"),
        ("sdos", "malware.json"),
        ("observables", "ipv4-addr.json"),
        ("common", "bundle.json"),
    ]
    for subdir, filename in cases:
        path = SCHEMAS_ROOT / "2.1" / subdir / filename
        assert path.is_file(), f"expected vendored schema {subdir}/{filename}"


def test_readme_documents_provenance_license_refresh_and_readonly() -> None:
    readme = (SCHEMAS_ROOT / "README.md").read_text(encoding="utf-8").lower()
    expected_phrases = [
        "provenance",
        "bsd",
        "refresh",
        "read-only",
    ]
    for phrase in expected_phrases:
        assert phrase in readme, f"README missing phrase: {phrase!r}"
