# Runtime patches

Three defects in the upstream wrapper / mem0ai make a local setup fail
**silently** — the tools return success while storing nothing. These are fixed
at runtime by `zz_mem0_qwen_patch.py`, which the installer drops into the venv's
`site-packages` alongside a `.pth` file so it loads at interpreter startup.

Nothing in the upstream package is edited, so a reinstall cannot lose the fixes
and the pinned commit stays byte-identical to what was reviewed.

## 1. Reasoning models return empty content

mem0 sends `options.num_predict=2000`. Reasoning models (qwen3, deepseek-r1,
qwq) spend that whole budget in their *thinking* channel, which Ollama strips
from `message.content`. The response arrives `done_reason="length"` with an
empty string, and mem0 extracts zero facts.

The upstream wrapper appends `/no_think` to the prompt **text**, which does not
work on Ollama 0.21+. The API-level `think=False` does.

Measured against mem0's real `FACT_RETRIEVAL_PROMPT`, 3 inputs:

| model | valid JSON |
|-------|-----------|
| qwen2.5:3b-instruct | 3/3 |
| qwen3:4b | 1/3 |

Prefer a non-thinking instruct model. This patch is the safety net.
Opt out: `MEM0_OLLAMA_THINK=true`.

## 2. mem0's default prompt discards technical facts

`FACT_RETRIEVAL_PROMPT` opens *"You are a Personal Information Organizer ...
facts, user memories, and preferences"*. Measured:

    "I prefer dark roast coffee, I work as a software engineer"
        -> ["Prefers dark roast coffee", "Works as a software engineer"]
    "The repair tag prefilter fix moved placed tasks from 232 to 247"
        -> []

Engineering statements return an **empty list**. For a memory layer whose
purpose is engineering context, that is a silent total failure.

`fact_prompt.txt` replaces it via `custom_fact_extraction_prompt`.
Point `MEM0_FACT_PROMPT_FILE` at it (the installer does this automatically).

## 3. `delete_all_memories` ignores its own empty-scope guard

Upstream `server.py:334`:

```python
uid = user_id or get_default_user_id()   # never empty
if not any([uid, agent_id, run_id]):     # therefore never True
    return {"error": "At least one scope ... is required."}   # dead code
```

The docstring promises *"Requires at least one filter."* It does not enforce it,
so a no-argument call wipes the entire default user scope. The sibling
`delete_entities` checks the **raw** params and is correct — the two disagree,
which is what makes this a bug rather than a design choice.

This patch restores the documented behaviour by wrapping the registered tool.
Verified to discriminate:

    guard on,  no args        -> refuses, 2 memories survive
    guard off, no args        -> deletes 2   (bug reproduced)
    guard on,  explicit scope -> deletes 6   (intended path still works)

Opt out: `MEM0_ALLOW_UNSCOPED_DELETE_ALL=true`. It must be a **real environment
variable** — the patch loads from a `.pth` at interpreter startup, so setting it
from inside Python is too late.
