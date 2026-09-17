"""Running a scanner inside a container.

Every real adapter runs its scanner in a container, so a scanner's dependencies
never touch the host and a run is reproducible from a clean checkout.

Two decisions worth stating, because both were tested rather than assumed:

  * The corpus is mounted READ-ONLY. A scanner that wrote to the corpus would
    corrupt the ground truth for every subsequent run, and we would have no way
    to tell that it had. Nothing about scanning requires write access.

  * Scanner containers reach the lab through the gateway at
    `host.docker.internal`, NOT by joining the lab network. Joining it would
    deny the scanner internet access, which several scanners need for
    LLM-as-judge analyzers -- we would be measuring our own network policy
    instead of their detection. Verified reachable.

The egress restriction exists to stop corpus servers exfiltrating. It was never
about the scanners, which are the instruments, not the subjects.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Where the corpus appears inside a scanner container.
CORPUS_MOUNTPOINT = "/corpus"

#: Hostname a scanner container uses to reach the lab gateway.
LAB_HOST = "host.docker.internal"

DEFAULT_TIMEOUT = 900


@dataclass
class ContainerResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    error: str | None = None

    @property
    def combined(self) -> str:
        return self.stdout if not self.stderr else f"{self.stdout}\n{self.stderr}"


@dataclass
class ContainerSpec:
    image: str
    args: list[str] = field(default_factory=list)
    entrypoint: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    mounts: list[tuple[Path, str, str]] = field(default_factory=list)  # (host, dest, mode)
    network: str | None = None
    timeout: int = DEFAULT_TIMEOUT
    workdir: str | None = None
    needs_lab: bool = False


def docker_available() -> tuple[bool, str]:
    try:
        p = subprocess.run(["docker", "info"], capture_output=True,
                           text=True, timeout=30)
    except FileNotFoundError:
        return False, "docker is not installed"
    except subprocess.TimeoutExpired:
        return False, "docker did not respond within 30s"
    if p.returncode != 0:
        return False, "the docker daemon is not running"
    return True, ""


def image_present(image: str) -> bool:
    p = subprocess.run(["docker", "image", "inspect", image],
                       capture_output=True, text=True, timeout=60)
    return p.returncode == 0


def pull_image(image: str, timeout: int = 900) -> tuple[bool, str]:
    try:
        p = subprocess.run(["docker", "pull", image], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"pulling {image} timed out after {timeout}s"
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()[:400]
    return True, ""


def corpus_mount(corpus_dir: Path) -> tuple[Path, str, str]:
    """Mount the corpus read-only. See the module docstring."""
    return (corpus_dir.resolve(), CORPUS_MOUNTPOINT, "ro")


def lab_url(port: int, path: str = "/mcp") -> str:
    """The URL a scanner container uses to reach a lab server."""
    return f"http://{LAB_HOST}:{port}{path}"


def build_command(spec: ContainerSpec) -> list[str]:
    cmd = ["docker", "run", "--rm"]

    # A scanner is under test, not trusted infrastructure.
    cmd += ["--security-opt", "no-new-privileges:true"]

    for host_path, dest, mode in spec.mounts:
        cmd += ["-v", f"{host_path}:{dest}:{mode}"]
    for k, v in sorted(spec.env.items()):
        cmd += ["-e", f"{k}={v}"]
    if spec.workdir:
        cmd += ["-w", spec.workdir]
    if spec.network:
        cmd += ["--network", spec.network]
    if spec.needs_lab:
        cmd += ["--add-host", f"{LAB_HOST}:host-gateway"]
    if spec.entrypoint:
        cmd += ["--entrypoint", spec.entrypoint]

    cmd.append(spec.image)
    cmd += spec.args
    return cmd


def run_container(spec: ContainerSpec) -> ContainerResult:
    ok, reason = docker_available()
    if not ok:
        return ContainerResult(None, "", "", 0.0, error=reason)

    cmd = build_command(spec)
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=spec.timeout)
    except subprocess.TimeoutExpired as exc:
        return ContainerResult(
            None,
            (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            "", time.monotonic() - started, timed_out=True,
            error=f"scanner exceeded {spec.timeout}s and was killed")
    except Exception as exc:
        return ContainerResult(None, "", "", time.monotonic() - started,
                               error=f"{type(exc).__name__}: {exc}")

    return ContainerResult(
        exit_code=p.returncode,
        stdout=p.stdout,
        stderr=p.stderr,
        duration_seconds=time.monotonic() - started,
    )
