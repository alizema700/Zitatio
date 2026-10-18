"""Optionales Prüfmodell über eine OpenAI-kompatible Schnittstelle.

Funktioniert mit jedem Server, der /v1/chat/completions anbietet, z. B. vLLM
oder Ollama lokal oder Infomaniak AI Tools mit Apertus oder Qwen in der Schweiz.

Konfiguration über Umgebungsvariablen:
  ZITATIO_LLM_BASE_URL  z. B. http://localhost:8000/v1
  ZITATIO_LLM_MODEL     z. B. swiss-ai/Apertus-8B-Instruct-2509
  ZITATIO_LLM_API_KEY   optional
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

from .verify import Verdict

SYSTEM_PROMPT = """Du prüfst Aussagen aus Due-Diligence-Berichten gegen Seiten aus dem Datenraum.
Urteile nur anhand der gegebenen Seiten, ohne Vorwissen.
Antworte ausschliesslich mit JSON:
{"urteil": "GESTUETZT" | "WIDERSPRUCH" | "NICHT_BELEGT",
 "zitat": "<wörtlicher Satz aus einer Seite, der dein Urteil belegt>",
 "begruendung": "<ein Satz>"}
Das Zitat muss Zeichen für Zeichen aus einer Seite kopiert sein."""


class OpenAICompatibleVerifier:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleVerifier | None":
        base, model = os.environ.get("ZITATIO_LLM_BASE_URL"), os.environ.get("ZITATIO_LLM_MODEL")
        if not base or not model:
            return None
        return cls(base, model, os.environ.get("ZITATIO_LLM_API_KEY"))

    @property
    def description(self) -> str:
        return f"{self.model} @ {self.base_url}"

    def __call__(self, claim: str, passages: list[tuple[str, str]]) -> Verdict | None:
        pages = "\n\n".join(f"=== {label} ===\n{text}" for label, text in passages)
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Aussage:\n{claim}\n\nSeiten:\n{pages}"},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content = json.load(response)["choices"][0]["message"]["content"]
        return parse_verdict(content)


def parse_verdict(content: str) -> Verdict | None:
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    label = str(data.get("urteil", "")).upper().replace("Ü", "UE")
    if label not in {"GESTUETZT", "WIDERSPRUCH", "NICHT_BELEGT"}:
        return None
    return Verdict(label, str(data.get("zitat", "")), str(data.get("begruendung", "")))
