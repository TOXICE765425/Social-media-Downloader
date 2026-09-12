import os
import re
import json
import asyncio
import tempfile
import threading
import subprocess
from pathlib import Path
from datetime import datetime

import requests
from flask import Flask

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait


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
# VALIDATION
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
        "Missing Environment Variables: "
        + ", ".join(missing)
    )


# ============================================================
# SETTINGS
# ============================================================

API_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300

# Normal Telegram Bot API upload safety limit
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
# DATABASE
# ============================================================

users = {}

music_cache = {}


def load_users():
    global users

    try:
        if USER_DB.exists():

            with open(
                USER_DB,
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

            if isinstance(data, dict):
                users = data

    except Exception as e:

        print(
            f"⚠️ User database load error: {e}"
        )

        users = {}


def save_users():

    try:

        tmp_file = USER_DB.with_suffix(".tmp")

        with open(
            tmp_file,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                users,
                f,
                indent=2,
                ensure_ascii=False,
            )

        tmp_file.replace(USER_DB)

    except Exception as e:

        print(
            f"⚠️ User database save error: {e}"
        )


def register_user(user):

    if not user:
        return

    user_id = str(user.id)

    old = users.get(
        user_id,
        {},
    )

    full_name = " ".join(
        x
        for x in [
            user.first_name or "",
            user.last_name or "",
        ]
        if x
    ).strip()

    users[user_id] = {

        "user_id": user.id,

        "first_name":
            user.first_name or "",

        "last_name":
            user.last_name or "",

        "full_name":
            full_name or "Unknown",

        "username":
            user.username or "",

        "is_bot":
            bool(user.is_bot),

        "first_seen":
            old.get(
                "first_seen",
                datetime.utcnow().isoformat(),
            ),

        "last_seen":
            datetime.utcnow().isoformat(),
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

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    flask_app.run(
        host="0.0.0.0",
        port=port,
    )


# ============================================================
# PYROGRAM
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
# GENERAL HELPERS
# ============================================================

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

    return url.rstrip(
        ".,!?)]}\"'"
    )


def detect_platform(url):

    url_lower = url.lower()

    for platform, domains in SUPPORTED_PLATFORMS.items():

        for domain in domains:

            if domain in url_lower:
                return platform

    return None


def safe_filename(name):

    name = re.sub(
        r'[\\/*?:"<>|]',
        "_",
        name,
    )

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


# ============================================================
# RECURSIVE URL FINDER
# ============================================================

def recursive_urls(obj):

    found = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(key).lower()

            if isinstance(value, str):

                if value.startswith(
                    (
                        "http://",
                        "https://",
                    )
                ):

                    value_lower = value.lower()

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
                            "hdurl",
                            "sdurl",
                            "videourl",
                        )
                    ):

                        found.append(value)

            elif isinstance(
                value,
                (dict, list),
            ):

                found.extend(
                    recursive_urls(value)
                )

    elif isinstance(obj, list):

        for item in obj:

            found.extend(
                recursive_urls(item)
            )

    return found


# ============================================================
# YOUTUBE VIDEO PARSER
# ============================================================

def get_youtube_videos(data):

    videos = []

    try:

        result = data.get(
            "result",
            {},
        )

        video = result.get(
            "video",
            {},
        )

        video_list = video.get(
            "videos",
            [],
        )

        if isinstance(
            video_list,
            list,
        ):

            for item in video_list:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                url = item.get("url")

                if not isinstance(
                    url,
                    str,
                ):
                    continue

                if not url.startswith(
                    (
                        "http://",
                        "https://",
                    )
                ):
                    continue

                quality = str(
                    item.get(
                        "quality",
                        "",
                    )
                )

                quality_label = str(
                    item.get(
                        "qualityLabel",
                        "",
                    )
                )

                has_audio = bool(
                    item.get(
                        "hasAudio",
                        item.get(
                            "audioAvailable",
                            False,
                        ),
                    )
                )

                needs_merge = bool(
                    item.get(
                        "needsMerge",
                        False,
                    )
                )

                videos.append(
                    {
                        "url": url,
                        "quality": quality,
                        "qualityLabel":
                            quality_label,
                        "hasAudio":
                            has_audio,
                        "needsMerge":
                            needs_merge,
                    }
                )

    except Exception as e:

        print(
            f"YouTube parser error: {e}"
        )

    return videos


def choose_youtube_video(data):

    videos = get_youtube_videos(
        data
    )

    if not videos:
        return None

    # First preference:
    # MP4 + audio + no merge
    progressive = [
        x
        for x in videos
        if x["hasAudio"]
        and not x["needsMerge"]
    ]

    if progressive:
        videos = progressive

    def quality_score(item):

        text = (
            str(item.get("quality", ""))
            + " "
            + str(
                item.get(
                    "qualityLabel",
                    "",
                )
            )
        ).lower()

        score = 0

        if "2160" in text:
            score += 2160

        elif "1440" in text:
            score += 1440

        elif "1080" in text:
            score += 1080

        elif "720" in text:
            score += 720

        elif "480" in text:
            score += 480

        elif "360" in text:
            score += 360

        elif "240" in text:
            score += 240

        if item["hasAudio"]:
            score += 10000

        if not item["needsMerge"]:
            score += 5000

        return score

    videos.sort(
        key=quality_score,
        reverse=True,
    )

    return videos[0]["url"]


# ============================================================
# GENERAL VIDEO URL PARSER
# ============================================================

def find_video_urls(data):

    urls = []

    # --------------------------------------------------------
    # result
    # --------------------------------------------------------

    result = (
        data.get("result")
        if isinstance(data, dict)
        else None
    )

    if isinstance(
        result,
        dict,
    ):

        for key in (
            "hdUrl",
            "sdUrl",
            "videoUrl",
            "downloadUrl",
        ):

            value = result.get(key)

            if (
                isinstance(value, str)
                and value.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ):

                urls.append(value)

        # Instagram / TikTok
        videos = result.get(
            "videos"
        )

        if isinstance(
            videos,
            list,
        ):

            for item in videos:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                value = item.get(
                    "url"
                )

                if (
                    isinstance(value, str)
                    and value.startswith(
                        (
                            "http://",
                            "https://",
                        )
                    )
                ):

                    urls.append(value)

        # Facebook / nested video
        nested_video = result.get(
            "video"
        )

        if isinstance(
            nested_video,
            dict,
        ):

            for key in (
                "hdUrl",
                "sdUrl",
                "videoUrl",
                "downloadUrl",
                "url",
            ):

                value = nested_video.get(
                    key
                )

                if (
                    isinstance(value, str)
                    and value.startswith(
                        (
                            "http://",
                            "https://",
                        )
                    )
                ):

                    urls.append(value)

            nested_videos = nested_video.get(
                "videos"
            )

            if isinstance(
                nested_videos,
                list,
            ):

                for item in nested_videos:

                    if not isinstance(
                        item,
                        dict,
                    ):
                        continue

                    value = item.get(
                        "url"
                    )

                    if (
                        isinstance(value, str)
                        and value.startswith(
                            (
                                "http://",
                                "https://",
                            )
                        )
                    ):

                        urls.append(value)

    # Recursive fallback
    urls.extend(
        recursive_urls(data)
    )

    # Remove duplicates
    unique = []

    for url in urls:

        if url not in unique:
            unique.append(url)

    return unique


def choose_best_video(data, platform):

    # YouTube needs special handling
    if platform == "youtube":

        yt_url = choose_youtube_video(
            data
        )

        if yt_url:
            return yt_url

    urls = find_video_urls(
        data
    )

    if not urls:
        return None

    def score(url):

        u = url.lower()

        points = 0

        if "hd" in u:
            points += 10

        if "1080" in u:
            points += 15

        elif "720" in u:
            points += 10

        if ".mp4" in u:
            points += 5

        return points

    return sorted(
        urls,
        key=score,
        reverse=True,
    )[0]


# ============================================================
# VIDEO API
# ============================================================

def call_video_api(
    platform,
    original_url,
):

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
                "User-Agent":
                    "Mozilla/5.0",
                "Accept":
                    "application/json",
            },
        )

        response.raise_for_status()

        try:

            data = response.json()

        except Exception:

            return (
                None,
                "API returned invalid JSON.",
            )

        return data, None

    except requests.Timeout:

        return (
            None,
            "API request timed out.",
        )

    except requests.RequestException as e:

        return (
            None,
            f"API request failed: {e}",
        )

    except Exception as e:

        return (
            None,
            f"Unexpected API error: {e}",
        )


# ============================================================
# DOWNLOAD
# ============================================================

def download_file(
    url,
    output_path,
):

    try:

        with requests.get(

            url,

            stream=True,

            timeout=DOWNLOAD_TIMEOUT,

            headers={
                "User-Agent":
                    "Mozilla/5.0",
            },

        ) as response:

            response.raise_for_status()

            total = 0

            with open(
                output_path,
                "wb",
            ) as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):

                    if not chunk:
                        continue

                    f.write(chunk)

                    total += len(chunk)

                    # 2GB safety
                    if total > (
                        2 * 1024 * 1024 * 1024
                    ):

                        raise RuntimeError(
                            "File is larger than 2 GB."
                        )

        return (
            True,
            total,
            None,
        )

    except requests.Timeout:

        return (
            False,
            0,
            "Download timed out.",
        )

    except requests.RequestException as e:

        return (
            False,
            0,
            f"Download failed: {e}",
        )

    except Exception as e:

        return (
            False,
            0,
            str(e),
        )


# ============================================================
# FFMPEG REMUX
# ============================================================

def remux_video(
    input_file,
    output_file,
):

    try:

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_file),

            "-c",
            "copy",

            "-movflags",
            "+faststart",

            str(output_file),
        ]

        result = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            timeout=180,
        )

        if result.returncode == 0:

            if output_file.exists():

                if output_file.stat().st_size > 0:

                    return True

    except Exception as e:

        print(
            f"FFmpeg remux error: {e}"
        )

    return False


# ============================================================
# START PROFILE PHOTO
# ============================================================

async def send_welcome(
    client,
    message,
):

    user = message.from_user

    if not user:
        return

    register_user(user)

    first_name = (
        user.first_name
        or "User"
    )

    text = (
        f"👋 **Welcome, {first_name}!**\n\n"

        "🚀 **Social Media Downloader**\n\n"

        "📥 Send me any supported video link "
        "and I'll download it for you.\n\n"

        "🎬 **Supported Platforms**\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Facebook\n"
        "• TikTok\n\n"

        "🎵 You can also search music."
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

    photo_path = (
        TEMP_DIR
        / f"profile_{user.id}.jpg"
    )

    try:

        full_user = await client.get_users(
            user.id
        )

        if (
            full_user
            and full_user.photo
            and full_user.photo.big_file_id
        ):

            downloaded = (
                await client.download_media(
                    full_user.photo.big_file_id,
                    file_name=str(
                        photo_path
                    ),
                )
            )

            if downloaded:

                await message.reply_photo(
                    photo=str(downloaded),
                    caption=text,
                    reply_markup=keyboard,
                )

                try:
                    Path(downloaded).unlink(
                        missing_ok=True
                    )
                except Exception:
                    pass

                return

    except Exception as e:

        print(
            f"Profile photo error: {e}"
        )

    # No profile photo / download failed
    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# START
# ============================================================

@app.on_message(
    filters.private
    & filters.command("start")
)
async def start_handler(
    client,
    message,
):

    await send_welcome(
        client,
        message,
    )


# ============================================================
# HELP
# ============================================================

@app.on_message(
    filters.private
    & filters.command("help")
)
async def help_handler(
    client,
    message,
):

    register_user(
        message.from_user
    )

    await message.reply_text(
        "📖 **How to use**\n\n"

        "🎬 **Video:**\n"
        "Simply send a supported video link.\n\n"

        "Supported:\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Facebook\n"
        "• TikTok\n\n"

        "🎵 **Music:**\n"
        "`/music song name`\n\n"

        "Example:\n"
        "`/music Arijit Singh`"
    )


# ============================================================
# ID
# ============================================================

@app.on_message(
    filters.private
    & filters.command("id")
)
async def id_handler(
    client,
    message,
):

    register_user(
        message.from_user
    )

    await message.reply_text(
        "🆔 **Your Telegram User ID**\n\n"
        f"`{message.from_user.id}`"
    )


# ============================================================
# MUSIC SEARCH API
# ============================================================

def call_music_api(
    query,
):

    try:

        response = requests.get(

            MUSIC_API_URL,

            params={
                "song": query,
            },

            timeout=API_TIMEOUT,

            headers={
                "User-Agent":
                    "Mozilla/5.0",
                "Accept":
                    "application/json",
            },
        )

        response.raise_for_status()

        return response.json(), None

    except requests.Timeout:

        return (
            None,
            "Music API timed out.",
        )

    except requests.RequestException as e:

        return (
            None,
            f"Music API request failed: {e}",
        )

    except Exception as e:

        return (
            None,
            str(e),
        )


def parse_music_results(data):

    results = []

    if not isinstance(
        data,
        dict,
    ):
        return results

    api_results = data.get(
        "results",
        [],
    )

    if not isinstance(
        api_results,
        list,
    ):
        return results

    for item in api_results:

        if not isinstance(
            item,
            dict,
        ):
            continue

        title = (
            item.get(
                "title"
            )
            or "Unknown Song"
        )

        artists = (
            item.get(
                "artists"
            )
            or ""
        )

        album = (
            item.get(
                "album"
            )
            or ""
        )

        duration = (
            item.get(
                "duration"
            )
            or ""
        )

        download_url = (
            item.get(
                "download_url"
            )
        )

        if not isinstance(
            download_url,
            str,
        ):
            continue

        if not download_url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        results.append(
            {
                "title": str(title),
                "artists": str(artists),
                "album": str(album),
                "duration": str(duration),
                "download_url":
                    download_url,
            }
        )

    return results[:MAX_MUSIC_RESULTS]


# ============================================================
# MUSIC COMMAND
# ============================================================

@app.on_message(
    filters.private
    & filters.command("music")
)
async def music_handler(
    client,
    message,
):

    register_user(
        message.from_user
    )

    if len(message.command) < 2:

        await message.reply_text(
            "🎵 **Music Search**\n\n"
            "Use:\n"
            "`/music song name`\n\n"
            "Example:\n"
            "`/music Arijit Singh`"
        )

        return

    query = " ".join(
        message.command[1:]
    ).strip()

    status = await message.reply_text(
        "🔎 **Searching music...**"
    )

    data, error = await asyncio.to_thread(
        call_music_api,
        query,
    )

    if error:

        await status.edit_text(
            f"❌ **Music API Error**\n\n"
            f"`{error}`"
        )

        return

    results = parse_music_results(
        data
    )

    if not results:

        await status.edit_text(
            "❌ **No music result found.**"
        )

        return

    user_id = str(
        message.from_user.id
    )

    music_cache[user_id] = results

    buttons = []

    for index, item in enumerate(
        results
    ):

        title = item["title"]

        if len(title) > 35:
            title = title[:32] + "..."

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎵 {index + 1}. {title}",
                    callback_data=(
                        f"music:{index}"
                    ),
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "📢 Support",
                url=SUPPORT_URL,
            )
        ]
    )

    await status.edit_text(

        "🎵 **Music Results**\n\n"

        f"🔎 Search: `{query}`\n\n"

        "👇 Select a song:",

        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# ============================================================
# MUSIC CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex(r"^music:\d+$")
)
async def music_callback(
    client,
    callback_query,
):

    user_id = str(
        callback_query.from_user.id
    )

    results = music_cache.get(
        user_id
    )

    if not results:

        await callback_query.answer(
            "Search expired. Search again.",
            show_alert=True,
        )

        return

    try:

        index = int(
            callback_query.data.split(
                ":"
            )[1]
        )

    except Exception:

        await callback_query.answer(
            "Invalid selection.",
            show_alert=True,
        )

        return

    if index >= len(results):

        await callback_query.answer(
            "Result not found.",
            show_alert=True,
        )

        return

    item = results[index]

    await callback_query.answer(
        "⏳ Downloading..."
    )

    status = await callback_query.message.reply_text(
        "🎵 **Preparing song...**\n\n"
        f"🎧 {item['title']}\n"
        "📥 Downloading..."
    )

    filename = safe_filename(
        f"music_{user_id}_{index}.mp4"
    )

    output = TEMP_DIR / filename

    ok, size, error = await asyncio.to_thread(
        download_file,
        item["download_url"],
        output,
    )

    if not ok:

        await status.edit_text(
            "❌ **Music Download Failed**\n\n"
            f"`{error}`"
        )

        return

    try:

        if size > MAX_TELEGRAM_FILE:

            await status.edit_text(
                "❌ **File Too Large**\n\n"
                f"Size: `{human_size(size)}`"
            )

            return

        await status.edit_text(
            "🎵 **Uploading song...**\n\n"
            f"🎧 {item['title']}"
        )

        caption = (
            f"🎵 **{item['title']}**\n\n"

            f"👤 {item['artists']}\n"

            f"💿 {item['album']}\n"

            f"⏱ {item['duration']}\n\n"

            "⚡ Powered by Misstu"
        )

        await callback_query.message.reply_audio(
            audio=str(output),
            caption=caption,
            title=item["title"],
            performer=item["artists"],
        )

        await status.delete()

    except Exception as e:

        await status.edit_text(
            "❌ **Upload Failed**\n\n"
            f"`{e}`"
        )

    finally:

        try:
            output.unlink(
                missing_ok=True
            )
        except Exception:
            pass


# ============================================================
# MUSIC HELP
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
        "`/music Sanam Teri Kasam`"
    )


# ============================================================
# VIDEO PROCESSING
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

    output = None
    repaired = None

    try:

        await asyncio.sleep(0.4)

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
                "❌ **API Error**\n\n"
                f"{error}"
            )

            return

        await status.edit_text(
            "⚡ **Checking response...**\n\n"
            "📡 Response received.\n"
            "🎬 Finding best video..."
        )

        video_url = choose_best_video(
            data,
            platform,
        )

        if not video_url:

            await status.edit_text(
                "❌ **Video URL not found.**\n\n"
                "API did not return a supported "
                "video URL."
            )

            return

        await status.edit_text(
            "⚡ **Fetching information...**\n\n"
            "📥 Downloading video..."
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
                "❌ **Download Failed**\n\n"
                f"{error}"
            )

            return

        if size <= 0:

            await status.edit_text(
                "❌ Downloaded file is empty."
            )

            return

        # ----------------------------------------------------
        # Check size
        # ----------------------------------------------------

        if size > MAX_TELEGRAM_FILE:

            await status.edit_text(
                "❌ **File Too Large**\n\n"
                f"Size: `{human_size(size)}`\n\n"
                "Telegram upload limit reached."
            )

            return

        # ----------------------------------------------------
        # Remux MP4
        # ----------------------------------------------------

        await status.edit_text(
            "⚡ **Finalizing result...**\n\n"
            "🔧 Preparing playable MP4..."
        )

        repaired = (
            TEMP_DIR
            / f"fixed_{message.from_user.id}_{message.id}.mp4"
        )

        remux_success = await asyncio.to_thread(
            remux_video,
            output,
            repaired,
        )

        upload_file = output

        if remux_success:

            repaired_size = repaired.stat().st_size

            if (
                repaired_size > 0
                and repaired_size <= MAX_TELEGRAM_FILE
            ):

                upload_file = repaired
                size = repaired_size

        await status.edit_text(
            "⚡ **Finalizing result...**\n\n"
            f"📦 Size: `{human_size(size)}`\n"
            "📤 Uploading to Telegram..."
        )

        caption = (
            f"🎬 **{platform.title()} Video**\n\n"
            f"📦 Size: `{human_size(size)}`\n"
            "⚡ Powered by Misstu"
        )

        try:

            await message.reply_video(
                video=str(upload_file),
                caption=caption,
                supports_streaming=True,
            )

            await status.delete()

        except Exception as upload_error:

            await status.edit_text(
                "❌ **Telegram Upload Failed**\n\n"
                f"`{upload_error}`"
            )

    except FloodWait as e:

        print(
            f"FloodWait: sleeping {e.value}s"
        )

        await asyncio.sleep(
            e.value
        )

    except Exception as e:

        print(
            "Video processing error:",
            repr(e),
        )

        try:

            await status.edit_text(
                "❌ **Something went wrong**\n\n"
                f"`{e}`"
            )

        except Exception:
            pass

    finally:

        for file in (
            output,
            repaired,
        ):

            if file:

                try:
                    file.unlink(
                        missing_ok=True
                    )
                except Exception:
                    pass


# ============================================================
# PRIVATE VIDEO HANDLER
# ============================================================

@app.on_message(
    filters.private
    & filters.text
    & ~filters.command(
        [
            "start",
            "help",
            "music",
            "broadcast",
            "broadcast_user",
            "user",
            "users",
            "id",
        ]
    )
)
async def private_video_handler(
    client,
    message,
):

    if not message.from_user:
        return

    register_user(
        message.from_user
    )

    url = extract_url(
        message.text
    )

    if not url:
        return

    platform = detect_platform(
        url
    )

    if not platform:
        return

    await process_video(
        client,
        message,
        url,
        platform,
    )


# ============================================================
# GROUP VIDEO HANDLER
# ============================================================

@app.on_message(
    filters.group
    & filters.text
)
async def group_handler(
    client,
    message,
):

    if not message.from_user:
        return

    register_user(
        message.from_user
    )

    if not message.text:
        return

    if message.text.startswith("/"):
        return

    url = extract_url(
        message.text
    )

    if not url:
        return

    platform = detect_platform(
        url
    )

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

    register_user(
        message.from_user
    )

    if not is_admin(
        message.from_user.id
    ):

        await message.reply_text(
            "❌ You are not authorized."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/broadcast Your message`"
        )

        return

    text = message.text.split(
        None,
        1,
    )[1].strip()

    if not text:

        await message.reply_text(
            "❌ Message is empty."
        )

        return

    status = await message.reply_text(
        "📢 **Broadcast started...**"
    )

    success = 0
    failed = 0

    for user_id in list(
        users.keys()
    ):

        try:

            await client.send_message(
                int(user_id),
                text,
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await client.send_message(
                    int(user_id),
                    text,
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
# BROADCAST USER
# ============================================================

@app.on_message(
    filters.private
    & filters.command("broadcast_user")
)
async def broadcast_user_handler(
    client,
    message,
):

    register_user(
        message.from_user
    )

    if not is_admin(
        message.from_user.id
    ):

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
            "❌ Message is empty."
        )

        return

    try:

        await client.send_message(
            target_id,
            text,
        )

        await message.reply_text(
            "✅ Message sent successfully."
        )

    except Exception as e:

        await message.reply_text(
            f"❌ Failed:\n`{e}`"
        )


# ============================================================
# USERS LIST
# ============================================================

@app.on_message(
    filters.private
    & filters.command(
        [
            "user",
            "users",
        ]
    )
)
async def users_handler(
    client,
    message,
):

    register_user(
        message.from_user
    )

    if not is_admin(
        message.from_user.id
    ):

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
            data.get(
                "full_name"
            )
            or "Unknown"
        )

        username = data.get(
            "username"
        )

        if username:
            username_text = (
                f"@{username}"
            )
        else:
            username_text = (
                "No username"
            )

        user_id = data.get(
            "user_id",
            "Unknown",
        )

        user_type = (
            "BOT"
            if data.get(
                "is_bot"
            )
            else "USER"
        )

        lines.append(
            f"**{index}. {full_name}**\n"
            f"├ ID: `{user_id}`\n"
            f"├ Username: {username_text}\n"
            f"└ Type: `{user_type}`\n"
        )

    chunks = []

    current = ""

    for line in lines:

        if len(
            current
        ) + len(line) > 3800:

            chunks.append(
                current
            )

            current = ""

        current += line + "\n"

    if current:
        chunks.append(
            current
        )

    for chunk in chunks:

        await message.reply_text(
            chunk
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    load_users()

    print(
        "=" * 60
    )

    print(
        "🚀 MISSTU SOCIAL MEDIA DOWNLOADER"
    )

    print(
        "=" * 60
    )

    print(
        f"👥 Users: {len(users)}"
    )

    print(
        "🎬 Video API: Configured"
    )

    print(
        "🎵 Music API: Configured"
    )

    print(
        "📢 Support: Configured"
    )

    print(
        "=" * 60
    )

    # Start Flask health server
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    print(
        "🌐 Health server started."
    )

    print(
        "🤖 Starting Telegram bot..."
    )

    app.run()
