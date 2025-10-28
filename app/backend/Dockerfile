# Use official Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements first (for caching)
COPY app/backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend source files into container
COPY app/backend /app/backend

# Expose Cloud Run port
EXPOSE 8080

# ✅ Start Flask app using Gunicorn, referencing full package path
CMD ["gunicorn", "-b", "0.0.0.0:8080", "backend.app:app"]
