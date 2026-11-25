# Contributing

Keep every new capability tied to an inspected immutable upstream revision.
Add behavior tests for compatibility mappings and compensation failures. Never
use production hosts for destructive tests. Keep source configs byte-for-byte
unchanged during migration. Unknown options must fail closed.

Install requirements-dev.txt in a private venv and run scripts/run_tests.sh.
Changes to service hardening or platform support also require isolated Ubuntu
integration evidence. Record executed and unexecuted checks separately.
Do not commit real configs, backups, logs, virtual environments or credentials.
