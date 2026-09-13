import os
import re
import json
import time
import asyncio
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, jsonify
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# =========================================================
# ENV — ONLY THESE 7
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

VIDEO_API_URL = os.getenv("VIDEO_API_URL", "").strip().rstrip("/")
MUSIC_API_URL = os.getenv("MUSIC_API_URL", "").strip().rstrip("/")
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()


# =========================================================
# SETTINGS
# =========================================================

PORT = int(os.getenv("PORT", "10000"))

API_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300

MAX_DOWNLOAD_SIZE = 49 * 1024 * 1024

TEMP_DIR = Path(tempfile.gettempdir()) / "social_media_downloader"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

USER_DB = TEMP_DIR / "users.json"


# =========================================================
# CHECK ENV
# =========================================================

missing = []

for name, value in [
    ("BOT_TOKEN", BOT_TOKEN),
    ("API_ID", API_ID),
    ("API_HASH", API_HASH),
    ("ADMIN_ID", ADMIN_ID),
    ("VIDEO_API_URL", VIDEO_API_URL),
    ("MUSIC_API_URL", MUSIC_API_URL),
    ("SUPPORT_URL", SUPPORT_URL),
]:
    if not value:
        missing.append(name)

if missing:
    raise RuntimeError(
        "Missing environment variables: "
        + ", ".join(missing)
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

    except Exception as e:
        print("User DB load error:", e)
        users = {}


def save_users():
    try:
        USER_DB.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        tmp = USER_DB.with_suffix(".tmp")

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                users,
                f,
                ensure_ascii=False,
                indent=2
            )

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
                "full_name": (
                    f"{user.first_name or ''} "
                    f"{user.last_name or ''}"
                ).strip(),
                "username": user.username or "",
                "is_bot": bool(user.is_bot),
                "first_seen": old.get(
                    "first_seen",
                    int(time.time())
                ),
                "last_seen": int(time.time())
            }

            save_users()

    except Exception as e:
        print("Register error:", e)


load_users()


# =========================================================
# FLASK HEALTH SERVER
# =========================================================

health_app = Flask(__name__)


@health_app.route("/")
def home():

    return jsonify({
        "status": "online",
        "service": "Social Media Downloader"
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

def main_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 Download Video",
                callback_data="download"
            )
        ],
        [
            InlineKeyboardButton(
                "🎵 Music Search",
                callback_data="music"
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
                callback_data="home"
            )
        ]
    ])


# =========================================================
# USER PROFILE PHOTO
# =========================================================

async def download_user_photo(user):

    try:

        chat = await bot.get_chat(user.id)

        if not chat.photo:
            return None

        photo_path = TEMP_DIR / (
            f"user_dp_{user.id}_{int(time.time())}.jpg"
        )

        downloaded = await bot.download_media(
            chat.photo.big_file_id,
            file_name=str(photo_path)
        )

        return downloaded

    except Exception as e:

        print(
            "User profile photo error:",
            repr(e)
        )

        return None


# =========================================================
# WELCOME
# =========================================================

async def show_welcome(
    chat_id,
    user,
    message_to_edit=None
):

    name = user.first_name or "User"

    text = (
        f"👋 **Welcome, {name}!**\n\n"
        "⚡ **Social Media Downloader**\n\n"
        "📥 Download videos from:\n"
        "• Instagram\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "🎵 Search music with:\n"
        "`/music song name`\n\n"
        "👇 Choose an option below."
    )

    # If coming back from button, edit message
    if message_to_edit:

        try:

            await message_to_edit.edit_text(
                text,
                reply_markup=main_keyboard()
            )

            return

        except Exception as e:
            print("Welcome edit error:", repr(e))

    # Otherwise send user's own profile DP
    photo = await download_user_photo(user)

    try:

        if photo and os.path.exists(photo):

            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                reply_markup=main_keyboard()
            )

        else:

            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=main_keyboard()
            )

    except Exception as e:

        print(
            "Welcome photo send error:",
            repr(e)
        )

        try:

            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=main_keyboard()
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

@bot.on_message(
    filters.private & filters.command("start")
)
async def start_handler(client, message):

    register_user(message.from_user)

    await show_welcome(
        message.chat.id,
        message.from_user
    )


# =========================================================
# HELP
# =========================================================

@bot.on_message(
    filters.private & filters.command("help")
)
async def help_handler(client, message):

    register_user(message.from_user)

    await message.reply_text(
        "📥 **Social Media Downloader**\n\n"
        "Send an Instagram, YouTube, TikTok "
        "or Facebook video link.\n\n"
        "🎵 Music:\n"
        "`/music song name`",
        reply_markup=main_keyboard()
    )


# =========================================================
# CALLBACK
# =========================================================

@bot.on_callback_query()
async def callback_handler(client, query):

    register_user(query.from_user)

    try:

        if query.data == "home":

            await query.answer()

            await show_welcome(
                query.message.chat.id,
                query.from_user,
                query.message
            )

        elif query.data == "download":

            await query.answer()

            await query.message.edit_text(
                "📥 **Video Downloader**\n\n"
                "Simply send the video link.\n\n"
                "Supported:\n"
                "• Instagram\n"
                "• YouTube\n"
                "• TikTok\n"
                "• Facebook",
                reply_markup=back_keyboard()
            )

        elif query.data == "music":

            await query.answer()

            await query.message.edit_text(
                "🎵 **Music Search**\n\n"
                "Use:\n"
                "`/music song name`\n\n"
                "Example:\n"
                "`/music Arijit Singh`",
                reply_markup=back_keyboard()
            )

    except Exception as e:

        print(
            "Callback error:",
            repr(e)
        )


# =========================================================
# URL DETECTION
# =========================================================

URL_PATTERN = re.compile(
    r"https?://[^\s<>]+",
    re.IGNORECASE
)


def detect_platform(url):

    u = url.lower()

    if "instagram.com" in u:
        return "instagram"

    if "youtu.be" in u or "youtube.com" in u:
        return "youtube"

    if "tiktok.com" in u:
        return "tiktok"

    if (
        "facebook.com" in u
        or "fb.watch" in u
    ):
        return "facebook"

    return None


# =========================================================
# VIDEO API
# =========================================================

def call_video_api(platform, url):

    api_url = (
        f"{VIDEO_API_URL}/api/"
        f"{platform}?url={quote(url, safe='')}"
    )

    print(
        f"[VIDEO API] {platform}:",
        api_url
    )

    response = requests.get(
        api_url,
        timeout=API_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    data = response.json()

    print(
        "[VIDEO API RESPONSE]",
        json.dumps(
            data,
            ensure_ascii=False
        )[:3000]
    )

    return data


# =========================================================
# URL CHECK
# =========================================================

def valid_http_url(value):

    if not isinstance(value, str):
        return False

    return value.startswith(
        ("http://", "https://")
    )


# =========================================================
# GET VIDEO
# =========================================================

def get_video_url(data, platform):

    # -----------------------------------------------------
    # FACEBOOK
    # -----------------------------------------------------

    if platform == "facebook":

        result = data.get("result", {})

        if isinstance(result, dict):

            hd = result.get("hdUrl")

            if valid_http_url(hd):
                return hd, "HD"

            sd = result.get("sdUrl")

            if valid_http_url(sd):
                return sd, "SD"


    # -----------------------------------------------------
    # INSTAGRAM
    # -----------------------------------------------------

    if platform == "instagram":

        result = data.get(
            "result",
            {}
        )

        if isinstance(result, dict):

            videos = result.get(
                "videos",
                []
            )

            if isinstance(videos, list):

                # First prefer HD
                for item in videos:

                    if not isinstance(item, dict):
                        continue

                    url = item.get("url")

                    quality = str(
                        item.get("quality", "")
                    ).lower()

                    if (
                        valid_http_url(url)
                        and quality == "hd"
                    ):

                        return url, "HD"

                # Then any valid video URL
                for item in videos:

                    if not isinstance(item, dict):
                        continue

                    url = item.get("url")

                    if valid_http_url(url):

                        return (
                            url,
                            item.get(
                                "quality",
                                "Video"
                            )
                        )


    # -----------------------------------------------------
    # YOUTUBE
    # -----------------------------------------------------

    if platform == "youtube":

        result = data.get(
            "result",
            {}
        )

        if isinstance(result, dict):

            video_data = result.get(
                "video",
                {}
            )

            if isinstance(video_data, dict):

                videos = video_data.get(
                    "videos",
                    []
                )

                if isinstance(videos, list):

                    # Prefer streams with audio
                    # and no merge requirement
                    for item in videos:

                        if not isinstance(item, dict):
                            continue

                        url = item.get("url")

                        if not valid_http_url(url):
                            continue

                        has_audio = (
                            item.get("hasAudio") is True
                            or
                            item.get("audioAvailable") is True
                        )

                        needs_merge = (
                            item.get("needsMerge") is True
                        )

                        if has_audio and not needs_merge:

                            quality = (
                                item.get("qualityLabel")
                                or item.get("quality")
                                or "YouTube"
                            )

                            return url, str(quality)

                    # Fallback to any video URL
                    for item in videos:

                        if not isinstance(item, dict):
                            continue

                        url = item.get("url")

                        if valid_http_url(url):

                            quality = (
                                item.get("qualityLabel")
                                or item.get("quality")
                                or "YouTube"
                            )

                            return url, str(quality)


    # -----------------------------------------------------
    # GENERIC RECURSIVE SEARCH
    # -----------------------------------------------------

    def walk(obj):

        if isinstance(obj, dict):

            # Ignore obvious non-video fields
            ignored = {
                "thumbnail",
                "cover",
                "image",
                "avatar",
                "music"
            }

            for key, value in obj.items():

                key_lower = str(key).lower()

                if key_lower in ignored:
                    continue

                if isinstance(value, str):

                    if (
                        valid_http_url(value)
                        and (
                            "video" in key_lower
                            or
                            key_lower in {
                                "url",
                                "videourl",
                                "video_url",
                                "downloadurl",
                                "download_url",
                                "hdurl",
                                "sdurl"
                            }
                        )
                    ):

                        return value

                result = walk(value)

                if result:
                    return result

        elif isinstance(obj, list):

            for item in obj:

                result = walk(item)

                if result:
                    return result

        return None


    generic = walk(data)

    if generic:
        return generic, "Auto"

    return None, None


# =========================================================
# DOWNLOAD FILE
# =========================================================

def download_file(
    url,
    output_path,
    max_size=MAX_DOWNLOAD_SIZE
):

    print(
        "[DOWNLOAD]",
        url[:300]
    )

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

        with open(
            output_path,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=256 * 1024
            ):

                if not chunk:
                    continue

                total += len(chunk)

                if (
                    max_size
                    and total > max_size
                ):
                    raise ValueError(
                        "File is larger than "
                        "Telegram upload limit."
                    )

                f.write(chunk)

    return output_path


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

    # Remove Telegram punctuation
    url = url.rstrip(
        ".,!?)]}>"
    )

    platform = detect_platform(url)

    if not platform:
        return

    status = await message.reply_text(
        "⏳ **Processing...**\n\n"
        "🔎 Searching video..."
    )

    file_path = None

    try:

        data = call_video_api(
            platform,
            url
        )

        video_url, quality = get_video_url(
            data,
            platform
        )

        if not video_url:

            raise ValueError(
                "No downloadable video found."
            )

        await status.edit_text(
            "⬇️ **Downloading video...**\n\n"
            f"🎬 Platform: `{platform.title()}`\n"
            f"🎞 Quality: `{quality}`"
        )

        file_path = TEMP_DIR / (
            f"video_"
            f"{message.from_user.id}_"
            f"{int(time.time())}.mp4"
        )

        download_file(
            video_url,
            file_path
        )

        size_mb = (
            file_path.stat().st_size
            / (1024 * 1024)
        )

        await status.edit_text(
            "📤 **Uploading to Telegram...**"
        )

        caption = (
            f"🎬 **{platform.title()} Video**\n\n"
            f"🎞 Quality: `{quality}`\n"
            f"📦 Size: `{size_mb:.1f} MB`\n\n"
            "⚡ Powered by **Misstu**"
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
            f"[VIDEO ERROR] {platform}:",
            repr(e)
        )

        try:

            await status.edit_text(
                "❌ **Download failed**\n\n"
                f"`{str(e)[:1500]}`"
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
# MUSIC API
# =========================================================

def search_music(song):

    api_url = (
        f"{MUSIC_API_URL}/search"
        f"?song={quote(song, safe='')}"
    )

    print(
        "[MUSIC API]",
        api_url
    )

    response = requests.get(
        api_url,
        timeout=API_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    data = response.json()

    print(
        "[MUSIC RESPONSE]",
        json.dumps(
            data,
            ensure_ascii=False
        )[:3000]
    )

    return data


# =========================================================
# FFMPEG MP4/AAC -> MP3
# =========================================================

def convert_to_mp3(input_file, output_file):

    import subprocess

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_file),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-ar",
        "44100",
        str(output_file)
    ]

    print(
        "[FFMPEG]",
        " ".join(command)
    )

    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if process.returncode != 0:

        print(
            "[FFMPEG ERROR]",
            process.stderr[-3000:]
        )

        raise RuntimeError(
            "MP3 conversion failed."
        )

    if not output_file.exists():

        raise RuntimeError(
            "MP3 file was not created."
        )

    return output_file


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
        f"🔎 Searching music...\n\n"
        f"🎵 **{song}**"
    )

    source_file = None
    mp3_file = None

    try:

        data = search_music(song)

        if not data.get("success"):

            raise ValueError(
                "Music API returned an error."
            )

        results = data.get(
            "results",
            []
        )

        if (
            not isinstance(results, list)
            or not results
        ):

            await status.edit_text(
                "❌ **No music result found.**"
            )

            return

        selected = None

        for item in results:

            if not isinstance(item, dict):
                continue

            download_url = item.get(
                "download_url"
            )

            if valid_http_url(download_url):

                selected = item
                break

        if not selected:

            raise ValueError(
                "No downloadable music found."
            )

        title = (
            selected.get("title")
            or song
        )

        artists = (
            selected.get("artists")
            or "Unknown Artist"
        )

        album = (
            selected.get("album")
            or ""
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

        source_file = TEMP_DIR / (
            f"music_source_"
            f"{message.from_user.id}_"
            f"{int(time.time())}.mp4"
        )

        download_file(
            download_url,
            source_file
        )

        await status.edit_text(
            "🎧 **Converting to MP3...**\n\n"
            f"🎵 {title}"
        )

        mp3_file = TEMP_DIR / (
            f"{re.sub(r'[^a-zA-Z0-9_-]+', '_', title)[:50]}_"
            f"{int(time.time())}.mp3"
        )

        convert_to_mp3(
            source_file,
            mp3_file
        )

        size_mb = (
            mp3_file.stat().st_size
            / (1024 * 1024)
        )

        await status.edit_text(
            "📤 **Uploading MP3...**"
        )

        caption = (
            f"🎵 **{title}**\n\n"
            f"👤 {artists}\n"
        )

        if album:
            caption += f"💿 {album}\n"

        if duration:
            caption += f"⏱ {duration}\n"

        caption += (
            f"📦 {size_mb:.1f} MB\n\n"
            "⚡ Powered by **Misstu**"
        )

        await client.send_audio(
            chat_id=message.chat.id,
            audio=str(mp3_file),
            caption=caption,
            title=title,
            performer=artists,
            duration=0
        )

        await status.delete()

    except Exception as e:

        print(
            "[MUSIC ERROR]",
            repr(e)
        )

        try:

            await status.edit_text(
                "❌ **Music download failed**\n\n"
                f"`{str(e)[:1500]}`"
            )

        except Exception:
            pass

    finally:

        for file_path in [
            source_file,
            mp3_file
        ]:

            if file_path and file_path.exists():

                try:
                    file_path.unlink()
                except Exception:
                    pass


# =========================================================
# /USER
# =========================================================

@bot.on_message(
    filters.private
    & filters.command(["user", "users"])
)
async def users_handler(client, message):

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    with users_lock:
        all_users = list(users.values())

    if not all_users:

        await message.reply_text(
            "👥 No users registered."
        )

        return

    all_users.sort(
        key=lambda x: x.get(
            "last_seen",
            0
        ),
        reverse=True
    )

    current = (
        "👥 **Social Media Bot Users**\n\n"
        f"📊 Total: `{len(all_users)}`\n\n"
    )

    chunks = []

    for index, user in enumerate(
        all_users,
        1
    ):

        name = (
            user.get("full_name")
            or "Unknown"
        )

        username = user.get(
            "username"
        )

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        uid = user.get(
            "user_id"
        )

        user_type = (
            "🤖 Bot"
            if user.get("is_bot")
            else "👤 User"
        )

        block = (
            f"**{index}. {name}**\n"
            f"├ Username: `{username_text}`\n"
            f"├ ID: `{uid}`\n"
            f"└ Type: {user_type}\n\n"
        )

        if len(current) + len(block) > 3800:

            chunks.append(current)
            current = block

        else:

            current += block

    if current:
        chunks.append(current)

    for chunk in chunks:

        await message.reply_text(
            chunk
        )


# =========================================================
# /BROADCAST
# =========================================================

@bot.on_message(
    filters.private
    & filters.command("broadcast")
)
async def broadcast_handler(client, message):

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "📣 **Usage:**\n"
            "`/broadcast Your message`"
        )

        return

    broadcast_text = message.text.split(
        " ",
        1
    )[1].strip()

    with users_lock:
        user_ids = list(users.keys())

    status = await message.reply_text(
        "📣 **Broadcast started...**\n\n"
        f"👥 Total: `{len(user_ids)}`"
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

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            failed += 1

            print(
                f"Broadcast error {uid}:",
                repr(e)
            )

    await status.edit_text(
        "✅ **Broadcast completed**\n\n"
        f"📨 Sent: `{sent}`\n"
        f"❌ Failed: `{failed}`\n"
        f"👥 Total: `{len(user_ids)}`"
    )


# =========================================================
# /PING
# =========================================================

@bot.on_message(
    filters.private & filters.command("ping")
)
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
# START
# =========================================================

print()
print("==========================================")
print("       SOCIAL MEDIA DOWNLOADER")
print("==========================================")
print("🟢 Bot starting...")
print("🌐 Health port:", PORT)
print("📥 Video API:", "Configured")
print("🎵 Music API:", "Configured")
print("📢 Support:", "Configured")
print("👥 Users:", len(users))
print("🎧 FFmpeg MP3 conversion: ENABLED")
print("==========================================")
print()

bot.run()
