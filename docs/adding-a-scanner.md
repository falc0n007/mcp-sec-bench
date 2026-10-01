# Adding a scanner

This is the walkthrough for adding a scanner to the benchmark, whether you
maintain the tool or are just a user of it. It is derived from the five adapters
that already exist, and every path and name below was checked against the code
at the time of writing. If this page and the code disagree, the code is right
and this page has a bug; please open an issue.

What you are submitting is **an adapter, a pinned Dockerfile, a mapping file,
and tests**. You are never submitting detection logic. This project does not
ship a scanner and will not merge one
([the no-scanner rule](governance.md#the-no-scanner-rule)).

## 1. Check eligibility

Inclusion is by criteria, not invitation
([governance.md](governance.md#which-scanners-are-included)). A scanner is
eligible when all five hold:

1. Reproducibly runnable from a clean environment, with no sales call, demo, or
   bespoke build.
2. Publicly obtainable: open source, source-available, or a free tier anyone can
   sign up for. An account requirement is allowed and is published in a
   `requires signup` column. It is not a disqualifier.
3. Containerizable.
4. Produces parseable output: machine-readable, or text stable enough to parse
   deterministically.
5. Licensed compatibly with being run and having its output published.

Out of scope for v1, by category and not by quality: commercial scanners behind
a sales process, and runtime gateway or proxy products.

You do not need the maintainers' permission to benchmark a publicly available
tool. You do not need to be the vendor. If you are the vendor, your authorship
of the adapter is disclosed on the scoreboard row, and a maintainer with any
disclosed tie to you recuses from reviewing it
([conflicts of interest](governance.md#conflicts-of-interest)).

## 2. Understand what you are plugging into

Read these first. Each is short.

- [taxonomy.md](taxonomy.md): the ten attack classes and which stage (static,
  runtime, or both) can reach each.
- [scoring.md](scoring.md): what counts as a hit. There is no partial credit and
  no composite score.
- [runner/README.md](../runner/README.md): the pipeline, and the rule that
  **adapters never map**.

The pipeline is:

```
raw scanner output -> RawFinding (adapter) -> MappedFinding (mapping/*.json)
                   -> ItemOutcome (scoring) -> report
```

Your adapter owns the first arrow only. Translating your tool's vocabulary into
our ten classes happens in one separate place, so that every judgment call is
reviewable together.

## 3. Write the adapter

The contract is the `Adapter` protocol in
[`runner/adapters/__init__.py`](../runner/adapters/__init__.py). Read that file's
docstring in full. The short version:

An adapter **must not** map a finding to our taxonomy, silently drop a finding
it does not understand, or modify the corpus.

Attributes every adapter declares:

| Attribute | Meaning |
| --- | --- |
| `scanner_id` | Stable row key. Lowercase letters, digits, hyphens. Must equal `scanner_id` in your mapping file. |
| `display_name` | The name as you write it. |
| `adapter_version` | Bumped whenever parsing or invocation changes. The mapping file records which version its labels were read from. |
| `stages` | `frozenset({"static"})`, `frozenset({"runtime"})`, or both. Declare only what your tool actually does. |
| `requires_signup` | True if the tool cannot run without an account or token. |
| `config_label` | `"default"` for the documented default configuration. |

Methods:

- `available() -> tuple[bool, str]`: can this adapter run right now? Return
  `(False, reason)` rather than raising. The runner publishes the reason on the
  scoreboard row, so a scanner we could not run is visible and not quietly
  omitted.
- `run_static(target: StaticTarget) -> AdapterResult`
- `run_runtime(target: RuntimeTarget) -> AdapterResult`

An adapter that does not declare a stage must refuse that method loudly. The
existing ones raise `NotImplementedError` with an explanation (see
`RampartsAdapter.run_static` in
[`runner/adapters/ramparts.py`](../runner/adapters/ramparts.py)). Returning an
empty result would read as "ran and found nothing", which is a different claim.

What you receive and return, all defined in
[`runner/adapters/__init__.py`](../runner/adapters/__init__.py) and
[`runner/models.py`](../runner/models.py):

- `StaticTarget`: `corpus_dir`, `server_dirs`, and `scope` (`"corpus"` or
  `"per-server"`). Record which you used. Whether your tool saw one server or
  all of them decides whether it could detect cross-server shadowing (A3).
- `RuntimeTarget`: `server_id`, `url`, `token`, `authenticated`,
  `sensitive_tools`.
- `AdapterResult`: `findings`, `raw_output`, `exit_code`, `duration_seconds`,
  `error`, `scanner_version`, `extra`. Put your tool's complete raw output in
  `raw_output`; raw output for every published run is committed so anyone can
  check the arithmetic without rerunning anything.
- `RawFinding`: `scanner_id`, `raw_label`, `server_id`, `file`, `line`,
  `message`, `severity`, `stage`, `raw`.

`raw_label` is the field the whole mapping layer keys on. Copy it **verbatim**
from the output: never re-case it, trim it, or clean it up. Decide which field
of your tool's output is its stable label (a rule id, a check name, a threat
name) and say so in your mapping file's `label_source_field`.

### Running the container

Use the helpers in
[`runner/adapters/container.py`](../runner/adapters/container.py):
`docker_available()`, `image_present()`, `ContainerSpec`, and
`run_container()`. Two properties are enforced there and you should not work
around them:

- The corpus is mounted **read-only** at `CORPUS_MOUNTPOINT` (`/corpus`).
- Scanner containers reach the lab through `LAB_HOST`
  (`host.docker.internal`), not by joining the lab network, so a scanner that
  needs the internet for an LLM-judge analyzer still has it. The egress block
  exists to stop corpus servers exfiltrating, not to constrain the instrument.

### Worked examples to copy from

| If your tool... | Read |
| --- | --- |
| scans a live URL | [`ramparts.py`](../runner/adapters/ramparts.py) |
| scans source on disk | [`mcp_guard.py`](../runner/adapters/mcp_guard.py) |
| reports labels from several analyzers in one report | [`cisco_mcp_scanner.py`](../runner/adapters/cisco_mcp_scanner.py) |
| needs a token to do anything | [`snyk_agent_scan.py`](../runner/adapters/snyk_agent_scan.py) |
| needs the adapter to drive server state across calls (rug-pull) | [`sentinel_scan.py`](../runner/adapters/sentinel_scan.py) |

Read the module docstring of the one nearest to yours. Each records the traps
its author hit. The Ramparts adapter, for example, exists in its current shape
because a default install ran with detection silently disabled and still
reported zero findings; it now refuses to return findings unless it can prove
the rules loaded. **Check that your tool cannot fail silently into a clean
result.** A scanner that is broken by our setup and reports zero would be
published as a measurement of the scanner.

### Default configuration

Your adapter runs the tool in its **documented default configuration**
([scoring.md](scoring.md#scanner-configuration)). Defaults are what users get,
so defaults are what we measure. Use the same invocation a person following your
README would use. Anything beyond that, such as an extra analyzer, a tuned rule
set, or a model key, is not the default row.

### An alternative configuration

A vendor may submit an alternative configuration. It is published as an
**additional row** with its own `config_label`, never as a replacement for the
default row ([governance.md](governance.md#what-vendors-can-and-cannot-influence)).
Configurations needing a paid tier, a sales call, or a non-public build are out
of scope.

If part of the tool is gated behind a credential, the ungated row is the
default view and a credentialed run is published as a second row
([scoring.md](scoring.md#access-friction)). Say which engines are gated, so a
reader can tell a detection failure from an unavailable engine.

### If a signup or token is required

Set `requires_signup = True`, and have `available()` return `(False, reason)`
when the credential is absent, checked **before** Docker. The reason is what
gets published. `SnykAgentScanAdapter.available()` in
[`runner/adapters/snyk_agent_scan.py`](../runner/adapters/snyk_agent_scan.py) is
the model: it reads the token from the environment, never writes it into a
generated config or into `raw_output`, and refuses rather than running a
partial scan that would measure nothing.

Also state in your `notes` anything the reader should know before supplying the
credential, for example whether analysis happens server-side.

## 4. Pin the Dockerfile

One Dockerfile per scanner in
[`runner/adapters/dockerfiles/`](../runner/adapters/dockerfiles/), named
`<scanner_id>.Dockerfile`.

- **Pin the version.** A published score must be reproducible from this file. If
  the tool is not released as a package, pin a commit SHA, not a branch or a
  tag (see
  [`mcp-guard.Dockerfile`](../runner/adapters/dockerfiles/mcp-guard.Dockerfile)).
  Bump the pin and `adapter_version` together; a scanner version change is a new
  row, not an edit to an old one.
- **Run as a non-root user** and assume the corpus is read-only.
- **Include whatever the install route omits.** If a package manager install
  does not ship rule files, bake them in from the matching source tag
  ([`ramparts.Dockerfile`](../runner/adapters/dockerfiles/ramparts.Dockerfile)).
- Tag the image `mcp-sec-bench/<scanner_id>:<version>` and expose that tag as an
  `IMAGE` constant in your adapter, with the exact `docker build` command in the
  message `available()` returns when the image is missing.

Add the build line to the `images` target of the [`Makefile`](../Makefile),
following the existing five:

```make
	docker build -f $(DOCKERFILES)/<scanner_id>.Dockerfile \
		-t mcp-sec-bench/<scanner_id>:<version> .
```

## 5. Write the mapping file

`mapping/<scanner_id>.json`, validated against
[`mapping/schema.json`](../mapping/schema.json) and loaded by `load_mapping_dir`
in [`runner/mapping.py`](../runner/mapping.py). Start from
[`mapping/example-scanner.json`](../mapping/example-scanner.json), which shows
the four cases that matter: a clean 1:1 map, a label spanning two classes, a
deliberately unmapped label, and a disputed entry carrying both positions. Its
labels are invented and prefixed `EXAMPLE_`; the loader refuses to score with it.

File-level fields to get right:

- `scanner_id` equals your adapter's `scanner_id`.
- `adapter_version` equals your adapter's `adapter_version`. Changing which field
  the adapter puts in `raw_label` invalidates the table.
- `label_source_field` names the output field you matched on.
- `label_provenance` is `captured-from-real-output` only if every label was
  copied from output this project actually produced and the capture is
  committed. Use `unverified` if you took them from documentation. Do not invent
  labels.
- `matching` is byte-exact unless you have observed instability and say so.
  Nothing fuzzy, stemmed, or substring is permitted.

### Every label needs a decision, and every decision needs reasoning

Each entry is either `map` to one class or `unmapped` with a reason. There is no
third option and no blank. Every entry, including the ones you leave unmapped,
carries a `rationale_id` (`MR-<scanner_id>-<NNN>`, never reused or renumbered),
a `rationale` of at least 40 characters written for someone who disagrees with
it, a `confidence`, and `decided_on` / `decided_by`.

The rules, from
[mapping-rationale.md](mapping-rationale.md#3-the-decision-procedure):

- A label maps only if what it reports satisfies a class's *Present when* test in
  [taxonomy.md](taxonomy.md). A `map` entry quotes that test and says how it is
  satisfied (`taxonomy_evidence`). "Closest in spirit" is not a reason.
- A label that spans classes lists the others it lost to (`considered_classes`)
  and the rules applied (`resolution_rules`).
- A mapping may not be keyed on which server the finding landed on, on its
  free-text message, or on severity.
- Declining to map is a legitimate and common decision. `unmapped` costs your
  tool nothing in precision, but it is not free: the item you may genuinely have
  found stays a false negative. Say so in your own submission rather than
  leaving it to be discovered.
- Be honest in `dispute_risk`. Under-marking it hides the invitation to contest.

The rationale lives in the entry in `mapping/<scanner_id>.json`. The per-scanner
tables in [mapping-rationale.md](mapping-rationale.md#10-per-scanner-mapping-tables)
are the human-readable record of those entries; the maintainers update them when
your file is accepted, and a pull request that changes a mapping should keep the
two consistent. Run the checks below and read the gap report: any label your
tool can emit that has no entry shows up there, and goes to your own
maintainers in the disclosure pack as something we ignored.

A mapping is frozen against a `corpus_version` before a scoring run
(`frozen_for_corpus_version`). Mid-run edits do not happen quietly.

## 6. Write the tests

Model them on the existing adapter tests,
[`tests/test_adapter_ramparts.py`](../tests/test_adapter_ramparts.py) and
[`tests/test_adapter_snyk.py`](../tests/test_adapter_snyk.py). Tests run without
Docker or network: they monkeypatch the container call and feed the adapter
captured output from [`tests/fixtures/`](../tests/fixtures/). Commit a real
captured output as a fixture, and mark any synthetic one as synthetic in its
filename.

A submission is expected to cover:

- Identity fields: `scanner_id`, `adapter_version`, `stages`,
  `requires_signup`, `config_label`.
- A stage you do not declare refuses rather than returning an empty result.
- `available()` says why when Docker is down, when the image is missing, and
  (if applicable) when a credential is absent. It never raises.
- Parsing a captured real output yields the expected findings.
- `raw_label` is carried verbatim, and severity and message are carried.
- An unparseable, empty, or unexpected-shaped output becomes an `error` on the
  `AdapterResult`, not a crash and not a silent zero.
- A finding the adapter does not understand is preserved, not dropped.
- A container-level failure is reported, not raised.
- Whatever your tool's silent-failure trap is, a test that it is caught.
- If a token is involved, it never appears in generated config, `raw_output`, or
  `error`.
- **Mapping coverage.** Every label your tool can emit has an entry, keyed on
  the current adapter version, as in
  `test_every_rule_this_adapter_could_ever_report_has_a_mapping_entry` and
  `test_the_mapping_table_is_keyed_on_this_adapter_version`.

Mapping-file mechanics (schema, duplicate labels, stage scoping) are covered by
[`tests/test_mapping.py`](../tests/test_mapping.py), and the loader validates
every file in `mapping/` against the schema whenever the runner starts.

## 7. Register and run it

Register the adapter in [`runner/cli.py`](../runner/cli.py): import it, and add
the class to `REAL_ADAPTERS`. That list is the only registry. A real adapter
**cannot** score without a mapping file; the runner refuses rather than handing
it a perfect identity mapping or a silent zero.

Then, from a clean checkout:

```bash
make setup                 # venv plus pinned dependencies
make images                # includes your new image
make lab-up                # corpus online, egress blocked
make verify                # manifests, credentials, every server, the lab, tests
```

Run only your scanner:

```bash
.venv/bin/python -m runner.cli --scanners <scanner_id> --runs 5 --detail
```

Flags that matter (all in `main()` in `runner/cli.py`):

| Flag | Meaning |
| --- | --- |
| `--scanners` | `fixtures`, `real`, `all`, or a comma-separated list of scanner ids |
| `--runs` | Runs per scanner. Default 5. Below 5 is below the minimum in scoring.md and not publishable |
| `--stages` | `static`, `runtime`, or `static,runtime` |
| `--detail` | Also print per-class recall |
| `--out` | Output directory. Defaults to `results/local/`, which is gitignored |
| `--no-reset` | Do not restart the corpus between runtime runs. Spread is then not attributable to the scanner |

Output goes to `results/local/results.json` and `results/local/scoreboard.md`,
with raw scanner output under `results/local/raw/`. Nothing there is a
published score. Publication is a separate, deliberate step
([below](#8-what-happens-next)).

What to check on your first run:

- Is the **unmapped** count what you expected? A label we did not know about
  appears in the gap report.
- Is a zero a real zero? Ask which kind. A scanner can score zero because it
  never reads the surface where the flaw lives, or because it read the surface
  and has no rule for it. Those are different claims about a tool. Your notes on
  the row should say which, if you know.
- If your tool declares only the static or only the runtime stage, the other
  stage's items are marked `not attempted` and excluded from the denominator. It
  is labelled "static only" or "runtime only", not penalised.

## 8. What happens next

1. **Open a pull request** with the adapter, Dockerfile, Makefile line, mapping
   file, registration in `runner/cli.py`, and tests. State in the description
   whether you are the vendor or a maintainer of the tool, and any other tie.
2. **Review is public.** A maintainer with a disclosed tie to your tool recuses.
   Expect to be argued with on mapping entries; that is the point of the file.
3. **Disclosure before publication.** No result is published before its
   maintainers have seen it. You (or the tool's maintainers, if you are not
   them) receive the full results, the methodology, the exact mapping decisions
   applied to the tool, and how it was invoked, with a **14-day window** to
   respond, correct, or identify a misconfiguration
   ([governance.md](governance.md#disclosure-before-publication)). The pack is
   built by `tools/disclosure_pack.py`.
4. **Your response is published** alongside the scores, unedited except for
   length. If you decline to respond, the row says "no response" and nothing
   else.
5. **If a result is wrong, it is corrected and the original stays visible**, with
   a pointer to the correction. Published results are never silently edited.
6. **Disputes** go in a public issue citing the `corpus_version`,
   `scanner_version`, `adapter_version`, and the specific item or
   `mapping_rationale_id`. If we are not persuaded on a mapping, both positions
   are published side by side on your row
   ([governance.md](governance.md#contesting-a-result)).

## What you cannot do

- Influence the corpus, the taxonomy, or the mapping decisions except through the
  public dispute process.
- Receive results ahead of other vendors.
- Make participation conditional on a favourable outcome, or require changes as
  a condition. We do not seek permission to measure publicly available tools.
- Submit anything that is itself a scanner.

## Known limits you should expect to meet

These apply to every row and are stated up front
([disclosure.md](disclosure.md#known-weaknesses-to-state-proactively)): the
corpus is small and synthetic; one A1 versus A4 case is knowingly mis-scored; the
near-miss counter is inflatable; credential-free configurations are what is
measured by default; and a zero needs its cause stated.
