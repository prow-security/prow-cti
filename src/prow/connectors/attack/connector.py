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

"""MITRE ATT&CK Enterprise STIX 2.1 connector."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from prow.connector.base import ConnectorBase
from prow.connector.context import ConnectorContext
from prow.stix import StixValidationError, validate_stix_object

_DEFAULT_STIX_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
)
_EMIT_BATCH_SIZE = 500


class AttackConnectorError(Exception):
    """Base class for ATT&CK connector failures."""


class AttackFetchError(AttackConnectorError):
    """Raised when the ATT&CK feed HTTP layer fails."""


class AttackFeedFormatError(AttackConnectorError):
    """Raised when the ATT&CK JSON payload is missing expected structure."""


@dataclass(frozen=True)
class _HttpFeedResult:
    not_modified: bool
    body: bytes
    etag: str | None
    last_modified: str | None


def _normalize_attack_object(obj: dict[str, Any]) -> dict[str, Any]:
    """Apply ingest-safe defaults to MITRE-published STIX objects."""
    out = dict(obj)
    out.setdefault("spec_version", "2.1")
    if out.get("type") == "malware" and "is_family" not in out:
        # MITRE maps ATT&CK software to malware SDOs without is_family.
        out["is_family"] = False
    return out


def _is_deprecated(obj: dict[str, Any]) -> bool:
    return obj.get("x_mitre_deprecated") is True or obj.get("revoked") is True


class AttackConnector(ConnectorBase):
    """Ingests the MITRE ATT&CK Enterprise STIX 2.1 bundle."""

    _http_client_override: httpx.AsyncClient | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def __init__(self, ctx: ConnectorContext) -> None:
        super().__init__(ctx)
        self._http_client_override = None
        self._client = None
        self._owns_client = False

    async def setup(self) -> None:
        timeout_s = float(self.ctx.config.get("http_timeout_seconds", 120))
        if self._http_client_override is not None:
            self._client = self._http_client_override
            self._owns_client = False
            return
        self._client = httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = True

    async def teardown(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def fetch(self) -> None:
        client = self._client
        if client is None:
            msg = "HTTP client is not initialised"
            raise RuntimeError(msg)

        stix_url = str(self.ctx.config.get("stix_url", _DEFAULT_STIX_URL))
        if not stix_url:
            self.ctx.log.error("attack.missing_stix_url")
            raise AttackFeedFormatError("stix_url is empty")

        include_deprecated = bool(self.ctx.config.get("include_deprecated", False))

        etag = await self.ctx.get_state("etag")
        last_modified = await self.ctx.get_state("last_modified")
        etag_s = etag if isinstance(etag, str) else None
        lm_s = last_modified if isinstance(last_modified, str) else None

        parsed = urlparse(stix_url)
        if parsed.scheme == "file":
            body, new_etag, new_lm = await self._read_file_feed(stix_url)
        else:
            http_result = await self._http_get_feed(client, stix_url, etag_s, lm_s)
            if http_result.not_modified:
                self.ctx.log.info("attack.feed_not_modified")
                return
            body = http_result.body
            new_etag = http_result.etag
            new_lm = http_result.last_modified

        try:
            objects, skipped_validation = self._extract_validated_objects(
                body,
                include_deprecated,
            )
        except AttackFeedFormatError as exc:
            self.ctx.log.error("attack.feed_format_error", error=str(exc))
            raise

        emitted = 0
        for index in range(0, len(objects), _EMIT_BATCH_SIZE):
            if self.ctx.cancelled.is_set():
                return
            batch = objects[index : index + _EMIT_BATCH_SIZE]
            await self.ctx.emit(
                {
                    "type": "bundle",
                    "id": f"bundle--{uuid.uuid4()}",
                    "objects": batch,
                },
            )
            emitted += len(batch)

        if new_etag is not None:
            await self.ctx.set_state("etag", new_etag)
        if new_lm is not None:
            await self.ctx.set_state("last_modified", new_lm)
        await self.ctx.set_state("last_successful_fetch", self.ctx.now.isoformat())

        self.ctx.log.info(
            "attack.fetch_complete",
            emitted_count=emitted,
            skipped_validation=skipped_validation,
        )

    async def _read_file_feed(self, feed_url: str) -> tuple[bytes, str | None, str | None]:
        path = Path(url2pathname(urlparse(feed_url).path))
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self.ctx.log.error("attack.file_read_failed", path=str(path), error=str(exc))
            raise AttackFetchError(f"cannot read ATT&CK file feed: {exc}") from exc
        return raw, None, None

    async def _http_get_feed(
        self,
        client: httpx.AsyncClient,
        url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> _HttpFeedResult:
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            self.ctx.log.error("attack.http_error", error=str(exc))
            raise AttackFetchError(str(exc)) from exc

        if response.status_code == 304:
            return _HttpFeedResult(
                not_modified=True,
                body=b"",
                etag=None,
                last_modified=None,
            )

        if response.status_code != 200:
            self.ctx.log.error(
                "attack.http_unexpected_status",
                status_code=response.status_code,
                body_preview=response.text[:500],
            )
            raise AttackFetchError(f"ATT&CK feed HTTP {response.status_code}")

        return _HttpFeedResult(
            not_modified=False,
            body=response.content,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )

    def _parse_feed_json(self, body: bytes) -> dict[str, Any]:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AttackFeedFormatError(f"ATT&CK feed is not valid UTF-8: {exc}") from exc
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AttackFeedFormatError(f"ATT&CK feed is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise AttackFeedFormatError("ATT&CK feed root must be a JSON object")
        return parsed

    def _extract_validated_objects(
        self,
        body: bytes,
        include_deprecated: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        data = self._parse_feed_json(body)
        raw = data.get("objects")
        if not isinstance(raw, list):
            raise AttackFeedFormatError("ATT&CK feed missing objects array")

        validated: list[dict[str, Any]] = []
        skipped_validation = 0
        for item in raw:
            if not isinstance(item, dict):
                raise AttackFeedFormatError("objects entries must be objects")
            if not include_deprecated and _is_deprecated(item):
                continue
            normalized = _normalize_attack_object(item)
            try:
                validate_stix_object(normalized, allow_custom_types=True)
            except StixValidationError as exc:
                object_id = normalized.get("id", "unknown")
                stix_type = normalized.get("type")
                self.ctx.log.warning(
                    "attack.object_validation_skipped",
                    object_id=object_id,
                    stix_type=stix_type,
                    error=exc.errors[0],
                )
                skipped_validation += 1
                continue
            validated.append(normalized)

        if skipped_validation:
            self.ctx.log.info(
                "attack.skipped_validation_failures",
                count=skipped_validation,
            )
        return validated, skipped_validation
