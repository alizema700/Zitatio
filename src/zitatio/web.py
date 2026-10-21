"""Lokale Weboberfläche: Bericht und Datenraum hochladen, Prüfbericht ansehen.

Start: uvicorn zitatio.web:app --reload
Alles läuft lokal; ohne Prüfmodell verlässt kein Dokument den Rechner.

Für einen gemeinsamen Server (Pilot bei einem Schweizer Hoster):
- ZITATIO_PASSWORT schützt alle Seiten mit HTTP-Basic-Anmeldung (Benutzer beliebig, ZITATIO_BENUTZER optional).
- ZITATIO_MAX_UPLOAD_MB begrenzt die Grösse eines Uploads (Standard 2048).
Hochgeladene Dateien bleiben nur im Arbeitsspeicher und werden nicht gespeichert oder protokolliert.
"""

from __future__ import annotations

import base64
import hmac
import html
import json
import os
import re
import time
from functools import lru_cache
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .dataroom import DataRoom
from .llm import OpenAICompatibleVerifier
from .pipeline import run_check
from .versions import parse_decisions
from .render import logo_svg, to_html
from .report import report_text

app = FastAPI(title="Zitatio", docs_url=None, redoc_url=None, openapi_url=None)
MAX_UPLOAD = int(os.environ.get("ZITATIO_MAX_UPLOAD_MB", "2048")) * 2**20


@app.middleware("http")
async def _guard(request: Request, call_next):
    """Anmeldung, wenn ZITATIO_PASSWORT gesetzt ist, und Sicherheits-Header für jede Antwort."""
    password = os.environ.get("ZITATIO_PASSWORT")
    if password and request.url.path != "/gesund":
        user = os.environ.get("ZITATIO_BENUTZER")
        given = request.headers.get("authorization", "")
        ok = False
        if given.startswith("Basic "):
            try:
                name, _, secret = base64.b64decode(given[6:]).decode("utf-8").partition(":")
            except ValueError:
                name, secret = "", ""
            ok = hmac.compare_digest(secret, password) and (user is None or hmac.compare_digest(name, user))
        if not ok:
            return Response("Anmeldung nötig.", 401, {"WWW-Authenticate": 'Basic realm="Zitatio", charset="UTF-8"'})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


async def _read(upload: UploadFile, used: list[int]) -> bytes:
    """Datei lesen und die Gesamtgrösse des Uploads begrenzen."""
    data = await upload.read(MAX_UPLOAD - used[0] + 1)
    used[0] += len(data)
    if used[0] > MAX_UPLOAD:
        raise HTTPException(413, f"Upload grösser als {MAX_UPLOAD // 2**20} MB.")
    return data

app.mount("/assets", StaticFiles(directory=str(resources.files("zitatio").joinpath("assets"))), name="assets")
EXAMPLE = Path(__file__).resolve().parents[2] / "beispiele" / "alpenblick"


def _model():
    model = OpenAICompatibleVerifier.from_env()
    return model, (model.description if model else None)


@lru_cache(maxsize=1)
def example_graph() -> str:
    """Prüfgraph der Startseite: das mitgelieferte Beispiel, echt geprüft."""
    report = EXAMPLE / "dd-bericht.md"
    if not report.exists():
        return "null"
    data = report.read_bytes()
    room = DataRoom.from_folder(EXAMPLE / "datenraum")
    run = run_check(report.name, data.decode(), data, room)
    graph = {
        "bericht": report.name,
        "dokumente": [{"label": d.label, "titel": d.title, "seiten": len(d.pages)} for d in room.documents],
        "aussagen": [
            {
                "nr": f.claim.number,
                "text": f.claim.clean_text,
                "status": f.status.value,
                "label": f.status.label,
                "fundstellen": [c.label for c in f.claim.citations],
                "dokumente": sorted({c.index for c in f.claim.citations}),
                "grund": f.reasons[0] if f.reasons else "",
                "beleg": (
                    {"wo": f"{f.evidence[0].doc_label}, S. {f.evidence[0].page}", "vor": f.evidence[0].before,
                     "treffer": f.evidence[0].match, "nach": f.evidence[0].after}
                    if f.evidence else None
                ),
            }
            for f in run.findings
        ],
    }
    return json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")


LARGE = Path(__file__).resolve().parents[2] / "beispiele" / "gross"


def _trim(text: str, width: int, left: bool = False) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return "…" + text[-width:].lstrip() if left else text[:width].rstrip() + "…"


@lru_cache(maxsize=1)
def hero_data() -> str:
    """Prüfscan der Startseite: der grosse Testfall, echt geprüft, mit einigen typischen Befunden."""
    report = LARGE / "dd-bericht.md"
    if not report.exists():
        return "null"
    from .report import load_report
    from .verify import Status

    started = time.perf_counter()
    room = DataRoom.from_folder(LARGE / "datenraum")
    text, data = load_report(report)
    run = run_check(report.name, text, data, room)
    seconds = time.perf_counter() - started
    order, pages = {}, 0
    for d in room.documents:
        order[d.label] = pages
        pages += len(d.pages)
    picks = [
        lambda f: f.status is Status.GEPRUEFT and f.method == "Regeln" and "EBITDA" in f.claim.text and "Mio." in f.claim.text,
        lambda f: f.status is Status.ABWEICHUNG and any("Spalte" in r for r in f.reasons),
        lambda f: f.status is Status.WIDERSPRUCH and len(f.evidence) > 1 and f.claim.facts,
        lambda f: f.status is Status.GEPRUEFT and f.method == "Nachgerechnet" and "Wachstum" in f.claim.text,
        lambda f: f.status is Status.FALSCHE_FUNDSTELLE and f.claim.facts,
        lambda f: f.status is Status.ABWEICHUNG and any("Zitat" in r for r in f.reasons),
        lambda f: f.status is Status.ABWEICHUNG and any("Betriebsergebnis" in r for r in f.reasons),
    ]
    chosen = []
    for pick in picks:
        f = next((f for f in run.findings if f not in chosen and pick(f)), None)
        if f:
            chosen.append(f)
    items = []
    for f in chosen:
        clean = f.claim.clean_text
        quote = re.search(r"„[^“]+“", clean)
        start, end = (quote.span() if quote else (f.claim.facts[0].start, f.claim.facts[0].end)) if (quote or f.claim.facts) else (0, 0)
        items.append({
            "nr": f.claim.number,
            "text": clean,
            "mark": [start, end],
            "status": f.status.value,
            "label": f.status.label,
            "grund": _trim(f.reasons[-1] if f.status is Status.WIDERSPRUCH else f.reasons[0], 150),
            "zitiert": [order[d.label] + c.page_from - 1 for c in f.claim.citations
                        if (d := room.get(c.index)) and c.page_from and c.page_from <= len(d.pages)],
            "belege": [
                {"wo": f"{e.doc_label}, S. {e.page}", "seite": order.get(e.doc_label, 0) + e.page - 1,
                 "vor": _trim(e.before, 46, left=True), "treffer": e.match, "nach": _trim(e.after, 46)}
                for e in list({(e.doc_label, e.page, e.match): e for e in f.evidence}.values())[:2]
            ],
        })
    hero = {
        "dokumente": [{"label": d.label, "titel": d.title, "seiten": len(d.pages)} for d in room.documents],
        "seiten": pages,
        "aussagen": len(run.findings),
        "sekunden": round(seconds, 1),
        "befunde": items,
    }
    return json.dumps(hero, ensure_ascii=False).replace("</", "<\\/")


@app.get("/gesund")
def health() -> dict:
    """Für den Healthcheck des Hosters; ohne Anmeldung, ohne Daten."""
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    model = _model()[1]
    status = (
        f"Prüfmodell: {html.escape(model)}" if model else "Läuft lokal · Prüfmodell aus, nur Regeln"
    )
    page = resources.files("zitatio").joinpath("assets/index.html").read_text(encoding="utf-8")
    values = {"logo": logo_svg(), "status": status, "version": __version__, "graph": example_graph(), "hero": hero_data()}
    for key, value in values.items():
        page = page.replace("{" + key + "}", value)
    return page


@app.post("/pruefen", response_class=HTMLResponse)
async def check(bericht: UploadFile | None = File(None), datenraum: list[UploadFile] = File(...),
                vorher: UploadFile | None = File(None), entscheide: UploadFile | None = File(None),
                spa: UploadFile | None = File(None), kaeuferfragen: UploadFile | None = File(None),
                sanktionen: UploadFile | None = File(None)) -> str:
    used = [0]
    room = DataRoom()
    for upload in datenraum:
        if upload.filename:  # leeres Feld, wenn nur Ordner oder nur ZIP gewählt wurde
            data = await _read(upload, used)
            path = Path(upload.filename)  # beim Hochladen eines Ordners mit Unterordnern
            await run_in_threadpool(room.add, path.name, data, path.parent.parts[1:])  # OCR blockiert nicht
    if not room.documents:
        raise HTTPException(400, "Der Datenraum enthält keine lesbaren Dokumente.")
    if bericht is not None and bericht.filename:
        data = await _read(bericht, used)
        name = Path(bericht.filename).name
        text = report_text(data, Path(name).suffix.lower())
    else:  # ohne Bericht: Red-Flag-Bericht aus dem Datenraum allein
        data, name, text = b"", "Datenraum", ""
    model, model_name = _model()
    previous = decisions = None
    if vorher is not None and vorher.filename:
        old = Path(vorher.filename).name
        previous = (old, report_text(await _read(vorher, used), Path(old).suffix.lower()))
    if entscheide is not None and entscheide.filename:
        decisions = parse_decisions((await _read(entscheide, used)).decode("utf-8-sig", errors="replace"))
    contract = None
    if spa is not None and spa.filename:
        spa_name = Path(spa.filename).name
        contract = (spa_name, report_text(await _read(spa, used), Path(spa_name).suffix.lower()))
    run = await run_in_threadpool(run_check, name, text, data, room, model, model_name, previous=previous,
                                  decisions=decisions, spa=contract)
    if kaeuferfragen is not None and kaeuferfragen.filename:
        from .antworten import answer, read_questions

        questions = read_questions(await _read(kaeuferfragen, used), Path(kaeuferfragen.filename).suffix.lower())
        run.answers = answer(questions, room)
    if sanktionen is not None and sanktionen.filename:
        from .sanktionen import attach

        attach(run, await _read(sanktionen, used), sanktionen.filename)
    return await run_in_threadpool(to_html, run)


@app.get("/beispiel", response_class=HTMLResponse)
def example() -> str:
    report = EXAMPLE / "dd-bericht.md"
    if not report.exists():
        raise HTTPException(404, "Beispiel nicht vorhanden.")
    data = report.read_bytes()
    room = DataRoom.from_folder(EXAMPLE / "datenraum")
    return to_html(run_check(report.name, data.decode(), data, room))
