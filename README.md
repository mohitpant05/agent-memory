# agent-memory

A local, self-hosted semantic memory layer shared between AI coding agents —
Claude Code, Kiro, or any other MCP client.

Everything runs on your machine. No API key, no cloud, no network egress.

```
    Claude Code ──┐                        ┌── facts, not transcripts
                  ├──▶ MCP ──▶ mem0 ──▶ Qdrant
    Kiro ─────────┘              │
                                 └── local LLM extracts, local model embeds
```

Tell one agent something; the other can recall it. Weeks later, in a different
repository.

## Quick start

    git clone https://github.com/mohitpant05/agent-memory.git
    cd agent-memory
    ./memory-layer up

That detects your platform, installs what is missing, starts the stack, proves
it works end to end, and registers it with your MCP clients. The first run
writes `.env` and pauses so you can review it.

    ./memory-layer verify    prove it works, over the real MCP protocol
    ./memory-layer graph     render the shared store as a local HTML page
    ./memory-layer doctor    diagnose a broken setup
    ./memory-layer status    what is running
    ./memory-layer stop      stop it (memories survive)

Platform guides: [macOS](docs/macos.md) · [Linux](docs/linux.md) ·
[Windows/WSL2](docs/windows.md) · [Troubleshooting](docs/troubleshooting.md)

## What it is

| Layer | Piece | Job |
|-------|-------|-----|
| Clients | Claude Code, Kiro | all reasoning — unchanged, not downgraded |
| Protocol | mem0-mcp-selfhosted | 11 MCP tools, scoping, guards |
| Engine | mem0ai | extract facts, dedupe, ADD/UPDATE/DELETE |
| Models | qwen2.5:3b-instruct, bge-m3 | prose → facts; text → vectors |
| Storage | Qdrant | vectors on a named volume |

[Full architecture](docs/architecture.md), including how cross-agent sharing
actually works and why a dead memory layer cannot break your agent.

## What it is not

- **Not session persistence.** Claude Code already stores transcripts and
  replays them with `--resume`. That is independent and unaffected if this is
  down. This layer is strictly additive.
- **Not a model swap.** The small local model only turns prose into stored
  facts. It never joins your conversation.

## Design notes

Only Qdrant is containerised. Ollama stays on the host so it can reach the GPU —
Docker Desktop on macOS has no Metal access, and on Linux this removes the
nvidia-container-toolkit dependency entirely.

Three upstream defects are fixed at runtime rather than by editing the package,
so the pinned commit stays byte-identical to what was reviewed. Each one fails
*silently* — tools report success while storing nothing. See
[patches/](patches/).

Dependencies are pinned below 2.x. `mcp` and `mem0ai` both shipped breaking
releases after the wrapper's pinned commit; unpinned installs do not import. CI
asserts the ceilings are still there.

## Security

The HTTP transport (Linux/remote) has **no inbound authentication**. Anyone who
can reach the port gets full read/write/delete on every memory. Bind loopback
and tunnel, or use a tailnet IP — the installer refuses `0.0.0.0`.

On the client side, Kiro is configured with `disabledTools` blocking the two
destructive tools. Claude Code has no equivalent, so there the protection is the
permission prompt.

## Credit

Wraps [elvismdev/mem0-mcp-selfhosted](https://github.com/elvismdev/mem0-mcp-selfhosted)
(MIT) over [mem0ai](https://github.com/mem0ai/mem0). This repository is the
installer, the platform integration, the runtime fixes and the docs.

## License

MIT
