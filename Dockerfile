# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (if you later need libusb/ios/adb tools, add here)
RUN apt-get update && apt-get install -y --no-install-recommends \    build-essential \    curl \    && rm -rf /var/lib/apt/lists/*

# Copy code
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Package layout: a Python package directory
COPY . /app

EXPOSE 8090

CMD ["uvicorn", "mobile_device_manager.main:app", "--host", "0.0.0.0", "--port", "8090"]
