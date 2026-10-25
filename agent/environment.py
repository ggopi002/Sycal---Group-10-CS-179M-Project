""" runs every command as `bash -c <command>`

"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment

_WINDOWS_GIT_BASH = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
)


def find_bash() -> str:
    if override := os.environ.get("SYCAL_BASH"):
        return override
    if os.name == "nt":
        for candidate in _WINDOWS_GIT_BASH:
            if candidate.is_file():
                return str(candidate)
        found = shutil.which("bash")
        # C:\Windows\System32\bash.exe is WSL, which can't see this venv's python.
        if found and "system32" not in found.lower():
            return found
        raise RuntimeError("Git Bash not found. Install Git for Windows or set SYCAL_BASH to bash.exe.")
    return shutil.which("bash") or "/bin/bash"


class BashEnvironment(LocalEnvironment):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bash = find_bash()

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = action.get("command", "")
        try:
            result = subprocess.run(
                [self.bash, "-c", command],
                cwd=cwd or self.config.cwd or os.getcwd(),
                env=os.environ | self.config.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.config.timeout,
            )
            output = {"output": result.stdout, "returncode": result.returncode, "exception_info": ""}
        except subprocess.TimeoutExpired as e:
            partial = e.output.decode("utf-8", "replace") if isinstance(e.output, bytes) else (e.output or "")
            output = {
                "output": partial,
                "returncode": -1,
                "exception_info": f"Command timed out after {e.timeout} seconds.",
                "extra": {"exception_type": "TimeoutExpired"},
            }
        self._check_finished(output)
        return output
