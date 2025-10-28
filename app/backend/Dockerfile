# Use official Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy backend requirements first (so Docker caching works)
COPY app/backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend source files into container
COPY app/backend /app

# Expose Cloud Run port
EXPOSE 8080

# Start Flask app using Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
