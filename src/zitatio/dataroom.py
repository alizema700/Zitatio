"""Datenraum einlesen: Dokumente mit Indexnummer und Seitentexten.

Konvention: Der Dateiname beginnt mit der Indexnummer des Datenraums,
z. B. "3.2.1 Mietvertrag Werk Winterthur.pdf". Ein DD-Bericht zitiert
dann "[DR 3.2.1, S. 2]".
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
_INDEX_RE = re.compile(r"^(\d+(?:\.\d+)*)[\s_\-]+(.+)$")


@dataclass
class Document:
    name: str
    index: str | None
    title: str
    sha256: str
    pages: list[str]

    @property
    def label(self) -> str:
        return f"DR {self.index}" if self.index else self.name


@dataclass
class DataRoom:
    documents: list[Document] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def get(self, index: str) -> Document | None:
        for doc in self.documents:
            if doc.index == index:
                return doc
        return None

    def add(self, name: str, data: bytes) -> None:
        stem, suffix = Path(name).stem, Path(name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            self.warnings.append(f"{name}: Dateityp nicht unterstützt, übersprungen.")
            return
        pages = read_pages(data, suffix)
        m = _INDEX_RE.match(stem)
        index, title = (m.group(1), m.group(2)) if m else (None, stem)
        if index is None:
            self.warnings.append(f"{name}: keine Indexnummer im Dateinamen, nicht zitierbar.")
        elif self.get(index):
            self.warnings.append(f"{name}: Indexnummer {index} doppelt vergeben, übersprungen.")
            return
        empty = [i + 1 for i, p in enumerate(pages) if not p.strip()]
        if empty:
            self.warnings.append(
                f"{name}: Seite(n) {', '.join(map(str, empty))} ohne Textebene (OCR nötig)."
            )
        digest = hashlib.sha256(data).hexdigest()
        self.documents.append(Document(Path(name).name, index, title, digest, pages))
        self.documents.sort(key=lambda d: _index_key(d.index))

    @classmethod
    def from_folder(cls, folder: str | Path) -> "DataRoom":
        room = cls()
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                room.add(path.name, path.read_bytes())
        return room


def _index_key(index: str | None):
    return [int(p) for p in index.split(".")] if index else [10**9]


def read_pages(data: bytes, suffix: str) -> list[str]:
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [clean_text(page.extract_text() or "") for page in reader.pages]
    if suffix == ".docx":
        from .docx import docx_to_text

        return [clean_text(p) for p in docx_to_text(data).split("\f")]
    text = data.decode("utf-8", errors="replace")
    return [clean_text(p) for p in text.split("\f")]


def clean_text(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # Silbentrennung am Zeilenende
    return text.replace("\r", "")
