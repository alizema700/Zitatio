"""Lokale Weboberfläche: Bericht und Datenraum hochladen, Prüfbericht ansehen.

Start: uvicorn zitatio.web:app --reload
Alles läuft lokal; ohne Prüfmodell verlässt kein Dokument den Rechner.
"""

from __future__ import annotations

import html
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .dataroom import DataRoom, read_pages
from .llm import OpenAICompatibleVerifier
from .pipeline import run_check
from .render import logo_svg, to_html

app = FastAPI(title="Zitatio")
EXAMPLE = Path(__file__).resolve().parents[2] / "beispiele" / "alpenblick"


def _model():
    model = OpenAICompatibleVerifier.from_env()
    return model, (model.description if model else None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    model = _model()[1]
    status = f"Prüfmodell: {html.escape(model)}" if model else "Prüfmodell aus · nur Regeln, alles lokal"
    example = '<a class="btn ghost" href="/beispiel">Beispiel ansehen</a>' if EXAMPLE.exists() else ""
    return INDEX.replace("{logo}", logo_svg()).replace("{status}", status).replace("{example}", example)


@app.post("/pruefen", response_class=HTMLResponse)
async def check(bericht: UploadFile = File(...), datenraum: list[UploadFile] = File(...)) -> str:
    room = DataRoom()
    for upload in datenraum:
        room.add(Path(upload.filename or "").name, await upload.read())
    if not room.documents:
        raise HTTPException(400, "Der Datenraum enthält keine lesbaren Dokumente.")
    data = await bericht.read()
    name = Path(bericht.filename or "bericht").name
    text = "\n\n".join(read_pages(data, ".pdf")) if name.lower().endswith(".pdf") else data.decode(
        "utf-8", errors="replace"
    )
    model, model_name = _model()
    return to_html(run_check(name, text, data, room, model, model_name))


@app.get("/beispiel", response_class=HTMLResponse)
def example() -> str:
    report = EXAMPLE / "dd-bericht.md"
    if not report.exists():
        raise HTTPException(404, "Beispiel nicht vorhanden.")
    data = report.read_bytes()
    room = DataRoom.from_folder(EXAMPLE / "datenraum")
    return to_html(run_check(report.name, data.decode(), data, room))


INDEX = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zitatio</title>
<style>
:root { --ink:#15202B; --ink-2:#4A5560; --line:#DCE1DD; --paper:#F7F8F6; --card:#FFFFFF;
  --green:#1E7A50; --term:#121A22; --term-ink:#DCE3E8; --term-dim:#7D8A95;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#EEF2F0; --ink-2:#A9B4BD; --line:#2A3540; --paper:#121A22; --card:#18222C;
    --green:#4CC38A; --term:#0B1117; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 var(--sans); }
main { max-width:960px; margin:0 auto; padding:24px 16px 80px; }
nav { display:flex; align-items:center; justify-content:space-between; }
.logo { height:26px; width:auto; }
.status { font:12px var(--mono); color:var(--ink-2); }
h1 { font-size:clamp(32px, 6vw, 52px); line-height:1.05; letter-spacing:-0.03em; margin:72px 0 16px; max-width:14em; }
.lead { font-size:18px; color:var(--ink-2); max-width:36em; margin:0 0 28px; }
.term { background:var(--term); color:var(--term-ink); border-radius:10px; padding:16px; font:13px/1.7 var(--mono);
  margin:0 0 48px; overflow-x:auto; white-space:pre; }
.term .d { color:var(--term-dim); } .term .ok { color:#4CC38A; } .term .bad { color:#F07A6E; } .term .warn { color:#E8B04B; }
form { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; display:grid; gap:16px; }
label { font-weight:600; display:grid; gap:6px; }
label span { font-weight:400; color:var(--ink-2); font-size:14px; }
input[type=file] { font:14px var(--sans); color:var(--ink); }
.row { display:flex; gap:12px; flex-wrap:wrap; }
.btn { font:600 15px var(--sans); background:var(--ink); color:var(--paper); border:0; border-radius:8px;
  padding:10px 18px; cursor:pointer; text-decoration:none; display:inline-block; }
.btn.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
ol { padding:0; list-style:none; display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin:48px 0; }
ol li { border-top:2px solid var(--green); padding-top:10px; color:var(--ink-2); font-size:14px; }
ol b { display:block; color:var(--ink); font-size:15px; }
h2 { font-size:20px; margin:48px 0 12px; }
details { border-bottom:1px solid var(--line); padding:12px 0; }
summary { cursor:pointer; font-weight:600; }
details p { color:var(--ink-2); margin:8px 0 0; }
</style>
</head>
<body>
<main>
<nav>{logo}<span class="status">{status}</span></nav>
<h1>Jede Aussage im DD-Bericht, gegen den Datenraum geprüft.</h1>
<p class="lead">Zitatio liest Bericht und Datenraum und markiert jede Aussage als geprüft, abweichend oder unbelegt,
mit der Seite, auf der es steht.</p>
<div class="term"><span class="d">$ zitatio pruefen dd-bericht.md --datenraum ./datenraum</span>
<span class="ok">✓</span> Aktienkapital CHF 500'000            <span class="d">DR 1.1, S. 1</span>    <span class="ok">GEPRÜFT</span>
<span class="bad">✗</span> Nettoerlös CHF 18'540'000             <span class="d">DR 2.1, S. 1</span>    <span class="bad">ABWEICHUNG</span>  <span class="d">Quelle: CHF 18'450'000</span>
<span class="warn">↷</span> Mietzins CHF 312'000 pro Jahr         <span class="d">DR 3.2.1, S. 3</span>  <span class="warn">FALSCHE FUNDSTELLE</span>  <span class="d">steht auf S. 2</span>
<span class="bad">✗</span> Lizenzvertrag Ostwind Software       <span class="d">DR 4.2, S. 1</span>    <span class="bad">QUELLE FEHLT</span>
</div>
<form action="/pruefen" method="post" enctype="multipart/form-data">
  <label>DD-Bericht <span>Markdown, Text oder PDF. Fundstellen im Format [DR 3.2.1, S. 4].</span>
    <input type="file" name="bericht" accept=".md,.txt,.pdf" required></label>
  <label>Datenraum <span>Ordner wählen. Dateinamen beginnen mit der Indexnummer, z. B. „3.2.1 Mietvertrag.pdf“.</span>
    <input type="file" name="datenraum" webkitdirectory directory multiple required></label>
  <div class="row"><button class="btn" type="submit">Prüfen</button>{example}</div>
</form>
<ol>
  <li><b>1. Bericht hochladen</b>IC-Memo oder DD-Report mit Fundstellen.</li>
  <li><b>2. Datenraum wählen</b>PDFs mit Indexnummern, wie im VDR.</li>
  <li><b>3. Prüfen</b>Beträge, Daten, Fristen, Prozente und UIDs gegen die zitierte Seite.</li>
  <li><b>4. Prüfbericht</b>Jede Aussage mit Status, Begründung und Belegstelle.</li>
</ol>
<h2>Fragen</h2>
<details><summary>Verlassen meine Dokumente den Rechner?</summary>
<p>Nein. Ohne Prüfmodell läuft alles lokal. Ein Prüfmodell wird nur über eine Adresse angesprochen, die ihr selbst festlegt, z. B. ein Server in der Schweiz.</p></details>
<details><summary>Was heisst „Geprüft“?</summary>
<p>Jeder Wert der Aussage steht auf der zitierten Seite. Den Sinn bestätigt nur das Prüfmodell, und nur mit einem wörtlichen Zitat aus der Quelle.</p></details>
<details><summary>Was passiert mit Aussagen ohne Zahlen?</summary>
<p>Ohne Prüfmodell bleiben sie „Ungeprüft“, mit der ähnlichsten Textstelle als Lesehilfe.</p></details>
</main>
</body>
</html>
"""
