"""Lokale Weboberfläche: Bericht und Datenraum hochladen, Prüfbericht ansehen.

Start: uvicorn zitatio.web:app --reload
Alles läuft lokal; ohne Prüfmodell verlässt kein Dokument den Rechner.
"""

from __future__ import annotations

import html
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .dataroom import DataRoom
from .llm import OpenAICompatibleVerifier
from .pipeline import run_check
from .render import logo_svg, to_html
from .report import report_text

app = FastAPI(title="Zitatio")
app.mount("/assets", StaticFiles(directory=str(resources.files("zitatio").joinpath("assets"))), name="assets")
EXAMPLE = Path(__file__).resolve().parents[2] / "beispiele" / "alpenblick"


def _model():
    model = OpenAICompatibleVerifier.from_env()
    return model, (model.description if model else None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    model = _model()[1]
    status = (
        f"Prüfmodell: {html.escape(model)}" if model else "Läuft lokal · Prüfmodell aus, nur Regeln"
    )
    page = resources.files("zitatio").joinpath("assets/index.html").read_text(encoding="utf-8")
    for key, value in {"logo": logo_svg(), "status": status, "version": __version__}.items():
        page = page.replace("{" + key + "}", value)
    return page


@app.post("/pruefen", response_class=HTMLResponse)
async def check(bericht: UploadFile = File(...), datenraum: list[UploadFile] = File(...)) -> str:
    room = DataRoom()
    for upload in datenraum:
        if upload.filename:  # leeres Feld, wenn nur Ordner oder nur ZIP gewählt wurde
            room.add(Path(upload.filename).name, await upload.read())
    if not room.documents:
        raise HTTPException(400, "Der Datenraum enthält keine lesbaren Dokumente.")
    data = await bericht.read()
    name = Path(bericht.filename or "bericht").name
    text = report_text(data, Path(name).suffix.lower())
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
