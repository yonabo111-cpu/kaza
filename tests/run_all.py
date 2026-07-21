# -*- coding: utf-8 -*-
"""Run every integration suite, each against a freshly booted server.

One command for local use and CI. Each suite is designed to start from an empty
database (they register the same test users), so every suite gets its own
temporary ``DATA_DIR`` and its own server process. Exits non-zero if any suite
fails.

    python tests/run_all.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE_PORT = int(os.environ.get("TEST_PORT", "5099"))

# Suites that exercise the HTTP API — each gets its own freshly booted server.
SUITES = [
    "api_test.py",
    "personal_test.py",
    "recipe_test.py",
    "bulletin_test.py",
    "notif_test.py",
    "security_test.py",
    "monthly_test.py",
    "bills_test.py",
]

# Suites that test standalone modules on their own throwaway data — no server.
UNIT_SUITES = [
    "backup_test.py",
]


def _wait_for_health(port: int, timeout: float = 30.0) -> bool:
    """Poll the health endpoint until it responds or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _stop(server: subprocess.Popen) -> None:
    """Terminate the server process, killing it if it does not exit promptly."""
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()


def _run_suite(suite: str, port: int) -> bool:
    """Boot a fresh server on ``port`` and run one suite. Return True on success."""
    data_dir = tempfile.mkdtemp(prefix="kaza-test-")
    env = {
        **os.environ,
        "DATA_DIR": data_dir,
        "PORT": str(port),
        "KAZA_ENV": "testing",
        "PYTHONIOENCODING": "utf-8",
    }
    server = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], env=env, cwd=ROOT)
    try:
        if not _wait_for_health(port):
            print(f"ERROR: server did not become healthy for {suite}")
            return False
        print(f"\n=== {suite} ===", flush=True)
        suite_env = {**env, "API_BASE": f"http://127.0.0.1:{port}/api"}
        return (
            subprocess.run([sys.executable, os.path.join(HERE, suite)], env=suite_env).returncode
            == 0
        )
    finally:
        _stop(server)
        shutil.rmtree(data_dir, ignore_errors=True)


def _run_unit(suite: str) -> bool:
    """Run a server-less suite directly. Return True on success."""
    print(f"\n=== {suite} ===", flush=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, os.path.join(HERE, suite)], env=env).returncode == 0


def main() -> int:
    """Run all suites; return an exit code (0 = all passed)."""
    failed = [
        suite for index, suite in enumerate(SUITES) if not _run_suite(suite, BASE_PORT + index)
    ]
    failed += [suite for suite in UNIT_SUITES if not _run_unit(suite)]
    if failed:
        print(f"\nFAILED SUITES: {', '.join(failed)}")
        return 1
    print("\nALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
