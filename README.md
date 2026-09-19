# Misstu Telegram Video + Music Downloader

Pyrogram/MTProto Telegram bot with:
- Instagram, YouTube, TikTok and Facebook video downloading
- Music search with inline result buttons
- HD-first video selection where the API provides quality
- Streaming download to disk, so the complete file is not kept in RAM
- Docker, Render, Railway and VPS deployment
- No force-join system
- Optional Support button
- No personal token, API hash or API URL hard-coded

## Environment

Copy `.env.example` to `.env`:

```env
BOT_TOKEN=
API_ID=
API_HASH=
ADMIN_ID=
SUPPORT_URL=
VIDEO_API_URL=
MUSIC_API_URL=
```

Note:- Set Video_Api_Url And Music_Api_url without endpoints 

Every host/user should put their own Telegram credentials, support URL and API URLs here.

## Commands

`/start`
`/help`
`/menu`
`/music Arijit Singh`

For videos, send a supported public URL.

## Local/VPS

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Docker

```bash
cp .env.example .env
# edit .env
docker compose up -d --build
```

## Render/Railway

Push the repository to GitHub, deploy it as a Docker service, and add the environment variables.

The `/health` endpoint is included.

## Large media

The bot downloads the returned media URL to temporary disk storage and uploads it through Pyrogram/MTProto. Telegram still enforces its current maximum upload/file size; files above Telegram's limit cannot be sent.

Use the downloader only for content you are permitted to download/redistribute and respect platform terms.
