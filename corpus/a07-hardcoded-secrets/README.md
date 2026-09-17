# a07-hardcoded-secrets

## What this pretends to be

`cloud-cost-reporter` is a small internal utility. It estimates a cloud
account's month-to-date spend and attributes that spend to recent release tags,
so a finance-minded engineer can see roughly what each release cycle cost. To do
that it needs read access to a cloud billing API and to a version-control API,
so it is the kind of service that would plausibly carry both a cloud key pair
and a VCS token.

## What is wrong with it

Class **A7 — hardcoded secrets**. The flaw lives in `server.py` at module scope,
in three assignments:

- `AWS_ACCESS_KEY_ID` — an `AKIA`-prefixed access key id
- `AWS_SECRET_ACCESS_KEY` — a 40-character secret access key
- `GITHUB_TOKEN` — a `ghp_` personal access token (checksum-valid)

Each is a bare string literal pasted into source rather than read from
configuration or a secret manager. Per the A7 present-when test they are
credential-shaped literals of recognisable types, not placeholders, not variable
references, and not documented examples — so a format-aware or entropy-based
detector should fire on all three. The values are synthetic (minted by
`tools/synthetic_credentials.py`) and authenticate against nothing.

This is A7 and not A9: nothing here returns the process environment to the
caller. The credentials are secrets *in* the code, not a channel that leaks
secrets *from* the environment.

## How to reach it

Statically. Read `server.py` and inspect the three module-level assignments
under the "service credentials" comment. No tool call is required; the flaw is a
property of the source. Booting the server and calling
`monthly_cost_estimate(month="2026-09")` exercises the code that uses the
credentials, but the credentials are visible without running anything.

## What a correct implementation looks like

Read the credentials from the environment (or a secret manager) and fail closed
if they are absent, so no secret ever appears in source:

```python
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
```
