# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# ✅ Cloud Run expects this port
EXPOSE 8080

# ✅ Start Flask on same port as Cloud Run ($PORT)
CMD ["python", "app.py"]
