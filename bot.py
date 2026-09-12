import os
import re
import json
import time
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, jsonify
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# =========================================================
# ENVIRONMENT VARIABLES — ONLY THESE 7
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

VIDEO_API_URL = os.getenv("VIDEO_API_URL", "").strip().rstrip("/")
MUSIC_API_URL = os.getenv("MUSIC_API_URL", "").strip().rstrip("/")
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()


# =========================================================
# BASIC SETTINGS
# =========================================================

PORT = int(os.getenv("PORT", "10000"))

API_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300

MAX_FILE_SIZE = 49 * 1024 * 1024

TEMP_DIR = Path(tempfile.gettempdir()) / "social_media_downloader"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

USER_DB = TEMP_DIR / "users.json"


# =========================================================
# VALIDATION
# =========================================================

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
        "Missing environment variables: " + ", ".join(missing)
    )


# =========================================================
# USER DATABASE
# =========================================================

users = {}
users_lock = threading.Lock()


def load_users():
    global users

    try:
        if USER_DB.exists():
            with open(USER_DB, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                users = data
            else:
                users = {}

    except Exception as e:
        print("User DB load error:", e)
        users = {}


def save_users():
    try:
        USER_DB.parent.mkdir(parents=True, exist_ok=True)

        tmp = USER_DB.with_suffix(".tmp")

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

        tmp.replace(USER_DB)

    except Exception as e:
        print("User DB save error:", e)


def register_user(user):
    if not user:
        return

    try:
        uid = str(user.id)

        with users_lock:

            old = users.get(uid, {})

            users[uid] = {
                "user_id": user.id,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username or "",
                "full_name": (
                    f"{user.first_name or ''} "
                    f"{user.last_name or ''}"
                ).strip(),
                "is_bot": bool(user.is_bot),
                "first_seen": old.get("first_seen", int(time.time())),
                "last_seen": int(time.time())
            }

            save_users()

    except Exception as e:
        print("Register user error:", e)


load_users()


# =========================================================
# FLASK HEALTH SERVER
# =========================================================

health_app = Flask(__name__)


@health_app.route("/")
def home():
    return jsonify({
        "status": "online",
        "bot": "Social Media Downloader"
    })


@health_app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    }), 200


def run_health_server():
    health_app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True,
        use_reloader=False
    )


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# =========================================================
# PYROGRAM
# =========================================================

bot = Client(
    "social_media_downloader",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False,
    max_concurrent_transmissions=1
)


# =========================================================
# KEYBOARDS
# =========================================================

def start_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 Download Video",
                callback_data="download_help"
            )
        ],
        [
            InlineKeyboardButton(
                "🎵 Music Search",
                callback_data="music_help"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Support",
                url=SUPPORT_URL
            )
        ]
    ])


def back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="back_home"
            )
        ]
    ])


# =========================================================
# PROFILE PHOTO WELCOME
# =========================================================

async def get_profile_photo(user):

    try:
        chat = await bot.get_chat(user.id)

        if not chat.photo:
            return None

        photo_id = chat.photo.big_file_id

        path = await bot.download_media(
            photo_id,
            file_name=str(
                TEMP_DIR / f"profile_{user.id}.jpg"
            )
        )

        return path

    except Exception as e:
        print("Profile photo error:", e)
        return None


async def send_welcome(chat_id, user, edit_message=None):

    first_name = user.first_name or "User"

    text = (
        f"👋 **Welcome, {first_name}!**\n\n"
        "⚡ **Social Media Downloader**\n\n"
        "📥 Download videos from:\n"
        "• Instagram\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "🎵 Search music using `/music song name`\n\n"
        "👇 Choose an option below."
    )

    photo = await get_profile_photo(user)

    try:

        if edit_message:

            await edit_message.edit_text(
                text,
                reply_markup=start_keyboard()
            )

        elif photo and os.path.exists(photo):

            await bot.send_photo(
                chat_id,
                photo,
                caption=text,
                reply_markup=start_keyboard()
            )

        else:

            await bot.send_message(
                chat_id,
                text,
                reply_markup=start_keyboard()
            )

    except Exception as e:
        print("Welcome send error:", e)

        try:
            await bot.send_message(
                chat_id,
                text,
                reply_markup=start_keyboard()
            )
        except Exception:
            pass

    finally:

        if photo and os.path.exists(photo):

            try:
                os.remove(photo)
            except Exception:
                pass


# =========================================================
# START
# =========================================================

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):

    register_user(message.from_user)

    await send_welcome(
        message.chat.id,
        message.from_user
    )


# =========================================================
# HELP
# =========================================================

@bot.on_message(filters.private & filters.command("help"))
async def help_handler(client, message):

    register_user(message.from_user)

    text = (
        "📥 **Social Media Downloader**\n\n"
        "Send a supported video URL directly.\n\n"
        "Supported platforms:\n"
        "• Instagram\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "🎵 Music:\n"
        "`/music song name`\n\n"
        "Example:\n"
        "`/music Arijit Singh`\n"
    )

    await message.reply_text(
        text,
        reply_markup=start_keyboard()
    )


# =========================================================
# CALLBACKS
# =========================================================

@bot.on_callback_query()
async def callback_handler(client, query):

    try:
        register_user(query.from_user)

        if query.data == "back_home":

            await query.answer()

            await send_welcome(
                query.message.chat.id,
                query.from_user,
                query.message
            )

        elif query.data == "download_help":

            await query.answer()

            text = (
                "📥 **Video Downloader**\n\n"
                "Simply send an Instagram, YouTube, "
                "TikTok or Facebook video link.\n\n"
                "Example:\n"
                "`https://www.youtube.com/watch?v=...`"
            )

            await query.message.edit_text(
                text,
                reply_markup=back_keyboard()
            )

        elif query.data == "music_help":

            await query.answer()

            text = (
                "🎵 **Music Search**\n\n"
                "Use:\n"
                "`/music song name`\n\n"
                "Example:\n"
                "`/music Arijit Singh`"
            )

            await query.message.edit_text(
                text,
                reply_markup=back_keyboard()
            )

        else:
            await query.answer()

    except Exception as e:
        print("Callback error:", e)


# =========================================================
# URL DETECTION
# =========================================================

URL_PATTERN = re.compile(
    r"https?://[^\s]+",
    re.IGNORECASE
)


def detect_platform(url):

    url_lower = url.lower()

    if (
        "instagram.com" in url_lower
        or "instagr.am" in url_lower
    ):
        return "instagram"

    if (
        "youtube.com" in url_lower
        or "youtu.be" in url_lower
        or "youtube-nocookie.com" in url_lower
    ):
        return "youtube"

    if (
        "tiktok.com" in url_lower
        or "vm.tiktok.com" in url_lower
    ):
        return "tiktok"

    if (
        "facebook.com" in url_lower
        or "fb.watch" in url_lower
        or "m.facebook.com" in url_lower
    ):
        return "facebook"

    return None


# =========================================================
# API REQUEST
# =========================================================

def call_video_api(platform, url):

    endpoint = (
        f"{VIDEO_API_URL}/api/"
        f"{platform}?url={quote(url, safe='')}"
    )

    print("API:", endpoint)

    response = requests.get(
        endpoint,
        timeout=API_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# RECURSIVE URL EXTRACTION
# =========================================================

VIDEO_KEYS = [
    "hdUrl",
    "sdUrl",
    "videoUrl",
    "video_url",
    "download_url",
    "downloadUrl",
    "url",
    "src"
]


def is_video_url(value):

    if not isinstance(value, str):
        return False

    v = value.lower()

    if not v.startswith(("http://", "https://")):
        return False

    video_extensions = (
        ".mp4",
        ".mkv",
        ".mov",
        ".webm",
        ".m4v"
    )

    return (
        any(ext in v for ext in video_extensions)
        or "video" in v
        or "videoplayback" in v
    )


def recursive_find_video(obj):

    found = []

    if isinstance(obj, dict):

        # Priority keys first
        for key in VIDEO_KEYS:

            value = obj.get(key)

            if is_video_url(value):

                found.append({
                    "url": value,
                    "quality": str(
                        obj.get("qualityLabel")
                        or obj.get("quality")
                        or key
                    ),
                    "has_audio": bool(
                        obj.get("hasAudio")
                        or obj.get("audioAvailable")
                        or not obj.get("needsMerge", False)
                    )
                })

        # Then inspect everything else
        for key, value in obj.items():

            if key in VIDEO_KEYS:
                continue

            found.extend(
                recursive_find_video(value)
            )

    elif isinstance(obj, list):

        for item in obj:
            found.extend(
                recursive_find_video(item)
            )

    return found


def get_best_video(api_data, platform):

    # -----------------------------------------------------
    # FACEBOOK
    # -----------------------------------------------------

    if platform == "facebook":

        result = api_data.get("result", {})

        if isinstance(result, dict):

            for key in ["hdUrl", "sdUrl"]:

                url = result.get(key)

                if is_video_url(url):
                    return {
                        "url": url,
                        "quality": key
                    }

    # -----------------------------------------------------
    # INSTAGRAM
    # -----------------------------------------------------

    if platform == "instagram":

        result = api_data.get("result", {})

        videos = (
            result.get("videos", [])
            if isinstance(result, dict)
            else []
        )

        if isinstance(videos, list):

            # HD first
            for video in videos:

                if not isinstance(video, dict):
                    continue

                url = video.get("url")

                if (
                    is_video_url(url)
                    and str(video.get("quality", "")).lower() == "hd"
                ):
                    return {
                        "url": url,
                        "quality": "HD"
                    }

            for video in videos:

                if not isinstance(video, dict):
                    continue

                url = video.get("url")

                if is_video_url(url):
                    return {
                        "url": url,
                        "quality": str(
                            video.get("quality", "video")
                        )
                    }

    # -----------------------------------------------------
    # YOUTUBE
    # -----------------------------------------------------

    if platform == "youtube":

        result = api_data.get("result", {})

        if isinstance(result, dict):

            video_data = result.get("video", {})

            if isinstance(video_data, dict):

                videos = video_data.get("videos", [])

                if isinstance(videos, list):

                    # Prefer streams that already contain audio
                    for video in videos:

                        if not isinstance(video, dict):
                            continue

                        url = video.get("url")

                        if not is_video_url(url):
                            continue

                        if (
                            video.get("hasAudio") is True
                            or video.get("audioAvailable") is True
                        ) and video.get("needsMerge") is not True:

                            return {
                                "url": url,
                                "quality": str(
                                    video.get("qualityLabel")
                                    or video.get("quality")
                                    or "YouTube"
                                )
                            }

                    # Fallback
                    for video in videos:

                        if not isinstance(video, dict):
                            continue

                        url = video.get("url")

                        if is_video_url(url):

                            return {
                                "url": url,
                                "quality": str(
                                    video.get("qualityLabel")
                                    or video.get("quality")
                                    or "YouTube"
                                )
                            }

    # -----------------------------------------------------
    # GENERIC FALLBACK
    # -----------------------------------------------------

    found = recursive_find_video(api_data)

    if found:

        # Prefer HD / highest-looking quality
        found.sort(
            key=lambda x: (
                "hd" in x["quality"].lower(),
                "1080" in x["quality"],
                "720" in x["quality"]
            ),
            reverse=True
        )

        return found[0]

    return None


# =========================================================
# DOWNLOAD FILE
# =========================================================

def download_file(url, filename):

    path = TEMP_DIR / filename

    with requests.get(
        url,
        stream=True,
        timeout=DOWNLOAD_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    ) as response:

        response.raise_for_status()

        total = 0

        with open(path, "wb") as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 256
            ):

                if not chunk:
                    continue

                total += len(chunk)

                if total > MAX_FILE_SIZE:
                    raise ValueError(
                        "File is larger than Telegram upload limit."
                    )

                f.write(chunk)

    return path


# =========================================================
# VIDEO HANDLER
# =========================================================

@bot.on_message(
    filters.text
    & ~filters.command([
        "start",
        "help",
        "music",
        "user",
        "users",
        "broadcast"
    ])
)
async def video_handler(client, message):

    register_user(message.from_user)

    text = message.text or ""

    match = URL_PATTERN.search(text)

    if not match:
        return

    url = match.group(0)

    platform = detect_platform(url)

    if not platform:
        return

    status = await message.reply_text(
        "⏳ **Processing your video...**\n\n"
        "🔗 Connecting to downloader\n"
        "🔎 Searching video\n"
        "📦 Preparing file..."
    )

    file_path = None

    try:

        api_data = call_video_api(
            platform,
            url
        )

        if not api_data.get("success", True):
            raise ValueError(
                "Downloader API returned an error."
            )

        video = get_best_video(
            api_data,
            platform
        )

        if not video:
            raise ValueError(
                "No downloadable video found."
            )

        await status.edit_text(
            "⬇️ **Downloading video...**\n\n"
            f"🎬 Platform: `{platform.title()}`\n"
            f"🎞 Quality: `{video.get('quality', 'Auto')}`"
        )

        extension = ".mp4"

        file_path = download_file(
            video["url"],
            f"video_{message.from_user.id}_{int(time.time())}{extension}"
        )

        size_mb = file_path.stat().st_size / (1024 * 1024)

        await status.edit_text(
            "📤 **Uploading to Telegram...**"
        )

        caption = (
            f"🎬 **{platform.title()} Video**\n\n"
            f"📦 Size: `{size_mb:.1f} MB`\n"
            f"⚡ Powered by **Misstu**"
        )

        await client.send_video(
            chat_id=message.chat.id,
            video=str(file_path),
            caption=caption,
            supports_streaming=True
        )

        await status.delete()

    except Exception as e:

        print(
            f"Video error [{platform}]:",
            repr(e)
        )

        try:
            await status.edit_text(
                "❌ **Download failed**\n\n"
                f"`{str(e)[:1000]}`"
            )
        except Exception:
            pass

    finally:

        if file_path and file_path.exists():

            try:
                file_path.unlink()
            except Exception:
                pass


# =========================================================
# MUSIC SEARCH API
# =========================================================

def search_music(song):

    endpoint = (
        f"{MUSIC_API_URL}/search"
        f"?song={quote(song, safe='')}"
    )

    print("Music API:", endpoint)

    response = requests.get(
        endpoint,
        timeout=API_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# MUSIC COMMAND
# =========================================================

@bot.on_message(
    filters.private & filters.command("music")
)
async def music_handler(client, message):

    register_user(message.from_user)

    if len(message.command) < 2:

        await message.reply_text(
            "🎵 **Music Search**\n\n"
            "Use:\n"
            "`/music song name`\n\n"
            "Example:\n"
            "`/music Arijit Singh`",
            reply_markup=back_keyboard()
        )

        return

    song = message.text.split(
        " ",
        1
    )[1].strip()

    status = await message.reply_text(
        f"🔎 Searching music:\n"
        f"**{song}**"
    )

    file_path = None

    try:

        data = search_music(song)

        if not data.get("success"):
            raise ValueError(
                "Music API returned unsuccessful response."
            )

        results = data.get("results", [])

        if not isinstance(results, list) or not results:

            await status.edit_text(
                "❌ **No music result found.**"
            )

            return

        # Use first valid result
        selected = None

        for item in results:

            if not isinstance(item, dict):
                continue

            download_url = item.get(
                "download_url"
            )

            if download_url:
                selected = item
                break

        if not selected:

            await status.edit_text(
                "❌ **No downloadable music found.**"
            )

            return

        title = (
            selected.get("title")
            or song
        )

        artists = (
            selected.get("artists")
            or "Unknown Artist"
        )

        duration = (
            selected.get("duration")
            or ""
        )

        download_url = selected.get(
            "download_url"
        )

        await status.edit_text(
            "⬇️ **Downloading music...**\n\n"
            f"🎵 {title}\n"
            f"👤 {artists}"
        )

        file_path = download_file(
            download_url,
            f"music_{message.from_user.id}_{int(time.time())}.mp4"
        )

        size_mb = file_path.stat().st_size / (1024 * 1024)

        await status.edit_text(
            "📤 **Uploading music...**"
        )

        caption = (
            f"🎵 **{title}**\n\n"
            f"👤 {artists}\n"
            f"💿 {selected.get('album', '')}\n"
            f"⏱ {duration}\n"
            f"📦 {size_mb:.1f} MB\n\n"
            f"⚡ Powered by **Misstu**"
        )

        try:

            await client.send_audio(
                chat_id=message.chat.id,
                audio=str(file_path),
                caption=caption,
                title=title,
                performer=artists
            )

        except Exception as audio_error:

            print(
                "send_audio failed:",
                repr(audio_error)
            )

            # Fallback: send as document
            await client.send_document(
                chat_id=message.chat.id,
                document=str(file_path),
                caption=caption
            )

        await status.delete()

    except Exception as e:

        print(
            "Music error:",
            repr(e)
        )

        try:
            await status.edit_text(
                "❌ **Music download failed**\n\n"
                f"`{str(e)[:1000]}`"
            )
        except Exception:
            pass

    finally:

        if file_path and file_path.exists():

            try:
                file_path.unlink()
            except Exception:
                pass


# =========================================================
# /USER
# =========================================================

@bot.on_message(
    filters.private & filters.command(["user", "users"])
)
async def user_handler(client, message):

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    register_user(message.from_user)

    with users_lock:
        all_users = list(users.values())

    if not all_users:

        await message.reply_text(
            "👥 No users registered yet."
        )

        return

    all_users.sort(
        key=lambda x: x.get("last_seen", 0),
        reverse=True
    )

    header = (
        "👥 **Social Media Bot Users**\n\n"
        f"📊 Total Users: `{len(all_users)}`\n\n"
    )

    chunks = []
    current = header

    for index, u in enumerate(all_users, 1):

        name = (
            u.get("full_name")
            or u.get("first_name")
            or "Unknown"
        )

        username = u.get("username")

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        uid = u.get("user_id")

        bot_status = (
            "🤖 Bot"
            if u.get("is_bot")
            else "👤 User"
        )

        block = (
            f"**{index}. {name}**\n"
            f"├ Username: `{username_text}`\n"
            f"├ ID: `{uid}`\n"
            f"└ Type: {bot_status}\n\n"
        )

        if len(current) + len(block) > 3800:

            chunks.append(current)
            current = block

        else:

            current += block

    if current.strip():
        chunks.append(current)

    for chunk in chunks:

        await message.reply_text(
            chunk
        )


# =========================================================
# /BROADCAST
# =========================================================

@bot.on_message(
    filters.private & filters.command("broadcast")
)
async def broadcast_handler(client, message):

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "📣 **Broadcast Usage**\n\n"
            "`/broadcast Hello everyone!`"
        )

        return

    broadcast_text = message.text.split(
        " ",
        1
    )[1].strip()

    with users_lock:
        user_ids = list(users.keys())

    status = await message.reply_text(
        "📣 Starting broadcast...\n\n"
        f"👥 Users: `{len(user_ids)}`"
    )

    sent = 0
    failed = 0

    for uid in user_ids:

        try:

            await client.send_message(
                int(uid),
                broadcast_text
            )

            sent += 1

            await asyncio_sleep_safe(0.05)

        except Exception as e:

            failed += 1

            print(
                f"Broadcast failed {uid}:",
                repr(e)
            )

    await status.edit_text(
        "✅ **Broadcast completed**\n\n"
        f"📨 Sent: `{sent}`\n"
        f"❌ Failed: `{failed}`\n"
        f"👥 Total: `{len(user_ids)}`"
    )


# =========================================================
# SAFE ASYNC SLEEP
# =========================================================

import asyncio


async def asyncio_sleep_safe(seconds):
    await asyncio.sleep(seconds)


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.on_message(filters.private & filters.command("ping"))
async def ping_handler(client, message):

    if message.from_user.id != ADMIN_ID:
        return

    start = time.time()

    msg = await message.reply_text(
        "🏓 Checking..."
    )

    ms = int(
        (time.time() - start) * 1000
    )

    await msg.edit_text(
        f"🏓 **Pong!**\n\n"
        f"⚡ Response: `{ms} ms`\n"
        f"🟢 Bot: Online"
    )


# =========================================================
# START BOT
# =========================================================

print("======================================")
print("   SOCIAL MEDIA DOWNLOADER")
print("======================================")
print("Bot starting...")
print("Health server:", PORT)
print("Video API configured:", bool(VIDEO_API_URL))
print("Music API configured:", bool(MUSIC_API_URL))
print("Support configured:", bool(SUPPORT_URL))
print("Users:", len(users))
print("======================================")


bot.run()
