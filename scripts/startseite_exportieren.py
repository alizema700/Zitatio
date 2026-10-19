"""Startseite als eigenständige HTML-Datei exportieren (Schrift, Logo und Icon eingebettet).

Aufruf: python scripts/startseite_exportieren.py ZIELORDNER
Legt startseite.html und beispiel-pruefbericht.html an; "Beispiel ansehen" verweist auf die zweite Datei.
Das Hochladeformular braucht den lokalen Server (uvicorn zitatio.web:app).
"""

import base64
import sys
from importlib import resources
from pathlib import Path

from zitatio.web import example, index

HINT = """
<script>
// Als Datei geöffnet: Prüfen braucht den lokalen Server
if (location.protocol === 'file:') document.querySelectorAll('form.upload').forEach(function (f) {
  f.addEventListener('submit', function (e) {
    e.preventDefault();
    alert('Zum Prüfen bitte Zitatio lokal starten: uvicorn zitatio.web:app, dann http://127.0.0.1:8000 öffnen.');
  });
});
</script>
"""


def main(out: Path) -> None:
    assets = resources.files("zitatio").joinpath("assets")
    page = index()
    for weight in (400, 500, 700):
        name = f"fonts/familjen-grotesk-latin-{weight}-normal.woff2"
        data = base64.b64encode(assets.joinpath(name).read_bytes()).decode()
        page = page.replace(f"url(/assets/{name})", f"url(data:font/woff2;base64,{data})")
    icon = base64.b64encode(assets.joinpath("zitatio-icon.svg").read_bytes()).decode()
    page = page.replace('href="/assets/zitatio-icon.svg"', f'href="data:image/svg+xml;base64,{icon}"')
    page = page.replace('href="/beispiel"', 'href="beispiel-pruefbericht.html"').replace('href="/"', 'href="#"')
    page = page.replace("</body>", HINT + "</body>")
    assert "/assets/" not in page, "nicht eingebettete Datei"
    out.mkdir(parents=True, exist_ok=True)
    (out / "startseite.html").write_text(page, encoding="utf-8")
    (out / "beispiel-pruefbericht.html").write_text(example(), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
