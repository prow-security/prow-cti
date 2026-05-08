# Prow Project Knowledge — README

Index of the files in this Claude Project's knowledge. Read this first.

## Files

| File | Purpose | Update cadence |
|---|---|---|
| `00_PROJECT_INSTRUCTIONS.md` | Mirror of the Project's custom instructions. Behavioral context for Claude. | When tone or workflow changes |
| `01_ARCHITECTURE.md` | Load-bearing technical decisions. The canonical "what and why" reference. | When an architectural decision changes (also add an ADR) |
| `02_CONNECTOR_SDK.md` | The connector framework spec. The most important DX surface in the project. | When the SDK contract evolves |
| `03_GLOSSARY.md` | STIX/TAXII/MITRE/CTI terminology. Domain primer. | Rarely; when a new term becomes load-bearing |
| `04_DECISION_LOG.md` | ADR-style decision log. Append-only history of architectural calls. | Append a new ADR per decision; never edit existing entries |
| `05_ROADMAP_STATUS.md` | Operational view: where we are, what's next, milestones. | Frequently as work progresses |

## How to use these files

**Architecture and SDK files are the source of truth.** If a conversation
proposes something that conflicts with `01_ARCHITECTURE.md` or
`02_CONNECTOR_SDK.md`, that's a decision point — surface it explicitly.
Either update the document (and add an ADR) or rework the proposal.

**The decision log is append-only.** Reverse a decision by adding a new
ADR that explicitly supersedes the old one. Don't edit ADR-0001 to
"just change our minds" — write ADR-0011 saying so.

**The roadmap is a living document.** Update it freely as scope and dates
shift. It's the operational tracker.

**The glossary is for Claude's grounding.** When a question uses a term
ambiguously (e.g. "connector" — connector-as-Python-package vs
connector-as-running-instance), the glossary should resolve it.

## What's deliberately NOT in here

- **Code.** The repo is the source of truth for code. Project knowledge
  holds intent and contracts, not implementation.
- **Other DaCosta Consulting projects.** LotWire, Archor, client work
  belong in their own contexts.
- **Sensitive secrets.** API keys, credentials, internal-only info don't
  go in project knowledge — they go in environment configs that never
  enter the chat.

## When to update what

- Made a real architectural call → ADR in `04_DECISION_LOG.md` + update
  to `01_ARCHITECTURE.md`
- Changed the connector contract → update `02_CONNECTOR_SDK.md` + ADR
- Shipped a milestone or shifted scope → update `05_ROADMAP_STATUS.md`
- Decided how Claude should engage differently → update
  `00_PROJECT_INSTRUCTIONS.md` and the live Project instructions
- Encountered a CTI term that keeps coming up unfamiliar → add to
  `03_GLOSSARY.md`
