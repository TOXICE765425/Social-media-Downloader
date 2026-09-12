FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# TgCrypto build ke liye gcc + required tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       g++ \
       make \
       libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

EXPOSE 10000

CMD ["python", "bot.py"]
