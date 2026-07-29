FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py config.example.ini ./
COPY invoice_bot ./invoice_bot
COPY tests ./tests

RUN mkdir -p /app/data /app/logs && chown -R app:app /app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os; os.kill(1, 0)"
CMD ["python", "app.py"]
