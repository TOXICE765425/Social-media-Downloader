import asyncio, logging, os, re, tempfile, time, uuid
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from flask import Flask
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "0").strip()
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()
VIDEO_API_URL = os.getenv("VIDEO_API_URL", "").strip().rstrip("/")
MUSIC_API_URL = os.getenv("MUSIC_API_URL", "").strip().rstrip("/")
PORT = int(os.getenv("PORT", "10000"))
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "300"))
MAX_MUSIC_RESULTS = int(os.getenv("MAX_MUSIC_RESULTS", "8"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "/tmp/misstu_downloader"))

if not BOT_TOKEN or not API_ID.isdigit() or not API_HASH:
    raise RuntimeError("Set BOT_TOKEN, API_ID and API_HASH in environment variables.")
if not VIDEO_API_URL or not MUSIC_API_URL:
    raise RuntimeError("Set VIDEO_API_URL and MUSIC_API_URL in environment variables.")

TEMP_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("misstu")
music_cache = {}
CACHE_TTL = 900

web = Flask(__name__)

@web.get("/")
def home():
    return "Misstu Telegram Downloader is running."

@web.get("/health")
def health():
    return {"status": "ok"}

def run_web():
    web.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

app = Client(
    "misstu_downloader",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False,
    max_concurrent_transmissions=1,
)

def esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def main_keyboard():
    rows = [
        [InlineKeyboardButton("🎬 Video Downloader", callback_data="video_menu"),
         InlineKeyboardButton("🎵 Music Search", callback_data="music_menu")]
    ]
    if SUPPORT_URL:
        rows.append([InlineKeyboardButton("📢 Support", url=SUPPORT_URL)])
    return InlineKeyboardMarkup(rows)

WELCOME = """<b>✨ Misstu Downloader</b>

<b>🎬 Video Downloader</b>
Send an Instagram, YouTube, TikTok or Facebook link.

<b>🎵 Music Search</b>
Use:
<code>/music Arijit Singh</code>

⚡ <i>Fast • Clean • Easy</i>

Choose an option below or simply send a video link."""

def extract_url(text):
    m = re.search(r"https?://[^\s<>()]+", text or "", re.I)
    return m.group(0).rstrip(".,!?)]}>") if m else None

def platform(url):
    h = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    if "instagram.com" in h: return "instagram"
    if h == "youtu.be" or "youtube.com" in h: return "youtube"
    if "tiktok.com" in h: return "tiktok"
    if "facebook.com" in h or h == "fb.watch": return "facebook"
    return None

def get_json(url):
    r = requests.get(url, timeout=API_TIMEOUT, headers={"User-Agent": "MisstuDownloader/1.0"})
    r.raise_for_status()
    return r.json()

def choose_instagram(result):
    arr = result.get("videos") or []
    arr = [x for x in arr if isinstance(x, dict) and x.get("url") and x.get("videoAvailable", True)]
    if not arr: return None
    def score(x):
        q = str(x.get("quality", "")).lower()
        m = re.search(r"(\d{3,4})", q)
        return (1 if "hd" in q else 0, int(m.group(1)) if m else 0)
    return sorted(arr, key=score, reverse=True)[0]

def choose_youtube(result):
    arr = (result.get("video") or {}).get("videos") or []
    good = [x for x in arr if isinstance(x, dict) and x.get("url")
            and not x.get("needsMerge", False)
            and x.get("videoAvailable", True)]
    with_audio = [x for x in good if x.get("hasAudio", x.get("audioAvailable", True))]
    arr = with_audio or good
    if not arr: return None
    def score(x):
        m = re.search(r"(\d{3,4})", str(x.get("qualityLabel") or x.get("quality") or ""))
        return int(m.group(1)) if m else 0
    return sorted(arr, key=score, reverse=True)[0]

def recursive_url(obj):
    if isinstance(obj, dict):
        for k in ("hdUrl", "sdUrl", "videoUrl", "url"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                if k != "url" or any(x in v.lower() for x in (".mp4", "video", "download", "cdn", "media")):
                    return v
        for v in obj.values():
            x = recursive_url(v)
            if x: return x
    elif isinstance(obj, list):
        for v in obj:
            x = recursive_url(v)
            if x: return x
    return None

def select_video(data, plat):
    result = data.get("result") or {}
    if plat == "instagram":
        x = choose_instagram(result)
        return (x.get("url"), x.get("quality", "video")) if x else (None, None)
    if plat == "youtube":
        x = choose_youtube(result)
        return (x.get("url"), x.get("qualityLabel") or x.get("quality", "video")) if x else (None, None)
    for k in ("hdUrl", "sdUrl", "videoUrl"):
        if result.get(k): return result[k], k
    x = recursive_url(result)
    return (x, "video") if x else (None, None)

def parse_duration(v):
    if not v: return None
    p = str(v).split(":")
    try:
        if len(p) == 2: return int(p[0])*60 + int(p[1])
        if len(p) == 3: return int(p[0])*3600 + int(p[1])*60 + int(p[2])
        if len(p) == 1 and p[0].isdigit(): return int(p[0])
    except: pass
    return None

async def download(url, suffix):
    def work():
        fd, path = tempfile.mkstemp(prefix="misstu_", suffix=suffix, dir=TEMP_DIR)
        os.close(fd)
        try:
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                              headers={"User-Agent": "MisstuDownloader/1.0"}) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk: f.write(chunk)
            return path
        except:
            try: os.remove(path)
            except: pass
            raise
    return await asyncio.to_thread(work)

def rm(path):
    if path:
        try: os.remove(path)
        except: pass

@app.on_message(filters.command("start"))
async def start(_, m):
    await m.reply_text(WELCOME, parse_mode=ParseMode.HTML,
                       reply_markup=main_keyboard(), disable_web_page_preview=True)

@app.on_message(filters.command(["help", "menu"]))
async def menu(_, m):
    await m.reply_text(WELCOME, parse_mode=ParseMode.HTML,
                       reply_markup=main_keyboard(), disable_web_page_preview=True)

@app.on_callback_query(filters.regex("^video_menu$"))
async def video_menu(_, q: CallbackQuery):
    await q.answer()
    await q.message.edit_text(
        "<b>🎬 Video Downloader</b>\n\n"
        "Send an Instagram, YouTube, TikTok or Facebook link.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

@app.on_callback_query(filters.regex("^music_menu$"))
async def music_menu(_, q: CallbackQuery):
    await q.answer()
    await q.message.edit_text(
        "<b>🎵 Music Search</b>\n\nUse:\n<code>/music Arijit Singh</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    )

@app.on_callback_query(filters.regex("^back$"))
async def back(_, q: CallbackQuery):
    await q.answer()
    await q.message.edit_text(WELCOME, parse_mode=ParseMode.HTML,
                              reply_markup=main_keyboard(), disable_web_page_preview=True)

@app.on_message(filters.command("music"))
async def music(_, m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.reply_text("<b>🎵 Use:</b> <code>/music Arijit Singh</code>", parse_mode=ParseMode.HTML)
        return
    query = parts[1].strip()
    status = await m.reply_text("🔎 <b>Searching music...</b>", parse_mode=ParseMode.HTML)
    try:
        data = await asyncio.to_thread(get_json, f"{MUSIC_API_URL}/search?song={quote_plus(query)}")
        if not data.get("success"): raise RuntimeError("Music API returned success=false.")
        items = [x for x in (data.get("results") or [])[:MAX_MUSIC_RESULTS]
                 if isinstance(x, dict) and x.get("download_url")]
        if not items:
            await status.edit_text("😕 <b>No music found.</b>", parse_mode=ParseMode.HTML); return

        music_cache = globals()["music_cache"]
        token = uuid.uuid4().hex[:10]
        music_cache[token] = {"uid": m.from_user.id, "time": time.time(), "items": items}
        rows = []
        for i, x in enumerate(items):
            title = str(x.get("title") or "Unknown")[:35]
            rows.append([InlineKeyboardButton(f"🎵 {i+1}. {title}", callback_data=f"music:{token}:{i}")])
        if SUPPORT_URL: rows.append([InlineKeyboardButton("📢 Support", url=SUPPORT_URL)])
        text = f"<b>🎵 Music Results</b>\n<i>Search:</i> <code>{esc(query)}</code>\n\n"
        for i, x in enumerate(items, 1):
            text += f"<b>{i}. {esc(x.get('title'))}</b>\n👤 {esc(x.get('artists'))}"
            if x.get("duration"): text += f"\n⏱ {esc(x.get('duration'))}"
            text += "\n\n"
        text += "<i>Tap a result to download.</i>"
        await status.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        log.exception("music")
        await status.edit_text(f"❌ <b>Music API error</b>\n<code>{esc(str(e)[:300])}</code>",
                               parse_mode=ParseMode.HTML)

@app.on_callback_query(filters.regex("^music:"))
async def music_pick(client, q: CallbackQuery):
    try: _, token, idx = q.data.split(":"); idx = int(idx)
    except: await q.answer("Invalid result.", show_alert=True); return
    cache = music_cache.get(token)
    if not cache or time.time() - cache["time"] > CACHE_TTL:
        await q.answer("Result expired. Search again.", show_alert=True); return
    if q.from_user.id != cache["uid"]:
        await q.answer("This result belongs to another user.", show_alert=True); return
    item = cache["items"][idx]
    await q.answer("Downloading audio…")
    status = await q.message.reply_text("⏬ <b>Downloading audio...</b>", parse_mode=ParseMode.HTML)
    path = None
    try:
        path = await download(item["download_url"], ".mp3")
        await client.send_audio(q.message.chat.id, path,
            caption=f"🎵 <b>{esc(item.get('title'))}</b>\n👤 {esc(item.get('artists'))}",
            parse_mode=ParseMode.HTML, title=str(item.get("title") or "")[:64],
            performer=str(item.get("artists") or "")[:64], duration=parse_duration(item.get("duration")))
        await status.delete()
    except Exception as e:
        log.exception("music send")
        await status.edit_text(f"❌ <b>Audio upload failed</b>\n<code>{esc(str(e)[:300])}</code>",
                               parse_mode=ParseMode.HTML)
    finally: rm(path)

@app.on_message(filters.text & ~filters.command(["start","help","menu","music"]))
async def video(client, m):
    url = extract_url(m.text)
    if not url: return
    plat = platform(url)
    if not plat:
        await m.reply_text("⚠️ <b>Unsupported link.</b>\nSupported: Instagram, YouTube, TikTok, Facebook.",
                           parse_mode=ParseMode.HTML); return
    status = await m.reply_text(f"🔎 <b>Processing {plat.title()}...</b>\n\n⏳ Fetching video...",
                                parse_mode=ParseMode.HTML)
    path = None
    try:
        api = f"{VIDEO_API_URL}/api/{plat}?url={quote_plus(url)}"
        data = await asyncio.to_thread(get_json, api)
        if not data.get("success"): raise RuntimeError("Video API returned success=false.")
        video_url, quality = select_video(data, plat)
        if not video_url: raise RuntimeError("No playable video URL returned by API.")
        await status.edit_text(f"✅ <b>Video found</b>\n📺 Quality: <b>{esc(quality)}</b>\n\n⬇️ Downloading...",
                               parse_mode=ParseMode.HTML)
        path = await download(video_url, ".mp4")
        await status.edit_text("📤 <b>Uploading to Telegram...</b>\n\n⏳ Please wait...",
                               parse_mode=ParseMode.HTML)
        caption = f"🎬 <b>{plat.title()} Video</b>\n📺 Quality: <b>{esc(quality)}</b>\n\n⚡ <i>Misstu Downloader</i>"
        try:
            await client.send_video(m.chat.id, path, caption=caption, parse_mode=ParseMode.HTML,
                                     supports_streaming=True, file_name="misstu_video.mp4")
        except Exception:
            await client.send_document(m.chat.id, path, caption=caption, parse_mode=ParseMode.HTML,
                                       file_name="misstu_video.mp4")
        await status.delete()
    except Exception as e:
        log.exception("video")
        await status.edit_text(f"❌ <b>Download failed</b>\n\n<code>{esc(str(e)[:500])}</code>",
                               parse_mode=ParseMode.HTML)
    finally: rm(path)

async def main():
    await app.start()
    me = await app.get_me()
    log.info("Started as @%s", me.username or me.id)
    asyncio.get_running_loop().run_in_executor(None, run_web)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
