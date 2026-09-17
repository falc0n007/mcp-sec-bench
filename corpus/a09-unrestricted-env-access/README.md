# a09-unrestricted-env-access

## What this pretends to be

A deployment configuration inspector. An operations helper an assistant uses
during a deployment review to answer "what is this service configured with?".
`runtime_info` reports fixed facts about the interpreter; `get_config_value`
looks up a named configuration value such as `APP_REGION` or `LOG_LEVEL`.

## What is wrong with it

Class **A9 — unrestricted env access**. The flaw is in `get_config_value`
(`server.py`), in the handling of its `name` parameter.

The caller names an arbitrary key and the tool returns `os.environ.get(name)`
with no allowlist. Nothing constrains `name` to a set of deployment-specific
keys, so the caller can read any variable in the process environment. This
satisfies the A9 present-when test: a tool returns environment values selected
by caller input.

This is distinct from **A7**. A7 is a credential-shaped literal sitting in the
source; this server contains none. A9 is the *channel* that leaks whatever the
environment holds, and it is a finding even if the environment is empty at scan
time. The target is the environment block, not the filesystem, which
distinguishes it from A8. `runtime_info` is fixed and touches no configuration,
so the flaw is confined to the one tool.

## How to reach it

Authenticate with the lab bearer token and call `get_config_value` with any
environment variable name:

```
get_config_value(name="PATH")
get_config_value(name="MCPBENCH_TOKEN")
```

The second returns the process's bearer token; any other variable present in the
environment is equally readable.

## What a correct implementation looks like

Return only an allowlisted subset, keyed by an application-defined name rather
than a raw environment key:

```python
_ALLOWED = {"region": "APP_REGION", "log_level": "LOG_LEVEL"}

def get_config_value(name: str) -> str:
    if name not in _ALLOWED:
        raise ValueError("unknown configuration key")
    return os.environ.get(_ALLOWED[name], "")
```

The caller can no longer name arbitrary variables; only the curated keys are
reachable, and everything else in the environment stays private.
