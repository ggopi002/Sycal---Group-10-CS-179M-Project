""" runs every command as `bash -c <command>`

"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment
from minisweagent.exceptions import Submitted

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
    def __init__(self, *, max_failed_checks: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.bash = find_bash()
        # Retry gate: each fix attempt is a full rewrite of events.json (30-75 s on a local model),
        # and a model that couldn't fix an error once rarely does on the next try.
        self.max_failed_checks = max_failed_checks
        self.failed_checks: list[str] = []

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
        self._check_retries(command, output)
        return output

    def _check_retries(self, command: str, output: dict) -> None:
        """End the run (finalize keeps the good events and flags the rest) when the validator
        fails with the same errors as last time, or has failed max_failed_checks times."""
        text = output.get("output", "")
        if "sycal.validate" not in command or not text.lstrip().startswith("FAIL:"):
            return
        errors = "\n".join(line for line in text.splitlines() if not line.startswith("auto-fixed"))
        repeated = bool(self.failed_checks) and errors == self.failed_checks[-1]
        self.failed_checks.append(errors)
        if repeated or len(self.failed_checks) >= self.max_failed_checks:
            reason = "same errors as the last check" if repeated else f"{len(self.failed_checks)} failed checks"
            raise Submitted(
                {
                    "role": "exit",
                    "content": f"Stopped retrying ({reason}); events with errors are flagged for review.",
                    "extra": {"exit_status": "RetryLimit", "submission": ""},
                }
            )
