# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Copy current directory contents
COPY . .

EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
