FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# GCC/G++ required to build TgCrypto
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy bot
COPY bot.py .

# Render health server
EXPOSE 10000

# Start bot
CMD ["python", "bot.py"]
