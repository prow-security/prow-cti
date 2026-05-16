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

"""Wire supervisor + scheduler from :class:`~prow.config.schema.ProwConfig`."""

from __future__ import annotations

import logging

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prow.config.schema import ProwConfig
from prow.connector.entry_point_resolve import (
    load_manifest_config_schema,
    resolve_connector_entry_point,
    validate_connector_instance_config,
)
from prow.connector.scheduler import ConnectorScheduler
from prow.connector.supervisor import Supervisor
from prow.db.emit_handler import create_db_emit_handler
from prow.db.state_handler import create_db_state_getter, create_db_state_setter

logger = structlog.get_logger(__name__)


def configure_logging(level: str) -> None:
    """Apply prow.yml ``log.level`` to the stdlib root logger."""

    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(level=numeric, force=True)


def _entry_point_usable(entry_point_name: str) -> bool:
    ep = resolve_connector_entry_point(entry_point_name)
    if ep is None:
        return False
    try:
        ep.load()
        load_manifest_config_schema(ep)
    except Exception as exc:
        logger.warning(
            "connector.entry_point_not_found",
            name=entry_point_name,
            error=str(exc),
        )
        return False
    return True


def build_supervisor_and_scheduler(
    config: ProwConfig,
    session_factory: async_sessionmaker[AsyncSession],
    runtime_version: str,
) -> tuple[Supervisor, ConnectorScheduler]:
    """Register enabled connectors from config; return supervisor and scheduler."""

    emit_handler = create_db_emit_handler(session_factory)
    state_get = create_db_state_getter(session_factory)
    state_set = create_db_state_setter(session_factory)

    supervisor = Supervisor(
        runtime_version=runtime_version,
        emit_handler=emit_handler,
        state_get_handler=state_get,
        state_set_handler=state_set,
    )
    scheduler = ConnectorScheduler(supervisor)

    for instance_cfg in config.connectors:
        if not instance_cfg.enabled:
            continue
        instance_id = instance_cfg.id
        if instance_id is None:
            continue
        if not _entry_point_usable(instance_cfg.name):
            continue
        try:
            validate_connector_instance_config(instance_cfg.name, instance_cfg.config)
        except ValueError as exc:
            logger.warning(
                "connector.config_invalid",
                name=instance_cfg.name,
                instance_id=instance_id,
                error=str(exc),
            )
            continue

        supervisor.add_instance(
            instance_id=instance_id,
            entry_point_name=instance_cfg.name,
            config=instance_cfg.config,
        )
        scheduler.register(instance_id, instance_cfg.schedule)

    return supervisor, scheduler
