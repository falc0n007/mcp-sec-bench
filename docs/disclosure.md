# Disclosure round

Status: **round 1 in progress**, opened 2026-09-17.

[governance.md](governance.md#disclosure-before-publication) commits to every
scanner's maintainers receiving their full results, the methodology, and the
exact mapping decisions applied to their tool, with **14 days** to respond,
before anyone else sees a number. Responses are published alongside the scores.

**Round 1 deviated from that ordering.** The repository was made public with
preliminary figures already in its commit history. The deviation is recorded in
[decisions.md](decisions.md) and stated in the README. Round 1 is being run
immediately rather than retroactively justified. Subsequent rounds follow the
policy as written.

## Why this round matters more than usual

Two of three runnable scanners scored zero recall against this corpus. A result
that damning is exactly the case where a maintainer is most likely to find a
genuine error in our setup -- and the project plan says finding one is the
point, not an embarrassment. Every claim below is therefore stated so it can be
checked and, if wrong, corrected.

## Status

| Scanner | Contact identified | Contact source | Sent | Window closes | Response | Corrections folded in |
| --- | --- | --- | --- | --- | --- | --- |
| Cisco mcp-scanner | yes — Cisco Open security alias, route 1 | [SECURITY.md](https://github.com/cisco-ai-defense/mcp-scanner/blob/main/SECURITY.md) | no | — | — | — |
| mcp-guard | yes — maintainer email listed in the policy, route 1 | [SECURITY.md](https://github.com/SaravanaGuhan/mcp-guard/blob/main/SECURITY.md) | no | — | — | — |
| Ramparts | no published contact — route 3 | [issues](https://github.com/highflame-ai/ramparts/issues) | no | — | — | — |
| sentinel-scan-cli | no published contact — route 3 | [issues](https://github.com/Ventrova/sentinel-scan-cli/issues) | no | — | — | — |
| Snyk agent-scan | route 3 (see below) | [issues](https://github.com/snyk/agent-scan/issues) | n/a | — | — | — |

Contacts verified 2026-09-30. GitHub private vulnerability reporting was
disabled on all five repositories at that date.

- **Cisco.** The repository's own SECURITY.md is more specific than Cisco PSIRT,
  whose policy covers Cisco products and hosted services rather than open
  source projects, so it is used in preference. PSIRT is the fallback.
- **Snyk.** SECURITY.md routes only to Snyk's vulnerability disclosure programme,
  which asks not to be contacted through other channels about security reports.
  Benchmark results are not a vulnerability report, so filing them there would
  misuse that channel. A GitHub issue asking where to send results, carrying no
  results itself, is the route.
- **Ramparts and sentinel-scan-cli** publish no security or maintainer contact.
  The vendor sites (highflame.com, ventrova.dev) have not yet been checked for
  one; check them before opening an issue.
- **mcp-guard** retracted every release before 2.0.0 for emitting fabricated
  findings. State in the email that only 2.0.0 was benchmarked, and cite the
  commit, since 2.0.0 has no tag or release.

**Version drift since the run.** Cisco 4.8.4 and sentinel-scan-cli 1.4.16 are
still current. Ramparts 0.8.9 exists but its tag points at the same commit as
0.8.8 (`70457dbf`), so cite the commit rather than a version number. Snyk
agent-scan is now 0.6.8; 0.6.4 removed the `dangerous_words` risk and 0.6.5
gated remote MCP connections, so the adapter must be re-verified against a
newer version before any credentialed Snyk row is produced.

Snyk is published as unavailable because a token gates all of its analysis, so
there is no result to disclose. It is still contacted, because "we could not
run your tool" is a claim about their tool and they should be able to correct it.

## Finding a contact

Do not guess an address. In order of preference:

1. A `SECURITY.md` or security policy in the scanner's own repository.
2. A published maintainer or security contact on the vendor's site. For Cisco,
   their product security channel rather than an individual.
3. A GitHub issue on the scanner's repository, asking where to send benchmark
   results privately. Public, but it asks for a private channel rather than
   publishing the result.

Record the source of each contact in the table above, so a later reader can see
we did not cold-email a stranger.

## What each maintainer receives

Everything needed to reproduce and dispute the result, not a summary:

1. **Their full results** — per-class recall and precision, mean and range over
   five runs, every item outcome, and the raw scanner output behind it.
2. **The methodology** — [taxonomy.md](taxonomy.md), [scoring.md](scoring.md),
   and the corpus version the numbers were produced against.
3. **The exact mapping decisions applied to their tool** — their file from
   `mapping/`, with the rationale for every label and every label we left
   unmapped. This is the most disputable part and it goes in the first email,
   not on request.
4. **How their tool was invoked** — the adapter, the pinned version, the
   configuration, and the container definition.
5. **A 14-day window**, and how to dispute.

Generate the per-scanner pack with:

```bash
make scoreboard                      # writes results/local/results.json
make disclosure-pack                 # a pack for every scanner in the results
make disclosure-pack SCANNER=ramparts   # or for one
```

Packs are written to `results/local/disclosure/<scanner>/`, which is
gitignored; no number is committed before the window has run.
[`tools/disclosure_pack.py`](../tools/disclosure_pack.py) fails on an unknown
scanner id. Each pack contains:

- `results.json` -- that scanner's slice of the results document (scoreboard
  metrics, `items`, `findings`, run counts), still schema-valid.
- `mapping.json` -- its file from `mapping/`.
- `adapter/` -- the adapter source, the shared container helper, and the
  scanner's Dockerfile.
- `PACK.json` -- corpus version, generation timestamp, scanner version.
- `README.md` -- what each file is and which of the known weaknesses below
  apply to that scanner.

The methodology documents are linked rather than copied, so they cannot drift
from the pack. Every finding carries its `mapping_rationale_id`, so a number
traces to the judgment call behind it.

## Email template

Plain text. No marketing, no embargo language, no request for a quote.

> Subject: Independent benchmark results for <TOOL>, 14-day review window
>
> Hello,
>
> I maintain mcp-sec-bench, an independent benchmark that measures how well MCP
> security scanners detect deliberately planted flaws. <TOOL> is one of the
> scanners measured. Before publishing a scoreboard I am sending you your
> results, the methodology, and the exact decisions I made when translating
> <TOOL>'s finding labels into the benchmark's attack classes.
>
> Attached or linked:
>   - your full per-class results, with the raw output behind every number
>   - the taxonomy and scoring rules, both written before any scanner was run
>   - the mapping decisions applied to <TOOL>, including labels I left unmapped
>   - exactly how <TOOL> was invoked: version, configuration, container
>
> Headline figure: <RECALL> recall and <PRECISION> precision against a corpus
> of <N> deliberately vulnerable MCP servers and <M> benign controls, over five
> runs.
>
> I am not asking you to endorse this. I am asking you to check it. Two things
> I would particularly like you to look at:
>
>   1. Whether <TOOL> was invoked the way you would invoke it. I used the
>      documented default configuration, credential-free, because that is what
>      a user gets by running the tool as published.
>   2. Whether any mapping decision misrepresents what one of your labels
>      means. Every mapping is a judgment call and I expect some to be wrong.
>
> You have 14 days, until <DATE>. Your response will be published alongside the
> scores, unedited except for length. If you would rather not respond, the row
> will say "no response" with no characterisation of why.
>
> If a result turns out to be wrong, it gets corrected and republished, with the
> original left visible and a pointer to the correction.
>
> I should also tell you plainly: the project's own policy says maintainers see
> results before anyone else, and for this first round I did not manage that --
> the repository went public with preliminary figures already in its commit
> history. That was my error and it is recorded in the repository rather than
> tidied away.
>
> <REPO URL>
>
> <NAME>

## Known weaknesses to state proactively

Disclose these without being asked. A maintainer who finds them unaided has a
reason to distrust everything else:

- **The corpus is small and synthetic.** Recall here is recall against 11
  planted flaws, not against real-world MCP servers.
- **A1 versus A4 is knowingly mis-scored in one case.** See the open question in
  [decisions.md](decisions.md).
- **The near-miss counter is inflatable** and is not evidence of near-competence.
- **Credential-free configurations only.** Cisco's source-code analyzer and
  Snyk's entire analysis require keys we did not supply, which bounds what those
  rows can show. Stated on the scoreboard, and worth repeating in the email.
- **Where a scanner scored zero, say which kind of zero it was.** For Ramparts
  the cause is its scan surface: 0.8.8 never reads source or tool return
  values. For Cisco it is a rule-coverage gap on text the scanner demonstrably
  read. Those are very different claims and conflating them would be unfair to
  both.
