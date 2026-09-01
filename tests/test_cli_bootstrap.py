from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_restarts_through_project_venv_when_base_python_lacks_dependencies() -> None:
    result = subprocess.run(
        [sys._base_executable, "-m", "backend.cli", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "EXANTE scenario chat" in result.stdout
