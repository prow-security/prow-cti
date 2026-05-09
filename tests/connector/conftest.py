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

"""Shared fixtures for connector runtime tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_src_on_pythonpath() -> None:
    """Let spawned connector subprocesses import ``prow`` (repo layout)."""

    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    sep = os.pathsep
    prev = os.environ.get("PYTHONPATH", "")
    chunks = [str(src), str(root)]
    merged = prev
    for extra in chunks:
        if extra not in merged.split(sep):
            merged = f"{extra}{sep}{merged}" if merged else extra
    os.environ["PYTHONPATH"] = merged


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: subprocess integration tests")
