# Prow — Glossary & Domain Primer

Reference for STIX, TAXII, MITRE, and CTI terminology used throughout the
project. When in doubt about a term, this is the source of truth for prow.

## STIX 2.1

**STIX (Structured Threat Information Expression)** — OASIS standard for
expressing cyber threat intelligence. JSON-based. Current version is 2.1
(Errata 01 published April 2025). Prow is STIX 2.1 native.

**STIX Object types:**

- **SDO (STIX Domain Object)** — high-level intelligence objects:
  `attack-pattern`, `campaign`, `course-of-action`, `grouping`, `identity`,
  `incident`, `indicator`, `infrastructure`, `intrusion-set`, `location`,
  `malware`, `malware-analysis`, `note`, `observed-data`, `opinion`,
  `report`, `threat-actor`, `tool`, `vulnerability`.

- **SCO (STIX Cyber-observable Object)** — observable artefacts:
  `artifact`, `autonomous-system`, `directory`, `domain-name`, `email-addr`,
  `email-message`, `file`, `ipv4-addr`, `ipv6-addr`, `mac-addr`, `mutex`,
  `network-traffic`, `process`, `software`, `url`, `user-account`,
  `windows-registry-key`, `x509-certificate`. SCOs have deterministic IDs
  derived from their content.

- **SRO (STIX Relationship Object)** — edges between objects. Two kinds:
  generic `relationship` with a `relationship_type` (e.g. `indicates`,
  `attributed-to`, `targets`, `uses`, `mitigates`), and `sighting` which
  records that an indicator was observed.

- **SMO (STIX Meta Object)** — metadata: `marking-definition` (TLP and
  statement markings), `language-content`, granular markings, extensions.

**Bundle** — a STIX Bundle is a JSON wrapper containing multiple STIX
objects. Bundles are the over-the-wire transport unit.

**Indicator pattern** — STIX 2.1 indicators carry a `pattern` field using
the STIX Patterning language (or an alternative `pattern_type` like
`snort`, `yara`, `sigma`, `pcre`). Example STIX pattern:
`[file:hashes.'SHA-256' = 'aec...']`.

**Versioning** — STIX objects carry `created` and `modified`. New versions
share the same `id` but increment `modified`. SCOs are not versioned.

**`created_by_ref`** — points to the `identity` SDO that created the object.
Re-publishing without modification preserves `created_by_ref`. Modifying
content requires a new `id` and new `created_by_ref`.

## TAXII 2.1

**TAXII (Trusted Automated Exchange of Intelligence Information)** — the
transport protocol for STIX. REST API over HTTPS. Current version 2.1.

**Key concepts:**
- **Discovery** — root endpoint that advertises available API roots.
- **API root** — collection of related collections, often per-trust-group.
- **Collection** — a logical grouping of objects (e.g. "phishing-indicators").
- **Channel** — pub/sub style, less commonly implemented than collections.

Prow ships a TAXII 2.1 server (so other tools pull from prow) and a TAXII
2.1 client (so prow pulls from other servers) starting v1.0.

## MITRE frameworks

**ATT&CK** — knowledge base of adversary tactics (the why) and techniques
(the how) observed in real-world attacks. Distributed as STIX 2.1 by MITRE.
Hierarchy: Matrices → Tactics → Techniques → Sub-techniques. Also covers
Groups (threat actors), Software (malware/tools), Mitigations, Data Sources.

**CAPEC** — Common Attack Pattern Enumeration and Classification. Catalog
of attack patterns. Distributed as STIX. Maps to ATT&CK techniques.

**D3FEND** — defensive countermeasures knowledge base. Counterpart to
ATT&CK. Less commonly integrated.

## TLP (Traffic Light Protocol)

Standardized markings for how intelligence may be shared:

- **TLP:RED** — recipients only, no further distribution.
- **TLP:AMBER** — limited distribution within recipient organization.
- **TLP:AMBER+STRICT** — recipient organization only, no third parties.
- **TLP:GREEN** — community-wide, not public.
- **TLP:CLEAR** (formerly TLP:WHITE) — unrestricted.

Prow propagates TLP through the enricher chain. Outbound sharing (TAXII,
exports, webhooks) respects TLP and refuses to publish TLP:RED externally
without explicit override.

## Confidence scoring

STIX 2.1 has a `confidence` property (integer 0–100) on most SDOs. Prow
distinguishes:

- **Source confidence** — what the connector or upstream feed asserts.
- **Computed confidence** — what prow's enricher chain assigns based on
  source trust, corroboration across feeds, age, and configurable rules.

Both are stored. Computed confidence is what's used for default filters
and downstream exports.

## CTI workflow concepts

**IOC (Indicator of Compromise)** — observable evidence of an intrusion.
Hashes, IPs, domains, URLs, registry keys. In STIX, expressed via
indicators with patterns over SCOs.

**TTP (Tactics, Techniques, and Procedures)** — adversary behaviors.
Mapped to ATT&CK tactics/techniques.

**Pyramid of Pain** — David Bianco's model ranking indicator types by how
much they hurt the adversary when blocked: hashes (trivial to change) <
IPs < domains < network/host artefacts < tools < TTPs (forces adversary
to retool). Higher-pain indicators are more durable intel.

**Diamond Model** — analytic framework for intrusion analysis with four
vertices: Adversary, Capability, Infrastructure, Victim.

**Kill Chain** — Lockheed Martin's intrusion phase model:
Reconnaissance → Weaponization → Delivery → Exploitation → Installation →
Command & Control → Actions on Objectives.

## Relevant feeds and platforms

- **MISP** — Malware Information Sharing Platform. AGPL-3.0. Event-centric,
  PHP. The dominant fully-OSS sharing platform. Strong at correlation and
  feed ingestion.
- **OpenCTI** — by Filigran. Open-core (Apache 2.0 CE + commercial EE).
  Knowledge-graph centric, STIX 2.1 native, modern stack but heavyweight.
- **abuse.ch** — runs URLhaus, ThreatFox, MalwareBazaar, Feodo Tracker,
  SSLBL. The single most important free-feed source for prow's v0.2.
- **AlienVault OTX / LevelBlue** — community pulse-based platform. Now
  owned by LevelBlue (AT&T spinoff). Generous free tier but ecosystem
  pull toward AT&T USM.
- **MITRE CTI repo** — STIX 2.1 distribution of ATT&CK and CAPEC.
- **CISA KEV** — Known Exploited Vulnerabilities. JSON, no auth, ideal
  walking-skeleton feed.
- **Spamhaus DROP/EDROP** — IP blocklists.
- **PhishTank, OpenPhish** — phishing URL feeds.

## Acronyms cheat sheet

| Acronym | Expansion |
|---|---|
| CTI | Cyber Threat Intelligence |
| TIP | Threat Intelligence Platform |
| IOC | Indicator of Compromise |
| TTP | Tactics, Techniques, and Procedures |
| SDO/SCO/SRO/SMO | STIX Domain / Cyber-observable / Relationship / Meta Object |
| TLP | Traffic Light Protocol |
| TAXII | Trusted Automated Exchange of Intelligence Information |
| STIX | Structured Threat Information Expression |
| SOC | Security Operations Center |
| SIEM | Security Information and Event Management |
| SOAR | Security Orchestration, Automation, and Response |
| EDR | Endpoint Detection and Response |
| KEV | Known Exploited Vulnerabilities (CISA) |
| ATT&CK | Adversarial Tactics, Techniques, and Common Knowledge (MITRE) |
| CAPEC | Common Attack Pattern Enumeration and Classification |
| CVE | Common Vulnerabilities and Exposures |
| OASIS CTI TC | OASIS Cyber Threat Intelligence Technical Committee |
