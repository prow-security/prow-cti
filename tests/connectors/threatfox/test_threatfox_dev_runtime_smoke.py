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

"""Dev-runtime smoke test for the ThreatFox connector."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_THREATFOX_PKG = _REPO_ROOT / "src" / "prow" / "connectors" / "threatfox"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "iocs_sample.json"


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    code = (
        "import json, os, sys\n"
        "from prow.cli import app\n"
        "sys.argv = json.loads(os.environ['P_CLI_ARGV'])\n"
        "raise SystemExit(app())\n"
    )
    env = os.environ | {
        "PYTHONPATH": str(_REPO_ROOT / "src"),
        "P_CLI_ARGV": json.dumps(["prow", *argv]),
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.slow
def test_cli_dev_threatfox_fixture_file_url() -> None:
    cfg = {"api_url": _FIXTURE.as_uri()}
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(json.dumps(cfg))
        tmp_path = tmp.name
    try:
        r = _run_cli(
            [
                "connector",
                "dev",
                "--no-watch",
                str(_THREATFOX_PKG),
                "--config",
                tmp_path,
            ],
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout + r.stderr
    assert "emit:" in out
    assert "21 objects" in out
