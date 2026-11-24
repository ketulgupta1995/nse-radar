"""Ask Claude through the owner's Pro login using the local `claude -p` (SPEC §11)."""

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable

from app.ai.base import AIError, AIProvider, register_provider
from app.jobs.context import StopRequested

log = logging.getLogger("ai.claude_cli")

STRIPPED_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
)
AVAILABLE_TTL_S = 60.0


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:  # noqa: BLE001
        log.warning("claude process did not exit cleanly after kill")


def _parse(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except ValueError:
        raise AIError("claude returned something that is not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("result"), str):
        raise AIError("claude's JSON had no 'result' text")
    if data.get("is_error"):
        raise AIError(f"claude reported an error: {data['result'][:300]}")
    return data["result"]


class ClaudeCli(AIProvider):
    name = "claude_cli"
    label = "Claude (your Pro plan, local claude command)"

    def __init__(self) -> None:
        self._cache: tuple[float, tuple[bool, str]] | None = None

    def available(self) -> tuple[bool, str]:
        now = time.monotonic()
        if self._cache and now - self._cache[0] < AVAILABLE_TTL_S:
            return self._cache[1]
        self._cache = (now, self._probe())
        return self._cache[1]

    def _probe(self) -> tuple[bool, str]:
        if not shutil.which("claude"):
            return False, "the 'claude' command was not found on PATH"
        try:
            r = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=15, env=child_env()
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"could not run claude: {e}"
        if r.returncode != 0:
            return False, (r.stderr.strip() or "claude --version failed")[-200:]
        return True, r.stdout.strip()

    def ask(
        self, prompt: str, *, model: str, timeout_s: int, stop_check: Callable[[], bool] | None = None
    ) -> str:
        # `--tools ""` disables every tool (docs/DATA_SOURCES.md, T044).
        cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", ""]
        with tempfile.TemporaryDirectory(prefix="ai_") as cwd:
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, cwd=cwd, env=child_env(), start_new_session=True,
                )  # fmt: skip
            except OSError as e:
                raise AIError(f"could not start claude: {e}") from None
            out, err = self._wait(proc, prompt, timeout_s, stop_check)
        if proc.returncode != 0:
            raise AIError(f"claude exited with code {proc.returncode}: {err.strip()[-500:]}")
        return _parse(out)

    @staticmethod
    def _wait(
        proc: subprocess.Popen, prompt: str, timeout_s: int, stop_check: Callable[[], bool] | None
    ) -> tuple[str, str]:
        deadline = time.monotonic() + timeout_s
        pending: str | None = prompt
        while True:
            if stop_check and stop_check():
                _kill_group(proc)
                raise StopRequested()
            left = deadline - time.monotonic()
            if left <= 0:
                _kill_group(proc)
                raise AIError(f"claude took longer than {timeout_s} s and was stopped")
            try:
                return proc.communicate(pending, timeout=min(0.5, left))
            except subprocess.TimeoutExpired:
                pending = None  # stdin was already written; later calls only wait
            except BrokenPipeError:
                pending = None


register_provider(ClaudeCli())
