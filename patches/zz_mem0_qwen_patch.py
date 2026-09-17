"""Runtime fixes for mem0-mcp-selfhosted, loaded via a .pth at startup.

Nothing in the upstream package is edited, so a reinstall cannot lose these and
the pinned commit stays byte-identical to what was reviewed.

1. think=False for reasoning models
-----------------------------------
mem0 sends options.num_predict (2000). Reasoning models such as qwen3 spend that
whole budget in their *thinking* channel, which Ollama strips from
message.content, so the call returns done_reason="length" with EMPTY content and
mem0 extracts zero facts. The upstream wrapper appends "/no_think" to the prompt
TEXT, which does not work on Ollama 0.21+. The API-level think=False does.

Measured on mem0's real FACT_RETRIEVAL_PROMPT, 3 inputs:
    qwen2.5:3b-instruct  3/3 valid JSON
    qwen3:4b             1/3
Prefer a non-thinking instruct model; this is the safety net.
Opt out: MEM0_OLLAMA_THINK=true

2. Engineering-oriented fact extraction prompt
----------------------------------------------
mem0's built-in prompt opens "You are a Personal Information Organizer ...
facts, user memories, and preferences". Measured: personal preferences extract
fine, technical statements return an EMPTY list, which makes the whole layer
silently useless for engineering context.
Set MEM0_FACT_PROMPT_FILE to override. Unset = mem0's default.

3. delete_all_memories empty-scope guard
----------------------------------------
Upstream server.py:334 computes `uid = user_id or get_default_user_id()` and
only THEN checks `if not any([uid, agent_id, run_id])`. get_default_user_id()
never returns empty, so the guard is unreachable and its error string is dead
code - while the docstring promises "Requires at least one filter." A no-arg
call therefore wipes the entire default user scope. Sibling delete_entities
checks the RAW params and is correct; the two disagree.
Opt out: MEM0_ALLOW_UNSCOPED_DELETE_ALL=true (must be a real env var - this
module loads from a .pth at interpreter startup, so setting it from inside
Python is too late).

4. Default agent_id from MEM0_AGENT_ID
--------------------------------------
Upstream has no notion of which agent wrote a memory, so the store is a flat
pile with no attribution. Setting agent_id does NOT partition it - verified: a
search by user_id alone returns memories from every agent, while passing
agent_id narrows to one. Attribution is free; sharing is unaffected.
Set MEM0_AGENT_ID per client (e.g. claude-code, kiro). Unset = no attribution.
"""

import os

_THINKING_MODELS = ("qwen3", "deepseek-r1", "qwq", "magistral", "phi4-reasoning")


def _truthy(name):
    return os.environ.get(name, "").lower() in ("true", "1", "yes")


def _wrap_create_server(flag, wrapper):
    """Wrap srv._create_server once, applying `wrapper` to the built server."""
    try:
        from mem0_mcp_selfhosted import server as srv
    except Exception:
        return
    if getattr(srv, flag, False):
        return
    original = srv._create_server

    def _create_server():
        server = original()
        try:
            wrapper(server)
        except Exception:
            pass
        return server

    srv._create_server = _create_server
    setattr(srv, flag, True)


def _patch_ollama_think():
    if _truthy("MEM0_OLLAMA_THINK"):
        return
    try:
        import ollama
    except Exception:
        return
    cls = getattr(ollama, "Client", None)
    if cls is None or getattr(cls, "_mem0_think_patched", False):
        return
    original = cls.chat

    def chat(self, *args, **kwargs):
        model = kwargs.get("model") or (args[0] if args else "")
        if isinstance(model, str) and "think" not in kwargs:
            if any(model.startswith(p) for p in _THINKING_MODELS):
                kwargs["think"] = False
        try:
            return original(self, *args, **kwargs)
        except TypeError:
            kwargs.pop("think", None)
            return original(self, *args, **kwargs)

    cls.chat = chat
    cls._mem0_think_patched = True


def _patch_fact_prompt():
    path = os.environ.get("MEM0_FACT_PROMPT_FILE")
    if not path or not os.path.isfile(path):
        return
    try:
        text = open(path, encoding="utf-8").read()
        from mem0_mcp_selfhosted import config as cfg
    except Exception:
        return
    if getattr(cfg, "_mem0_prompt_patched", False):
        return
    original = cfg.build_config

    def build_config():
        config_dict, providers, split = original()
        config_dict["custom_fact_extraction_prompt"] = text
        return config_dict, providers, split

    cfg.build_config = build_config
    cfg._mem0_prompt_patched = True


def _patch_delete_guard():
    if _truthy("MEM0_ALLOW_UNSCOPED_DELETE_ALL"):
        return

    def apply(server):
        import json
        tool = server._tool_manager._tools.get("delete_all_memories")
        if tool is None:
            return
        inner = tool.fn

        def guarded(user_id=None, agent_id=None, run_id=None, **kwargs):
            if not any([user_id, agent_id, run_id]):
                return json.dumps(
                    {"error": "At least one scope (user_id, agent_id, or run_id) "
                              "is required. Refusing to delete an unscoped set."},
                    ensure_ascii=False,
                )
            return inner(user_id=user_id, agent_id=agent_id, run_id=run_id, **kwargs)

        guarded.__name__ = getattr(inner, "__name__", "delete_all_memories")
        guarded.__doc__ = getattr(inner, "__doc__", None)
        tool.fn = guarded

    _wrap_create_server("_mem0_delete_guard_patched", apply)


def _patch_default_agent():
    agent = os.environ.get("MEM0_AGENT_ID", "").strip()
    if not agent:
        return

    def apply(server):
        tool = server._tool_manager._tools.get("add_memory")
        if tool is None:
            return
        inner = tool.fn

        def tagged(*args, **kwargs):
            if not kwargs.get("agent_id"):
                kwargs["agent_id"] = agent
            return inner(*args, **kwargs)

        tagged.__name__ = getattr(inner, "__name__", "add_memory")
        tagged.__doc__ = getattr(inner, "__doc__", None)
        tool.fn = tagged

    _wrap_create_server("_mem0_agent_patched", apply)


_patch_ollama_think()
_patch_fact_prompt()
_patch_delete_guard()
_patch_default_agent()
