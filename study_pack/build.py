"""Build the study pack PDFs from the Markdown sources in this folder.

    python study_pack/build.py            # every PDF
    python study_pack/build.py guide      # one of: guide, lessons, cheatsheet

Markdown is rendered with python-markdown, wrapped in style.css and printed by
Chromium (render_pdf.mjs). Sections that restate a source -- the decision and
assumption registers, the ten reference answers -- are generated from the
snapshots in sources/, taken from the delivered commit, so they cannot drift
from it. The table of contents gets its page numbers from a first render.
"""

from __future__ import annotations

import csv
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import markdown
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fonts  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "deliverables" / "study_pack"
BUILD = HERE / "_build"
DELIVERED = HERE / "sources" / "delivered"
POST = HERE / "sources" / "post_delivery"

DELIVERED_COMMIT = "fc0c281"
DELIVERED_BRANCH = "delivery-freeze-2026-10-28"

EXTENSIONS = ["tables", "attr_list", "md_in_html", "fenced_code", "sane_lists", "toc"]

# ---------------------------------------------------------------------------
# Markdown with callouts:  :::say Title  ...  :::
# ---------------------------------------------------------------------------

CALLOUT = re.compile(r"^:::(\w+)[ \t]*(.*?)\n(.*?)^:::[ \t]*$", re.M | re.S)
DEFAULT_LABEL = {
    "say": "Say it like this", "weak": "Weak spot -- be ready", "post": "After delivery",
    "evidence": "Evidence", "danger": "Do not say", "key": "Remember",
}


def callouts(text: str) -> str:
    def repl(m: re.Match) -> str:
        kind, label, body = m.group(1), m.group(2).strip(), m.group(3)
        label = label or DEFAULT_LABEL.get(kind, kind)
        return (f'<div class="box {kind}" markdown="1">\n<span class="label">{html.escape(label)}</span>\n\n'
                f"{body}\n</div>\n")
    return CALLOUT.sub(repl, text)


def md(text: str) -> str:
    return markdown.markdown(callouts(expand(text)), extensions=EXTENSIONS,
                             extension_configs={"toc": {"permalink": False}})


# ---------------------------------------------------------------------------
# Generated content from the delivered snapshots
# ---------------------------------------------------------------------------

def load(name: str):
    return json.loads((DELIVERED / name).read_text(encoding="utf-8"))


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v - round(v)) > 1e-9 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def rows_table(rows: list[dict], cols: list[str] | None = None, limit: int | None = None) -> str:
    if not rows:
        return "_no rows_"
    cols = cols or list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" if isinstance(rows[0].get(c), (int, float)) else "---" for c in cols) + "|"]
    for r in rows[:limit]:
        out.append("| " + " | ".join(fmt(r.get(c)).replace("|", "/") for c in cols) + " |")
    if limit and len(rows) > limit:
        out.append(f"| _+{len(rows) - limit} more_ |" + " |" * (len(cols) - 1))
    return '<div class="compact-wrap" markdown="1">\n\n' + "\n".join(out) + "\n\n</div>"


def ref_sql(qid: str) -> str:
    text = (DELIVERED / "60_reference_queries.sql").read_text(encoding="utf-8")
    blocks = re.split(r"^--\s*@@(Q\d+)\s*$", text, flags=re.M)
    found = {blocks[i]: blocks[i + 1] for i in range(1, len(blocks) - 1, 2)}
    body = found[qid]
    sql = "\n".join(l for l in body.strip().splitlines() if not l.lstrip().startswith("--")).strip()
    return f"```sql\n{sql}\n```"


def llm_sql(qid: str, local: bool = False) -> str:
    data = load("local_llm_results.json" if local else "llm_results.json")["results"][qid]
    sql = data.get("generated_sql", "").strip()
    try:
        import sqlglot  # noqa: PLC0415 - only needed for pretty printing
        sql = sqlglot.transpile(sql, read="postgres", write="postgres", pretty=True)[0]
    except Exception:  # noqa: BLE001 - show the model's text as it was
        pass
    return f"```sql\n{sql}\n```"


def verdicts(qid: str) -> str:
    claude = {v["question_id"]: v for v in load("evaluation.json")["verdicts"]}[qid]
    local = {v["question_id"]: v for v in load("local_evaluation.json")["verdicts"]}[qid]
    llm = load("llm_results.json")["results"][qid]
    def chip(v):
        return {"match": "fixed", "partial": "disc", "mismatch": "open"}.get(v, "")
    return (f'Claude Sonnet 5.5 (recorded run): <span class="tag {chip(claude["verdict"])}">{claude["verdict"]}</span> '
            f'{claude["matched_values"]}/{claude["expected_values"]} values, attempt {llm.get("attempts_used")} &nbsp;·&nbsp; '
            f'Ollama qwen2.5-coder:3b (local run): <span class="tag {chip(local["verdict"])}">{local["verdict"]}</span> '
            f'{local["matched_values"]}/{local["expected_values"]} values')


def ref_table(qid: str, limit: int | None = None) -> str:
    rows = load("reference_results.json")["results"][qid]["rows"]
    return rows_table(rows, limit=limit)


def decisions_register(path: Path, heading_level: str = "###") -> str:
    text = path.read_text(encoding="utf-8")
    out = []
    group = None
    for part in re.split(r"\n(?=## D\d{3}|# [A-Z])", text):
        if part.startswith("# ") and not part.startswith("# DECISIONS"):
            group = part.splitlines()[0][2:].strip()
            gid = "dec-" + re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-")
            out.append(f'\n<h2 id="{gid}">{html.escape(group)}</h2>\n')
            continue
        m = re.match(r"## (D\d{3}) - (.*)", part)
        if not m:
            continue
        did, title = m.groups()
        fields = re.findall(r"\*\*(Context|Options|Choice|Reason|Cost|Consequence|Reason and consequence|Honest note on one evaluator change)\.?\*\*\s*(.*?)(?=\n\*\*[A-Z][^*]{2,40}\.?\*\*|\n---|\Z)", part, re.S)
        body = [f'<div class="reg" markdown="1">\n\n{heading_level} {did} · {title}\n']
        for name, value in fields:
            value = " ".join(value.split())
            body.append(f'<p class="field"><b>{name}</b>{md_inline(value)}</p>')
        body.append("</div>")
        out.append("\n".join(body))
    return "\n".join(out)


def md_inline(text: str) -> str:
    h = markdown.markdown(text, extensions=["sane_lists"])
    return re.sub(r"^<p>|</p>$", "", h.strip())


def assumptions_register(path: Path) -> str:
    out, section = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            sid = "ass-" + re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")
            out.append(f'\n<h2 id="{sid}">{html.escape(section)}</h2>\n')
            out.append('<table class="compact"><thead><tr><th>ID</th><th>Scope</th><th>Assumption</th>'
                       '<th>Why</th><th>What changes if wrong</th></tr></thead><tbody>')
            out.append("</tbody></table>")
            continue
        m = re.match(r"\| \*\*(A\d+)\*\*(.*?)\| (.*?) \| (.*?) \| (.*?) \| (.*?) \|\s*$", line)
        if m and out:
            aid, extra, scope, a, why, wrong = m.groups()
            row = (f"<tr><td><b>{aid}</b>{md_inline(extra.strip())}</td><td>{md_inline(scope)}</td><td>{md_inline(a)}</td>"
                   f"<td>{md_inline(why)}</td><td>{md_inline(wrong)}</td></tr>")
            out.insert(len(out) - 1, row)
    return "\n".join(out)


def defects_table() -> str:
    rows = list(csv.DictReader((DELIVERED / "defects.csv").open(encoding="utf-8")))
    out = ['<table class="compact"><thead><tr><th>Defect type</th><th>Table</th><th>Dimension</th><th>Severity</th>'
           '<th class="num">Rows</th><th>Handling</th></tr></thead><tbody>']
    for r in rows:
        out.append(f'<tr><td>{html.escape(r["Defect type"])}</td><td>{html.escape(r["Table(s)"])}</td>'
                   f'<td>{html.escape(r["Dimension"])}</td><td><span class="sev {r["Severity"]}">{r["Severity"]}</span></td>'
                   f'<td class="num">{int(r["Rows affected"]):,}</td><td>{html.escape(r["Handling"])}</td></tr>')
    out.append("</tbody></table>")
    return "\n".join(out)


GENERATORS = {
    "ref_table": lambda a: ref_table(a.split(",")[0], int(a.split(",")[1]) if "," in a else None),
    "ref_sql": ref_sql,
    "llm_sql": llm_sql,
    "local_sql": lambda a: llm_sql(a, local=True),
    "verdicts": verdicts,
    "decisions": lambda a: decisions_register(DELIVERED / "DECISIONS.md"),
    "decisions_post": lambda a: decisions_register(POST / "DECISIONS_D028_D029.md"),
    "assumptions": lambda a: assumptions_register(DELIVERED / "ASSUMPTIONS.md"),
    "assumptions_post": lambda a: assumptions_register_post(),
    "defects": lambda a: defects_table(),
}


def assumptions_register_post() -> str:
    text = "## Added after delivery (not in the delivered version)\n" + (POST / "ASSUMPTIONS_A47_A49.md").read_text(encoding="utf-8")
    tmp = BUILD / "post_assumptions.md"
    tmp.write_text(text, encoding="utf-8")
    return assumptions_register(tmp)


def expand(text: str) -> str:
    def repl(m: re.Match) -> str:
        name, arg = m.group(1), m.group(2) or ""
        return GENERATORS[name](arg)
    return re.sub(r"\[\[(\w+)(?::([^\]]*))?\]\]", repl, text)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

DOCS = {
    "guide": {
        "file": "01_Study_Guide.pdf",
        "footer": "Berka governed data product · study guide",
        "kicker": "Walkthrough preparation · study guide",
        "title": "The Governed Data Product for AI, explained step by step",
        "sub": "Every step from raw files to an LLM that is treated as a dumb and dangerous client: "
               "what was built, why, what it costs, what the evidence is, and where it is weak.",
        "parts": sorted((HERE / "guide").glob("*.md")),
        "toc": True,
    },
    "lessons": {
        "file": "02_Lessons_Learned_and_Self_Audit.pdf",
        "footer": "Berka governed data product · lessons learned and self-audit",
        "kicker": "Walkthrough preparation · self-audit",
        "title": "Mistakes, sloppiness and lessons learned",
        "sub": "What went wrong, how it was found, what it cost, what was fixed, what is still open -- "
               "every finding checked against the code, the evidence or the database.",
        "parts": sorted((HERE / "lessons").glob("*.md")),
        "toc": True,
    },
    "kids": {
        "file": "01b_Study_Guide_School_Edition.pdf",
        "footer": "The school, the archive and the robot · study guide, school edition",
        "kicker": "The same study guide · school edition",
        "title": "The School, the Archive and the Robot",
        "sub": "The whole project explained as if the bank were a school: the pupils, the teachers, "
               "the record books in the archive, and a robot that helps everyone understand their own files.",
        "pills": ["Same chapters as the study guide", "Pupils = clients", "Record books = accounts",
                  "Topics = districts", "Tutors = bank staff", "The robot = the LLM"],
        "meta": "Every number is the real number from the delivered version (commit fc0c281), dressed up in "
                "school words. Each chapter ends with an <b>In grown-up words</b> box that translates back.",
        "css": "style_kids.css",
        "parts": sorted((HERE / "guide_kids").glob("*.md")),
        "toc": True,
    },
    "cheatsheet": {
        "file": "04_Cheat_Sheet.pdf",
        "footer": "Berka governed data product · cheat sheet",
        "parts": [HERE / "cheatsheet.md"],
        "toc": False,
    },
}


def cover(doc: dict) -> str:
    pills = "".join(f'<span class="pill">{html.escape(p)}</span>' for p in doc.get("pills", DEFAULT_PILLS))
    meta = doc.get("meta", DEFAULT_META)
    return f"""
<section class="cover">
  <div>
    <div class="kicker">{html.escape(doc['kicker'])}</div>
    <div class="title">{html.escape(doc['title'])}</div>
    <div class="sub">{html.escape(doc['sub'])}</div>
  </div>
  <div class="meta">
    {pills}<br><br>
    {meta}
  </div>
</section>"""


DEFAULT_PILLS = ["Berka (PKDD'99) take-home", "PostgreSQL", "Data quality", "Semantic layer",
                 "Row level security", "LLM as untrusted client"]
DEFAULT_META = (f"Describes the <b>delivered version</b>: branch <b>{DELIVERED_BRANCH}</b>, commit "
                f"<b>{DELIVERED_COMMIT}</b> (code b5b18f2), 2026-10-28.<br>"
                "Work done <b>after</b> delivery (D028, D029, branch ccr-46f6f45a-t9wtd4) is marked as such "
                "wherever it appears.<br>Every figure comes from the delivered evidence files or a query run "
                "on 2026-11-04; nothing is from memory.")


def assemble(doc: dict, toc_pages: dict[str, int] | None) -> tuple[str, list[tuple[int, str, str]]]:
    body = "\n".join(md(p.read_text(encoding="utf-8")) for p in doc["parts"])
    heads: list[tuple[int, str, str]] = []
    counter = 0

    def mark(m: re.Match) -> str:
        nonlocal counter
        level, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
        idm = re.search(r'id="([^"]+)"', attrs)
        if level > 2 or not idm or "cover-title" in attrs:
            return m.group(0)
        counter += 1
        text = re.sub(r"<[^>]+>", " ", inner).strip()
        text = re.sub(r"\s+", " ", text)
        heads.append((level, idm.group(1), html.unescape(text)))
        marker = ""
        return f"<h{level}{attrs}>{marker}{inner}</h{level}>"

    body = re.sub(r"<h([12])([^>]*)>(.*?)</h\1>", mark, body, flags=re.S)
    toc = ""
    if doc.get("toc"):
        items = []
        for i, (level, hid, text) in enumerate(heads, start=1):
            page = (toc_pages or {}).get(f"{i:03d}", "")
            items.append(f'<li class="l{level}"><span class="t"><a href="#{hid}">{html.escape(text)}</a></span>'
                         f'<span class="p">{page}</span></li>')
        toc = (f'<section class="toc"><h1 id="contents-page">Contents</h1><ol>{"".join(items)}</ol>'
               + "</section>")
    head = (f'<meta charset="utf-8"><style>{fonts.ensure(BUILD / "fonts")}</style>'
            f'<link rel="stylesheet" href="{(HERE / "style.css").as_uri()}">')
    if doc.get("css"):
        head += f'<link rel="stylesheet" href="{(HERE / doc["css"]).as_uri()}">'
    pre = cover(doc) if "title" in doc else ""
    return f"<!doctype html><html lang=\"en\"><head>{head}<title>{html.escape(doc.get('title', doc['footer']))}</title></head><body>{pre}{toc}{body}</body></html>", heads


def render(html_text: str, name: str, footer: str) -> Path:
    BUILD.mkdir(exist_ok=True)
    src = BUILD / f"{name}.html"
    # images are referenced relative to the study_pack folder
    src.write_text(html_text.replace('src="assets/', f'src="{(HERE / "assets").as_uri()}/'), encoding="utf-8")
    pdf = BUILD / f"{name}.pdf"
    subprocess.run(["node", str(HERE / "render_pdf.mjs"), str(src), str(pdf), footer], check=True)
    return pdf


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def page_numbers(pdf: Path, heads: list[tuple[int, str, str]]) -> dict[str, int]:
    """Find each heading's page from the rendered text.

    Every level-1 heading starts a page, so its page is the first one whose
    text begins with it; a level-2 heading is the next occurrence at or after
    its chapter's page.
    """
    pages = [_norm(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    found: dict[str, int] = {}
    pointer = 0
    for i, (level, _, text) in enumerate(heads, start=1):
        key = _norm(text)[:60]
        if not key:
            continue
        if level == 1:
            hit = next((n for n in range(pointer, len(pages)) if pages[n].startswith(key)), None)
        else:
            hit = next((n for n in range(pointer, len(pages)) if key in pages[n]), None)
        if hit is not None:
            found[f"{i:03d}"] = hit + 1
            pointer = hit
    return found


def build(name: str) -> Path:
    doc = DOCS[name]
    first, heads = assemble(doc, None)
    pdf = render(first, name, doc["footer"])
    if doc.get("toc"):
        final, _ = assemble(doc, page_numbers(pdf, heads))
        pdf = render(final, name, doc["footer"])
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / doc["file"]
    target.write_bytes(pdf.read_bytes())
    n = len(PdfReader(str(target)).pages)
    print(f"wrote {target.relative_to(ROOT)} -- {n} pages")
    return target


if __name__ == "__main__":
    names = sys.argv[1:] or list(DOCS)
    for name in names:
        build(name)
