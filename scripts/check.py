"""Run portable project checks and save machine-readable verification evidence."""
from __future__ import annotations

import argparse
import ast
import json
import platform
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    """Run all checks without changing services, packages or real server files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shellcheck", default=shutil.which("shellcheck"))
    parser.add_argument("--bash", default=shutil.which("bash"))
    options = parser.parse_args()
    if not options.shellcheck or not options.bash:
        parser.error("Both --shellcheck and --bash must identify installed check tools")
    root = Path(__file__).resolve().parents[1]
    for source in [*root.glob("scmanager/*.py"), *root.glob("scripts/*.py"), root / "launch_gui.py"]:
        ast.parse(source.read_text(encoding="utf-8"), feature_version=(3, 10))
    temporary = root / ".test-tmp"
    temporary.mkdir(exist_ok=True)
    commands = {
        "shellcheck": [options.shellcheck, "-x", "shadowsocks-c-manager.sh", "launch_gui.sh", "scripts/setup.sh", "scripts/run_tests.sh"],
        "bash_syntax": [options.bash, "-c", 'for script in *.sh lib/*.sh scripts/*.sh; do bash -n "$script" || exit; done'],
        "ruff": [sys.executable, "-m", "ruff", "check", "."],
        "mypy": [sys.executable, "-m", "mypy", "scmanager"],
        "pytest": [sys.executable, "-m", "pytest", "-q", "--basetemp=.test-tmp/check-" + uuid.uuid4().hex[:10],
                   "--junitxml=docs/test-results.xml"],
        "gui_render": [sys.executable, "scripts/render_preview.py"],
    }
    results: dict[str, dict[str, object]] = {}
    for name, arguments in commands.items():
        process = subprocess.run(arguments, cwd=root, capture_output=True, text=True, timeout=300)
        results[name] = {"exit_code": process.returncode, "status": "PASS" if process.returncode == 0 else "FAIL"}
        print(f"{name}: {results[name]['status']}", flush=True)
        if process.returncode:
            print(process.stdout + process.stderr)
    xml_path = root / "docs" / "test-results.xml"
    if xml_path.exists():
        tree = ET.parse(xml_path)
        for element in tree.iter():
            element.attrib.pop("hostname", None)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        suite = tree.getroot().find("testsuite")
        if suite is not None:
            results["pytest"]["counts"] = {key: suite.get(key) for key in ("tests", "failures", "errors", "skipped")}
    report = {"date": "2026-11-20", "platform": platform.system(), "python": platform.python_version(),
              "checks": results, "ubuntu_integration": "NOT EXECUTED", "remote_relay": "NOT EXECUTED",
              "mobaxterm_x11": "NOT EXECUTED"}
    (root / "docs" / "TEST_EXECUTION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(item["exit_code"] == 0 for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
