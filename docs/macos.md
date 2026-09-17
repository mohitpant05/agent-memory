# macOS

Tested on Apple Silicon (M5, 16GB, macOS 26).

## Install

    git clone https://github.com/mohitpant05/agent-memory.git
    cd agent-memory
    ./memory-layer up

`up` runs install → start → verify → wire. The first `install` writes `.env`
from the platform defaults and stops so you can review it; run it again to
continue.

Missing dependencies (Homebrew, docker, ollama, uv) are installed for you.
Docker Desktop needs one manual launch the first time.

## What it puts where

| Piece | Where | Why |
|-------|-------|-----|
| Qdrant | Docker, `127.0.0.1:6333` | stateful, wants a volume |
| Ollama | host | Docker Desktop is a VM with no Metal access |
| MCP server | `./venv`, stdio | launched on demand by the client |

## Resource use

| | Disk | RAM |
|---|---|---|
| Qdrant container | ~250MB | ~360MB measured |
| bge-m3 | 1.2GB | ~1.5GB when loaded |
| qwen2.5:3b-instruct | 1.9GB | ~2.5GB when loaded |
| venv | ~400MB | — |

Models unload after 30 minutes idle.

## Everyday

    ./memory-layer status
    ./memory-layer stop      # memories survive
    ./memory-layer doctor    # when something is wrong
