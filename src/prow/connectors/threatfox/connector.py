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

"""abuse.ch ThreatFox IOC connector."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from prow.connector.base import ConnectorBase
from prow.connector.context import ConnectorContext
from prow.stix.helpers import (
    bundle,
    domain_observable,
    file_observable,
    indicator,
    ipv4_observable,
    relationship,
    url_observable,
)
from prow.stix.types import Malware

_DEFAULT_API_URL = "https://threatfox-api.abuse.ch/api/v1/"
_DEFAULT_USER_AGENT = "Prow-CTI/0.1 (security research; https://github.com/prow-cti)"


class ThreatFoxConnectorError(Exception):
    """Base class for ThreatFox connector failures."""


class ThreatFoxFetchError(ThreatFoxConnectorError):
    """Raised when the ThreatFox HTTP layer fails."""


class ThreatFoxFeedFormatError(ThreatFoxConnectorError):
    """Raised when the ThreatFox JSON payload is missing expected structure."""


def _parse_abuse_ch_datetime(raw: str) -> datetime:
    base = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    return base


def _stix_pattern_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _split_ip_port(value: str) -> str:
    host, _, _port = value.partition(":")
    return host.strip()


class ThreatFoxConnector(ConnectorBase):
    """Pulls IOCs from abuse.ch ThreatFox as STIX 2.1 objects."""

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
        headers = {
            "User-Agent": str(self.ctx.config.get("user_agent", _DEFAULT_USER_AGENT)),
            "Content-Type": "application/json",
        }
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

        last_fetch = await self.ctx.get_state("last_fetch_date")
        if isinstance(last_fetch, str) and last_fetch.strip():
            days = 1
        else:
            days = int(self.ctx.config.get("days_back", 7))

        api_url = str(self.ctx.config.get("api_url", _DEFAULT_API_URL))
        payload = {"query": "get_iocs", "days": days}

        if urlparse(api_url).scheme == "file":
            try:
                path = Path(url2pathname(urlparse(api_url).path))
                raw = path.read_bytes()
            except OSError as exc:
                raise ThreatFoxFetchError(f"cannot read ThreatFox file feed: {exc}") from exc
        else:
            try:
                response = await client.post(api_url, json=payload)
            except httpx.HTTPError as exc:
                self.ctx.log.error("threatfox.http_error", error=str(exc))
                raise ThreatFoxFetchError(str(exc)) from exc

            if response.status_code != 200:
                self.ctx.log.error(
                    "threatfox.http_unexpected_status",
                    status_code=response.status_code,
                    body_preview=response.text[:500],
                )
                raise ThreatFoxFetchError(f"ThreatFox HTTP {response.status_code}")
            raw = response.content

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ThreatFoxFeedFormatError(f"ThreatFox feed is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ThreatFoxFeedFormatError("ThreatFox feed root must be a JSON object")

        entries = self._extract_iocs(data)
        if not entries:
            self.ctx.log.info("threatfox.no_results", days=days)
            await self.ctx.set_state("last_fetch_date", self.ctx.now.date().isoformat())
            return

        objects: list[Any] = []
        for entry in entries:
            if self.ctx.cancelled.is_set():
                return
            objects.extend(self._objects_for_ioc(entry))

        if not objects:
            self.ctx.log.info("threatfox.no_objects_built", days=days)
            await self.ctx.set_state("last_fetch_date", self.ctx.now.date().isoformat())
            return

        stix_bundle = bundle(objects)
        await self.ctx.emit(stix_bundle)
        await self.ctx.set_state("last_fetch_date", self.ctx.now.date().isoformat())
        await self.ctx.set_state("last_successful_fetch", self.ctx.now.isoformat())
        self.ctx.log.info(
            "threatfox.fetch_complete",
            ioc_count=len(entries),
            object_count=len(objects),
            days=days,
            bundle_id=stix_bundle.id,
        )

    def _extract_iocs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        status = data.get("query_status")
        if status == "no_results":
            return []
        raw = data.get("data")
        if not isinstance(raw, list):
            raise ThreatFoxFeedFormatError("ThreatFox feed missing data array")
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            else:
                raise ThreatFoxFeedFormatError("data entries must be objects")
        return out

    def _objects_for_ioc(self, entry: dict[str, Any]) -> list[Any]:
        ioc_value = entry.get("ioc")
        ioc_type = entry.get("ioc_type")
        if not isinstance(ioc_value, str) or not ioc_value.strip():
            raise ThreatFoxFeedFormatError("ThreatFox entry missing ioc")
        if not isinstance(ioc_type, str):
            raise ThreatFoxFeedFormatError("ThreatFox entry missing ioc_type")

        seen_raw = entry.get("first_seen")
        if not isinstance(seen_raw, str):
            raise ThreatFoxFeedFormatError("ThreatFox entry missing first_seen")
        try:
            valid_from = _parse_abuse_ch_datetime(seen_raw)
        except ValueError as exc:
            raise ThreatFoxFeedFormatError(f"invalid first_seen {seen_raw!r}") from exc

        confidence_raw = entry.get("confidence_level")
        confidence = int(confidence_raw) if isinstance(confidence_raw, int) else 50

        obs = self._build_observable(ioc_type, ioc_value)
        ind = indicator(
            name=f"ThreatFox IOC: {ioc_value[:60]}",
            pattern=self._indicator_pattern(ioc_type, ioc_value),
            pattern_type="stix",
            indicator_types=["malicious-activity"],
            valid_from=valid_from,
            confidence=confidence,
        )
        rel = relationship(ind, "based-on", obs)
        objects: list[Any] = [obs, ind, rel]

        malware_name = entry.get("malware_printable")
        if isinstance(malware_name, str) and malware_name.strip():
            now = datetime.now(UTC)
            malware = Malware(
                id=f"malware--{uuid.uuid4()}",
                created=now,
                modified=now,
                is_family=True,
                name=malware_name.strip(),
            )
            objects.append(malware)
            objects.append(relationship(ind, "indicates", malware))
        return objects

    def _indicator_pattern(self, ioc_type: str, ioc_value: str) -> str:
        quoted = _stix_pattern_quote(ioc_value)
        if ioc_type == "ip:port":
            ip = _split_ip_port(ioc_value)
            return f"[ipv4-addr:value = '{_stix_pattern_quote(ip)}']"
        if ioc_type == "domain":
            return f"[domain-name:value = '{quoted}']"
        if ioc_type == "url":
            return f"[url:value = '{quoted}']"
        if ioc_type == "sha256_hash":
            return f"[file:hashes.'SHA-256' = '{quoted}']"
        if ioc_type == "md5_hash":
            return f"[file:hashes.'MD5' = '{quoted}']"
        raise ThreatFoxFeedFormatError(f"unsupported ThreatFox ioc_type {ioc_type!r}")

    def _build_observable(self, ioc_type: str, ioc_value: str) -> Any:
        if ioc_type == "ip:port":
            return ipv4_observable(value=_split_ip_port(ioc_value))
        if ioc_type == "domain":
            return domain_observable(value=ioc_value)
        if ioc_type == "url":
            return url_observable(value=ioc_value)
        if ioc_type == "sha256_hash":
            return file_observable(hashes={"SHA-256": ioc_value})
        if ioc_type == "md5_hash":
            return file_observable(hashes={"MD5": ioc_value})
        raise ThreatFoxFeedFormatError(f"unsupported ThreatFox ioc_type {ioc_type!r}")
