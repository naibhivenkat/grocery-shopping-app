FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080

# 👇 Use the correct module path
CMD ["gunicorn", "-b", "0.0.0.0:8080", "backend.main:app"]
