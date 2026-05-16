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

"""Command-line interface for Prow (Typer application entrypoint)."""

import typer

from prow.cli.api import app as api_app
from prow.cli.connector import app as connector_app

app = typer.Typer(invoke_without_command=True)

app.add_typer(api_app, name="api", help="HTTP API server")
app.add_typer(connector_app, name="connector", help="Connector tooling")


@app.callback()
def _root(_ctx: typer.Context) -> None:
    """Prow CLI."""
