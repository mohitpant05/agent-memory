# Architecture — the layers

```
┌─ L1  CLIENTS ─────────────────────────────────────────────────────┐
│  Claude Code (Opus 5)          Kiro                               │
│  Both speak MCP. Both do ALL your reasoning. Neither is replaced  │
│  or downgraded by anything below.                                 │
└───────────────────────────┬───────────────────────────────────────┘
                            │ MCP  (stdio locally, HTTP remotely)
┌─ L2  MCP SERVER ──────────▼───────────────────────────────────────┐
│  mem0-mcp-selfhosted  — 11 tools                                  │
│    add_memory  search_memories  get_memories  get_memory          │
│    update_memory  delete_memory  delete_all_memories              │
│    list_entities  delete_entities  search_graph  get_entity       │
│  Translates tool calls into mem0ai library calls.                 │
└───────────────────────────┬───────────────────────────────────────┘
                            │
┌─ L3  MEMORY ENGINE ───────▼───────────────────────────────────────┐
│  mem0ai (1.x)                                                     │
│   add:    text ──▶ EXTRACT facts ──▶ compare to existing ──▶      │
│                                      ADD / UPDATE / DELETE        │
│   search: query ──▶ embed ──▶ vector search ──▶ ranked facts      │
└───────┬───────────────────────────────────────┬───────────────────┘
        │                                       │
┌─ L4a  EXTRACTION LLM ─────┐   ┌─ L4b  EMBEDDER ───────────────────┐
│  qwen2.5:3b-instruct      │   │  bge-m3, 1024 dims                │
│  via Ollama, local        │   │  via Ollama, local                │
│  Prose ──▶ JSON facts     │   │  Text ──▶ vector                  │
│  NEVER talks to you       │   │  Used on both write and read      │
└───────────────────────────┘   └───────────────┬───────────────────┘
                                                │
┌─ L5  STORAGE ──────────────────────────────────▼──────────────────┐
│  Qdrant (Docker) — collection mem0_shared                         │
│  Volume mem0-qdrant. Survives container destruction.              │
│  (Neo4j graph layer optional, disabled by default.)               │
└───────────────────────────────────────────────────────────────────┘
```

## What runs where

| Layer | macOS | Linux box |
|-------|-------|-----------|
| L1 clients | native | native (or remote over tunnel) |
| L2 server | host venv, **stdio** | host venv, **systemd + HTTP** |
| L4 Ollama | host (Metal GPU) | host + systemd (NVIDIA GPU) |
| L5 Qdrant | **Docker** | **Docker** |

Only Qdrant is containerised. Ollama stays on the host in both cases so it can
reach the GPU: on macOS Docker Desktop is a VM with no Metal access, and on
Linux keeping it on the host avoids needing nvidia-container-toolkit at all.

## The read and write paths

**Write** — `add_memory("we pinned mcp<2 because 2.x renamed FastMCP")`
1. L2 receives the tool call
2. L3 sends the text to L4a with the extraction prompt
3. L4a returns `{"facts": ["This project pins mcp<2", "mcp 2.x renamed FastMCP"]}`
4. L3 embeds each fact via L4b, compares against existing memories
5. L3 issues ADD / UPDATE / DELETE into L5

**Read** — `search_memories("why is mcp pinned?")`
1. L4b embeds the query
2. L5 returns nearest facts by cosine similarity
3. L2 hands them back as tool output
4. **L1 (Opus 5) reasons over them** — the small model is not involved

## Two things this is NOT

- **Not session persistence.** Claude Code already stores transcripts in
  `~/.claude/projects/<slug>/*.jsonl` and replays them with `--resume`. That is
  untouched and works whether or not any of this is running.
- **Not a replacement for hand-curated project notes.** If you keep such notes,
  let them stay authoritative for project specifics and let this layer carry
  cross-tool, cross-repo context. Two stores that drift are worse than one.

## Failure behaviour

Every layer below L1 can die without breaking Claude Code. The MCP tools simply
become unavailable; transcripts, `--resume`, `CLAUDE.md` and the curated memory
files are all unaffected.


## Seeing it

    ./memory-layer graph

Writes a self-contained `memory-graph.html` (no external requests) showing each
agent, how many facts it wrote, and the single store they all read from.

Attribution comes from `agent_id`, which the wiring sets per client
(`claude-code`, `kiro`). Memories written before attribution existed show as
`unattributed`.

**Attribution is not access control.** `agent_id` records who *wrote* a fact; a
search scoped to the user returns every agent's facts regardless. Verified:

    search by user_id only              -> 2 hits (both agents)
    search by user_id + agent_id=kiro   -> 1 hit  (narrowed)

That asymmetry is the whole mechanism. Writes are attributable, reads are
shared — which is what makes the store genuinely common rather than two private
piles that happen to live in one database.
