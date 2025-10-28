# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Copy backend code
COPY . /app/backend

EXPOSE 8080

# Use Gunicorn (production server)
CMD ["gunicorn", "-b", "0.0.0.0:8080", "backend.app:app"]
