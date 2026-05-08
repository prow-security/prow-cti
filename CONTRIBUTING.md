# Contributing

<!-- Owner: replace this placeholder with contribution guidelines. -->

## Local development setup

Prow CTI requires Python 3.12 or newer. The project's CI runs against
3.12; using an older interpreter locally will work today (the scaffold
is simple) but will break the moment 3.12-only syntax lands.

**Recommended ways to get 3.12+:**

- **macOS / Linux:** `pyenv install 3.12` then `pyenv local 3.12` in
  the project directory.
- **Windows:** the python.org installer, or WSL with pyenv as above.
- **Anywhere:** `uv python install 3.12` if you use uv for version
  management. (The project does not require uv; this is one way to
  get 3.12 if you don't already have it.)

Once 3.12 is available:

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pre-commit install          # if pre-commit hooks are configured
pytest -q
```

If `pip install -e ".[dev]"` fails with a requires-python error,
your active interpreter is below 3.12. Fix that before continuing;
`--ignore-requires-python` is not a supported workflow.

## Getting started

*(Placeholder section.)*

## Development workflow

*(Placeholder section.)*

## Pull requests

*(Placeholder section.)*

## Community

*(Placeholder section.)*
