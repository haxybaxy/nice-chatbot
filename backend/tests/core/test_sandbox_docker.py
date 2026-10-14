"""``DockerSandboxClient``: the CLI plumbing against a fake ``docker`` script, and one real-Docker check.

The fake ``docker`` executes the requested interpreter on the host, so stdin feeding, bounded
output capture, exit codes, timeouts and cancellation are all exercised offline. The real
container test runs only with a Docker daemon and the image present (``-m docker``).
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from app.core.exceptions import AppError
from app.core.sandbox import EXIT_CANCELLED, EXIT_TIMED_OUT, DockerSandboxClient, SandboxRun, default_sandbox_client
from app.core.ui_stream import CancelToken

IMAGE = "python:3.13-slim"


@pytest.fixture
def fake_docker(tmp_path: Path) -> str:
    """A ``docker`` stand-in: ``docker run ... IMAGE python -`` runs the host interpreter on stdin."""
    script = tmp_path / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "kill" ]; then exit 0; fi\n'
        "while [ $# -gt 2 ]; do shift; done\n"
        f'if [ "$1" = "python" ]; then exec "{sys.executable}" -; fi\n'
        "exec /bin/bash -s\n"
    )
    script.chmod(0o700)
    return str(script)


def _client(docker: str, **overrides: int) -> DockerSandboxClient:
    options: dict[str, object] = {
        "image": IMAGE,
        "max_timeout_s": 120,
        "memory": "512m",
        "cpus": "1",
        "pids_limit": 128,
        "max_output_bytes": 65_536,
        "docker_path": docker,
    }
    options.update(overrides)
    return DockerSandboxClient(**options)  # pyright: ignore[reportArgumentType] — test shorthand


class TestWithFakeDocker:
    async def test_python_stdout_stderr_and_exit_code(self, fake_docker: str) -> None:
        result = await _client(fake_docker).run(
            SandboxRun(
                language="python",
                code="import sys\nprint(17*23)\nprint('warn', file=sys.stderr)\nsys.exit(3)",
                timeout_s=10,
            )
        )
        assert (result.stdout, result.stderr, result.exit_code) == ("391\n", "warn\n", 3)
        assert result.duration_ms >= 0
        assert (result.truncated, result.timed_out) == (False, False)

    async def test_bash(self, fake_docker: str) -> None:
        result = await _client(fake_docker).run(SandboxRun(language="bash", code="echo hi; exit 7", timeout_s=10))
        assert (result.stdout, result.exit_code) == ("hi\n", 7)

    async def test_output_is_capped(self, fake_docker: str) -> None:
        result = await _client(fake_docker, max_output_bytes=1000).run(
            SandboxRun(language="python", code="print('x' * 100000)", timeout_s=10)
        )
        assert len(result.stdout) == 1000
        assert result.truncated is True
        assert result.exit_code == 0

    async def test_timeout_kills_the_program(self, fake_docker: str) -> None:
        result = await _client(fake_docker).run(
            SandboxRun(language="python", code="import time\nprint('start', flush=True)\ntime.sleep(30)", timeout_s=1)
        )
        assert result.timed_out is True
        assert result.exit_code == EXIT_TIMED_OUT
        assert result.stdout == "start\n"
        assert result.duration_ms < 10_000

    async def test_timeout_is_clamped_to_the_maximum(self, fake_docker: str) -> None:
        result = await _client(fake_docker, max_timeout_s=1).run(
            SandboxRun(language="python", code="import time\ntime.sleep(30)", timeout_s=120)
        )
        assert result.timed_out is True

    async def test_cancel_kills_the_program(self, fake_docker: str) -> None:
        cancel = CancelToken()

        async def _cancel_soon() -> None:
            await asyncio.sleep(0.2)
            cancel.request("user")

        canceller = asyncio.ensure_future(_cancel_soon())
        result = await _client(fake_docker).run(
            SandboxRun(language="python", code="import time\ntime.sleep(30)", timeout_s=30), cancel=cancel
        )
        await canceller
        assert result.exit_code == EXIT_CANCELLED
        assert result.timed_out is False

    async def test_docker_start_failure_is_a_service_error(self, tmp_path: Path) -> None:
        failing = tmp_path / "docker"
        failing.write_text("#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 125\n")
        failing.chmod(0o700)
        with pytest.raises(AppError) as error:
            await _client(str(failing)).run(SandboxRun(language="python", code="print(1)", timeout_s=5))
        assert error.value.status_code == 503
        assert error.value.message == "Code execution environment unavailable"


def test_default_client_is_disabled_in_the_test_environment() -> None:
    assert default_sandbox_client() is None


async def _real_docker_ready() -> str | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = await asyncio.create_subprocess_exec(
        docker, "image", "inspect", IMAGE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return docker if await probe.wait() == 0 else None


@pytest.mark.docker
async def test_real_container_has_no_network_and_returns_output() -> None:
    docker = await _real_docker_ready()
    if docker is None:
        pytest.skip(f"docker daemon with {IMAGE} not available")
    client = _client(docker)
    ok = await client.run(SandboxRun(language="python", code="print(sum(range(10)))", timeout_s=30))
    assert (ok.stdout, ok.exit_code) == ("45\n", 0)
    offline = await client.run(
        SandboxRun(
            language="python", code="import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)", timeout_s=30
        ),
    )
    assert offline.exit_code != 0
