# Use official Python image
FROM python:3.11-slim

# Set working directory to backend folder
WORKDIR /app/backend

# Copy requirements first
COPY app/backend/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy only backend code into container
COPY app/backend /app/backend

# Expose the Cloud Run port
EXPOSE 8080

# Run Flask app via Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
