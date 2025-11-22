# Use Debian base compatible with WeasyPrint
FROM python:3.13-slim-bookworm

# Install system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    build-essential \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libxml2 \
    libxslt1.1 \
    libjpeg62-turbo \
    shared-mime-info \
    fonts-liberation \
    fonts-dejavu-core \
 && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y fonts-noto-color-emoji
# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt


#Test Build
#again testing
# 3rd r

# Environment variable for WeasyPrint headless mode
ENV WEASYPRINT_VISIBLE_HEADLESS=True

# Run your Flask app with Gunicorn
CMD exec gunicorn --bind :8080 --workers 2 --threads 8 main:app
