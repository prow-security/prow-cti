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

"""CISA KEV connector implementation."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from prow.connector.base import ConnectorBase
from prow.connector.context import ConnectorContext
from prow.stix.helpers import bundle, indicator, relationship
from prow.stix.types import ExternalReference, Identity, Indicator, Relationship, Vulnerability


class KevConnectorError(Exception):
    """Base class for KEV connector failures."""


class KevFetchError(KevConnectorError):
    """Raised when the KEV feed HTTP layer fails."""


class KevFeedFormatError(KevConnectorError):
    """Raised when the KEV JSON payload is missing expected structure."""


def _kev_date_to_utc_datetime(iso_date: str) -> datetime:
    """Parse a KEV ``YYYY-MM-DD`` field into UTC midnight."""
    stripped = iso_date.strip()
    base = datetime.fromisoformat(stripped)
    if base.tzinfo is None:
        return base.replace(tzinfo=UTC)
    return base.astimezone(UTC)


@dataclass(frozen=True)
class _HttpFeedResult:
    not_modified: bool
    body: bytes
    etag: str | None
    last_modified: str | None


class KevConnector(ConnectorBase):
    """Pulls the CISA KEV catalog as STIX 2.1 objects."""

    _http_client_override: httpx.AsyncClient | None
    _client: httpx.AsyncClient | None
    _identity: Identity | None
    _owns_client: bool

    def __init__(self, ctx: ConnectorContext) -> None:
        super().__init__(ctx)
        self._http_client_override = None
        self._client = None
        self._identity = None
        self._owns_client = False

    async def setup(self) -> None:
        self._identity = self._build_identity()
        timeout_s = float(self.ctx.config.get("http_timeout_seconds", 30))
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
        self._identity = None

    async def fetch(self) -> None:
        if self._identity is None:
            msg = "KevConnector.setup must run before fetch"
            raise RuntimeError(msg)
        client = self._client
        if client is None:
            msg = "HTTP client is not initialised"
            raise RuntimeError(msg)

        feed_url = str(self.ctx.config.get("feed_url", ""))
        if not feed_url:
            self.ctx.log.error("kev.missing_feed_url")
            raise KevFeedFormatError("feed_url is empty")

        etag = await self.ctx.get_state("etag")
        last_modified = await self.ctx.get_state("last_modified")
        etag_s = etag if isinstance(etag, str) else None
        lm_s = last_modified if isinstance(last_modified, str) else None

        parsed = urlparse(feed_url)
        new_etag: str | None
        new_lm: str | None
        if parsed.scheme == "file":
            body, new_etag, new_lm = await self._read_file_feed(feed_url)
        else:
            http_result = await self._http_get_feed(client, feed_url, etag_s, lm_s)
            if http_result.not_modified:
                self.ctx.log.info("kev.feed_not_modified")
                return
            body = http_result.body
            new_etag = http_result.etag
            new_lm = http_result.last_modified

        try:
            data = self._parse_feed_json(body)
            entries = self._extract_vulnerabilities(data)
        except KevFeedFormatError as exc:
            self.ctx.log.error("kev.feed_format_error", error=str(exc))
            raise

        objects: list[Any] = [self._identity]
        for entry in entries:
            if self.ctx.cancelled.is_set():
                return
            vuln = self._build_vulnerability(entry)
            ind = self._build_indicator(entry, vuln)
            rel = self._build_relationship(ind, vuln)
            objects.extend((vuln, ind, rel))

        stix_bundle = bundle(objects)
        await self.ctx.emit(stix_bundle)

        if new_etag is not None:
            await self.ctx.set_state("etag", new_etag)
        if new_lm is not None:
            await self.ctx.set_state("last_modified", new_lm)
        await self.ctx.set_state("last_successful_fetch", self.ctx.now.isoformat())

        self.ctx.log.info(
            "kev.fetch_complete",
            cve_count=len(entries),
            bundle_id=stix_bundle.id,
        )

    async def _read_file_feed(self, feed_url: str) -> tuple[bytes, str | None, str | None]:
        path = Path(url2pathname(urlparse(feed_url).path))
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self.ctx.log.error("kev.file_read_failed", path=str(path), error=str(exc))
            raise KevFetchError(f"cannot read KEV file feed: {exc}") from exc
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
            self.ctx.log.error("kev.http_error", error=str(exc))
            raise KevFetchError(str(exc)) from exc

        if response.status_code == 304:
            return _HttpFeedResult(
                not_modified=True,
                body=b"",
                etag=None,
                last_modified=None,
            )

        if response.status_code != 200:
            self.ctx.log.error(
                "kev.http_unexpected_status",
                status_code=response.status_code,
                body_preview=response.text[:500],
            )
            raise KevFetchError(f"KEV feed HTTP {response.status_code}")

        new_etag = response.headers.get("ETag")
        new_lm = response.headers.get("Last-Modified")
        return _HttpFeedResult(
            not_modified=False,
            body=response.content,
            etag=new_etag,
            last_modified=new_lm,
        )

    def _parse_feed_json(self, body: bytes) -> dict[str, Any]:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KevFeedFormatError(f"KEV feed is not valid UTF-8: {exc}") from exc
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise KevFeedFormatError(f"KEV feed is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise KevFeedFormatError("KEV feed root must be a JSON object")
        return parsed

    def _extract_vulnerabilities(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        raw = data.get("vulnerabilities")
        if not isinstance(raw, list):
            raise KevFeedFormatError("KEV feed missing vulnerabilities array")
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            else:
                raise KevFeedFormatError("vulnerabilities entries must be objects")
        return out

    def _build_identity(self) -> Identity:
        now = datetime.now(UTC)
        return Identity(
            id=f"identity--{uuid.uuid4()}",
            created=now,
            modified=now,
            name="Cybersecurity and Infrastructure Security Agency",
            identity_class="organization",
            description="United States Cybersecurity and Infrastructure Security Agency (CISA).",
        )

    def _external_reference_for_cve(self, cve_id: str) -> ExternalReference:
        return ExternalReference(
            source_name="cve",
            external_id=cve_id,
            url=f"https://www.cve.org/CVERecord?id={cve_id}",
            description=f"CVE record for {cve_id}",
        )

    def _build_vulnerability(self, entry: dict[str, Any]) -> Vulnerability:
        if self._identity is None:
            msg = "identity not initialised"
            raise RuntimeError(msg)
        cve_id = entry.get("cveID")
        if not isinstance(cve_id, str) or not cve_id.strip():
            raise KevFeedFormatError("KEV entry missing cveID")

        short_desc = entry.get("shortDescription")
        description = short_desc if isinstance(short_desc, str) else ""

        added_raw = entry.get("dateAdded")
        if not isinstance(added_raw, str):
            raise KevFeedFormatError(f"KEV entry {cve_id!r} missing dateAdded")
        try:
            added = _kev_date_to_utc_datetime(added_raw)
        except ValueError as exc:
            raise KevFeedFormatError(f"KEV entry {cve_id!r} has invalid dateAdded") from exc

        due = entry.get("dueDate")
        due_s = due if isinstance(due, str) else ""
        req = entry.get("requiredAction")
        req_s = req if isinstance(req, str) else ""
        rw = entry.get("knownRansomwareCampaignUse")
        rw_s = rw if isinstance(rw, str) else ""

        return Vulnerability(
            id=f"vulnerability--{uuid.uuid4()}",
            created=added,
            modified=added,
            created_by_ref=self._identity.id,
            name=cve_id,
            description=description,
            external_references=[self._external_reference_for_cve(cve_id)],
            extensions={
                "x_kev_due_date": due_s,
                "x_kev_required_action": req_s,
                "x_kev_known_ransomware_use": rw_s,
            },
        )

    def _build_indicator(self, entry: dict[str, Any], vuln: Vulnerability) -> Indicator:
        if self._identity is None:
            msg = "identity not initialised"
            raise RuntimeError(msg)
        cve_id = entry.get("cveID")
        if not isinstance(cve_id, str) or not cve_id.strip():
            raise KevFeedFormatError("KEV entry missing cveID")

        added_raw = entry.get("dateAdded")
        if not isinstance(added_raw, str):
            raise KevFeedFormatError(f"KEV entry {cve_id!r} missing dateAdded")
        try:
            added = _kev_date_to_utc_datetime(added_raw)
        except ValueError as exc:
            raise KevFeedFormatError(f"KEV entry {cve_id!r} has invalid dateAdded") from exc

        return indicator(
            name=f"KEV: {cve_id}",
            pattern=f"[vulnerability:name = '{cve_id}']",
            pattern_type="stix",
            indicator_types=["malicious-activity"],
            valid_from=added,
            confidence=100,
            created_by_ref=self._identity.id,
        )

    def _build_relationship(self, ind: Indicator, vuln: Vulnerability) -> Relationship:
        if self._identity is None:
            msg = "identity not initialised"
            raise RuntimeError(msg)
        return relationship(
            ind,
            "indicates",
            vuln,
            created_by_ref=self._identity.id,
        )
