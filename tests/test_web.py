from pathlib import Path

from fastapi.testclient import TestClient

from zitatio.web import app

EXAMPLE = Path(__file__).resolve().parents[1] / "beispiele" / "alpenblick"
client = TestClient(app)


def test_index_and_example():
    page = client.get("/").text
    assert "Kein Satz ohne Beleg" in page
    assert "{graph}" not in page and "\"aussagen\"" in page
    assert "Prüfprotokoll" in client.get("/beispiel").text


def test_upload():
    files = [("bericht", ("dd-bericht.md", (EXAMPLE / "dd-bericht.md").read_bytes()))]
    for pdf in sorted((EXAMPLE / "datenraum").glob("*.pdf")):
        files.append(("datenraum", (f"datenraum/{pdf.name}", pdf.read_bytes(), "application/pdf")))
    response = client.post("/pruefen", files=files)
    assert response.status_code == 200
    assert "Quelle fehlt" in response.text
