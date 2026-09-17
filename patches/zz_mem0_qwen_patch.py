"""Two runtime fixes for mem0-mcp-selfhosted, applied via a .pth at startup.

1. think=False on Ollama chat calls for reasoning models
-------------------------------------------------------
mem0's extraction sends options.num_predict (2000). Reasoning models such as
qwen3 spend that entire budget in their *thinking* channel, which Ollama strips
from message.content, so the call returns done_reason="length" with EMPTY
content and mem0 extracts zero facts. The upstream wrapper appends "/no_think"
to the prompt text, which does not work on Ollama 0.21+ (verified). The
API-level think=False does.

Measured on mem0's real FACT_RETRIEVAL_PROMPT, 3 inputs:
    qwen3:4b             1/3 valid JSON
    qwen2.5:3b-instruct  3/3 valid JSON
Non-thinking models are preferred here; this patch is the safety net.

Set MEM0_OLLAMA_THINK=true to opt back into thinking.

2. Engineering-oriented fact extraction prompt
----------------------------------------------
mem0's built-in prompt opens "You are a Personal Information Organizer ...
facts, user memories, and preferences". Measured: personal preferences extract
fine, technical statements return an EMPTY list -
    "The VRP repair tag prefilter fix moved placed tasks 232 -> 247"  ->  []
which makes the memory layer silently useless for engineering context.

Set MEM0_FACT_PROMPT_FILE to override. Unset = mem0's default.

3. delete_all_memories empty-scope guard (upstream bug)
-------------------------------------------------------
server.py:334 computes `uid = user_id or get_default_user_id()` and THEN checks
`if not any([uid, agent_id, run_id])`. get_default_user_id() never returns
empty, so the guard is unreachable and its error string is dead code - while
the docstring promises "Requires at least one filter." A no-argument call
therefore wipes the entire default user scope instead of refusing.

Sibling delete_entities:388 checks the RAW params and is correct; the two
disagree, which is what makes this a bug rather than a design choice.

This patch restores the documented behaviour: an explicit scope is required.
Set MEM0_ALLOW_UNSCOPED_DELETE_ALL=true to opt out.
"""

import os

_THINKING_MODELS = ("qwen3", "deepseek-r1", "qwq", "magistral", "phi4-reasoning")


def _wants_think():
    return os.environ.get("MEM0_OLLAMA_THINK", "").lower() in ("true", "1", "yes")


def _patch_ollama_think():
    if _wants_think():
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
    except Exception:
        return
    try:
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
    if os.environ.get("MEM0_ALLOW_UNSCOPED_DELETE_ALL", "").lower() in ("true", "1", "yes"):
        return
    try:
        from mem0_mcp_selfhosted import server as srv
    except Exception:
        return
    if getattr(srv, "_mem0_delete_guard_patched", False):
        return
    original_create = srv._create_server

    def _create_server():
        server = original_create()
        try:
            tool = server._tool_manager._tools.get("delete_all_memories")
            if tool is None:
                return server
            inner = tool.fn

            def guarded(user_id=None, agent_id=None, run_id=None, **kwargs):
                if not any([user_id, agent_id, run_id]):
                    import json as _json
                    return _json.dumps(
                        {"error": "At least one scope (user_id, agent_id, or run_id) "
                                  "is required. Refusing to delete an unscoped set."},
                        ensure_ascii=False,
                    )
                return inner(user_id=user_id, agent_id=agent_id, run_id=run_id, **kwargs)

            guarded.__name__ = getattr(inner, "__name__", "delete_all_memories")
            guarded.__doc__ = getattr(inner, "__doc__", None)
            tool.fn = guarded
        except Exception:
            pass
        return server

    srv._create_server = _create_server
    srv._mem0_delete_guard_patched = True


_patch_ollama_think()
_patch_fact_prompt()
_patch_delete_guard()
