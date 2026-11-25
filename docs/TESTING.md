# Testing

Install the development dependencies in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
bash scripts/run_tests.sh
```

The check runner requires Bash and ShellCheck. It runs Python syntax, lint,
type and test checks. GUI tests require the dependencies in requirements-gui.txt.

Tests cover configuration validation, backup integrity, recovery behavior,
workflow sequencing, GUI interactions and synthetic X11 environments.
Privileged operations use recording doubles and temporary directories.
These tests do not certify live Ubuntu service changes or TCP/UDP relay.
The Unix symlink test may be skipped on Windows.
