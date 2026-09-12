import os
import re
import json
import asyncio
import tempfile
import threading
from pathlib import Path
from datetime import datetime

import requests
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import FloodWait, RPCError


# ============================================================
# ENVIRONMENT VARIABLES — ONLY THESE 7
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

VIDEO_API_URL = os.getenv("VIDEO_API_URL", "").strip().rstrip("/")
MUSIC_API_URL = os.getenv("MUSIC_API_URL", "").strip().rstrip("/")
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()


# ============================================================
# BASIC VALIDATION
# ============================================================

missing = []

if not BOT_TOKEN:
    missing.append("BOT_TOKEN")

if not API_ID:
    missing.append("API_ID")

if not API_HASH:
    missing.append("API_HASH")

if not ADMIN_ID:
    missing.append("ADMIN_ID")

if not VIDEO_API_URL:
    missing.append("VIDEO_API_URL")

if not MUSIC_API_URL:
    missing.append("MUSIC_API_URL")

if not SUPPORT_URL:
    missing.append("SUPPORT_URL")

if missing:
    raise RuntimeError(
        "Missing Environment Variables: " + ", ".join(missing)
    )


# ============================================================
# CODE SETTINGS
# ============================================================

API_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300

MAX_TELEGRAM_FILE = 49 * 1024 * 1024

MAX_MUSIC_RESULTS = 10

TEMP_DIR = Path(tempfile.gettempdir()) / "misstu_downloader"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

USER_DB = TEMP_DIR / "users.json"

SUPPORTED_PLATFORMS = {
    "youtube": [
        "youtube.com",
        "youtu.be",
    ],
    "instagram": [
        "instagram.com",
    ],
    "tiktok": [
        "tiktok.com",
    ],
    "facebook": [
        "facebook.com",
        "fb.watch",
    ],
}


# ============================================================
# USER DATABASE
# ============================================================

users = {}


def load_users():
    global users

    try:
        if USER_DB.exists():
            with open(USER_DB, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                users = data

    except Exception as e:
        print(f"⚠️ User DB load error: {e}")
        users = {}


def save_users():
    try:
        tmp_file = USER_DB.with_suffix(".tmp")

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                users,
                f,
                indent=2,
                ensure_ascii=False,
            )

        tmp_file.replace(USER_DB)

    except Exception as e:
        print(f"⚠️ User DB save error: {e}")


def register_user(user):
    if not user:
        return

    user_id = str(user.id)

    old = users.get(user_id, {})

    users[user_id] = {
        "user_id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "full_name": " ".join(
            x for x in [
                user.first_name or "",
                user.last_name or "",
            ]
            if x
        ).strip(),
        "username": user.username or "",
        "is_bot": bool(user.is_bot),
        "first_seen": old.get(
            "first_seen",
            datetime.utcnow().isoformat(),
        ),
        "last_seen": datetime.utcnow().isoformat(),
    }

    save_users()


# ============================================================
# FLASK HEALTH SERVER
# ============================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Misstu Downloader Bot is running."


@flask_app.route("/health")
def health():
    return {
        "status": "ok",
        "users": len(users),
    }


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(
        host="0.0.0.0",
        port=port,
    )


# ============================================================
# PYROGRAM CLIENT
# ============================================================

app = Client(
    "misstu_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False,
    max_concurrent_transmissions=1,
)


# ============================================================
# HELPERS
# ============================================================

def detect_platform(url):
    url_lower = url.lower()

    for platform, domains in SUPPORTED_PLATFORMS.items():
        for domain in domains:
            if domain in url_lower:
                return platform

    return None


def extract_url(text):
    if not text:
        return None

    match = re.search(
        r"https?://[^\s<>\"]+",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    url = match.group(0).strip()

    url = url.rstrip(".,!?)]}\"'")

    return url


def safe_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip()

    if not name:
        name = "download"

    return name[:120]


def human_size(size):
    try:
        size = float(size)

        if size < 1024:
            return f"{size:.0f} B"

        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"

        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"

        return f"{size / (1024 * 1024 * 1024):.2f} GB"

    except Exception:
        return "Unknown"


def recursive_urls(obj):
    """
    API response ke kisi bhi nested JSON ke andar
    video/audio URLs dhundhta hai.
    """

    found = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(key).lower()

            if isinstance(value, str):

                value_lower = value.lower()

                if (
                    value.startswith("http://")
                    or value.startswith("https://")
                ):

                    if (
                        ".mp4" in value_lower
                        or ".m3u8" in value_lower
                        or ".webm" in value_lower
                        or ".mov" in value_lower
                        or ".mkv" in value_lower
                        or "video" in key_lower
                        or "download" in key_lower
                        or "media" in key_lower
                        or key_lower in (
                            "url",
                            "sdurl",
                            "hdurl",
                            "videourl",
                        )
                    ):
                        found.append(value)

            elif isinstance(value, (dict, list)):
                found.extend(recursive_urls(value))

    elif isinstance(obj, list):

        for item in obj:
            found.extend(recursive_urls(item))

    return found


def find_media_urls(data):
    """
    Different APIs ke different response formats handle karta hai.
    """

    results = []

    # --------------------------------------------------------
    # Direct common fields
    # --------------------------------------------------------

    if isinstance(data, dict):

        result = data.get("result")

        if isinstance(result, dict):

            direct_keys = [
                "hdUrl",
                "sdUrl",
                "videoUrl",
                "downloadUrl",
                "url",
            ]

            for key in direct_keys:
                value = result.get(key)

                if (
                    isinstance(value, str)
                    and value.startswith(("http://", "https://"))
                ):
                    results.append(value)

            # ------------------------------------------------
            # Facebook / similar
            # ------------------------------------------------

            video = result.get("video")

            if isinstance(video, dict):

                for key in [
                    "hdUrl",
                    "sdUrl",
                    "videoUrl",
                    "downloadUrl",
                    "url",
                ]:
                    value = video.get(key)

                    if (
                        isinstance(value, str)
                        and value.startswith(("http://", "https://"))
                    ):
                        results.append(value)

                videos = video.get("videos")

                if isinstance(videos, list):

                    for item in videos:

                        if not isinstance(item, dict):
                            continue

                        value = item.get("url")

                        if (
                            isinstance(value, str)
                            and value.startswith(
                                ("http://", "https://")
                            )
                        ):
                            results.append(value)

            # ------------------------------------------------
            # Instagram / TikTok videos
            # ------------------------------------------------

            videos = result.get("videos")

            if isinstance(videos, list):

                for item in videos:

                    if not isinstance(item, dict):
                        continue

                    value = item.get("url")

                    if (
                        isinstance(value, str)
                        and value.startswith(
                            ("http://", "https://")
                        )
                    ):
                        results.append(value)

        # ----------------------------------------------------
        # Root-level media fields
        # ----------------------------------------------------

        for key in [
            "hdUrl",
            "sdUrl",
            "videoUrl",
            "downloadUrl",
        ]:

            value = data.get(key)

            if (
                isinstance(value, str)
                and value.startswith(("http://", "https://"))
            ):
                results.append(value)

    # --------------------------------------------------------
    # Recursive fallback
    # --------------------------------------------------------

    results.extend(recursive_urls(data))

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique = []

    for url in results:

        if url not in unique:
            unique.append(url)

    return unique


def choose_best_video(urls):
    """
    Best available video URL choose karta hai.
    """

    if not urls:
        return None

    def score(url):

        u = url.lower()
        points = 0

        if "hd" in u:
            points += 10

        if "720" in u:
            points += 8

        if "1080" in u:
            points += 12

        if "2160" in u:
            points += 15

        if ".mp4" in u:
            points += 5

        if "video" in u:
            points += 2

        return points

    return sorted(
        urls,
        key=score,
        reverse=True,
    )[0]


# ============================================================
# API REQUEST
# ============================================================

def call_video_api(platform, original_url):

    endpoint = (
        f"{VIDEO_API_URL}/api/{platform}"
    )

    try:

        response = requests.get(
            endpoint,
            params={
                "url": original_url,
            },
            timeout=API_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()

        try:
            data = response.json()
        except Exception:
            return None, "API returned invalid JSON."

        return data, None

    except requests.Timeout:
        return None, "API request timed out."

    except requests.RequestException as e:
        return None, f"API request failed: {e}"

    except Exception as e:
        return None, f"Unexpected API error: {e}"


# ============================================================
# DOWNLOAD FILE
# ============================================================

def download_file(url, output_path):

    try:

        with requests.get(
            url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
            },
        ) as response:

            response.raise_for_status()

            total = 0

            with open(output_path, "wb") as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):

                    if not chunk:
                        continue

                    f.write(chunk)

                    total += len(chunk)

                    # Prevent enormous downloads
                    if total > 2 * 1024 * 1024 * 1024:
                        raise RuntimeError(
                            "File is larger than 2 GB."
                        )

        return True, total, None

    except requests.Timeout:
        return False, 0, "Download timed out."

    except requests.RequestException as e:
        return False, 0, f"Download failed: {e}"

    except Exception as e:
        return False, 0, str(e)


# ============================================================
# START COMMAND
# ============================================================

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):

    register_user(message.from_user)

    first_name = (
        message.from_user.first_name
        if message.from_user
        else "User"
    )

    text = (
        f"👋 **Welcome, {first_name}!**\n\n"
        "🚀 **Misstu Downloader Bot**\n\n"
        "Send me a supported video link and "
        "I'll try to download it for you.\n\n"
        "📥 **Supported:**\n"
        "• YouTube\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "🎵 Music search is also available."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Support",
                    url=SUPPORT_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "🎵 Music Search",
                    callback_data="music_help",
                )
            ],
        ]
    )

    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# HELP
# ============================================================

@app.on_message(filters.private & filters.command("help"))
async def help_handler(client, message):

    register_user(message.from_user)

    await message.reply_text(
        "📖 **How to use**\n\n"
        "Simply send a video link.\n\n"
        "Supported platforms:\n"
        "• YouTube\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "For music search use:\n"
        "`/music song name`"
    )


# ============================================================
# MUSIC SEARCH
# ============================================================

@app.on_message(
    filters.private
    & filters.command("music")
)
async def music_handler(client, message):

    register_user(message.from_user)

    if len(message.command) < 2:

        await message.reply_text(
            "🎵 **Music Search**\n\n"
            "Use:\n"
            "`/music song name`\n\n"
            "Example:\n"
            "`/music Arijit Singh`"
        )

        return

    query = " ".join(message.command[1:]).strip()

    status = await message.reply_text(
        "🔎 Searching music..."
    )

    try:

        response = requests.get(
            MUSIC_API_URL,
            params={
                "song": query,
            },
            timeout=API_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:

        await status.edit_text(
            f"❌ Music API error:\n`{e}`"
        )

        return

    # --------------------------------------------------------
    # Extract results
    # --------------------------------------------------------

    results = []

    def collect_music(obj):

        if isinstance(obj, list):

            for item in obj:
                collect_music(item)

        elif isinstance(obj, dict):

            # likely result item
            url = (
                obj.get("url")
                or obj.get("audio")
                or obj.get("audioUrl")
                or obj.get("downloadUrl")
            )

            title = (
                obj.get("title")
                or obj.get("name")
                or obj.get("song")
                or obj.get("videoTitle")
                or "Unknown"
            )

            if (
                isinstance(url, str)
                and url.startswith(("http://", "https://"))
            ):
                results.append(
                    {
                        "title": str(title),
                        "url": url,
                    }
                )

            for value in obj.values():

                if isinstance(value, (dict, list)):
                    collect_music(value)

    collect_music(data)

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique_results = []

    seen_urls = set()

    for item in results:

        if item["url"] in seen_urls:
            continue

        seen_urls.add(item["url"])
        unique_results.append(item)

    results = unique_results[:MAX_MUSIC_RESULTS]

    if not results:

        await status.edit_text(
            "❌ No music result found."
        )

        return

    buttons = []

    for index, item in enumerate(results):

        title = item["title"]

        if len(title) > 35:
            title = title[:32] + "..."

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎵 {index + 1}. {title}",
                    callback_data=f"music:{index}",
                )
            ]
        )

    # Store temporarily on message object impossible,
    # so use simple per-user cache.
    music_cache[str(message.from_user.id)] = results

    buttons.append(
        [
            InlineKeyboardButton(
                "📢 Support",
                url=SUPPORT_URL,
            )
        ]
    )

    await status.edit_text(
        f"🎵 **Music Results**\n\n"
        f"Search: `{query}`\n\n"
        "Select a result:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


music_cache = {}


# ============================================================
# MUSIC CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex(r"^music:")
)
async def music_callback(client, callback_query):

    user_id = str(callback_query.from_user.id)

    results = music_cache.get(user_id, [])

    if not results:

        await callback_query.answer(
            "Search expired. Please search again.",
            show_alert=True,
        )

        return

    try:
        index = int(
            callback_query.data.split(":", 1)[1]
        )
    except Exception:
        await callback_query.answer(
            "Invalid selection.",
            show_alert=True,
        )
        return

    if index >= len(results):

        await callback_query.answer(
            "Result unavailable.",
            show_alert=True,
        )

        return

    item = results[index]

    await callback_query.answer(
        "Downloading...",
    )

    await callback_query.message.reply_text(
        f"🎵 **{item['title']}**\n\n"
        "⏳ Downloading audio..."
    )

    output = (
        TEMP_DIR
        / f"music_{user_id}_{index}.mp3"
    )

    ok, size, error = download_file(
        item["url"],
        output,
    )

    if not ok:

        await callback_query.message.reply_text(
            f"❌ Download failed:\n`{error}`"
        )

        return

    try:

        if size > MAX_TELEGRAM_FILE:

            await callback_query.message.reply_text(
                "❌ Audio file is too large "
                "for the current upload limit."
            )

            return

        await callback_query.message.reply_audio(
            str(output),
            caption=(
                f"🎵 {item['title']}\n\n"
                "⚡ Powered by Misstu"
            ),
        )

    except Exception as e:

        await callback_query.message.reply_text(
            f"❌ Upload failed:\n`{e}`"
        )

    finally:

        try:
            output.unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# MUSIC HELP CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex("^music_help$")
)
async def music_help_callback(
    client,
    callback_query,
):

    await callback_query.answer()

    await callback_query.message.reply_text(
        "🎵 **Music Search**\n\n"
        "Use:\n"
        "`/music song name`\n\n"
        "Example:\n"
        "`/music Arijit Singh`"
    )


# ============================================================
# VIDEO PROCESSOR
# ============================================================

async def process_video(
    client,
    message,
    url,
    platform,
):

    status = await message.reply_text(
        "⚡ **Searching Database...**\n\n"
        "🔌 Connecting API..."
    )

    try:

        await asyncio.sleep(0.5)

        await status.edit_text(
            "⚡ **Searching Database...**\n\n"
            "🔌 Connecting API...\n"
            "🔎 Searching records..."
        )

        data, error = await asyncio.to_thread(
            call_video_api,
            platform,
            url,
        )

        if error:

            await status.edit_text(
                f"❌ **API Error**\n\n{error}"
            )

            return

        await status.edit_text(
            "⚡ **Checking response...**\n\n"
            "📡 API response received."
        )

        video_urls = find_media_urls(data)

        if not video_urls:

            await status.edit_text(
                "❌ **Video URL not found.**\n\n"
                "The API did not return a supported "
                "video URL."
            )

            return

        video_url = choose_best_video(
            video_urls
        )

        if not video_url:

            await status.edit_text(
                "❌ No usable video found."
            )

            return

        await status.edit_text(
            "⚡ **Fetching information...**\n\n"
            "📥 Preparing video download..."
        )

        filename = safe_filename(
            f"{platform}_{message.from_user.id}_{message.id}.mp4"
        )

        output = TEMP_DIR / filename

        ok, size, error = await asyncio.to_thread(
            download_file,
            video_url,
            output,
        )

        if not ok:

            await status.edit_text(
                f"❌ **Download Failed**\n\n"
                f"{error}"
            )

            return

        await status.edit_text(
            "⚡ **Finalizing result...**\n\n"
            f"📦 Size: {human_size(size)}\n"
            "📤 Uploading to Telegram..."
        )

        if size > MAX_TELEGRAM_FILE:

            await status.edit_text(
                "❌ **File Too Large**\n\n"
                f"Downloaded size: {human_size(size)}\n\n"
                "The current Telegram upload path "
                "does not accept this file size."
            )

            return

        caption = (
            f"🎬 **{platform.title()} Video**\n\n"
            f"📦 Size: `{human_size(size)}`\n"
            "⚡ Powered by Misstu"
        )

        try:

            await message.reply_video(
                str(output),
                caption=caption,
                supports_streaming=True,
            )

            await status.delete()

        except Exception as upload_error:

            await status.edit_text(
                f"❌ **Upload Failed**\n\n"
                f"`{upload_error}`"
            )

    except FloodWait as e:

        await asyncio.sleep(e.value)

        try:
            await process_video(
                client,
                message,
                url,
                platform,
            )
        except Exception:
            pass

    except Exception as e:

        print(
            f"Video processing error: {repr(e)}"
        )

        try:

            await status.edit_text(
                f"❌ **Something went wrong**\n\n"
                f"`{e}`"
            )

        except Exception:
            pass

    finally:

        # Find temporary files belonging to this message
        prefix = f"{platform}_{message.from_user.id}_{message.id}"

        try:

            for file in TEMP_DIR.glob(
                f"{prefix}*"
            ):
                try:
                    file.unlink()
                except Exception:
                    pass

        except Exception:
            pass


# ============================================================
# VIDEO MESSAGE HANDLER
# ============================================================

@app.on_message(
    filters.text
    & ~filters.command(
        [
            "start",
            "help",
            "music",
            "broadcast",
            "user",
            "users",
        ]
    )
)
async def video_handler(client, message):

    if not message.from_user:
        return

    register_user(message.from_user)

    url = extract_url(
        message.text or ""
    )

    if not url:
        return

    platform = detect_platform(url)

    if not platform:
        return

    await process_video(
        client,
        message,
        url,
        platform,
    )


# ============================================================
# GROUP USER REGISTRATION
# ============================================================

@app.on_message(
    filters.group & filters.text
)
async def group_register_handler(
    client,
    message,
):

    if message.from_user:

        register_user(
            message.from_user
        )

    # Don't process commands here
    if not message.text:
        return

    if message.text.startswith("/"):
        return

    url = extract_url(
        message.text
    )

    if not url:
        return

    platform = detect_platform(url)

    if not platform:
        return

    await process_video(
        client,
        message,
        url,
        platform,
    )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(user_id):
    return int(user_id) == ADMIN_ID


# ============================================================
# BROADCAST
# ============================================================

@app.on_message(
    filters.private
    & filters.command("broadcast")
)
async def broadcast_handler(
    client,
    message,
):

    register_user(message.from_user)

    if not is_admin(message.from_user.id):

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/broadcast Your message here`"
        )

        return

    broadcast_text = message.text.split(
        None,
        1,
    )[1].strip()

    if not broadcast_text:

        await message.reply_text(
            "❌ Broadcast message empty."
        )

        return

    status = await message.reply_text(
        "📢 Starting broadcast..."
    )

    success = 0
    failed = 0

    for user_id in list(users.keys()):

        try:

            await client.send_message(
                int(user_id),
                broadcast_text,
            )

            success += 1

            await asyncio.sleep(0.05)

        except FloodWait as e:

            await asyncio.sleep(e.value)

            try:

                await client.send_message(
                    int(user_id),
                    broadcast_text,
                )

                success += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

    await status.edit_text(
        "📢 **Broadcast Completed**\n\n"
        f"✅ Sent: `{success}`\n"
        f"❌ Failed: `{failed}`\n"
        f"👥 Total: `{len(users)}`"
    )


# ============================================================
# BROADCAST TO SPECIFIC USER
# ============================================================

@app.on_message(
    filters.private
    & filters.command("broadcast_user")
)
async def broadcast_user_handler(
    client,
    message,
):

    register_user(message.from_user)

    if not is_admin(message.from_user.id):

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if len(message.command) < 3:

        await message.reply_text(
            "Usage:\n"
            "`/broadcast_user USER_ID MESSAGE`"
        )

        return

    try:
        target_id = int(
            message.command[1]
        )
    except ValueError:

        await message.reply_text(
            "❌ Invalid User ID."
        )

        return

    text = message.text.split(
        None,
        2,
    )[2].strip()

    if not text:

        await message.reply_text(
            "❌ Message empty."
        )

        return

    try:

        await client.send_message(
            target_id,
            text,
        )

        await message.reply_text(
            f"✅ Message sent to `{target_id}`"
        )

    except Exception as e:

        await message.reply_text(
            f"❌ Failed:\n`{e}`"
        )


# ============================================================
# USER LIST
# ============================================================

@app.on_message(
    filters.private
    & filters.command(
        ["user", "users"]
    )
)
async def users_handler(
    client,
    message,
):

    register_user(message.from_user)

    if not is_admin(message.from_user.id):

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if not users:

        await message.reply_text(
            "👥 No users registered yet."
        )

        return

    lines = []

    lines.append(
        "👥 **REGISTERED USERS**"
    )

    lines.append(
        f"Total: `{len(users)}`"
    )

    lines.append("")

    for index, data in enumerate(
        users.values(),
        start=1,
    ):

        full_name = (
            data.get("full_name")
            or "Unknown"
        )

        username = data.get(
            "username"
        )

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        user_id = data.get(
            "user_id",
            "Unknown",
        )

        bot_status = (
            "BOT"
            if data.get("is_bot")
            else "USER"
        )

        lines.append(
            f"**{index}. {full_name}**\n"
            f"├ ID: `{user_id}`\n"
            f"├ Username: {username_text}\n"
            f"└ Type: `{bot_status}`\n"
        )

    # Telegram message limit
    chunks = []

    current = ""

    for line in lines:

        if len(current) + len(line) > 3800:

            chunks.append(current)
            current = ""

        current += line + "\n"

    if current:
        chunks.append(current)

    for chunk in chunks:

        await message.reply_text(
            chunk
        )


# ============================================================
# ERROR HANDLER
# ============================================================

@app.on_message(
    filters.private
    & filters.command("id")
)
async def id_handler(client, message):

    register_user(message.from_user)

    await message.reply_text(
        f"🆔 Your Telegram User ID:\n"
        f"`{message.from_user.id}`"
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    load_users()

    print("=" * 55)
    print("🚀 MISSTU DOWNLOADER BOT")
    print("=" * 55)
    print(f"👥 Users: {len(users)}")
    print(f"🎬 Video API: {'Configured' if VIDEO_API_URL else 'Missing'}")
    print(f"🎵 Music API: {'Configured' if MUSIC_API_URL else 'Missing'}")
    print(f"📢 Support: {'Configured' if SUPPORT_URL else 'Missing'}")
    print("=" * 55)

    # Flask health server
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    # Start Telegram bot
    print("🤖 Starting Telegram bot...")

    app.run()
