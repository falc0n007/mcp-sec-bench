"""sentinel-scan-cli adapter -- Ventrova/sentinel-scan-cli 1.4.16, MIT.

Read docs/scanner-survey.md section 3 before touching this file. Its headline
is the whole design problem: *"CONFIRMED, but it does not scan what we have."*
``sentinel-scan mcp`` takes ``--manifest <mcp.json>`` and nothing else. It
cannot read a source directory and it cannot connect to a live endpoint. Our
corpus is fifteen source directories that also run as fifteen HTTP endpoints,
and it ships no ``mcp.json`` at all.

So this adapter has to *manufacture the scanner's input*, and almost every
decision below is about doing that without measuring our own artifact instead
of the tool.

Why this scanner is on the board
--------------------------------
A2 (rug-pull) is detected by nobody. mcp-guard, Ramparts and Cisco all score
0.00 on it. sentinel-scan-cli ships ``tool_definition_drift`` behind
``--baseline``, which hashes ``(name, description, inputSchema)`` per tool and
flags a tool whose hash moved since the baseline was recorded. That is a
purpose-built rug-pull check and, as of this writing, the only one on the
board. **It works on this corpus** (see "Driving the drift sequence").

What we hand it
---------------
One ``mcp.json`` per server, containing:

  * ``tools`` -- the descriptors **exactly as ``tools/list`` served them**, in
    wire format (``inputSchema``, not ``input_schema``: sentinel's
    ``excessive_agency_schema`` reads ``inputSchema`` first, and relying on its
    fallback spelling would be luck rather than design). Nothing is rewritten,
    renamed or namespaced -- a prefixed tool name would change the input that
    ``tool_name_shadowing``'s edit-distance and normalised-collision routes
    read, which is the one heuristic most sensitive to the exact name text.

  * ``mcpServers`` -- one entry, ``{"url": ..., "headers": ...}``, the real
    shape a client config uses for an HTTP-transport server. Four of the
    eleven heuristics (``hardcoded_credential``, ``unpinned_remote_source``,
    ``missing_provenance``, ``overbroad_tool_scope``) only ever read this
    block, so omitting it would run the tool at seven-elevenths of its
    capability and call the result a measurement. docs/scanner-survey.md asks
    for both blocks for exactly this reason.

**The disclosure that goes with that block, because it changes how the raw
output should be read.** ``unpinned_remote_source`` and ``missing_provenance``
fire on every server in the corpus -- 15 + 15 findings, dominating the output.
They are true statements (the lab genuinely serves plain HTTP, and no corpus
server declares provenance metadata) but they are statements about *how the
lab is deployed and how this adapter writes a config file*, not about any
corpus server's source. Both labels are `unmapped` in
mapping/sentinel-scan-cli.json, so they cost the scanner nothing and earn it
nothing; a reader of the raw output should not read 30 of 40 findings as
detections of planted flaws.

**The credential we decline to plant.** The lab's bearer token goes into the
manifest as the ``${MCPBENCH_TOKEN}`` placeholder, not as a literal. Writing
the literal would make ``hardcoded_credential`` fire on all eleven
authenticated servers; that label maps to A7, and the finding would be a true
positive manufactured by the harness against a credential *we* put in a file
*we* wrote -- including against c01 and c02, which tolerate nothing. The cost
of the placeholder is stated rather than hidden: ``hardcoded_credential``
cannot fire in this configuration at all, and A7's ground truth is a literal
in ``a07-hardcoded-secrets/server.py``, a file this scanner cannot read.

Where the descriptors come from, and therefore which stage this is
------------------------------------------------------------------
``stages = {"runtime"}``. The adapter acts as an MCP client, connects to the
live endpoint and calls ``tools/list``; the scanner itself makes no network
call of any kind. That split is the single most important thing to understand
about this row, so it is stated three ways: here, in
mapping/sentinel-scan-cli.json's notes, and in ``AdapterResult.extra``
(``descriptor_source``).

Declaring ``runtime`` rather than ``static`` is a deliberate choice with a
scoring consequence, and both readings were weighed:

  * The data analysed is the descriptor **as served over the wire**, obtained
    by connecting to and exercising a live endpoint -- including the repeated
    ``tools/list`` calls that provoke a02's mutation. docs/taxonomy.md's
    runtime route for A1/A2/A3 is exactly "the differing descriptors are
    observed across repeated ``tools/list`` calls". Calling that static would
    misdescribe where every finding came from.

  * The scanner never sees a source tree. Declaring ``static`` would claim a
    surface it cannot reach and would score A7, A8, A9 and A10 as five false
    negatives for source it was never shown -- the category error
    docs/scoring.md warns about. Under ``runtime`` those five items are
    ``not_attempted`` and excluded from the denominator instead.

  * The cost is accepted and stated: A4, A5 and A6 *are* scored as false
    negatives. The adapter exercises only ``tools/list``, never a tool call,
    and sentinel-scan-cli reads only descriptors, so it cannot reach a
    return-value payload (A4), an egress attempt (A5) or an auth posture (A6).
    Those are real misses for a scanner given runtime access.

  * A practical fact settles what the two arguments leave balanced. The runner
    restarts the corpus between **runtime** runs and not between static ones
    (runner/execute.py). a02's rug-pull counter lives in the server process
    and never rewinds, so under a static declaration only the first of five
    runs could observe the drift and A2's recall would read 0.2 with range
    [0, 1] -- a number about our harness wearing the costume of scanner
    variance. Under ``runtime`` every run starts from a reset server and the
    drift is observed every time.

Scope: per-server, and verified to cost nothing
-----------------------------------------------
docs/taxonomy.md is explicit that a scanner given one server at a time
structurally cannot detect A3, and that this only counts against the scanner
if the harness did not impose it. Whole-corpus scope is the configuration to
prefer, and the runner's runtime stage hands an adapter one
:class:`RuntimeTarget` at a time, so this adapter scans one server per
invocation and records ``scope = "per-server"``.

That limitation was **tested rather than assumed**. A whole-corpus manifest
(all 15 servers, 42 tools, one flat ``tools`` array) and the union of the 15
per-server manifests produce the **identical finding set** on corpus v1 --
same 40 (heuristic, tool) pairs, both with and without the ``mcpServers``
block. The whole-corpus manifest and its report are committed at
``tests/fixtures/sentinel-scan-cli-whole-corpus-manifest.json`` and
``tests/fixtures/sentinel-scan-cli-whole-corpus-report.json`` so a reader can
check that claim without a lab. Nothing cross-server fires: no
``tool_name_shadowing`` from a normalised-name collision (all 42 corpus tool
names are distinct and none is within edit distance 2 of another), and
a03-tool-shadowing's payload does not match sentinel's shadow-claim regex --
it says "route those calls to this tool instead" where the pattern wants "use
this tool"/"instead of the built-in". **The A3 miss is the scanner's, not the
harness's, and that is a measured statement.**

Driving the drift sequence for A2
---------------------------------
``tool_definition_drift`` needs two captures of the same tool and a recorded
baseline between them, so the adapter drives the whole sequence itself, within
a single run, in this order:

  1. Open one MCP session and call ``tools/list`` ``probe_depth`` times
     (default 6). Keep the first and the last response.
  2. Container pass 1: scan a manifest built from the **first** capture with
     ``--baseline /work/baseline.json --update-baseline``. This records
     ``{tool_name: sha256(name, description, inputSchema)}`` and is also a real
     scan whose findings are kept.
  3. Container pass 2: scan a manifest built from the **last** capture with
     ``--baseline /work/baseline.json`` (no update). Any tool whose hash moved
     between capture 1 and capture ``probe_depth`` is reported as
     ``tool_definition_drift``.
  4. Union the two passes' findings, de-duplicated on
     ``(heuristic, tool, severity, evidence)``, recording in ``raw["phases"]``
     which passes produced each one. Pass 2's finding set is a superset of pass
     1's on this corpus, but the union is taken rather than pass 2 alone so
     that no finding can be dropped by an invocation choice.

``probe_depth`` defaults to 6 and is applied uniformly to all fifteen servers
-- it is not a per-server number read out of a manifest. a02's trigger is the
4th ``tools/list``, recorded in its manifest precisely so the runner can
exercise it: docs/taxonomy.md requires the trigger be deterministic and
documented "so that Stage 2 is reproducible and a scanner is not penalised for
probing a different number of times than we did", and says "the runner
exercises the trigger explicitly". Six is that depth plus headroom, so the
number is not tuned to the exact trigger index. Nothing is carried between
runs: the sequence starts from ``tools/list`` call 1 on a freshly restarted
server every time.

**One consequence of provoking the mutation, disclosed because it costs the
scanner a point.** Once a02's descriptor has flipped, pass 2's manifest
contains the injected text, and ``tool_description_injection`` fires on
``summarize_changelog`` as well. That label maps to A1; a02 declares A2 and
tolerates nothing, so the finding scores as a **false positive and a near miss**
("right server, wrong class"). It exists only because the harness drove the
rug-pull. We do not suppress it: mapping is keyed on the label alone and never
on the server or its state (docs/mapping-rationale.md R5), and an error a
reader can see on a named item is the one to prefer (R6). It is the same
phenomenon A2 credits, reported under an A1-shaped label.

Two more behaviours this adapter absorbs
----------------------------------------
  * **The JSON report is written to a file, never to stdout.** stdout carries
    the summary object, a human-readable finding list and two upsell URLs.
    The adapter therefore mounts a host temp directory read-write at ``/work``
    and reads ``--output`` back from it; it never tries to parse stdout for
    findings. The temp directory is created per invocation and removed after,
    and never points into the repository or the corpus.

  * **``--fail-on none`` is passed explicitly.** The tool's default is already
    ``none``, but stating it makes exit 0 mean "the scan ran" and a non-zero
    exit mean the scanner actually failed (missing manifest, unparseable JSON),
    rather than "some finding crossed a severity threshold". The parser still
    accepts a non-zero exit that produced a readable report, because
    suppressing findings over an exit code would be the worse failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..models import RawFinding
from . import AdapterResult, RuntimeTarget, StaticTarget
from .container import (
    ContainerSpec,
    docker_available,
    image_present,
    run_container,
)

# --------------------------------------------------------------------------
# Pinned build identity. Must match dockerfiles/sentinel-scan-cli.Dockerfile.
# --------------------------------------------------------------------------

#: PyPI release the Dockerfile installs, and the string sentinel-scan-cli
#: reports in summary.version.
SCANNER_VERSION = "1.4.16"

IMAGE = f"mcp-sec-bench/sentinel-scan-cli:{SCANNER_VERSION}"

DOCKERFILE_PATH = Path(__file__).parent / "dockerfiles" / "sentinel-scan-cli.Dockerfile"

BUILD_HINT = (
    f"docker build -f {DOCKERFILE_PATH} -t {IMAGE} "
    f"{DOCKERFILE_PATH.parent}"
)

#: Where the per-invocation temp directory is bind-mounted read-write.
WORK_MOUNTPOINT = "/work"

#: How many `tools/list` calls the adapter makes against each server, uniformly
#: -- not a per-server number read out of a manifest. The deepest documented
#: rug-pull trigger in corpus v1 is the 4th call (a02); 6 clears it with
#: headroom without being the trigger index itself, so the depth is not tuned
#: to one server. See "Driving the drift sequence for A2" in the module
#: docstring for why provoking the trigger is the runner's job.
DEFAULT_PROBE_DEPTH = 6

DEFAULT_CONTAINER_TIMEOUT_SECS = 180
DEFAULT_PROBE_TIMEOUT_SECS = 60

#: How long to wait for a freshly restarted server to finish coming up before
#: giving up on it. The runner restarts the corpus before every runtime run and
#: waits for the TCP port to open, but a FastMCP server accepts a connection
#: slightly before its HTTP app will answer an `initialize` -- observed as
#: "Server disconnected without sending a response" on the first three servers
#: of a run. Without this wait that race reads on a scoreboard as a scanner
#: that found nothing on three servers.
DEFAULT_READY_ATTEMPTS = 15
DEFAULT_READY_DELAY_SECS = 1.0

#: Names of the two scan passes. Recorded on every finding.
PHASE_BASELINE = "baseline"
PHASE_POST_TRIGGER = "post-trigger"

#: In-container filenames. Deliberately free of any corpus server id: the
#: adapter declares `RawFinding.server_id` itself, and a path carrying a server
#: name would give runner.mapping.ServerResolver a second, redundant route to
#: the same answer that looks like evidence and is not.
MANIFEST_BASELINE = "mcp.json"
MANIFEST_POST_TRIGGER = "mcp-post-trigger.json"
BASELINE_HASHES = "baseline.json"
REPORT_BASELINE = "report-baseline.json"
REPORT_POST_TRIGGER = "report-post-trigger.json"

#: The placeholder written in place of the lab bearer token. See the module
#: docstring: a literal here would manufacture `hardcoded_credential`.
TOKEN_PLACEHOLDER = "${MCPBENCH_TOKEN}"


class SentinelManifestError(RuntimeError):
    """The adapter could not obtain the descriptors it needs to build a manifest.

    Raised internally and converted to ``AdapterResult.error``. It is its own
    type because "we could not build the scanner's input" must never be
    reported as "the scanner found nothing": the two are indistinguishable on
    a scoreboard and only one of them is a statement about the vendor.
    """


# --------------------------------------------------------------------------
# Manifest generation (pure; no network, no Docker)
# --------------------------------------------------------------------------


def server_entry(url: str, authenticated: bool) -> dict[str, Any]:
    """One ``mcpServers`` entry for an HTTP-transport MCP server.

    ``url`` is the endpoint as it really is -- plain HTTP on a lab port -- so
    ``unpinned_remote_source``'s plaintext-transport branch fires truthfully
    rather than being dodged. The bearer token is a placeholder; see the module
    docstring for why a literal is refused.
    """
    entry: dict[str, Any] = {"url": url}
    if authenticated:
        entry["headers"] = {"Authorization": f"Bearer {TOKEN_PLACEHOLDER}"}
    return entry


def build_manifest(
    server_id: str,
    url: str,
    authenticated: bool,
    tools: Sequence[dict[str, Any]],
    *,
    capture_index: int | None = None,
    probe_depth: int | None = None,
) -> dict[str, Any]:
    """Build the ``mcp.json`` document handed to the scanner.

    The ``mcpServers`` key is the corpus ``server_id``, which is what
    sentinel-scan-cli puts in the ``tool`` field of every config-level finding
    -- so those findings name the server directly instead of being attributed
    by us.

    ``_mcp_sec_bench`` is provenance metadata for a human reading the committed
    artifact. sentinel-scan-cli reads only ``tools`` and
    ``mcpServers``/``servers``, so an extra top-level key is inert; it is named
    with a leading underscore so it cannot collide with a future key of the
    tool's own.
    """
    provenance: dict[str, Any] = {
        "generated_by": "runner/adapters/sentinel_scan.py",
        "server_id": server_id,
        "descriptor_source": "MCP tools/list over HTTP, verbatim wire format",
        "note": (
            "Generated input. The corpus ships no mcp.json; sentinel-scan-cli "
            "takes a manifest and nothing else. Tool descriptors are unmodified; "
            "the mcpServers block describes the live lab endpoint and the bearer "
            "token is a placeholder, never a literal."
        ),
    }
    if capture_index is not None:
        provenance["tools_list_capture_index"] = capture_index
    if probe_depth is not None:
        provenance["tools_list_probe_depth"] = probe_depth

    return {
        "_mcp_sec_bench": provenance,
        "mcpServers": {server_id: server_entry(url, authenticated)},
        "tools": [dict(t) for t in tools],
    }


def descriptor_digest(tools: Sequence[dict[str, Any]]) -> str:
    """Our own hash of a capture, recorded so a reader can see whether the two
    captures differed at all without having to diff two manifests.

    This is NOT the scanner's hash and is never used to decide anything: the
    drift verdict is the scanner's to make. It exists so that "the descriptors
    never changed" and "the descriptors changed and the scanner missed it" are
    distinguishable in the run record.
    """
    blob = json.dumps(list(tools), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# --------------------------------------------------------------------------
# Report parsing
# --------------------------------------------------------------------------


def _finding_key(f: RawFinding) -> tuple[str, str, str, str]:
    return (
        f.raw_label,
        str(f.raw.get("tool")),
        str(f.severity),
        f.message,
    )


def parse_report(
    report: dict[str, Any],
    *,
    scanner_id: str,
    server_id: str | None,
    phase: str,
    manifest_path: str,
    stage: str = "runtime",
) -> list[RawFinding]:
    """Turn one sentinel-scan-cli JSON report into RawFindings.

    Every element of ``report["results"]`` becomes exactly one RawFinding,
    including an element whose ``heuristic`` this project has never seen: an
    unrecognised label becomes a finding and is scored ``unmapped``, which costs
    the scanner nothing and tells us our taxonomy has a gap. Dropping it would
    hide both (runner/adapters/__init__.py).

    ``raw_label`` is ``results[].heuristic`` VERBATIM -- never re-cased, never
    normalised. mapping/sentinel-scan-cli.json is keyed on that exact string.
    """
    results = report.get("results")
    if not isinstance(results, list):
        return []

    out: list[RawFinding] = []
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            # Preserved, not dropped: we cannot say what it was, but we can say
            # that the scanner emitted something here.
            out.append(RawFinding(
                scanner_id=scanner_id,
                raw_label="",
                server_id=server_id,
                file=manifest_path,
                message=f"malformed finding at results[{index}]",
                stage=stage,
                raw={"malformed": True, "phase": phase, "phases": [phase],
                     "value": repr(item)[:500]},
            ))
            continue

        label = item.get("heuristic")
        label = label if isinstance(label, str) else ""

        severity = item.get("severity")
        severity = severity if isinstance(severity, str) else None

        message = item.get("evidence")
        if not isinstance(message, str):
            message = "" if message is None else str(message)

        raw: dict[str, Any] = {
            "heuristic": label,
            "tool": item.get("tool"),
            "owasp_category": item.get("owasp_category"),
            "owasp_mcp_category": item.get("owasp_mcp_category"),
            "confidence": item.get("confidence"),
            "recommendation": item.get("recommendation"),
            "phase": phase,
            "phases": [phase],
            # Provenance of the thing that was scanned, carried on every
            # finding so it survives into the persisted results.
            "descriptor_source": "MCP tools/list over HTTP",
            "scanned_manifest": manifest_path,
        }

        out.append(RawFinding(
            scanner_id=scanner_id,
            raw_label=label,
            server_id=server_id,
            file=manifest_path,
            # sentinel-scan-cli's JSON findings carry no line number (its SARIF
            # output does, against the manifest text). A generated manifest's
            # line numbers are an artifact of how we serialised it, so nothing
            # useful is lost.
            line=None,
            message=message,
            severity=severity,
            stage=stage,
            raw=raw,
        ))

    return out


def merge_phases(
    baseline: Sequence[RawFinding],
    post_trigger: Sequence[RawFinding],
) -> list[RawFinding]:
    """Union the two passes' findings, collapsing exact duplicates.

    A finding identical in ``(heuristic, tool, severity, evidence)`` across both
    passes is one finding observed twice, not two findings: it is emitted once
    with ``raw["phases"] == ["baseline", "post-trigger"]``. Nothing is
    discarded -- both observations are recorded on the surviving finding -- and
    no pass's output is preferred over the other's, so which findings the
    benchmark sees does not depend on an invocation choice.
    """
    merged: list[RawFinding] = []
    seen: dict[tuple[str, str, str, str], RawFinding] = {}

    for f in list(baseline) + list(post_trigger):
        key = _finding_key(f)
        prior = seen.get(key)
        if prior is None:
            seen[key] = f
            merged.append(f)
            continue
        phases = list(prior.raw.get("phases") or [])
        new_phase = f.raw.get("phase")
        if new_phase and new_phase not in phases:
            phases.append(new_phase)
        prior.raw["phases"] = phases
    return merged


# --------------------------------------------------------------------------
# Live descriptor capture
# --------------------------------------------------------------------------


def _wire_format(tool: Any) -> dict[str, Any]:
    """A `tools/list` entry in wire format.

    ``by_alias=True`` is what produces ``inputSchema`` rather than
    ``input_schema``; ``excessive_agency_schema`` reads ``inputSchema`` first,
    and while sentinel-scan-cli happens to accept the snake_case spelling as a
    fallback, depending on that would be depending on luck.
    """
    if hasattr(tool, "model_dump"):
        return tool.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(tool, dict):
        return dict(tool)
    raise SentinelManifestError(
        f"cannot serialise a tools/list entry of type {type(tool).__name__}")


def _client(url: str, token: str | None):
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth

    return Client(url, auth=BearerAuth(token) if token else None)


async def _probe_async(
    url: str,
    token: str | None,
    depth: int,
    ready_attempts: int,
    ready_delay: float,
) -> list[list[dict[str, Any]]]:
    # Readiness first, with bare sessions that perform the `initialize`
    # handshake and no `tools/list`. This is safe for a02 specifically, and it
    # was verified rather than assumed: a02's RugPullMiddleware hooks
    # on_list_tools only and its manifest states that the handshake is not
    # counted. Restarting a02 and then opening three bare sessions still put
    # the mutation on the 4th tools/list, so no number of readiness attempts
    # can consume the rug-pull trigger.
    last: Exception | None = None
    for attempt in range(ready_attempts):
        try:
            async with _client(url, token):
                pass
            last = None
            break
        except Exception as exc:
            last = exc
            if attempt + 1 < ready_attempts:
                await asyncio.sleep(ready_delay)
    if last is not None:
        raise SentinelManifestError(
            f"{url} did not answer an MCP initialize after {ready_attempts} "
            f"attempts: {type(last).__name__}: {last}")

    captures: list[list[dict[str, Any]]] = []
    async with _client(url, token) as client:
        for index in range(1, depth + 1):
            try:
                tools = await client.list_tools()
            except Exception as exc:
                # Deliberately NOT retried. A failure partway through the
                # sequence leaves us with an unknown number of tools/list calls
                # already spent on the server, so a retry could take its
                # "baseline" capture from an already-mutated descriptor and
                # silently turn a detectable rug-pull into a clean scan. Failing
                # is the honest outcome.
                raise SentinelManifestError(
                    f"tools/list call {index} of {depth} against {url} failed "
                    f"after {len(captures)} successful capture(s); refusing to "
                    f"retry, because a retry could take the baseline capture "
                    f"from an already-mutated descriptor: "
                    f"{type(exc).__name__}: {exc}") from exc
            captures.append([_wire_format(t) for t in tools])
    return captures


def probe_descriptors(
    url: str,
    token: str | None,
    depth: int = DEFAULT_PROBE_DEPTH,
    timeout: float = DEFAULT_PROBE_TIMEOUT_SECS,
    ready_attempts: int = DEFAULT_READY_ATTEMPTS,
    ready_delay: float = DEFAULT_READY_DELAY_SECS,
) -> list[list[dict[str, Any]]]:
    """Call ``tools/list`` ``depth`` times and return every capture, in order.

    All ``depth`` calls happen inside one MCP session. a02's rug-pull middleware
    counts ``tools/list`` requests on the server process and does not count the
    ``initialize`` handshake, so session boundaries are irrelevant to it -- but
    one session is fewer moving parts and one fewer way for a run to differ from
    the run before it.
    """
    if depth < 2:
        raise SentinelManifestError(
            f"probe_depth must be at least 2 to compare two captures, got {depth}")

    budget = timeout + ready_attempts * (ready_delay + 5.0)

    async def _run() -> list[list[dict[str, Any]]]:
        return await asyncio.wait_for(
            _probe_async(url, token, depth, ready_attempts, ready_delay), budget)

    try:
        return asyncio.run(_run())
    except SentinelManifestError:
        raise
    except Exception as exc:  # unreachable endpoint, auth failure, protocol error
        raise SentinelManifestError(
            f"could not read tools/list from {url}: {type(exc).__name__}: {exc}"
        ) from exc


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------


@dataclass
class SentinelScanAdapter:
    """Runs sentinel-scan-cli's manifest scan against a generated ``mcp.json``."""

    scanner_id: str = "sentinel-scan-cli"
    display_name: str = "sentinel-scan-cli (Ventrova)"
    adapter_version: str = "1.0.0"
    stages: frozenset[str] = frozenset({"runtime"})
    requires_signup: bool = False
    config_label: str = "default"

    image: str = IMAGE
    probe_depth: int = DEFAULT_PROBE_DEPTH
    container_timeout: int = DEFAULT_CONTAINER_TIMEOUT_SECS
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT_SECS
    ready_attempts: int = DEFAULT_READY_ATTEMPTS
    ready_delay: float = DEFAULT_READY_DELAY_SECS
    #: Recorded on every result. "per-server" is what the runner's runtime
    #: stage imposes; the module docstring records the tested equivalence with
    #: whole-corpus scope on corpus v1.
    scope: str = "per-server"
    notes: list[str] = field(default_factory=list)

    # -- protocol ---------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        """Can this adapter run right now? Never raises.

        docs/governance.md publishes a scanner we could not run together with
        the reason, which only works if this method always answers.
        """
        ok, reason = docker_available()
        if not ok:
            return False, f"{reason}; sentinel-scan-cli runs in a container"
        try:
            present = image_present(self.image)
        except Exception as exc:  # docker present but misbehaving
            return False, (f"could not inspect the {self.image} image "
                           f"({type(exc).__name__}: {exc})")
        if not present:
            return False, (f"the {self.image} image is not built. Build it with: "
                           f"{BUILD_HINT}")
        # The scanner cannot fetch its own input. Without an MCP client on the
        # host there is no manifest to scan, and that is an unavailable row
        # rather than a scanner that found nothing.
        try:
            import fastmcp  # noqa: F401
        except Exception as exc:
            return False, (
                "the adapter needs an MCP client on the host to build the "
                "manifest sentinel-scan-cli scans (it cannot connect to an "
                f"endpoint itself); importing fastmcp failed: "
                f"{type(exc).__name__}: {exc}")
        return True, ""

    def run_static(self, target: StaticTarget) -> AdapterResult:
        raise NotImplementedError(
            "SentinelScanAdapter declares stages={'runtime'}. sentinel-scan-cli "
            "cannot read a source tree at all -- it takes an mcp.json manifest "
            "and nothing else -- and the descriptors it scans here are obtained "
            "by the adapter calling tools/list against the live endpoint. See "
            "the module docstring for why 'runtime' is the honest declaration "
            "and what it costs.")

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(findings=[], error=reason,
                                 scanner_version=SCANNER_VERSION,
                                 extra=self._base_extra(target))

        if target.authenticated and not target.token:
            # Mirrors the ramparts adapter: deciding from `authenticated`
            # rather than "the token is truthy" means a harness bug that drops
            # the token fails loudly instead of producing a plausible-looking
            # scan of an endpoint we never authenticated to.
            return AdapterResult(
                findings=[],
                error=(f"RuntimeTarget for {target.server_id!r} is marked "
                       "authenticated=True but carries no token -- refusing to "
                       "probe unauthenticated by accident."),
                scanner_version=SCANNER_VERSION,
                extra=self._base_extra(target),
            )

        try:
            captures = probe_descriptors(
                target.url, target.token, self.probe_depth, self.probe_timeout,
                self.ready_attempts, self.ready_delay)
        except SentinelManifestError as exc:
            return AdapterResult(
                findings=[], error=str(exc), scanner_version=SCANNER_VERSION,
                extra=self._base_extra(target))

        first, last = captures[0], captures[-1]
        extra = self._base_extra(target)
        extra.update({
            "tools_first_capture": [t.get("name") for t in first],
            "tools_last_capture": [t.get("name") for t in last],
            "first_capture_digest": descriptor_digest(first),
            "last_capture_digest": descriptor_digest(last),
            "descriptors_changed_across_probes":
                descriptor_digest(first) != descriptor_digest(last),
        })

        manifest_first = build_manifest(
            target.server_id, target.url, target.authenticated, first,
            capture_index=1, probe_depth=self.probe_depth)
        manifest_last = build_manifest(
            target.server_id, target.url, target.authenticated, last,
            capture_index=self.probe_depth, probe_depth=self.probe_depth)

        with tempfile.TemporaryDirectory(prefix="sentinel-scan-") as tmp:
            work = Path(tmp)
            # The container runs as uid 10001 and has to write --output and the
            # baseline file. A temp directory the container cannot write to
            # would look exactly like a scanner that produced nothing.
            os.chmod(work, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            (work / MANIFEST_BASELINE).write_text(
                json.dumps(manifest_first, indent=2), encoding="utf-8")
            (work / MANIFEST_POST_TRIGGER).write_text(
                json.dumps(manifest_last, indent=2), encoding="utf-8")

            pass1 = self._scan(
                work,
                manifest=MANIFEST_BASELINE,
                report=REPORT_BASELINE,
                update_baseline=True,
            )
            pass2 = self._scan(
                work,
                manifest=MANIFEST_POST_TRIGGER,
                report=REPORT_POST_TRIGGER,
                update_baseline=False,
            )
            baseline_hashes = _read_json(work / BASELINE_HASHES)

        raw_output = _raw_output(
            target, manifest_first, manifest_last, pass1, pass2)

        errors = [e for e in (pass1.error, pass2.error) if e]
        if pass1.report is None and pass2.report is None:
            return AdapterResult(
                findings=[], raw_output=raw_output,
                exit_code=pass2.exit_code if pass2.exit_code is not None else pass1.exit_code,
                duration_seconds=(pass1.duration or 0.0) + (pass2.duration or 0.0),
                error="; ".join(errors) or "sentinel-scan-cli produced no readable report",
                scanner_version=SCANNER_VERSION, extra=extra)

        findings_first = parse_report(
            pass1.report or {}, scanner_id=self.scanner_id,
            server_id=target.server_id, phase=PHASE_BASELINE,
            manifest_path=f"{WORK_MOUNTPOINT}/{MANIFEST_BASELINE}")
        findings_last = parse_report(
            pass2.report or {}, scanner_id=self.scanner_id,
            server_id=target.server_id, phase=PHASE_POST_TRIGGER,
            manifest_path=f"{WORK_MOUNTPOINT}/{MANIFEST_POST_TRIGGER}")
        findings = merge_phases(findings_first, findings_last)

        reported_version = None
        for rep in (pass2.report, pass1.report):
            if isinstance(rep, dict):
                v = (rep.get("summary") or {}).get("version")
                if isinstance(v, str) and v:
                    reported_version = v
                    break
        if reported_version and reported_version != SCANNER_VERSION:
            errors.append(
                f"image {self.image} reports sentinel-scan-cli "
                f"{reported_version}, not the pinned {SCANNER_VERSION}")

        extra.update({
            "probe_depth": self.probe_depth,
            "baseline_tool_hashes_recorded":
                len(baseline_hashes) if isinstance(baseline_hashes, dict) else None,
            "summary_baseline_pass": (pass1.report or {}).get("summary"),
            "summary_post_trigger_pass": (pass2.report or {}).get("summary"),
            "findings_baseline_pass": len(findings_first),
            "findings_post_trigger_pass": len(findings_last),
            "findings_after_merge": len(findings),
            "drift_labels_in_post_trigger_pass": sorted({
                f.raw_label for f in findings_last
                if f.raw_label == "tool_definition_drift"}),
            "exit_code_baseline_pass": pass1.exit_code,
            "exit_code_post_trigger_pass": pass2.exit_code,
        })

        return AdapterResult(
            findings=findings,
            raw_output=raw_output,
            exit_code=pass2.exit_code,
            duration_seconds=(pass1.duration or 0.0) + (pass2.duration or 0.0),
            error="; ".join(errors) if errors else None,
            scanner_version=reported_version or SCANNER_VERSION,
            extra=extra,
        )

    # -- internals --------------------------------------------------------

    def _base_extra(self, target: RuntimeTarget) -> dict[str, Any]:
        return {
            "image": self.image,
            "scanner_version_pinned": SCANNER_VERSION,
            "scope": self.scope,
            "server_id": target.server_id,
            "url": target.url,
            "authenticated": target.authenticated,
            # The load-bearing disclosure: the scanner never connected to
            # anything. The adapter did, and handed it a file.
            "descriptor_source": (
                "MCP tools/list called by the adapter; sentinel-scan-cli makes "
                "no network calls and scans a generated mcp.json"),
            "manifest_is_generated": True,
            "token_written_to_manifest": TOKEN_PLACEHOLDER,
        }

    def _scan(
        self,
        work: Path,
        *,
        manifest: str,
        report: str,
        update_baseline: bool,
    ) -> "_ScanPass":
        args = [
            "mcp",
            "--manifest", f"{WORK_MOUNTPOINT}/{manifest}",
            "--format", "json",
            "--output", f"{WORK_MOUNTPOINT}/{report}",
            "--baseline", f"{WORK_MOUNTPOINT}/{BASELINE_HASHES}",
            # Exit 0 means "the scan ran"; see the module docstring.
            "--fail-on", "none",
        ]
        if update_baseline:
            args.append("--update-baseline")

        spec = ContainerSpec(
            image=self.image,
            args=args,
            mounts=[(work.resolve(), WORK_MOUNTPOINT, "rw")],
            # The `mcp` subcommand makes no network calls. Denying one means a
            # future release that grows one fails here instead of quietly
            # reaching the internet.
            network="none",
            workdir=WORK_MOUNTPOINT,
            timeout=self.container_timeout,
        )
        run = run_container(spec)

        parsed = _read_json(work / report)
        error: str | None = None
        if run.error and run.exit_code is None:
            error = run.error
        elif not isinstance(parsed, dict):
            detail = (run.stderr or run.stdout or "").strip()[:400]
            error = (f"sentinel-scan-cli wrote no readable JSON report for the "
                     f"{manifest} pass (exit {run.exit_code})"
                     + (f": {detail}" if detail else ""))
            parsed = None
        elif run.exit_code not in (0, 1):
            # A readable report with an unexpected exit is worth recording and
            # is NOT a reason to discard findings.
            error = (f"sentinel-scan-cli exited {run.exit_code} on the "
                     f"{manifest} pass; its report was still parsed and its "
                     f"findings are included")

        return _ScanPass(
            report=parsed if isinstance(parsed, dict) else None,
            exit_code=run.exit_code,
            duration=run.duration_seconds,
            stdout=run.stdout,
            stderr=run.stderr,
            error=error,
            args=args,
        )


@dataclass
class _ScanPass:
    report: dict[str, Any] | None
    exit_code: int | None
    duration: float | None
    stdout: str
    stderr: str
    error: str | None
    args: list[str]


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _raw_output(
    target: RuntimeTarget,
    manifest_first: dict[str, Any],
    manifest_last: dict[str, Any],
    pass1: _ScanPass,
    pass2: _ScanPass,
) -> str:
    """Everything needed to reproduce this scan by hand.

    runner/execute.py persists ``raw_output`` and nothing else, and the input to
    this scanner is generated rather than checked in -- so the generated
    manifests go here too. Without them a reader could not tell whether a
    finding was about a corpus server or about how the adapter wrote a config
    file.
    """
    blocks = [
        f"### sentinel-scan-cli {SCANNER_VERSION} :: {target.server_id}",
        f"# url: {target.url}  authenticated: {target.authenticated}",
        "",
        f"### GENERATED MANIFEST -- capture 1 ({MANIFEST_BASELINE})",
        json.dumps(manifest_first, indent=2),
        "",
        f"### GENERATED MANIFEST -- last capture ({MANIFEST_POST_TRIGGER})",
        json.dumps(manifest_last, indent=2),
        "",
        f"### PASS 1 (baseline, --update-baseline) argv: {pass1.args}",
        f"# exit: {pass1.exit_code}",
        pass1.stdout,
        pass1.stderr,
        "### PASS 1 REPORT",
        json.dumps(pass1.report, indent=2) if pass1.report is not None else "(none)",
        "",
        f"### PASS 2 (post-trigger, --baseline) argv: {pass2.args}",
        f"# exit: {pass2.exit_code}",
        pass2.stdout,
        pass2.stderr,
        "### PASS 2 REPORT",
        json.dumps(pass2.report, indent=2) if pass2.report is not None else "(none)",
    ]
    return "\n".join(blocks)


def build_command() -> list[str]:
    """The exact command that builds this adapter's image. Published with the row."""
    return ["docker", "build", "-f", str(DOCKERFILE_PATH), "-t", IMAGE,
            str(DOCKERFILE_PATH.parent)]
