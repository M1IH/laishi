#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 knowledge/src/*.json 生成一页可读的审阅页 knowledge/review.html。

用法：
    python knowledge/build_review.py
"""
import html
import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT = ROOT / "review.html"

ORDER = [
    "self", "maimai", "arknights", "sanguosha", "memes", "vrchat",
    "anime", "vtuber", "vocaloid", "touhou",
]
CONF_LABEL = {"high": "高", "medium": "中", "low": "低"}


def esc(text):
    return html.escape(str(text or ""), quote=True)


def load():
    topics = []
    for p in sorted(SRC.glob("*.json")):
        data = json.load(io.open(p, encoding="utf-8"))
        topics.append(data)
    topics.sort(key=lambda t: ORDER.index(t["topic"]) if t["topic"] in ORDER else 99)
    return topics


def card(entry):
    conf = entry.get("confidence", "medium")
    flags = [f'<span class="badge conf-{esc(conf)}">置信 {CONF_LABEL.get(conf, conf)}</span>']
    if entry.get("sensitive"):
        flags.append('<span class="badge sens">敏感（默认不注入）</span>')
    aliases = "".join(f'<span class="alias">{esc(a)}</span>' for a in entry.get("aliases", []))
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in entry.get("tags", ""))
    src = entry.get("source", "")
    src_html = (
        f'<a class="src" href="{esc(src)}" target="_blank" rel="noreferrer">{esc(src)}</a>'
        if src.startswith("http")
        else f'<span class="src">{esc(src)}</span>'
    )
    return f"""
    <article class="card" data-text="{esc((entry.get('title','') + entry.get('summary','') + entry.get('detail','') + ' '.join(entry.get('aliases', [])) + ' '.join(entry.get('tags', []))).lower())}">
      <div class="card-head">
        <h3>{esc(entry.get('title'))}<span class="slug">{esc(entry.get('slug'))}</span></h3>
        <div class="flags">{''.join(flags)}</div>
      </div>
      <p class="summary">{esc(entry.get('summary'))}</p>
      <p class="detail">{esc(entry.get('detail'))}</p>
      <div class="meta">{aliases}{tags}</div>
      <div class="source">{src_html}</div>
    </article>"""


def main():
    topics = load()
    total = sum(len(t["entries"]) for t in topics)
    nav = "".join(
        f'<a class="chip" href="#{esc(t["topic"])}" data-topic="{esc(t["topic"])}">{esc(t["title"])}<b>{len(t["entries"])}</b></a>'
        for t in topics
    )
    sections = []
    for t in topics:
        cards = "".join(card(e) for e in t["entries"])
        sections.append(f"""
    <section id="{esc(t['topic'])}" class="topic">
      <div class="topic-head">
        <h2>{esc(t['title'])}<span class="count">{len(t['entries'])} 条</span></h2>
        <p>{esc(t.get('description',''))}</p>
      </div>
      <div class="cards">{cards}</div>
    </section>""")

    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Miruku 知识库审阅 · {total} 条</title>
<style>
  :root {{
    --bg:#f6f5f2; --card:#fffdf9; --ink:#24211d; --muted:#6f6a62;
    --line:#e4dfd6; --accent:#8a5c3a; --accent-soft:#f1e7dc;
    --green:#2f6b45; --amber:#8a5a12; --red:#8a2f2f;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.65 "Microsoft YaHei","PingFang SC","Noto Sans SC",system-ui,sans-serif; }}
  header {{ position:sticky; top:0; z-index:9; background:rgba(246,245,242,.95);
    backdrop-filter:blur(8px); border-bottom:1px solid var(--line); padding:18px 28px 12px; }}
  .title-row {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
  h1 {{ font-size:20px; margin:0; letter-spacing:.5px; }}
  .sub {{ color:var(--muted); font-size:13px; }}
  .tools {{ display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; align-items:center; }}
  #q {{ flex:1 1 260px; max-width:420px; padding:8px 12px; border:1px solid var(--line);
    border-radius:8px; background:#fff; font:inherit; }}
  #q:focus {{ outline:2px solid var(--accent-soft); border-color:var(--accent); }}
  #hit {{ color:var(--muted); font-size:12px; }}
  nav {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
  .chip {{ display:inline-flex; align-items:center; gap:6px; padding:5px 11px; border-radius:999px;
    border:1px solid var(--line); background:#fff; color:var(--ink); text-decoration:none; font-size:13px; }}
  .chip b {{ color:var(--muted); font-weight:600; font-size:12px; }}
  .chip:hover {{ border-color:var(--accent); background:var(--accent-soft); }}
  main {{ max-width:1080px; margin:0 auto; padding:24px 28px 80px; }}
  .topic {{ margin:34px 0 10px; scroll-margin-top:150px; }}
  .topic-head h2 {{ font-size:18px; margin:0 0 4px; display:flex; align-items:baseline; gap:10px; }}
  .count {{ font-size:12px; color:var(--muted); font-weight:400; }}
  .topic-head p {{ margin:0 0 14px; color:var(--muted); font-size:13px; }}
  .cards {{ display:grid; grid-template-columns:1fr; gap:12px; }}
  @media (min-width:900px) {{ .cards {{ grid-template-columns:1fr 1fr; }} }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:14px 16px 12px; box-shadow:0 1px 0 rgba(0,0,0,.02); }}
  .card.hide {{ display:none; }}
  .card-head {{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }}
  .card h3 {{ margin:0; font-size:16px; line-height:1.4; }}
  .slug {{ display:block; font-size:11px; color:#a39d94; font-weight:400; margin-top:2px;
    font-family:ui-monospace,Consolas,monospace; }}
  .flags {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }}
  .badge {{ font-size:11px; padding:2px 8px; border-radius:999px; white-space:nowrap; }}
  .conf-high {{ background:#e7f2ea; color:var(--green); }}
  .conf-medium {{ background:#f8eeda; color:var(--amber); }}
  .conf-low {{ background:#f7e3e3; color:var(--red); }}
  .sens {{ background:#f3e8f0; color:#7a3b63; }}
  .summary {{ margin:10px 0 6px; font-size:15px; font-weight:600; }}
  .detail {{ margin:0 0 10px; color:#3b3731; }}
  .meta {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }}
  .alias {{ font-size:11px; color:#6b645a; background:#f1eee7; border-radius:4px; padding:1px 6px; }}
  .tag {{ font-size:11px; color:#7a5a3a; background:var(--accent-soft); border-radius:4px; padding:1px 6px; }}
  .source {{ border-top:1px dashed var(--line); padding-top:8px; }}
  .src {{ font-size:11px; color:#8b857b; word-break:break-all; text-decoration:none; }}
  .src:hover {{ color:var(--accent); }}
  .empty {{ display:none; padding:40px 0; color:var(--muted); }}
  @media print {{
    header {{ position:static; }} .tools {{ display:none; }}
    .card {{ break-inside:avoid; box-shadow:none; }}
  }}
</style>
</head>
<body>
<header>
  <div class="title-row">
    <h1>Miruku 知识库审阅</h1>
    <span class="sub">{len(topics)} 个主题 · {total} 条 · 生成自 knowledge/src/*.json</span>
  </div>
  <div class="tools">
    <input id="q" type="search" placeholder="搜标题、内容、别名、标签（Ctrl+K）" autocomplete="off">
    <span id="hit"></span>
  </div>
  <nav>{nav}</nav>
</header>
<main>
  {''.join(sections)}
  <p class="empty" id="empty">没有匹配的条目。</p>
</main>
<script>
  const q = document.getElementById('q');
  const hit = document.getElementById('hit');
  const empty = document.getElementById('empty');
  const cards = [...document.querySelectorAll('.card')];
  const topics = [...document.querySelectorAll('.topic')];
  function filter() {{
    const kw = q.value.trim().toLowerCase();
    let n = 0;
    cards.forEach(c => {{
      const ok = !kw || c.dataset.text.includes(kw);
      c.classList.toggle('hide', !ok);
      if (ok) n++;
    }});
    topics.forEach(t => {{
      const any = [...t.querySelectorAll('.card')].some(c => !c.classList.contains('hide'));
      t.style.display = any ? '' : 'none';
    }});
    hit.textContent = kw ? `命中 ${{n}} / ${{cards.length}}` : `共 ${{cards.length}} 条`;
    empty.style.display = n ? 'none' : 'block';
  }}
  q.addEventListener('input', filter);
  document.addEventListener('keydown', e => {{
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {{ e.preventDefault(); q.focus(); }}
    if (e.key === 'Escape') {{ q.value = ''; filter(); q.blur(); }}
  }});
  filter();
</script>
</body>
</html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"OK -> {OUT}  topics={len(topics)} entries={total} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
