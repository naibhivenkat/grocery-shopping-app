# Use official Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app/backend

# Copy only backend code (not the entire repo)
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend files
COPY app/backend/ .

# Expose port 8080 (Cloud Run default)
EXPOSE 8080

# Start Gunicorn with proper module path
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
