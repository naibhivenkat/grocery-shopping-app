# Use official Python image
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code (everything in context)
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
