"""Render the shared memory store as a self-contained HTML page.

Reads Qdrant directly (scroll API) rather than going through MCP, so it works
even when no agent is connected. Output has no external requests of any kind.

The point it is trying to make: every memory in the store is readable by every
agent. agent_id records who WROTE a memory, not who may read it.
"""

import html
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

QDRANT = os.environ.get("MEM0_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("MEM0_COLLECTION", "mem0_shared")
USER = os.environ.get("MEM0_USER_ID", "user")


def scroll():
    points, offset = [], None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        req = urllib.request.Request(
            f"{QDRANT}/collections/{COLLECTION}/points/scroll",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception as exc:
            sys.exit(f"Could not read Qdrant at {QDRANT}: {exc}")
        result = res.get("result", {})
        points.extend(result.get("points", []))
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return points


def fmt_time(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def build(points):
    rows = []
    for p in points:
        pl = p.get("payload") or {}
        rows.append({
            "id": str(p.get("id", ""))[:8],
            "text": pl.get("data") or pl.get("memory") or "",
            "agent": pl.get("agent_id") or "unattributed",
            "user": pl.get("user_id") or "",
            "created": fmt_time(pl.get("created_at")),
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    return rows


def svg(rows):
    """Bipartite diagram: agents on the left, the shared store on the right."""
    agents = Counter(r["agent"] for r in rows)
    if not agents:
        return '<p class="empty">No memories yet.</p>'
    order = sorted(agents.items(), key=lambda kv: (-kv[1], kv[0]))
    h = max(220, 90 + len(order) * 78)
    store_y = h / 2
    parts = [
        f'<svg viewBox="0 0 760 {h}" role="img" '
        f'aria-label="Agents writing into one shared memory store">',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>',
    ]
    for i, (name, count) in enumerate(order):
        y = 60 + i * 78
        parts.append(
            f'<rect class="agent" x="24" y="{y - 22}" rx="10" width="212" height="44"/>'
            f'<text class="agent-label" x="130" y="{y - 2}">{html.escape(name)}</text>'
            f'<text class="agent-sub" x="130" y="{y + 15}">wrote {count}</text>'
            f'<path class="link" d="M244,{y} C 360,{y} 380,{store_y} 500,{store_y}" '
            f'marker-end="url(#a)"/>'
        )
    parts.append(
        f'<rect class="store" x="504" y="{store_y - 48}" rx="12" width="228" height="96"/>'
        f'<text class="store-label" x="618" y="{store_y - 16}">shared store</text>'
        f'<text class="store-count" x="618" y="{store_y + 14}">{len(rows)}</text>'
        f'<text class="store-sub" x="618" y="{store_y + 34}">'
        f'facts, all readable by every agent</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render(rows):
    agents = Counter(r["agent"] for r in rows)
    by_agent = defaultdict(list)
    for r in rows:
        by_agent[r["agent"]].append(r)
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")

    chips = "".join(
        f'<span class="chip"><b>{html.escape(a)}</b> {n}</span>'
        for a, n in sorted(agents.items(), key=lambda kv: (-kv[1], kv[0]))
    ) or '<span class="chip muted">no memories</span>'

    trs = "".join(
        f'<tr><td class="c-agent"><span class="dot d{abs(hash(r["agent"])) % 6}"></span>'
        f'{html.escape(r["agent"])}</td>'
        f'<td class="c-text">{html.escape(r["text"])}</td>'
        f'<td class="c-time">{html.escape(r["created"])}</td></tr>'
        for r in rows
    ) or ('<tr><td colspan="3" class="empty">Nothing stored yet. '
          'Ask an agent to remember something, then re-run.</td></tr>')

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-memory — shared store</title>
<style>
  :root {{
    --bg:#fbfbfa; --fg:#1a1a18; --muted:#6b6b64; --line:#e3e2dd;
    --card:#fff; --accent:#4a6fa5; --store:#3f7d6a;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#16161a; --fg:#e8e8e4; --muted:#9a9a92; --line:#2c2c33;
             --card:#1e1e24; --accent:#7ea2d4; --store:#69b096; }}
  }}
  :root[data-theme="dark"] {{ --bg:#16161a; --fg:#e8e8e4; --muted:#9a9a92;
    --line:#2c2c33; --card:#1e1e24; --accent:#7ea2d4; --store:#69b096; }}
  :root[data-theme="light"] {{ --bg:#fbfbfa; --fg:#1a1a18; --muted:#6b6b64;
    --line:#e3e2dd; --card:#fff; --accent:#4a6fa5; --store:#3f7d6a; }}

  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:40px 20px 72px; }}
  h1 {{ font-size:24px; margin:0 0 6px; letter-spacing:-.01em; }}
  .sub {{ color:var(--muted); margin:0 0 28px; font-size:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line);
    border-radius:14px; padding:20px; margin-bottom:22px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:4px; }}
  .chip {{ border:1px solid var(--line); border-radius:999px;
    padding:5px 12px; font-size:13px; }}
  .chip.muted {{ color:var(--muted); }}
  .note {{ font-size:13.5px; color:var(--muted); margin:14px 0 0;
    border-left:2px solid var(--line); padding-left:12px; }}

  svg {{ width:100%; height:auto; display:block; }}
  .agent {{ fill:none; stroke:var(--accent); stroke-width:1.5; }}
  .agent-label {{ fill:var(--fg); font-size:14px; font-weight:600;
    text-anchor:middle; }}
  .agent-sub {{ fill:var(--muted); font-size:11.5px; text-anchor:middle; }}
  .store {{ fill:none; stroke:var(--store); stroke-width:2; }}
  .store-label {{ fill:var(--muted); font-size:12px; text-anchor:middle;
    text-transform:uppercase; letter-spacing:.09em; }}
  .store-count {{ fill:var(--fg); font-size:26px; font-weight:650;
    text-anchor:middle; }}
  .store-sub {{ fill:var(--muted); font-size:11.5px; text-anchor:middle; }}
  .link {{ fill:none; stroke:var(--line); stroke-width:1.6; }}
  .arrow {{ fill:var(--line); }}

  .scroll {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th {{ text-align:left; color:var(--muted); font-weight:500; font-size:12px;
    text-transform:uppercase; letter-spacing:.07em;
    border-bottom:1px solid var(--line); padding:0 12px 9px; }}
  td {{ border-bottom:1px solid var(--line); padding:11px 12px;
    vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  .c-agent {{ white-space:nowrap; color:var(--muted); }}
  .c-time {{ white-space:nowrap; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .c-text {{ min-width:340px; }}
  .dot {{ display:inline-block; width:7px; height:7px; border-radius:50%;
    margin-right:7px; vertical-align:middle; background:var(--accent); }}
  .d1{{background:#c98a5b}} .d2{{background:#6a9a78}} .d3{{background:#9a7bb0}}
  .d4{{background:#c47b8a}} .d5{{background:#5b8fa8}}
  .empty {{ color:var(--muted); text-align:center; padding:26px; }}
  footer {{ color:var(--muted); font-size:12.5px; margin-top:26px; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; }}
</style>
<div class="wrap">
  <h1>Shared memory</h1>
  <p class="sub">collection <code>{html.escape(COLLECTION)}</code> ·
     user <code>{html.escape(USER)}</code> · {len(rows)} facts</p>

  <div class="card">{svg(rows)}
    <p class="note">Each agent writes into one store. <b>Attribution is not
    access control</b> — <code>agent_id</code> records who wrote a fact, and a
    search scoped to the user returns every agent's facts. That is what makes
    the memory shared rather than merely co-located.</p>
  </div>

  <div class="card">
    <div class="chips">{chips}</div>
  </div>

  <div class="card scroll">
    <table>
      <thead><tr><th>Written by</th><th>Fact</th><th>Stored</th></tr></thead>
      <tbody>{trs}</tbody>
    </table>
  </div>

  <footer>Generated {html.escape(generated)} · read directly from Qdrant ·
    regenerate with <code>./memory-layer graph</code></footer>
</div>
"""


def main():
    rows = build(scroll())
    out = os.environ.get("MEM0_GRAPH_OUT") or os.path.join(os.getcwd(), "memory-graph.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(rows))
    agents = Counter(r["agent"] for r in rows)
    print(f"  {len(rows)} memories across {len(agents)} agent(s)")
    for a, n in sorted(agents.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {a}: {n}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
