# Ethics and scope note

Status: **in force from 2026-09-17.**

This repository contains deliberately vulnerable MCP servers. That fact deserves
a direct account of what they are for, what constrains them, and what we will
not accept into the corpus — written at the start rather than assembled
defensively after someone objects.

## Purpose

The corpus exists to **measure detection tooling**, not to attack anything.

Published figures suggest MCP security scanners detect a small fraction of the
flaws they are aimed at, with recall reported as low as 0% for some tools, and
with mutually disjoint taxonomies between them. Those claims are either true and
important, or wrong and worth correcting. Neither can be settled without a
shared corpus and a reproducible method. Building one is the contribution.

The targets are instruments. They are designed to be *found*, not to be
effective.

## The minimal payload principle

This is the rule that most constrains corpus design, and it is the one we will
be judged on.

**A payload only has to be detectable. It does not have to work.**

An injection payload in this corpus instructs the agent to emit a benign marker
string. It does not attempt to exfiltrate data, escalate privilege, persist, or
cause any effect beyond being observable. A command-execution flaw reaches a
sink that runs a harmless recorded command. An exfiltration flaw attempts a
connection to a sandbox-local sinkhole that logs it and drops it.

In every case the detection surface a scanner examines is faithful, and the
consequence if the payload succeeded is nil. If a corpus change would make a
payload more *effective* without making it more *detectable*, it is rejected.

## Sandboxing

- Every server runs inside the lab's containers. **Egress is blocked** at the
  network layer; the only reachable destination is the lab's own sinkhole.
- Servers **bind to loopback or the lab network only**. Nothing in this corpus
  is intended to be deployed on a public interface, and the compose files do not
  offer a way to do it casually.
- The lab is **ephemeral**: it is brought up for a run and torn down.
- No corpus server ever contacts a third-party service.

## No real credentials

The corpus contains planted credentials by design — A7 is an attack class. Every
one of them is synthetic.

- Values are **format-valid and, where a credential type defines one,
  checksum-valid**, so that format-aware and entropy-based detectors behave as
  they would in the field. A fake-looking secret would make the A7 measurement
  meaningless.
- No value in this repository has ever authenticated against anything. Where a
  vendor publishes reserved or test ranges, those are used.
- Phase 1 ships a **generator and a repository-wide assertion test** that fails
  CI if a credential-shaped literal appears outside the registry of known
  synthetic values.
- Contributions containing a real credential — live, expired, or revoked — are
  rejected. An expired real key is still a real key that existed.

**They are realistic enough that GitHub blocks the push.** Publishing this
repository was rejected by GitHub secret scanning, which identified the planted
`AKIA...` access key id and its 40-character secret as an Amazon AWS credential
pair.

That is the A7 design goal confirmed by a production detector rather than
asserted by us. [taxonomy.md](taxonomy.md) calls this an open tension: planted
values have to be realistic enough that format-aware and entropy-based
detectors fire, while being verifiably non-functional. A detector that ignored
them would make the A7 measurement meaningless. GitHub's does not ignore them.

The operational consequence, which anyone forking or contributing will hit:

- Publishing this corpus to GitHub requires allowing those specific detections
  through push protection. That is a deliberate, reviewable act by the
  repository owner, and that is the right place for the decision to sit.
- Do **not** resolve a blocked push by weakening a synthetic credential until
  the scanner stops noticing. That would leave the corpus looking healthy while
  A7 quietly stopped testing anything.
- Every flagged value must first be traced to
  `tools/synthetic_credentials.py`. `tools/check_no_real_credentials.py` is
  what establishes that, and it should be run and seen to pass before anything
  is allowed through.

## What we will not accept

Contributions are refused, without exception, if they:

- Target a **real, third-party, or deployed** MCP server, service, or endpoint.
- Include a **working exploit** for an unpatched vulnerability in real software.
  This corpus plants flaws in servers we wrote; it is not a vulnerability
  disclosure channel. Report those to the affected maintainers.
- Contain **live command-and-control**, beaconing, or any callback to a
  non-sandbox destination.
- Perform **credential harvesting**, or carry any real credential.
- Include **malware, destructive payloads**, persistence mechanisms, or
  anti-analysis techniques.
- Add a payload whose **harm exceeds what detection requires** — see the minimal
  payload principle.

## Using this repository

- Run the corpus **inside the provided lab**. Do not deploy these servers
  anywhere reachable, and do not install them into a real agent's tool
  configuration.
- Do not aim payloads from this corpus at servers you do not own.
- The vulnerable servers are **not examples to learn from as patterns**. Each one
  is documented with what is wrong with it; the benign controls are the ones
  written the right way.

## Dual-use, stated honestly

A library of vulnerable MCP servers is dual-use. Someone could read it as a
catalogue of techniques.

We publish anyway, for reasons we think hold up:

- **The techniques are already public.** Every class in the taxonomy is drawn
  from existing published literature on MCP attacks. The taxonomy document cites
  the vocabulary rather than inventing it. Withholding a corpus does not
  withhold the ideas.
- **The asymmetry favours defence.** An attacker does not need our corpus; they
  need one vulnerable server. A defender evaluating scanners needs a corpus, a
  method, and controls, and currently has none that are independent.
- **The alternative is worse.** The only public comparison in this category
  comes from a repository whose own tool scores 100%. The choice is not between
  a corpus and no corpus — it is between an independent one and a self-interested
  one.
- **The payloads are inert.** What we publish is not weaponized, by construction.

We would reconsider if the corpus started being used to attack rather than to
measure. Reports of misuse go to the contact in the README.

## Framing in publications

Any writeup published from this project leads with **methodology and
limitations**, not rankings, and states plainly that recall here is recall
against a small synthetic corpus rather than against real-world servers.

Given how poor the already-published figures are, results are likely to look
damning without help. Understating them is both more accurate and more credible
than amplifying them, and this is a standing editorial rule rather than a
case-by-case decision.

## Coordinated disclosure

If work on this benchmark uncovers a genuine vulnerability in a real scanner, a
real MCP server, or the MCP specification itself, it goes to the affected
maintainers privately first, with the ordinary disclosure courtesy, and it is
**not** published as a benchmark result. Measuring tools and disclosing bugs in
them are different activities, and conflating them would make maintainers
reasonably reluctant to engage with the benchmark at all.
