FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps required by WeasyPrint (used by legacy invoice endpoints).
# Harmless for the new routes; lets `import weasyprint` succeed at boot.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects $PORT (defaults to 8080). Use a shell so the variable is
# expanded at container start, not at image build time.
ENV PORT=8080
EXPOSE 8080

CMD exec gunicorn --bind ":${PORT}" --workers 2 --threads 8 --timeout 120 main:app
