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

"""HTTP API (FastAPI + uvicorn) commands."""

from __future__ import annotations

import typer
import uvicorn

app = typer.Typer(help="Run the Prow HTTP API.")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind socket to this host."),
    port: int = typer.Option(8000, "--port", "-p", help="Listen on this port."),
    reload: bool = typer.Option(
        False,
        "--reload",
        "-r",
        help="Reload the app when Python files change (dev only).",
    ),
) -> None:
    """Start the FastAPI application (same app the UI expects on this port)."""
    uvicorn.run(
        "prow.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )
