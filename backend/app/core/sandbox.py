"""Code execution for the ``run_code`` tool — one throwaway Docker container per execution.

``SandboxClient`` is the seam; ``DockerSandboxClient`` shells out to the ``docker`` CLI with a
hardened ``run`` (no network, memory/CPU/pid caps, read-only root with a small ``/tmp``, all
capabilities dropped, unprivileged user), feeds the program on stdin, caps what it reads back and
kills the container on timeout or cancel. A non-zero exit is a *result*, not an error.

Security posture: mounting the Docker socket into the worker is root-equivalent on the host, so
``SANDBOX_BACKEND=docker`` is for local development. Production runs a dedicated sandbox host
(rootless Docker / gVisor) or a hosted adapter (E2B, Daytona, Modal) implementing ``run()``.
Out of v1: files in/out, package installs, sessions, network.
"""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from asyncio.subprocess import PIPE, Process
from dataclasses import dataclass
from functools import cache
from typing import Literal, Protocol

from app.core.config import sandbox_settings
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.core.ui_stream import CancelToken

logger = get_logger(__name__)

type SandboxLanguage = Literal["python", "bash"]
_INTERPRETERS: dict[SandboxLanguage, tuple[str, ...]] = {"python": ("python", "-"), "bash": ("bash", "-s")}
# Extra time for the container to start and for `docker` to report the exit code.
_GRACE_S = 2.0
_KILL_WAIT_S = 10.0
_READ_CHUNK = 64 * 1024
# `docker run` exit codes that mean the container never ran the program (daemon down, image missing).
_DOCKER_FAILURE_CODES = frozenset({125, 126, 127})
EXIT_TIMED_OUT = 124
EXIT_CANCELLED = 130
# (stdin fed, (stdout, truncated), (stderr, truncated), exit code)
type _Collected = tuple[None, tuple[bytes, bool], tuple[bytes, bool], int]


@dataclass(frozen=True, slots=True)
class SandboxRun:
    language: SandboxLanguage
    code: str
    timeout_s: int


@dataclass(frozen=True, slots=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool
    timed_out: bool


class SandboxClient(Protocol):
    async def run(self, run: SandboxRun, *, cancel: CancelToken | None = None) -> SandboxResult: ...


# ── Docker ───────────────────────────────────────────────────────────────────


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> tuple[bytes, bool]:
    """Drain ``stream`` to EOF keeping at most ``cap`` bytes (the child never blocks on a full pipe)."""
    if stream is None:
        return b"", False
    kept = bytearray()
    truncated = False
    while chunk := await stream.read(_READ_CHUNK):
        room = cap - len(kept)
        if room > 0:
            kept.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True
    return bytes(kept), truncated


async def _feed_stdin(process: Process, code: str) -> None:
    if process.stdin is None:
        return
    try:
        process.stdin.write(code.encode("utf-8"))
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the program exited without reading its input
    finally:
        process.stdin.close()


class DockerSandboxClient:
    """``SandboxClient`` over the ``docker`` CLI."""

    def __init__(
        self,
        *,
        image: str,
        max_timeout_s: int,
        memory: str,
        cpus: str,
        pids_limit: int,
        max_output_bytes: int,
        docker_path: str | None = None,
    ) -> None:
        self._image = image
        self._max_timeout_s = max_timeout_s
        self._memory = memory
        self._cpus = cpus
        self._pids_limit = pids_limit
        self._max_output_bytes = max_output_bytes
        self._docker_path = docker_path

    def _docker(self) -> str:
        path = self._docker_path or shutil.which("docker")
        if path is None:
            raise AppError.service_unavailable("Code execution is unavailable: docker CLI not found")
        self._docker_path = path
        return path

    def _command(self, docker: str, name: str, language: SandboxLanguage) -> list[str]:
        return [
            docker,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--memory",
            self._memory,
            "--memory-swap",
            self._memory,
            "--cpus",
            self._cpus,
            "--pids-limit",
            str(self._pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108 — the container's tmpfs, not a host path
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",  # noqa: S108 — inside the container
            "--env",
            "HOME=/tmp",
            "--name",
            name,
            self._image,
            *_INTERPRETERS[language],
        ]

    async def _kill(self, docker: str, name: str, process: Process) -> None:
        killer = await asyncio.create_subprocess_exec(
            docker, "kill", name, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=PIPE
        )
        await killer.wait()
        if process.returncode is None:
            process.kill()

    async def run(self, run: SandboxRun, *, cancel: CancelToken | None = None) -> SandboxResult:
        docker = self._docker()
        name = f"sbx-{uuid.uuid4().hex}"
        timeout_s = max(1, min(run.timeout_s, self._max_timeout_s))
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *self._command(docker, name, run.language), stdin=PIPE, stdout=PIPE, stderr=PIPE
        )
        collect: asyncio.Future[_Collected] = asyncio.ensure_future(
            asyncio.gather(
                _feed_stdin(process, run.code),
                _read_capped(process.stdout, self._max_output_bytes),
                _read_capped(process.stderr, self._max_output_bytes),
                process.wait(),
            )
        )
        waiters: list[asyncio.Future[_Collected] | asyncio.Task[str]] = [collect]
        cancel_waiter: asyncio.Task[str] | None = None
        if cancel is not None:
            cancel_waiter = asyncio.ensure_future(cancel.wait())
            waiters.append(cancel_waiter)
        done, _ = await asyncio.wait(waiters, timeout=timeout_s + _GRACE_S, return_when=asyncio.FIRST_COMPLETED)
        timed_out = collect not in done and (cancel_waiter is None or cancel_waiter not in done)
        cancelled = cancel_waiter is not None and cancel_waiter in done
        if cancel_waiter is not None and not cancel_waiter.done():
            cancel_waiter.cancel()
        if collect not in done:
            await self._kill(docker, name, process)
            try:
                await asyncio.wait_for(collect, _KILL_WAIT_S)
            except TimeoutError:
                collect.cancel()
                raise AppError.service_unavailable("Code execution could not be stopped", container=name) from None
        _, (out, out_truncated), (err, err_truncated), exit_code = collect.result()
        duration_ms = int((time.monotonic() - started) * 1000)
        stderr = err.decode("utf-8", errors="replace")
        if exit_code in _DOCKER_FAILURE_CODES and not out:
            logger.warning("sandbox failed to start", exit_code=exit_code, stderr=stderr[:500])
            raise AppError.service_unavailable("Code execution environment unavailable", exit_code=exit_code)
        if timed_out:
            exit_code = EXIT_TIMED_OUT
        elif cancelled:
            exit_code = EXIT_CANCELLED
        logger.info(
            "sandbox run", language=run.language, exit_code=exit_code, duration_ms=duration_ms, timed_out=timed_out
        )
        return SandboxResult(
            stdout=out.decode("utf-8", errors="replace"),
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            truncated=out_truncated or err_truncated,
            timed_out=timed_out,
        )


# ── Wiring ───────────────────────────────────────────────────────────────────


@cache
def default_sandbox_client() -> SandboxClient | None:
    """The process sandbox, or ``None`` when ``SANDBOX_BACKEND=disabled`` (``run_code`` hidden)."""
    if sandbox_settings.sandbox_backend == "disabled":
        logger.info("code execution disabled", reason="SANDBOX_BACKEND=disabled")
        return None
    return DockerSandboxClient(
        image=sandbox_settings.sandbox_image,
        max_timeout_s=sandbox_settings.sandbox_max_timeout_s,
        memory=sandbox_settings.sandbox_memory,
        cpus=sandbox_settings.sandbox_cpus,
        pids_limit=sandbox_settings.sandbox_pids_limit,
        max_output_bytes=sandbox_settings.sandbox_max_output_bytes,
    )
