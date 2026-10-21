# Zitatio als Webdienst, z. B. für einen Pilot bei einem Schweizer Hoster.
# Bauen:   docker build -t zitatio .
# Starten: docker run -p 8000:8000 -e ZITATIO_PASSWORT=… zitatio
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra \
       tesseract-ocr-ita poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY beispiele ./beispiele
RUN pip install --no-cache-dir -e ".[web]" && useradd --create-home --uid 1000 zitatio

USER zitatio
ENV PYTHONUNBUFFERED=1 ZITATIO_MAX_UPLOAD_MB=2048
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/gesund')" || exit 1
CMD ["uvicorn", "zitatio.web:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
