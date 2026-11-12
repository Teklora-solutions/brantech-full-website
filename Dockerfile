FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Local document OCR; never send scans to an external OCR provider.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY brandtechsolution/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application code
COPY brandtechsolution/ ./brandtechsolution/
COPY skills/ ./skills/
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

WORKDIR /app/brandtechsolution

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
