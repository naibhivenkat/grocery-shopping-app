# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install deps
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Copy backend source directly to /app (not /app/backend)
COPY app/backend /app

EXPOSE 8080

# ✅ Run Flask app (since app.py is now directly inside /app)
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
