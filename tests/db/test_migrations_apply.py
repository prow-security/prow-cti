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

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_initial_revision_is_single_head() -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["20260513_0001"]


@pytest.mark.skipif(
    not os.environ.get("PROW_TEST_DATABASE_URL"),
    reason="Set PROW_TEST_DATABASE_URL to run migration integration (see .env.example).",
)
def test_alembic_upgrade_and_downgrade() -> None:
    env = os.environ.copy()
    env["PROW_DATABASE_URL"] = os.environ["PROW_TEST_DATABASE_URL"]

    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    up = _run(["upgrade", "head"])
    assert up.returncode == 0, f"stdout={up.stdout!r} stderr={up.stderr!r}"

    down = _run(["downgrade", "base"])
    assert down.returncode == 0, f"stdout={down.stdout!r} stderr={down.stderr!r}"
