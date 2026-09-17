# Troubleshooting

Every entry here was hit for real during setup, with the cause verified.

## `add_memory` returns 0 facts / search finds nothing

**Most likely: mem0's default extraction prompt.** It opens with *"You are a
Personal Information Organizer ... facts, user memories, and preferences"*.
Measured behaviour:

    "I prefer dark roast coffee, I work as a software engineer"
        -> ['Prefers dark roast coffee', 'Works as a software engineer']
    "The batch scheduler fix raised successfully placed jobs from 232 to 247"
        -> []

It discards technical statements. Fix: set `MEM0_FACT_PROMPT_FILE` to
`patches/fact_prompt.txt` (an engineering-oriented prompt). The patch in
`patches/zz_mem0_qwen_patch.py` injects it via `custom_fact_extraction_prompt`.

Check it is active:

    grep MEM0_FACT_PROMPT_FILE .env
    ls -l venv/lib/python3.*/site-packages/zz_mem0_qwen_patch.pth

## `Empty or invalid JSON from Ollama, retrying once`

**Cause: a reasoning model.** mem0 sends `options.num_predict=2000`. qwen3 and
friends spend that entire budget in the *thinking* channel, which Ollama strips
from `message.content`. The response comes back `done_reason="length"` with an
empty string.

Verified by hand:

    options {num_predict:2000, ...}                -> '' , done=length
    same + "think": false                          -> valid JSON, done=stop
    no options at all                              -> valid JSON, done=stop

The wrapper's `/no_think` *text* injection does not work on Ollama 0.21+; the
API-level `think=False` does, and the patch supplies it.

But the real fix is model choice. Measured on mem0's actual prompt, 3 inputs:

| model | valid JSON |
|-------|-----------|
| qwen2.5:3b-instruct | 3/3 |
| qwen3:4b | 1/3 |

qwen3 also degenerates into a whitespace loop mid-object and never closes the
JSON. **Use a non-thinking instruct model.** Avoid qwen3, deepseek-r1, qwq.

## Extraction runs forever / `Unterminated string` / `done_reason=length`

The wrapper appends `" /no_think"` to the last user message for **every** Ollama
model. On a non-thinking instruct model that is not a control directive, just
text, and it derails generation. Measured on qwen2.5:3b-instruct with mem0's
real prompt and identical options:

    plain prompt            -> valid JSON, 2 facts
    + " /no_think"          -> never terminates
                               5220 chars at num_predict=2000
                               20820 chars at num_predict=8000

So the workaround for reasoning models breaks the models you should be using.
`patches/` strips the injection for any model not in the thinking list; the
API-level `think=False` already handles the reasoning ones properly.

Symptom in the logs is a truncated JSON parse error such as
`Error in new_retrieved_facts: Unterminated string starting at: line 1
column 5217`.

## `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`

Upstream declares `mcp[cli]>=1.23.0` with **no upper bound**, but MCP SDK 2.x
renamed `FastMCP` to `MCPServer`. A fresh unpinned install resolves to 2.x and
cannot import at all. Last working version: `mcp 1.30.0`.

Fix: install with `"mcp[cli]>=1.23,<2"`. Both installers already do.

## `Top-level entity parameters ... are not supported in search()`

Same class of bug. `mem0ai>=1.0.3` unbounded resolves to 2.x, which moved
`search(user_id=...)` to `search(filters={'user_id': ...})`. The wrapper's
`hooks.py:130` still calls the old form — so **the session hooks are broken
against mem0ai 2.x**, not just ad-hoc scripts.

Fix: pin `"mem0ai[llms]>=1.0.3,<2"`.

## `Error: pg_config executable not found` / `ld: library 'ssl' not found`

`mem0ai[graph]` pulls `apache-age-python` → `psycopg2`, which is source-only.
The wrapper **never imports it** — graph is disabled — so do not fight the
build. Install `mem0ai[llms]` instead of `[graph,llms]`, and install the
wrapper with `--no-deps`. Both installers do this.

## `A virtual environment already exists at: venv`

A failed install leaves the directory behind and `uv venv` will not overwrite
it. Both installers now pass `--clear`. Manually: `rm -rf venv`.

## Models re-pull on every run

`ollama list` prints `bge-m3:latest`; a bare `grep -qx bge-m3` never matches.
Both installers normalise the `:latest` suffix before comparing.

## Server connects but tools error with "Memory not initialized"

Infrastructure is unreachable. Check in order:

    curl -s http://localhost:6333/healthz      # Qdrant
    curl -s http://localhost:11434/api/version # Ollama
    ollama list                                # models actually present

## `delete_all_memories` with no arguments wipes everything

Upstream bug (`server.py:334`): it computes `uid = user_id or
get_default_user_id()` and only THEN checks `if not any([uid, agent_id,
run_id])`. `get_default_user_id()` never returns empty, so the guard is
unreachable and its error string is dead code — while the docstring promises
"Requires at least one filter." Sibling `delete_entities:388` checks the raw
params and is correct; the two disagree.

`patches/zz_mem0_qwen_patch.py` restores the documented behaviour by wrapping
the registered tool. Verified to discriminate:

    guard on,  no args        -> refuses, 2 memories survive
    guard off, no args        -> deletes 2 (bug reproduced)
    guard on,  explicit scope -> deletes 6 as intended

Escape hatch: `MEM0_ALLOW_UNSCOPED_DELETE_ALL=true`. It must be a real
environment variable — the patch loads via a `.pth` at interpreter startup, so
setting it from inside Python is too late.

## Patch not installed -> extraction silently returns nothing

The installers locate `patches/` by searching `./patches`, `../patches`,
`patches`, `~/patches`, `/opt/mem0/patches` and **abort** if absent,
because a missing patch fails silently at runtime rather than loudly at install.
They also rewrite `MEM0_FACT_PROMPT_FILE` in `.env` to the resolved path, so the
prompt file is found on whatever machine you installed on.

## Claude Code hook timeouts

SessionStart hooks time out at 15s, Stop at 30s. A *refused* connection fails
instantly; a *hung* one (sleeping server, dropped VPN) burns the full timeout
at every session start. The tunnel template sets `ConnectTimeout=5` for this
reason. Do not install hooks until the endpoint has been stable for a while.

## Wiping everything and starting over

    docker compose down -v          # destroys the volume and all memories
    rm -rf venv
    ./memory-layer                        # or ./memory-layer on Linux

To clear memories but keep the install:

    curl -X DELETE http://localhost:6333/collections/mem0_shared
