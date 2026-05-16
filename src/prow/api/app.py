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

"""FastAPI application instance."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from prow import __version__
from prow.api import deps
from prow.api.connector_startup import build_supervisor_and_scheduler, configure_logging
from prow.api.routers import connectors, health, ingest, stix
from prow.config import load_config
from prow.db.config import load_database_settings
from prow.db.session import create_async_engine_from_settings, create_async_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    prow_config = load_config()
    configure_logging(prow_config.log.level)

    db_settings = load_database_settings()
    engine = create_async_engine_from_settings(db_settings)
    session_factory = create_async_sessionmaker(engine)
    deps._session_factory = session_factory

    supervisor, scheduler = build_supervisor_and_scheduler(
        prow_config,
        session_factory,
        runtime_version=__version__,
    )
    deps._supervisor = supervisor

    await supervisor.start_health_probes()
    await scheduler.start()

    yield

    await scheduler.stop()
    await supervisor.shutdown_all()
    deps._supervisor = None
    await engine.dispose()


app = FastAPI(
    title="Prow CTI",
    description="Open-source threat intelligence platform.",
    version="0.1.0",
    license_info={"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(stix.router)
app.include_router(connectors.router)
app.include_router(ingest.router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _mount_ui() -> None:
    """Serve the built dashboard; hashed bundles live under /assets."""
    if not _STATIC_DIR.is_dir():
        return

    assets_dir = _STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

    favicon = _STATIC_DIR / "favicon.svg"
    if favicon.is_file():

        @app.get("/favicon.svg", include_in_schema=False)
        async def favicon_route() -> FileResponse:
            return FileResponse(favicon)

    if not _INDEX_HTML.is_file():
        return

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(_spa_path: str) -> FileResponse:
        return FileResponse(_INDEX_HTML)


_mount_ui()
