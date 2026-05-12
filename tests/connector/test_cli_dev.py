# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOOD_PKG = Path(__file__).parent / "dev_fixtures" / "good_pkg"
_BAD_MANIFEST = Path(__file__).parent / "dev_fixtures" / "bad_manifest"


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
    }
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.slow
def test_cli_validate_good_connector() -> None:
    r = _run_cli(["connector", "validate", str(_GOOD_PKG)])
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


@pytest.mark.slow
def test_cli_validate_bad_manifest() -> None:
    r = _run_cli(["connector", "validate", str(_BAD_MANIFEST)])
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "config_schema" in combined or "required keys" in combined


@pytest.mark.slow
def test_cli_dev_no_watch_emits_summary() -> None:
    r = _run_cli(["connector", "dev", "--no-watch", str(_GOOD_PKG)])
    assert r.returncode == 0, r.stderr + r.stdout
    assert "emit:" in r.stdout


@pytest.mark.slow
def test_cli_test_stub() -> None:
    r = _run_cli(
        [
            "connector",
            "test",
            str(_GOOD_PKG),
            "--fixture",
            str(_GOOD_PKG / "dummy.json"),
        ],
    )
    assert r.returncode == 1
    assert "not yet implemented" in (r.stdout + r.stderr).lower()
