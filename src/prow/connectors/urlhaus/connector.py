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

"""abuse.ch URLhaus malicious URL connector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from prow.connector.base import ConnectorBase
from prow.connector.context import ConnectorContext
from prow.stix.helpers import bundle, indicator, relationship, url_observable

_DEFAULT_API_BASE = "https://urlhaus-api.abuse.ch/v1"
_DEFAULT_USER_AGENT = "Prow-CTI/0.1 (security research; https://github.com/prow-cti)"
_URLHAUS_CONFIDENCE = 75


class UrlhausConnectorError(Exception):
    """Base class for URLhaus connector failures."""


class UrlhausFetchError(UrlhausConnectorError):
    """Raised when the URLhaus HTTP layer fails."""


class UrlhausFeedFormatError(UrlhausConnectorError):
    """Raised when the URLhaus JSON payload is missing expected structure."""


def _parse_abuse_ch_datetime(raw: str) -> datetime:
    """Parse abuse.ch ``YYYY-MM-DD HH:MM:SS UTC`` timestamps."""
    base = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    return base


def _stix_pattern_quote(value: str) -> str:
    """Escape a value for inclusion in a STIX pattern single-quoted string."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class UrlhausConnector(ConnectorBase):
    """Pulls recent malicious URLs from abuse.ch URLhaus as STIX 2.1 objects."""

    _http_client_override: httpx.AsyncClient | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def __init__(self, ctx: ConnectorContext) -> None:
        super().__init__(ctx)
        self._http_client_override = None
        self._client = None
        self._owns_client = False

    async def setup(self) -> None:
        timeout_s = float(self.ctx.config.get("http_timeout_seconds", 60))
        headers = {"User-Agent": str(self.ctx.config.get("user_agent", _DEFAULT_USER_AGENT))}
        auth_key = self.ctx.config.get("auth_key")
        if isinstance(auth_key, str) and auth_key.strip():
            headers["Auth-Key"] = auth_key.strip()
        if self._http_client_override is not None:
            self._client = self._http_client_override
            self._owns_client = False
            return
        self._client = httpx.AsyncClient(timeout=timeout_s, headers=headers)
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

        limit = int(self.ctx.config.get("limit", 1000))
        min_confidence = int(self.ctx.config.get("min_confidence", 0))
        api_base = str(self.ctx.config.get("api_base", _DEFAULT_API_BASE)).rstrip("/")
        parsed_base = urlparse(api_base)
        if parsed_base.scheme == "file":
            try:
                path = Path(url2pathname(parsed_base.path))
                raw = path.read_bytes()
            except OSError as exc:
                raise UrlhausFetchError(f"cannot read URLhaus file feed: {exc}") from exc
        else:
            url = f"{api_base}/urls/recent/limit/{limit}"
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                self.ctx.log.error("urlhaus.http_error", error=str(exc))
                raise UrlhausFetchError(str(exc)) from exc

            if response.status_code != 200:
                self.ctx.log.error(
                    "urlhaus.http_unexpected_status",
                    status_code=response.status_code,
                    body_preview=response.text[:500],
                )
                raise UrlhausFetchError(f"URLhaus HTTP {response.status_code}")
            raw = response.content

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UrlhausFeedFormatError(f"URLhaus feed is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise UrlhausFeedFormatError("URLhaus feed root must be a JSON object")

        entries = self._extract_urls(data)
        if not entries:
            self.ctx.log.info("urlhaus.no_results")
            return

        objects: list[Any] = []
        for entry in entries:
            if self.ctx.cancelled.is_set():
                return
            confidence = _URLHAUS_CONFIDENCE
            if confidence < min_confidence:
                continue
            objects.extend(self._objects_for_url(entry))

        if not objects:
            self.ctx.log.info("urlhaus.no_objects_after_filter")
            return

        stix_bundle = bundle(objects)
        await self.ctx.emit(stix_bundle)
        await self.ctx.set_state("last_successful_fetch", self.ctx.now.isoformat())
        self.ctx.log.info(
            "urlhaus.fetch_complete",
            url_count=len(entries),
            object_count=len(objects),
            bundle_id=stix_bundle.id,
        )

    def _extract_urls(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        status = data.get("query_status")
        if status == "no_results":
            return []
        raw = data.get("urls")
        if not isinstance(raw, list):
            raise UrlhausFeedFormatError("URLhaus feed missing urls array")
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            else:
                raise UrlhausFeedFormatError("urls entries must be objects")
        return out

    def _objects_for_url(self, entry: dict[str, Any]) -> list[Any]:
        url_value = entry.get("url")
        if not isinstance(url_value, str) or not url_value.strip():
            raise UrlhausFeedFormatError("URLhaus entry missing url")

        added_raw = entry.get("date_added")
        if not isinstance(added_raw, str):
            raise UrlhausFeedFormatError("URLhaus entry missing date_added")
        try:
            valid_from = _parse_abuse_ch_datetime(added_raw)
        except ValueError as exc:
            raise UrlhausFeedFormatError(f"invalid date_added {added_raw!r}") from exc

        obs = url_observable(value=url_value)
        display_url = url_value if len(url_value) <= 60 else f"{url_value[:57]}..."
        quoted = _stix_pattern_quote(url_value)
        ind = indicator(
            name=f"Malicious URL: {display_url}",
            pattern=f"[url:value = '{quoted}']",
            pattern_type="stix",
            indicator_types=["malicious-activity"],
            valid_from=valid_from,
            confidence=_URLHAUS_CONFIDENCE,
        )
        rel = relationship(ind, "based-on", obs)
        return [obs, ind, rel]
