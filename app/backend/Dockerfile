# Use official Python image
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy requirements and install dependencies
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY app/backend/ . 

# Expose port
EXPOSE 5000

# Default command to run your Flask app
CMD ["python", "app.py"]
