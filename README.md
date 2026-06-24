# pranavpy

A small practice CLI tool built with [Typer](https://typer.tiangolo.com/), created to learn
how Python command-line apps are structured, packaged, tested, and published to PyPI.

It does one thing: greets you by name.

```bash
$ pranavpy --name Alice
Hello Alice!
```

## Why this project exists

This is a learning sandbox for the full lifecycle of a Python CLI app:

- Structuring a project with a `src/` layout and `pyproject.toml`
- Building a CLI with Typer
- Packaging with [Hatchling](https://hatch.pypa.io/) + `python -m build`
- Testing with `pytest` and Typer's built-in `CliRunner`
- Publishing to (Test)PyPI with `twine`

## Project layout

```text
pranavpy/
├── pyproject.toml          # project metadata, dependencies, build config
├── makefile                # shortcuts for install/test/build/publish
├── README.md
├── src/
│   └── pranavpy/
│       ├── __init__.py
│       └── cli.py          # the Typer app
└── tests/
    └── test_cli.py
```

The entry point is wired up in `pyproject.toml`:

```toml
[project.scripts]
pranavpy = "pranavpy.cli:app"   # the `pranavpy` command calls app() in cli.py
```

## Requirements

- Python 3.10+

## Getting started

Create a virtual environment and install the project in **editable mode** with dev tools:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Editable mode (`-e`) means edits to `cli.py` take effect immediately — no reinstall needed.

## Usage

```bash
pranavpy --name Alice      # Hello Alice!
pranavpy --help            # show all options
```

The `--name` option is required; running `pranavpy` with no arguments exits with an error.

### Easter egg 🥚

Run it with `--name Pranav` (case-insensitive) and it prints a little ASCII-art banner of the
creator's name before the greeting:

```bash
$ pranavpy --name Pranav

        ██████  ██████   █████  ███    ██  █████  ██    ██
        ██   ██ ██   ██ ██   ██ ████   ██ ██   ██ ██    ██
        ██████  ██████  ███████ ██ ██  ██ ███████ ██    ██
        ██      ██   ██ ██   ██ ██  ██ ██ ██   ██  ██  ██
        ██      ██   ██ ██   ██ ██   ████ ██   ██   ████

Hello Pranav!
```

## Development

This repo uses a `makefile` for common tasks:

| Command             | What it does                                       |
| ------------------- | -------------------------------------------------- |
| `make install`      | Install the package + dev dependencies (editable)  |
| `make test`         | Run the test suite with `pytest`                   |
| `make clean`        | Remove `dist/` and build artifacts                 |
| `make build`        | Clean, test, build the wheel/sdist, and check them |
| `make publish`      | Build and upload to PyPI                            |
| `make publish-test` | Build and upload to TestPyPI                        |

### Running tests

```bash
make test
# or directly:
pytest
```

Tests use Typer's `CliRunner`, which invokes the app in-process (no subprocess needed):

```python
from typer.testing import CliRunner
from pranavpy.cli import app

runner = CliRunner()

def test_main():
    result = runner.invoke(app, ["--name", "Alice"])
    assert result.exit_code == 0
    assert "Hello Alice" in result.output
```

## Building & publishing

The build reads `pyproject.toml` and produces two files in `dist/`:

- `.whl` (wheel) — a zip of the package, what `pip` actually installs
- `.tar.gz` (sdist) — the raw source, a fallback for platforms without a wheel

Release checklist:

```bash
# 1. Bump the version in pyproject.toml
# 2. Make sure tests pass
pytest

# 3. Clean old builds, build, and verify
make build          # runs clean + test + build + twine check

# 4. Try it on TestPyPI first (separate account at test.pypi.org)
make publish-test

# 5. Publish for real
make publish
```

Installing a published version for end users (no dev tools needed):

```bash
pipx install pranavpy
```

## License

Practice project — not intended for distribution.
