FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies
# build-essential = gcc + g++ + libc development headers
# ffmpeg = video remux + MP3 conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Bot source
COPY bot.py .

EXPOSE 10000

CMD ["python", "bot.py"]
