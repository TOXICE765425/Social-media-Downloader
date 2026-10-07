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
FIREBASE_DATABASE_URL=
FIREBASE_SERVICE_ACCOUNT_JSON=
```

All video platform endpoints and the complete music `/search?song=` endpoint are configured only through environment variables. They are not hard-coded in the bot source.

### Firebase persistent users

The bot stores users under the Firebase Realtime Database path `users/<telegram_user_id>`. On `/start`, the user's Telegram details are saved/updated, including ID, name, username, language, premium flag, first-seen time and last-seen time.

The `/user` and `/users` commands read the current list directly from Firebase. `/broadcast` also loads the Firebase list before sending, so users are retained across restarts, redeployments and new deployments.

Set these Firebase variables:
- `FIREBASE_DATABASE_URL` — your Realtime Database URL.
- `FIREBASE_SERVICE_ACCOUNT_JSON` — the complete Firebase Admin SDK service-account JSON as a single environment-variable value.

Never commit the service-account JSON to GitHub.

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
