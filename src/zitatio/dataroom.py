"""Datenraum einlesen: Dokumente mit Indexnummer und Seitentexten.

Konvention: Der Dateiname beginnt mit der Indexnummer des Datenraums,
z. B. "3.2.1 Mietvertrag Werk Winterthur.pdf". Ein DD-Bericht zitiert
dann "[DR 3.2.1, S. 2]".
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".txt", ".md"}
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
        wanted = normalize_index(index)
        for doc in self.documents:
            if doc.index == wanted:
                return doc
        return None

    def add(self, name: str, data: bytes) -> None:
        stem, suffix = Path(name).stem, Path(name).suffix.lower()
        if suffix == ".zip":
            self.add_zip(name, data)
            return
        if suffix not in SUPPORTED_SUFFIXES:
            self.warnings.append(f"{name}: Dateityp nicht unterstützt, übersprungen.")
            return
        pages = read_pages(data, suffix)
        m = _INDEX_RE.match(stem)
        index, title = (normalize_index(m.group(1)), m.group(2)) if m else (None, stem)
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

    def add_zip(self, name: str, data: bytes) -> None:
        """ZIP-Export eines virtuellen Datenraums; Unterordner werden mitgelesen."""
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            self.warnings.append(f"{name}: kein gültiges ZIP-Archiv.")
            return
        with archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                inner = _zip_name(info)
                base = Path(inner).name
                if info.is_dir() or not base or base.startswith(".") or "__MACOSX" in inner:
                    continue
                if Path(base).suffix.lower() == ".zip":
                    self.warnings.append(f"{inner}: verschachteltes ZIP, übersprungen.")
                    continue
                self.add(base, archive.read(info))

    @classmethod
    def from_folder(cls, folder: str | Path) -> "DataRoom":
        room = cls()
        if Path(folder).is_file():
            room.add(Path(folder).name, Path(folder).read_bytes())
            return room
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                room.add(path.name, path.read_bytes())
        return room


def normalize_index(index: str) -> str:
    """'01.02' und '1.2' bezeichnen dasselbe Dokument."""
    return ".".join(str(int(p)) for p in index.strip(".").split("."))


def _zip_name(info: zipfile.ZipInfo) -> str:
    """Windows-ZIPs speichern Umlaute oft in CP437 statt UTF-8."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


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
    if suffix == ".xlsx":
        from .xlsx import xlsx_to_pages

        return [clean_text(p) for p in xlsx_to_pages(data)]
    text = data.decode("utf-8", errors="replace")
    return [clean_text(p) for p in text.split("\f")]


def clean_text(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # Silbentrennung am Zeilenende
    return text.replace("\r", "")
