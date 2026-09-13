FROM python:3.12-slim

# ============================================================
# BASIC PYTHON SETTINGS
# ============================================================

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1


# ============================================================
# WORK DIRECTORY
# ============================================================

WORKDIR /app


# ============================================================
# SYSTEM DEPENDENCIES
# ============================================================

# build-essential:
#   gcc
#   g++
#   make
#   libc development headers
#
# ffmpeg:
#   Video remux / media processing
#
# ca-certificates:
#   HTTPS API requests
#
# curl:
#   Health/debugging support
# ============================================================

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libc6-dev \
        ffmpeg \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*


# ============================================================
# PYTHON REQUIREMENTS
# ============================================================

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ============================================================
# BOT SOURCE
# ============================================================

COPY bot.py .


# ============================================================
# RENDER / WEB HEALTH PORT
# ============================================================

EXPOSE 10000


# ============================================================
# START BOT
# ============================================================

CMD ["python", "bot.py"]
