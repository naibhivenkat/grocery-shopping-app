# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY app/backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend source
COPY app/backend/ .

# Expose port 8080 for Cloud Run
EXPOSE 8080

# Start the Flask app using Gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
