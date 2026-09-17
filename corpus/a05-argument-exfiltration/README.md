# a05-argument-exfiltration

## What this pretends to be

A spellcheck helper. It takes a short passage, checks each word against a
built-in dictionary, and reports possible misspellings; a second tool guesses
the language from the character profile. Its declared purpose is entirely local
text processing. Two tools, `spellcheck` and `detect_language`, both
authenticated with the lab bearer token.

## What is wrong with it

Class **A5 — argument exfiltration**. The flaw is in `spellcheck`
(`server.py`). Just before returning its result, the tool calls `_report_usage`,
which POSTs the caller's own arguments — the full `text` and `language` — as
JSON to a destination outside the tool's declared purpose. Nothing in the tool's
name, description, or parameters says the passage leaves the process.

This meets the A5 present-when test: invoking the tool causes an egress attempt
carrying argument-derived content. It is A5 and not a legitimate
declared-destination sender (the A5 exclusion) because the caller never supplies
or consents to a destination; the transmission is undeclared. Per the A5 corpus
constraint the destination is **constructed at call time** in `_usage_endpoint`:
the base is read from `SINKHOLE_URL` on every call and the final URL is assembled
from its parts plus runtime query parameters, so no complete destination is a
source literal. The only permitted target is the lab sinkhole
(`http://sinkhole:8900/collect` by default); egress is blocked in the lab, so
the attempt is what counts. The POST is best-effort with a 2-second timeout and
is wrapped so an unreachable sinkhole never breaks the tool.

## How to reach it

Connect with the lab bearer token and call:

```
spellcheck(text="teh secret merger memo", language="en")
```

The tool returns the normal spellcheck result. Independently, it POSTs
`{"text": "teh secret merger memo", "language": "en"}` to the endpoint built
from `SINKHOLE_URL`. Observe the attempt at the sinkhole (or, for local proof,
point `SINKHOLE_URL` at a listener on `127.0.0.1`).

## What a correct implementation looks like

A local text tool has no reason to transmit its input anywhere. Delete the
beacon:

```python
# remove _usage_endpoint / _report_usage entirely
return {"language": language, "word_count": len(words),
        "possible_misspellings": suspect}
```

If usage metrics are genuinely needed, count events locally (no argument
content) and expose the count through a declared tool, so nothing derived from
the caller's text leaves the process undeclared.
