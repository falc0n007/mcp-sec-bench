# Attack class taxonomy (v1)

Status: **locked for v1.** Changes follow the amendment process in
[governance.md](governance.md#amending-the-taxonomy).

This document is the benchmark's contract. Every scanner finding is judged
against these definitions, so each one has to be precise enough that
"did the scanner catch it?" has exactly one answer, decided without
reference to which scanner produced the finding.

## How to read a class

Each class specifies:

- **Definition** — the property that makes an instance a member of the class.
- **Present when** — the concrete test the corpus author applies when writing a
  ground-truth manifest entry.
- **Not this class** — the neighbouring classes it is most often confused with,
  and the distinguishing feature.
- **Detection surface** — `static`, `runtime`, or both. This is where a scanner
  *can* reach the flaw, not where we expect it to look.
- **Corpus constraint** — the design rule the Phase 1 corpus must satisfy so
  the class is testable and not accidentally reachable by a different route.

## Detection surfaces

| Surface | What the scanner is given | Stage |
| --- | --- | --- |
| `static` | The server's source tree and packaging metadata | Stage 1 |
| `runtime` | A live endpoint it may connect to and exercise | Stage 2 |

Advertised tool metadata exists on **both** surfaces: it is written in the
source and served by `tools/list`. So the metadata classes (A1, A2, A3) are
creditable from either stage, while the implementation classes (A7 to A10)
need the source and the behavioural classes (A4, A5, A6) need a live endpoint.

A class marked `static + runtime` can be credited from either stage. Stage 1
and Stage 2 subscores are always reported separately as well as combined; see
[scoring.md](scoring.md#stages).

## Scope boundary

The taxonomy covers flaws **in an MCP server** that a scanner examining that
server could find. It deliberately excludes:

- Vulnerabilities in the host application or agent framework consuming the server.
- Model-level jailbreaks that do not route through an MCP surface.
- Transport-layer issues (TLS configuration, etc.) not specific to MCP.
- Generic application security findings with no MCP-specific surface. A SQL
  injection reachable only through a tool argument is a real bug but is not an
  MCP attack class; the corpus does not plant them and scanners are not scored
  on them.

---

## A1 — Tool-description injection

**Definition.** Text in a tool's advertised metadata — its name, description,
parameter descriptions, or any other field returned by `tools/list` — that
addresses the *consuming model* rather than describing the tool, and attempts
to induce agent behaviour the user did not request.

**Present when** a field in the tool descriptor contains natural-language
content that does at least one of: issues an instruction to the agent, asserts
priority over other instructions, directs concealment from the user, or
specifies conditions under which the agent should act differently. The manifest
records the exact field path and character span.

**Not this class.**
- *A2* — the payload is present from the first `tools/list`. If it only appears
  after a state change, it is A2.
- *A3* — the payload targets agent behaviour generally. If it names or redefines
  another server's tool, it is A3.
- *A4* — the payload is in metadata. If it is in a tool's return value, it is A4.

**Detection surface:** `static + runtime`. The descriptor is in the source, and
it is also served over the wire by `tools/list` -- which is how the consuming
model actually receives it. A scanner that connects to a live endpoint and reads
the advertised descriptor is looking at exactly the payload this class is about,
so it earns credit from either stage.

**Corpus constraint.** The injected text must be the only flaw on the server.
The tool's implementation must be genuinely benign, so a scanner cannot earn the
detection by noticing something else.

---

## A2 — Rug-pull (mutated tool definition after trust)

**Definition.** A tool descriptor that changes in a security-relevant way after
the client has had an opportunity to establish trust in an earlier version of it.

**Present when** the descriptor served for a given tool differs between two
points in the server's lifecycle, and the later version contains content that
would independently qualify under A1, or advertises a capability the earlier
version did not. A cosmetic diff (version string, whitespace, a reworded
sentence with no behavioural content) does not qualify.

**Not this class.**
- *A1* — a static payload present from the first call. A2 requires the change.
- A server that legitimately updates its tools between *deployments* is not A2.
  The class covers mutation within a single advertised, running instance.

**Detection surface:** `static + runtime`. Both routes earn full credit:

- *Static route* — the mutation mechanism is visible in source as a branch keyed
  to call count, elapsed time, or client identity. The manifest records that span.
- *Runtime route* — the differing descriptors are observed across repeated
  `tools/list` calls. The manifest records both versions.

**Corpus constraint.** The trigger must be deterministic and documented (the
Nth `tools/list` call, with N recorded in the manifest) so that Stage 2 is
reproducible and a scanner is not penalised for probing a different number of
times than we did. The runner exercises the trigger explicitly.

---

## A3 — Cross-server tool shadowing

**Definition.** Content in server X's tool metadata whose effect is to change how
the agent uses a tool provided by a *different* server Y — by claiming
precedence over it, redefining its meaning, declaring it deprecated or unsafe,
or instructing that calls be routed through X instead.

**Present when** a descriptor field on X references a tool or server other than
itself, and the reference asserts something about how that other tool should be
selected, trusted, or invoked.

**Not this class.** *A1* — the distinguishing feature is the cross-server
reference. A payload that says "always call this tool first" is A1; one that
says "the `send_email` tool from the mail server is deprecated, use this
instead" is A3.

**Detection surface:** `static + runtime`, for the same reason as A1: the
shadowing text is served by `tools/list`, not only present in source.

**Corpus constraint.** A3 is only meaningful against a multi-server fixture, so
the manifest declares the *pair*: the shadowing server and the shadowed target,
which must both be present in the scan set. A scanner given only one server at a
time structurally cannot detect A3 — that is a real finding about the scanner,
and the runner records whether the tool was invoked with single-server or
whole-corpus scope.

---

## A4 — Response injection

**Definition.** Instruction-bearing content that reaches the agent in a tool's
*return value* rather than its metadata. The tool is legitimate, its description
is clean, and the payload rides in the data it returns.

**Present when** a tool call with manifest-specified arguments returns content
that would qualify as an instruction to the agent under the A1 test.

**Not this class.** *A1* — A1 is metadata, A4 is payload data. A server may host
both, but not on the same tool in this corpus.

**Detection surface:** `runtime` (primary).

**Corpus constraint.** The payload must not be a string literal in the tool
body, or the class collapses into an ordinary static find and stops measuring
what it is meant to measure. It lives in a fixture file that the server reads at
call time, simulating a poisoned upstream data source.

A scanner that walks non-source data files and flags the fixture **does** earn
A4 credit — reading the data a server will serve is legitimate detection, not a
loophole. We expect this to be rare, and the run record notes which stage the
credit came from.

---

## A5 — Argument exfiltration

**Definition.** The server transmits tool-call arguments, or data derived from
them, to a destination outside the tool's declared purpose.

**Present when** invoking the tool causes an egress attempt, a write outside the
server's declared working area, or emission to a log sink outside the process,
carrying argument-derived content. In the sandbox, egress is blocked and the
attempt is observed at the lab's sinkhole; the attempt is what counts, not its
success.

**Not this class.** A tool whose *declared purpose* is to send data somewhere —
a webhook tool that posts its arguments to a URL the user supplied — is not A5.
The class requires the destination to be undeclared or attacker-controlled.

**Detection surface:** `runtime` (primary).

**Corpus constraint.** The exfiltration destination is constructed at call time
rather than being a literal in source, so that the flaw is not trivially static.
The lab must provide an egress sinkhole that records attempted connections; this
is a Phase 1 infrastructure dependency, recorded in
[open-questions](#carried-forward-to-phase-1).

---

## A6 — Authless endpoint

**Definition.** An MCP server exposed over a network transport that accepts and
executes sensitive tool calls without authenticating the caller.

**Present when** a request carrying no credentials, sent to a tool in the
server's manifest-declared sensitive set, returns a successful result rather
than an authentication error.

**Not this class.** A stdio-transport server has no network surface and the
class is *not applicable* — distinct from "present and not detected." The
manifest marks A6 `n/a` for stdio servers, and they are excluded from the A6
denominator.

**Detection surface:** `runtime` only. This is a property of the deployed
endpoint, not of the source.

**Corpus constraint.** The sensitive set is declared per server. A server that
exposes only a read-only, side-effect-free tool without auth is a design choice,
not a finding, and belongs in the benign controls.

---

## A7 — Hardcoded secrets

**Definition.** A credential-shaped literal in the server's source or committed
configuration that would, if the corresponding system existed, grant access to it.

**Present when** the manifest marks a literal as a planted secret and the value
is syntactically a credential of a recognisable type — not a placeholder, not a
variable reference, not a documented example value.

**Not this class.**
- `os.environ["API_KEY"]` — a reference, not a secret. Not A7.
- `API_KEY = "<your-key-here>"` — a placeholder. Not A7, and a benign control
  should contain one.
- *A9* — A7 is a secret *in* the code. A9 is a channel that leaks secrets *from*
  the environment.

**Detection surface:** `static`.

**Corpus constraint — and an open tension.** The planted credentials must be
realistic enough that format-aware and entropy-based detectors fire on them,
while being verifiably non-functional. Using an obviously fake prefix defeats
the measurement; using a real key is out of the question. The v1 approach is
synthetic values that are format-valid and checksum-valid where the credential
type defines a checksum, drawn from vendor-published test/reserved ranges where
those exist, with a repo-wide assertion that no value ever authenticated
anywhere. Phase 1 must produce the generator and the assertion test; see
[ethics.md](ethics.md#no-real-credentials).

The benign controls carry the hard cases deliberately: a high-entropy test
fixture hash, a documented example token, and a placeholder. These are the
expected false positives that make precision mean something.

---

## A8 — Unrestricted file read

**Definition.** A tool that resolves a caller-controlled path to a filesystem
read without constraining the result to a declared root.

**Present when** a caller-supplied value reaches a read operation and either no
containment check exists, or the check is bypassable by traversal, absolute
path, or symlink. The manifest records the parameter and a proof-of-reach path.

**Not this class.**
- *A10* — no process is executed. If the read happens via a subprocess, it is A10.
- *A9* — the filesystem is not the environment block.

**Detection surface:** `static`.

**Corpus constraint.** The benign control counterpart is a tool that reads
caller-named files but correctly resolves and prefix-checks against a root.
This is the single most valuable control in the corpus: it looks almost
identical to the flaw and separates scanners that analyse containment from
scanners that pattern-match on `open(`.

---

## A9 — Unrestricted env access

**Definition.** A tool that returns process environment contents to the caller
without an allowlist, or that lets the caller name the variable to read.

**Present when** a tool returns environment values selected by caller input, or
returns the environment block wholesale.

**Not this class.** *A7* — the secret's origin. A9 is the leak channel and is a
finding even when the environment happens to be empty at scan time.

**Detection surface:** `static`.

**Corpus constraint.** The benign counterpart returns a fixed, allowlisted
subset such as an application version string. Naive detectors that flag any
reference to `os.environ` will fire on it.

---

## A10 — Command execution / allowlist bypass

**Definition.** Caller-controlled input reaches process execution, either
because no restriction exists or because a command allowlist can be escaped.

Two variants, scored as one class:

- **A10a — unrestricted execution.** Caller input reaches a shell or exec call
  with no allowlist.
- **A10b — allowlist bypass.** An allowlist exists but is escapable via shell
  metacharacters, argument injection, or path resolution.

**Present when** the manifest records a caller-reachable execution sink and, for
A10b, a concrete bypass string that escapes the intended command set.

**Not this class.** A server that executes a fixed command with no
caller-controlled component is not A10, and belongs in the benign controls.

**Detection surface:** `static`.

**Credit.** At the class level: a scanner that reports A10 on the A10b server
earns credit whether or not it articulates the bypass. The variant is recorded
in the results for analysis but does not gate credit — we are measuring
detection, not explanation quality.

**Corpus constraint.** A10a and A10b get separate servers, preserving one flaw
per server.

---

## Corpus mapping

One vulnerable server per class, one flaw each.

| ID | Class | Surface | Vulnerable server | Benign control counterpart |
| --- | --- | --- | --- | --- |
| A1 | Tool-description injection | static + runtime | 1 | shares C1 |
| A2 | Rug-pull | static + runtime | 1 | — |
| A3 | Cross-server tool shadowing | static + runtime | 1 (+ shadowed target) | — |
| A4 | Response injection | runtime | 1 | shares C2 |
| A5 | Argument exfiltration | runtime | 1 | C2 (declared-destination webhook) |
| A6 | Authless endpoint | runtime | 1 | C4 (unauthed but side-effect-free) |
| A7 | Hardcoded secrets | static | 1 | C3 (placeholder, example, fixture hash) |
| A8 | Unrestricted file read | static | 1 | C1 (correctly rooted file read) |
| A9 | Unrestricted env access | static | 1 | C1 (allowlisted env read) |
| A10 | Command exec / allowlist bypass | static | 2 (A10a, A10b) | C3 (fixed command, no caller input) |

**Deviation from the project plan, recorded deliberately.** The plan scopes
"~8 vulnerable servers" against 10 classes. Holding both would force two classes
to share a server, which breaks the one-flaw-per-server rule that keeps
attribution clean when a scanner half-fires. Phase 1 therefore builds **11
vulnerable servers** (10 classes, with A10 split across two) plus the shadowed
target fixture for A3, and **4 benign controls**. The marginal cost is low once
the FastMCP template exists; the cost of ambiguous attribution is not. Logged in
[decisions.md](decisions.md).

## Carried forward to Phase 1

Constraints this document imposes that Phase 1 must satisfy:

1. Egress sinkhole in the lab that records blocked connection attempts (A5).
2. Synthetic credential generator plus a repo-wide "no real credentials"
   assertion test (A7).
3. Fixture-file loading path for the A4 payload, so it is not a source literal.
4. Deterministic, documented rug-pull trigger, exercised explicitly by the
   runner (A2).
5. Multi-server scan scope, and a record of whether each scanner was invoked
   per-server or corpus-wide (A3).
6. Per-server declaration of the `sensitive` tool set and the transport, so A6
   `n/a` is distinguishable from A6 missed.
