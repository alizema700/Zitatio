"""Prüfbericht als eigenständige HTML-Datei und als JSON."""

from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import html
import io
import json
from dataclasses import dataclass
from importlib import resources

from . import __version__
from .dataroom import DataRoom
from .facts import KIND_LABELS
from .verify import Finding, Status

SYMBOLS = {
    Status.GEPRUEFT: "✓",
    Status.ABWEICHUNG: "✗",
    Status.FALSCHE_FUNDSTELLE: "↷",
    Status.QUELLE_FEHLT: "✗",
    Status.OHNE_BELEG: "!",
    Status.UNGEPRUEFT: "?",
}
ORDER = [Status.ABWEICHUNG, Status.QUELLE_FEHLT, Status.FALSCHE_FUNDSTELLE, Status.OHNE_BELEG,
         Status.UNGEPRUEFT, Status.GEPRUEFT]


@dataclass
class Run:
    report_name: str
    report_sha256: str
    room: DataRoom
    findings: list[Finding]
    model: str | None = None
    created: dt.datetime | None = None

    def __post_init__(self):
        self.created = self.created or dt.datetime.now().astimezone()

    def counts(self) -> dict[Status, int]:
        return {s: sum(f.status is s for f in self.findings) for s in ORDER}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CSV_COLUMNS = ["Nr", "Abschnitt", "Aussage", "Fundstellen", "Status", "Methode", "Begründung", "Belege",
               "Entscheid", "Notiz", "Prüfer"]


def _rows(run: Run) -> list[list]:
    return [
        [
            f.claim.number,
            f.claim.section,
            f.claim.clean_text,
            ", ".join(c.label for c in f.claim.citations),
            f.status.label,
            f.method,
            " ".join(f.reasons),
            " | ".join(f"{e.doc_label}, S. {e.page}: {e.before}{e.match}{e.after}" for e in f.evidence),
            "", "", "",
        ]
        for f in run.findings
    ]


def to_csv(run: Run) -> str:
    """Eine Zeile pro Aussage; Semikolon und BOM, damit Excel in der Schweiz es direkt öffnet.

    Die Spalten Entscheid, Notiz und Prüfer sind für die menschliche Durchsicht da;
    der HTML-Prüfbericht füllt sie beim Export aus.
    """
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows(_rows(run))
    return "\ufeff" + out.getvalue()


def to_json(run: Run) -> str:
    return json.dumps(
        {
            "zitatio_version": __version__,
            "erstellt": run.created.isoformat(timespec="seconds"),
            "bericht": {"name": run.report_name, "sha256": run.report_sha256},
            "pruefmodell": run.model,
            "datenraum": [
                {"index": d.index, "name": d.name, "seiten": len(d.pages), "sha256": d.sha256}
                for d in run.room.documents
            ],
            "hinweise": run.room.warnings,
            "zusammenfassung": {s.value: n for s, n in run.counts().items()},
            "aussagen": [
                {
                    "nr": f.claim.number,
                    "abschnitt": f.claim.section,
                    "aussage": f.claim.text,
                    "fundstellen": [c.label for c in f.claim.citations],
                    "werte": [
                        {"art": x.kind, "text": x.text, "normalisiert": x.display()}
                        for x in f.claim.facts
                    ],
                    "status": f.status.value,
                    "methode": f.method,
                    "begruendung": f.reasons,
                    "belege": [
                        {"dokument": e.doc_label, "seite": e.page,
                         "ausschnitt": e.before + e.match + e.after}
                        for e in f.evidence
                    ],
                }
                for f in run.findings
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def logo_svg() -> str:
    svg = resources.files("zitatio").joinpath("assets/zitatio-logo.svg").read_text()
    return (
        svg.replace('fill="#15202B"', 'style="fill:var(--ink)"')
        .replace('fill="#1E7A50"', 'style="fill:var(--green)"')
        .replace("<svg ", '<svg class="logo" role="img" aria-label="Zitatio" ', 1)
    )


def _font_faces() -> str:
    """Hausschrift als Data-URI, damit der Prüfbericht als einzelne Datei offline gleich aussieht."""
    faces = []
    for weight in (400, 700):
        data = resources.files("zitatio").joinpath(f"assets/fonts/familjen-grotesk-latin-{weight}-normal.woff2").read_bytes()
        faces.append(
            '@font-face {{ font-family:"Familjen Grotesk"; font-weight:%d; font-display:swap; '
            'src:url(data:font/woff2;base64,%s) format("woff2"); }}' % (weight, base64.b64encode(data).decode())
        )
    return "\n".join(faces).replace("{{", "{").replace("}}", "}")


def _highlight(finding: Finding) -> str:
    """Aussage mit markierten Werten (ohne Fundstellenklammern)."""
    clean = finding.claim.clean_text
    out, pos = [], 0
    for fact in finding.claim.facts:
        out.append(html.escape(clean[pos : fact.start]))
        out.append(
            f'<mark title="{KIND_LABELS[fact.kind]}: {html.escape(fact.display())}">'
            f"{html.escape(clean[fact.start : fact.end])}</mark>"
        )
        pos = fact.end
    out.append(html.escape(clean[pos:]))
    return "".join(out)


def _protocol_line(f: Finding) -> str:
    short = f.claim.clean_text
    if len(short) > 78:
        short = short[:76].rstrip() + "…"
    where = ", ".join(c.label for c in f.claim.citations) or "ohne Fundstelle"
    return (
        f'<a class="pl s-{f.status.value}" href="#a{f.claim.number}">'
        f'<span class="sym">{SYMBOLS[f.status]}</span>'
        f'<span class="nr">{f.claim.number:02d}</span>'
        f'<span class="txt">{html.escape(short)}</span>'
        f'<span class="where">{html.escape(where)}</span>'
        f'<span class="st">{f.status.label.upper()}</span></a>'
    )


def _card(f: Finding) -> str:
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in f.reasons)
    evidence = "".join(
        f'<figure class="ev"><figcaption>{html.escape(e.doc_label)}, S. {e.page}'
        f' <span class="file">{html.escape(e.doc_name)}</span></figcaption>'
        f"<blockquote>{html.escape(e.before)}<mark>{html.escape(e.match)}</mark>"
        f"{html.escape(e.after)}</blockquote></figure>"
        for e in f.evidence
    )
    where = ", ".join(c.label for c in f.claim.citations) or "keine"
    section = f'<span class="sec">{html.escape(f.claim.section)}</span>' if f.claim.section else ""
    return f"""
<article class="card s-{f.status.value}" id="a{f.claim.number}" data-status="{f.status.value}">
  <header><span class="badge">{SYMBOLS[f.status]} {f.status.label}</span>
  <span class="num">Aussage {f.claim.number}</span>{section}
  <span class="method">{html.escape(f.method)}</span></header>
  <p class="claim">{_highlight(f)}</p>
  <p class="cite">Fundstelle: {html.escape(where)}</p>
  <ul class="reasons">{reasons}</ul>
  {evidence}
  <div class="decide" data-nr="{f.claim.number}">
    <span class="q">Ihr Entscheid</span>
    <button type="button" data-d="ok">Zustimmen</button>
    <button type="button" data-d="nein">Widersprechen</button>
    <input type="text" placeholder="Notiz, z. B. korrigiert in Version 2" aria-label="Notiz zu Aussage {f.claim.number}">
  </div>
</article>"""


def to_html(run: Run) -> str:
    counts = run.counts()
    total = len(run.findings)
    problems = total - counts[Status.GEPRUEFT] - counts[Status.UNGEPRUEFT]
    headline = (
        f"{problems} von {total} Aussagen brauchen eine Korrektur."
        if problems
        else f"Alle {total} prüfbaren Aussagen stimmen mit dem Datenraum überein."
    )
    chips = "".join(
        f'<button class="chip s-{s.value}" data-filter="{s.value}">'
        f'<b>{n}</b> {s.label}</button>'
        for s, n in counts.items()
        if n
    )
    protocol = "\n".join(_protocol_line(f) for f in run.findings)
    cards = "\n".join(_card(f) for f in sorted(run.findings, key=lambda f: (ORDER.index(f.status), f.claim.number)))
    docs = "".join(
        f"<tr><td>{html.escape(d.label)}</td><td>{html.escape(d.title)}</td><td>{len(d.pages)}</td>"
        f'<td class="hash">{d.sha256[:16]}…</td></tr>'
        for d in run.room.documents
    )
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in run.room.warnings)
    warnings_html = f'<ul class="warn">{warnings}</ul>' if warnings else ""
    model = html.escape(run.model) if run.model else "aus (nur Regeln)"
    stamp = run.created.strftime("%d.%m.%Y, %H:%M")
    return TEMPLATE.format(
        fonts=_font_faces(),
        csv=base64.b64encode(to_csv(run).encode("utf-8")).decode(),
        rows=json.dumps({"columns": CSV_COLUMNS, "rows": _rows(run)}, ensure_ascii=False).replace("</", "<\\/"),
        key=html.escape(run.report_sha256 + "-" + run.created.isoformat(timespec="seconds")),
        csv_name=html.escape(run.report_name.rsplit(".", 1)[0] + "-pruefbericht.csv"),
        title=html.escape(run.report_name),
        logo=logo_svg(),
        report=html.escape(run.report_name),
        stamp=stamp,
        model=model,
        headline=headline,
        total=total,
        docs_count=len(run.room.documents),
        chips=chips,
        protocol=protocol,
        cards=cards,
        docs=docs,
        warnings=warnings_html,
        report_hash=run.report_sha256[:16],
        version=__version__,
    )


TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prüfbericht · {title}</title>
<style>
{fonts}
:root {{
  --ink:#15202B; --ink-2:#4A5560; --line:#DCE1DD; --paper:#F7F8F6; --card:#FFFFFF;
  --green:#1E7A50; --green-bg:#E6F2EC; --red:#B42318; --red-bg:#FBEAE8;
  --amber:#9A5B00; --amber-bg:#FBF1DF; --gray:#5B6670; --gray-bg:#EEF0EF;
  --term:#121A22; --term-ink:#DCE3E8; --term-dim:#7D8A95; --mark:#FFF0B3;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --sans: "Familjen Grotesk", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --ink:#EEF2F0; --ink-2:#A9B4BD; --line:#2A3540; --paper:#121A22; --card:#18222C;
    --green:#4CC38A; --green-bg:#16352A; --red:#F07A6E; --red-bg:#3A1F1E;
    --amber:#E8B04B; --amber-bg:#3A2E16; --gray:#A9B4BD; --gray-bg:#24303A;
    --term:#0B1117; --mark:#5A4A10;
  }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 var(--sans); }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px 64px; }}
.top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
.logo {{ height:28px; width:auto; }}
.meta {{ font:12px/1.5 var(--mono); color:var(--ink-2); text-align:right; }}
.meta a {{ color:var(--green); }}
h1 {{ font-size:30px; line-height:1.15; letter-spacing:-0.02em; margin:40px 0 8px; }}
.sub {{ color:var(--ink-2); margin:0 0 20px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 24px; }}
.chip {{ font:13px var(--sans); border:1px solid var(--line); background:var(--card); color:var(--ink);
  border-radius:999px; padding:5px 12px; cursor:pointer; }}
.chip b {{ font-variant-numeric:tabular-nums; }}
.chip.on {{ outline:2px solid var(--ink); }}
.term {{ background:var(--term); color:var(--term-ink); border-radius:10px; padding:14px 0 10px;
  font:12.5px/1.5 var(--mono); overflow:hidden; }}
.term .bar {{ color:var(--term-dim); padding:0 16px 8px; border-bottom:1px solid #22303C; margin-bottom:6px; }}
.pl {{ display:grid; grid-template-columns:18px 26px 1fr auto auto; gap:10px; padding:3px 16px;
  color:inherit; text-decoration:none; }}
.pl:hover {{ background:#1C2833; }}
.pl .nr, .pl .where {{ color:var(--term-dim); }}
.pl .txt {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.pl .st {{ font-weight:600; }}
.pl.s-geprueft .sym, .pl.s-geprueft .st {{ color:#4CC38A; }}
.pl.s-abweichung .sym, .pl.s-abweichung .st, .pl.s-quelle_fehlt .sym, .pl.s-quelle_fehlt .st {{ color:#F07A6E; }}
.pl.s-falsche_fundstelle .sym, .pl.s-falsche_fundstelle .st, .pl.s-ohne_beleg .sym, .pl.s-ohne_beleg .st {{ color:#E8B04B; }}
.pl.s-ungeprueft .sym, .pl.s-ungeprueft .st {{ color:#A9B4BD; }}
h2 {{ font-size:18px; margin:40px 0 12px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--c); border-radius:8px;
  padding:16px 18px; margin:0 0 12px; }}
.card header {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; font-size:13px; color:var(--ink-2); }}
.badge {{ font-weight:600; color:var(--c); background:var(--cbg); border-radius:4px; padding:2px 8px; }}
.method {{ margin-left:auto; font:11px var(--mono); }}
.sec {{ font-style:italic; }}
.claim {{ font-size:16px; margin:10px 0 4px; }}
.claim mark, blockquote mark {{ background:var(--mark); color:inherit; border-radius:2px; padding:0 2px; }}
.cite {{ font:12px var(--mono); color:var(--ink-2); margin:0 0 8px; }}
.reasons {{ margin:0 0 8px; padding-left:18px; }}
.ev {{ margin:8px 0 0; }}
.ev figcaption {{ font:12px var(--mono); color:var(--ink-2); }}
.ev .file {{ opacity:.7; }}
blockquote {{ margin:4px 0 0; padding:8px 12px; background:var(--paper); border-radius:6px; font-size:14px; }}
.s-geprueft {{ --c:var(--green); --cbg:var(--green-bg); }}
.s-abweichung, .s-quelle_fehlt {{ --c:var(--red); --cbg:var(--red-bg); }}
.s-falsche_fundstelle, .s-ohne_beleg {{ --c:var(--amber); --cbg:var(--amber-bg); }}
.s-ungeprueft {{ --c:var(--gray); --cbg:var(--gray-bg); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
td, th {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
.hash {{ font:12px var(--mono); color:var(--ink-2); }}
.warn {{ color:var(--amber); font-size:13px; }}
.note {{ font-size:13px; color:var(--ink-2); }}
.review {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px; background:var(--card); border:1px solid var(--line);
  border-radius:8px; padding:12px 16px; margin:0 0 24px; font-size:14px; }}
.review input {{ font:14px var(--sans); color:var(--ink); background:var(--paper); border:1px solid var(--line);
  border-radius:6px; padding:6px 10px; min-width:0; }}
.review .bar {{ flex:1 1 160px; height:6px; background:var(--gray-bg); border-radius:3px; overflow:hidden; }}
.review .bar i {{ display:block; height:100%; width:0; background:var(--green); transition:width .2s; }}
.review a {{ color:var(--green); font-weight:600; }}
.decide {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:12px; padding-top:12px; border-top:1px dashed var(--line); }}
.decide .q {{ font-size:13px; color:var(--ink-2); margin-right:4px; }}
.decide button {{ font:13px var(--sans); border:1px solid var(--line); background:transparent; color:var(--ink);
  border-radius:6px; padding:4px 12px; cursor:pointer; }}
.decide button.on[data-d=ok] {{ background:var(--green); border-color:var(--green); color:var(--card); }}
.decide button.on[data-d=nein] {{ background:var(--ink); border-color:var(--ink); color:var(--card); }}
.decide input {{ flex:1 1 200px; min-width:0; font:13px var(--sans); color:var(--ink); background:var(--paper);
  border:1px solid var(--line); border-radius:6px; padding:5px 10px; }}
.card.done {{ opacity:.72; }}
@media (max-width:640px) {{ .hash {{ display:none; }} .pl {{ grid-template-columns:18px 1fr auto; }} .pl .nr, .pl .where {{ display:none; }} }}
@media print {{ .chips, .review a, .decide button:not(.on) {{ display:none; }} .card {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<main>
  <div class="top">{logo}
    <div class="meta">Prüfbericht · {stamp}<br>Prüfmodell: {model}</div>
  </div>
  <h1>{headline}</h1>
  <p class="sub">{report} · {total} Aussagen gegen {docs_count} Dokumente im Datenraum geprüft.</p>
  <div class="chips">{chips}</div>
  <div class="review" id="review">
    <label>Durchgesehen von <input type="text" id="reviewer" placeholder="Name" autocomplete="name"></label>
    <span id="progress">0 von {total} entschieden</span><span class="bar"><i id="bar"></i></span>
    <a id="export" href="data:text/csv;charset=utf-8;base64,{csv}" download="{csv_name}">Protokoll exportieren</a>
  </div>
  <section class="term" aria-label="Prüfprotokoll">
    <div class="bar">$ zitatio pruefen {report}</div>
    {protocol}
  </section>
  <h2>Aussagen im Detail</h2>
  {cards}
  <h2>Datenraum</h2>
  <table><thead><tr><th>Index</th><th>Dokument</th><th>Seiten</th><th class="hash">SHA-256</th></tr></thead>
  <tbody>{docs}</tbody></table>
  {warnings}
  <p class="note">„Geprüft“ heisst: Jeder Betrag, jedes Datum, jeder Prozentsatz, jede Frist und jede UID der Aussage
  steht auf der zitierten Seite. Den Sinn einer Aussage bestätigt nur das Prüfmodell, und nur mit einem Zitat,
  das wörtlich in der Quelle steht. Bericht SHA-256 {report_hash}… · Zitatio {version}</p>
</main>
<script type="application/json" id="rows">{rows}</script>
<script>
document.querySelectorAll('.chip').forEach(function (chip) {{
  chip.addEventListener('click', function () {{
    var on = !chip.classList.contains('on');
    document.querySelectorAll('.chip').forEach(function (c) {{ c.classList.remove('on'); }});
    if (on) chip.classList.add('on');
    document.querySelectorAll('.card').forEach(function (card) {{
      card.hidden = on && card.dataset.status !== chip.dataset.filter;
    }});
  }});
}});

// Menschliche Durchsicht: Entscheide bleiben in diesem Browser gespeichert und gehen ins CSV.
(function () {{
  var KEY = 'zitatio:{key}', data = JSON.parse(document.getElementById('rows').textContent);
  var state = {{ reviewer: '', d: {{}} }};
  try {{ state = JSON.parse(localStorage.getItem(KEY)) || state; }} catch (e) {{}}
  var who = document.getElementById('reviewer'), link = document.getElementById('export');
  function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}} }}
  function cell(v) {{ v = String(v == null ? '' : v); return /[;"\\r\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }}
  function refresh() {{
    var done = 0;
    document.querySelectorAll('.decide').forEach(function (box) {{
      var d = state.d[box.dataset.nr] || {{}};
      box.querySelectorAll('button').forEach(function (b) {{ b.classList.toggle('on', b.dataset.d === d.v); }});
      box.closest('.card').classList.toggle('done', !!d.v);
      if (d.v) done++;
    }});
    var total = data.rows.length;
    document.getElementById('progress').textContent = done + ' von ' + total + ' entschieden';
    document.getElementById('bar').style.width = (100 * done / total) + '%';
    var labels = {{ ok: 'Zugestimmt', nein: 'Widersprochen' }};
    var lines = [data.columns].concat(data.rows.map(function (r) {{
      var d = state.d[r[0]] || {{}};
      return r.slice(0, -3).concat([labels[d.v] || '', d.n || '', d.v || d.n ? state.reviewer : '']);
    }}));
    var csv = '\\ufeff' + lines.map(function (r) {{ return r.map(cell).join(';'); }}).join('\\r\\n') + '\\r\\n';
    link.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
  }}
  who.value = state.reviewer || '';
  who.addEventListener('input', function () {{ state.reviewer = who.value; save(); refresh(); }});
  document.querySelectorAll('.decide').forEach(function (box) {{
    var nr = box.dataset.nr, note = box.querySelector('input');
    note.value = (state.d[nr] || {{}}).n || '';
    box.querySelectorAll('button').forEach(function (b) {{
      b.addEventListener('click', function () {{
        var d = state.d[nr] = state.d[nr] || {{}};
        d.v = d.v === b.dataset.d ? '' : b.dataset.d;
        save(); refresh();
      }});
    }});
    note.addEventListener('input', function () {{ (state.d[nr] = state.d[nr] || {{}}).n = note.value; save(); refresh(); }});
  }});
  refresh();
}})();
</script>
</body>
</html>
"""
