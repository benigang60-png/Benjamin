# -*- coding: utf-8 -*-
"""
ربات تلگرامی اختصاصی گروه
====================================
یک ربات تک‌فایلی برای مدیریت یک گروه تلگرامی خاص با امکانات:
- همگام‌سازی نام ربات با نام گروه
- پنل ادمین در پیوی (فعال‌سازی با ارسال 1212)
- پیام همگانی، تنظیم لینک گروه، مدیریت بازی‌ها، روشن/خاموش کردن هوش مصنوعی
- سیستم کاربران داستان‌دار + درخواست «کاربر اصلی شدن»
- ۲۰ بازی گروهی: دوز، سنگ‌کاغذقیچی، حدس عدد، تاس شانس، شیر یا خط،
  حدس کلمه، کوییز، ریاضی سریع، این یا اون، حدس اموجی، بلک‌جک،
  حروف به‌هم‌ریخته، چیستان، تایپ سریع، حدس پرچم، زنجیره کلمات،
  ضرب‌المثل، حافظه، رنگ سریع، کلمه در دسته
- کوییز / حدس کلمه / اموجی / چیستان و بقیه با GPT-OSS-20B ساخته می‌شن تا تکراری نباشن
- چت هوش مصنوعی با گراک (GPT-OSS-120B) + چرخش چند کلید هنگام ریت‌لیمیت

نحوه اجرا:
    pip install -r requirements.txt
    python bot-1.py
"""

import os
import re
import json
import time
import random
import string
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

import httpx
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ============================================================================
# تنظیمات (Config)
# ============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8750717991:AAHPqBuR-qrPSjE4RnfA21o12-6qRTk2LmI")


def _collect_groq_keys():
    """کلیدها از محیط یا فایل groq_keys.txt خونده می‌شن تا تو گیت لو نرن."""
    keys = []
    env_multi = os.environ.get("GROQ_API_KEYS", "")
    if env_multi:
        keys.extend(k.strip() for k in re.split(r"[,\s]+", env_multi) if k.strip())
    env_one = os.environ.get("GROQ_API_KEY", "")
    if env_one:
        keys.append(env_one.strip())
    keys_file = os.environ.get("GROQ_KEYS_FILE", os.path.join(os.path.dirname(__file__) or ".", "groq_keys.txt"))
    try:
        with open(keys_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith("gsk_"):
                    keys.append(line)
    except FileNotFoundError:
        pass
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


GROQ_API_KEYS = _collect_groq_keys()
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

GROQ_CHAT_MODEL = "openai/gpt-oss-120b"
GROQ_GAME_MODEL = "openai/gpt-oss-20b"
GROQ_MODEL = GROQ_CHAT_MODEL
GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY_COOLDOWN_DEFAULT = 60

AI_RATE_LIMIT_SECONDS = 15
AI_GROUP_COOLDOWN_SECONDS = 5
AI_MAX_OUTPUT_TOKENS = 1024

DB_PATH = os.environ.get("BOT_DB_PATH", "bot_data.db")
ADMIN_PASSCODE = "1212"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("group_bot")

GAMES = {
    "tictactoe": {"trigger": "دوز", "title": "دوز (سه در سه)", "min": 2, "max": 2},
    "rps": {"trigger": "سنگ کاغذ قیچی", "title": "سنگ کاغذ قیچی", "min": 2, "max": 2},
    "guess": {"trigger": "حدس عدد", "title": "حدس عدد (بدون محدودیت نفرات)", "min": 1, "max": None},
    "dice": {"trigger": "تاس شانس", "title": "تاس شانس (دو نفره)", "min": 2, "max": 2},
    "coin": {"trigger": "شیر یا خط", "title": "شیر یا خط (دو نفره)", "min": 2, "max": 2},
    "hangman": {"trigger": "حدس کلمه", "title": "حدس کلمه (دار)", "min": 1, "max": None},
    "trivia": {"trigger": "کوییز", "title": "کوییز اطلاعات عمومی", "min": 1, "max": None},
    "math": {"trigger": "ریاضی", "title": "ریاضی سریع", "min": 1, "max": None},
    "wyr": {"trigger": "این یا اون", "title": "این یا اون", "min": 1, "max": None},
    "emoji": {"trigger": "حدس اموجی", "title": "حدس اموجی", "min": 1, "max": None},
    "bj": {"trigger": "بلک جک", "title": "بلک جک (مقابل دیلر)", "min": 1, "max": None},
    "scramble": {"trigger": "حروف به هم ریخته", "title": "حروف به‌هم‌ریخته", "min": 1, "max": None},
    "riddle": {"trigger": "چیستان", "title": "چیستان", "min": 1, "max": None},
    "typerace": {"trigger": "تایپ سریع", "title": "تایپ سریع", "min": 1, "max": None},
    "flag": {"trigger": "حدس پرچم", "title": "حدس پرچم", "min": 1, "max": None},
    "chain": {"trigger": "زنجیره کلمات", "title": "زنجیره کلمات", "min": 1, "max": None},
    "proverb": {"trigger": "ضرب المثل", "title": "ضرب‌المثل", "min": 1, "max": None},
    "memory": {"trigger": "حافظه", "title": "حافظه تصویری", "min": 1, "max": None},
    "colors": {"trigger": "رنگ سریع", "title": "رنگ سریع", "min": 1, "max": None},
    "category": {"trigger": "کلمه در دسته", "title": "کلمه در دسته", "min": 1, "max": None},
    "whoami": {"trigger": "کی هستم", "title": "کی هستم؟", "min": 1, "max": None},
    "oddone": {"trigger": "گزینه ناجور", "title": "گزینه ناجور", "min": 1, "max": None},
    "quote": {"trigger": "حدس فیلم", "title": "حدس فیلم از دیالوگ", "min": 1, "max": None},
    "year": {"trigger": "حدس سال", "title": "حدس سال", "min": 1, "max": None},
    "codes": {"trigger": "کد سریع", "title": "کد سریع", "min": 1, "max": None},
    "lie": {"trigger": "دروغه کدومه", "title": "دروغه کدومه؟", "min": 1, "max": None},
}
TRIGGER_TO_GAME = {meta["trigger"]: key for key, meta in GAMES.items()}

# ============================================================================
# دیتابیس
# ============================================================================

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA journal_mode=WAL")


def db_init():
    c = _conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute(
        "CREATE TABLE IF NOT EXISTS stories ("
        "user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, story TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS story_requests ("
        "user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, requested_at TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS game_settings ("
        "game_key TEXT PRIMARY KEY, enabled INTEGER DEFAULT 1)"
    )
    c.execute("CREATE TABLE IF NOT EXISTS ai_prompts (id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT)")
    c.execute(
        "CREATE TABLE IF NOT EXISTS known_users ("
        "user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, first_seen TEXT)"
    )
    _conn.commit()
    for key in GAMES:
        c.execute("INSERT OR IGNORE INTO game_settings (game_key, enabled) VALUES (?, 1)", (key,))
    _conn.commit()


def get_setting(key: str, default=None):
    row = _conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str):
    _conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    _conn.commit()


def get_owner_id():
    v = get_setting("owner_id")
    return int(v) if v else None


def get_group_id():
    v = get_setting("group_id")
    return int(v) if v else None


def is_ai_enabled() -> bool:
    return get_setting("ai_enabled", "1") == "1"


def is_game_enabled(key: str) -> bool:
    row = _conn.execute("SELECT enabled FROM game_settings WHERE game_key = ?", (key,)).fetchone()
    return bool(row and row[0])


def toggle_game(key: str):
    cur = is_game_enabled(key)
    _conn.execute("UPDATE game_settings SET enabled = ? WHERE game_key = ?", (0 if cur else 1, key))
    _conn.commit()


def remember_user(user):
    _conn.execute(
        "INSERT OR IGNORE INTO known_users (user_id, full_name, username, first_seen) VALUES (?, ?, ?, ?)",
        (user.id, user.full_name, user.username or "", datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()


def get_story(user_id: int):
    row = _conn.execute("SELECT story FROM stories WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def list_stories():
    return _conn.execute("SELECT user_id, full_name, story FROM stories ORDER BY full_name").fetchall()


def save_story(user_id: int, full_name: str, username: str, story: str):
    _conn.execute(
        "INSERT INTO stories (user_id, full_name, username, story) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET story = excluded.story, full_name = excluded.full_name",
        (user_id, full_name, username or "", story),
    )
    _conn.execute("DELETE FROM story_requests WHERE user_id = ?", (user_id,))
    _conn.commit()


def delete_story(user_id: int):
    _conn.execute("DELETE FROM stories WHERE user_id = ?", (user_id,))
    _conn.commit()


def add_story_request(user_id: int, full_name: str, username: str):
    if get_story(user_id) is not None:
        return False
    _conn.execute(
        "INSERT OR IGNORE INTO story_requests (user_id, full_name, username, requested_at) VALUES (?, ?, ?, ?)",
        (user_id, full_name, username or "", datetime.now(timezone.utc).isoformat()),
    )
    _conn.commit()
    return True


def list_story_requests():
    return _conn.execute("SELECT user_id, full_name, username FROM story_requests ORDER BY requested_at").fetchall()


def reject_story_request(user_id: int):
    _conn.execute("DELETE FROM story_requests WHERE user_id = ?", (user_id,))
    _conn.commit()


def add_ai_prompt(text: str):
    _conn.execute("INSERT INTO ai_prompts (prompt) VALUES (?)", (text,))
    _conn.commit()


def get_ai_system_prompt() -> str:
    rows = _conn.execute("SELECT prompt FROM ai_prompts ORDER BY id").fetchall()
    base = (
        "تو یک دستیار هوش مصنوعی داخل یک گروه تلگرامی هستی. فارسی و دوستانه و طبیعی جواب بده، "
        "مگر اینکه دستور دیگه‌ای بهت داده شده باشه."
    )
    extra = "\n".join(r[0] for r in rows)
    return base + ("\n" + extra if extra else "")


db_init()

# ============================================================================
# وضعیت درون‌حافظه‌ای
# ============================================================================

PENDING_CHALLENGES = {}
ACTIVE_GAMES = {}
GUESS_GAMES = {}
HANGMAN_GAMES = {}
TRIVIA_GAMES = {}
MATH_GAMES = {}
WYR_GAMES = {}
EMOJI_GAMES = {}
BLACKJACK_GAMES = {}
SCRAMBLE_GAMES = {}
RIDDLE_GAMES = {}
TYPERACE_GAMES = {}
FLAG_GAMES = {}
CHAIN_GAMES = {}
PROVERB_GAMES = {}
MEMORY_GAMES = {}
COLOR_GAMES = {}
CATEGORY_GAMES = {}
WHOAMI_GAMES = {}
ODDONE_GAMES = {}
QUOTE_GAMES = {}
YEAR_GAMES = {}
CODE_GAMES = {}
LIE_GAMES = {}
RECENT_CONTENT = {}
AI_LAST_USED = {}
AI_GROUP_LAST_USED = {}
AI_HISTORY = {}

HANGMAN_WORDS = [
    ("گربه", "حیوانات"), ("فیل", "حیوانات"), ("زرافه", "حیوانات"), ("پروانه", "حیوانات"),
    ("گوسفند", "حیوانات"), ("کبوتر", "حیوانات"), ("روباه", "حیوانات"), ("پلنگ", "حیوانات"),
    ("سیب", "خوراکی"), ("هندوانه", "خوراکی"), ("پلو", "خوراکی"), ("کباب", "خوراکی"),
    ("آش", "خوراکی"), ("زعفران", "خوراکی"), ("گردو", "خوراکی"), ("انار", "خوراکی"),
    ("ایران", "کشورها"), ("ژاپن", "کشورها"), ("برزیل", "کشورها"), ("مصر", "کشورها"),
    ("کتاب", "اشیا"), ("چتر", "اشیا"), ("دوچرخه", "اشیا"), ("عینک", "اشیا"),
    ("گیتار", "اشیا"), ("ساعت", "اشیا"), ("آینه", "اشیا"), ("چراغ", "اشیا"),
    ("دریا", "طبیعت"), ("کوهستان", "طبیعت"), ("رنگینکمان", "طبیعت"), ("آبشار", "طبیعت"),
    ("فوتبال", "ورزش"), ("والیبال", "ورزش"), ("شطرنج", "ورزش"), ("کشتی", "ورزش"),
    ("کامپیوتر", "تکنولوژی"), ("اینترنت", "تکنولوژی"), ("موبایل", "تکنولوژی"),
    ("تهران", "شهرها"), ("شیراز", "شهرها"), ("اصفهان", "شهرها"), ("تبریز", "شهرها"),
    ("خورشید", "آسمان"), ("ستاره", "آسمان"), ("کهکشان", "آسمان"),
    ("نقاش", "شغل"), ("پزشک", "شغل"), ("معلم", "شغل"), ("آشپز", "شغل"),
]

TRIVIA_QUESTIONS = [
    {"q": "پایتخت فرانسه کجاست؟", "options": ["برلین", "پاریس", "رم", "مادرید"], "answer": 1, "cat": "جغرافیا"},
    {"q": "بزرگ‌ترین اقیانوس جهان کدام است؟", "options": ["اطلس", "هند", "آرام", "منجمد شمالی"], "answer": 2, "cat": "جغرافیا"},
    {"q": "بلندترین قله ایران چه نام دارد؟", "options": ["سبلان", "دماوند", "علم‌کوه", "زردکوه"], "answer": 1, "cat": "جغرافیا"},
    {"q": "طولانی‌ترین رودخانه‌ی جهان کدام است؟", "options": ["آمازون", "نیل", "میسیسیپی", "یانگ‌تسه"], "answer": 1, "cat": "جغرافیا"},
    {"q": "نزدیک‌ترین سیاره به خورشید کدام است؟", "options": ["زهره", "زمین", "عطارد", "مریخ"], "answer": 2, "cat": "علمی"},
    {"q": "آب از چه دو عنصری تشکیل شده؟", "options": ["هیدروژن و اکسیژن", "کربن و اکسیژن", "نیتروژن و هیدروژن", "هلیوم و اکسیژن"], "answer": 0, "cat": "علمی"},
    {"q": "سریع‌ترین حیوان خشکی جهان کدام است؟", "options": ["شیر", "یوزپلنگ", "اسب", "گورخر"], "answer": 1, "cat": "علمی"},
    {"q": "قلب انسان چند حفره دارد؟", "options": ["۲", "۳", "۴", "۵"], "answer": 2, "cat": "علمی"},
    {"q": "جام جهانی فوتبال هر چند سال یک‌بار برگزار می‌شود؟", "options": ["۲", "۳", "۴", "۵"], "answer": 2, "cat": "ورزش"},
    {"q": "یک بازی فوتبال معمولاً چند دقیقه است؟", "options": ["۶۰", "۷۰", "۸۰", "۹۰"], "answer": 3, "cat": "ورزش"},
    {"q": "در شطرنج، کدام مهره فقط مورب حرکت می‌کند؟", "options": ["اسب", "رخ", "فیل", "وزیر"], "answer": 2, "cat": "ورزش"},
    {"q": "فردوسی نویسنده‌ی کدام اثر است؟", "options": ["گلستان", "شاهنامه", "مثنوی", "بوستان"], "answer": 1, "cat": "فرهنگ"},
    {"q": "نوروز مصادف با شروع کدام فصل است؟", "options": ["زمستان", "بهار", "تابستان", "پاییز"], "answer": 1, "cat": "فرهنگ"},
    {"q": "پول رسمی ژاپن چه نام دارد؟", "options": ["وون", "ین", "یوان", "روپیه"], "answer": 1, "cat": "عمومی"},
    {"q": "بزرگ‌ترین کشور جهان از نظر مساحت کدام است؟", "options": ["چین", "کانادا", "روسیه", "آمریکا"], "answer": 2, "cat": "عمومی"},
    {"q": "زبان رسمی برزیل چیست؟", "options": ["اسپانیایی", "پرتغالی", "انگلیسی", "فرانسوی"], "answer": 1, "cat": "عمومی"},
    {"q": "کدام سیاره به «سیاره‌ی سرخ» معروف است؟", "options": ["زهره", "مشتری", "مریخ", "زحل"], "answer": 2, "cat": "علمی"},
    {"q": "المپیک تابستانی هر چند سال برگزار می‌شود؟", "options": ["۲", "۳", "۴", "۵"], "answer": 2, "cat": "ورزش"},
    {"q": "پایتخت ایران کجاست؟", "options": ["اصفهان", "تبریز", "تهران", "شیراز"], "answer": 2, "cat": "جغرافیا"},
    {"q": "کدام گاز بیشترین حجم هوای کره‌ی زمین را تشکیل می‌دهد؟", "options": ["اکسیژن", "نیتروژن", "دی‌اکسید کربن", "هیدروژن"], "answer": 1, "cat": "علمی"},
    {"q": "نویسنده رمان بوف کور کیست؟", "options": ["هدایت", "آل‌احمد", "دانشور", "گلشیری"], "answer": 0, "cat": "ادبیات"},
    {"q": "واحد پول ترکیه چیست؟", "options": ["لیر", "دینار", "درهم", "روپیه"], "answer": 0, "cat": "عمومی"},
    {"q": "کدام سیاره حلقه‌های معروف دارد؟", "options": ["مریخ", "زهره", "زحل", "عطارد"], "answer": 2, "cat": "علمی"},
    {"q": "پایتخت کانادا کجاست؟", "options": ["تورنتو", "اتاوا", "ونکوور", "مونترال"], "answer": 1, "cat": "جغرافیا"},
    {"q": "حافظ از شاعران کدام شهر است؟", "options": ["تبریز", "مشهد", "شیراز", "یزد"], "answer": 2, "cat": "فرهنگ"},
]

WYR_QUESTIONS = [
    ("همیشه یک ساعت زودتر همه‌جا برسی", "همیشه یک ساعت دیرتر همه‌جا برسی"),
    ("بتونی پرواز کنی", "بتونی نامرئی بشی"),
    ("تمام عمر پیتزا بخوری", "تمام عمر کباب بخوری"),
    ("همیشه تابستون باشه", "همیشه زمستون باشه"),
    ("ذهن دیگران رو بخونی", "بتونی آینده رو ببینی"),
    ("پولدار ولی تنها باشی", "فقیر ولی دور و برت پر از دوست باشه"),
    ("هیچ‌وقت نتونی دروغ بگی", "هیچ‌وقت نتونی حقیقتو تشخیص بدی"),
    ("همیشه توی ترافیک گیر کنی", "همیشه پرواز رو از دست بدی"),
    ("بدون گوشی یک هفته زندگی کنی", "بدون اینترنت یک ماه زندگی کنی"),
    ("عاشق شغلت باشی ولی حقوق کم بگیری", "از شغلت متنفر باشی ولی حقوق عالی بگیری"),
    ("همیشه برنده بشی ولی تنها بازی کنی", "گاهی ببازی ولی با دوستات بازی کنی"),
    ("بتونی هر زبونی رو بلد باشی", "بتونی هر سازی رو بنوازی"),
    ("صد سال توی گذشته زندگی کنی", "صد سال توی آینده زندگی کنی"),
    ("هر روز صبح زود بیدار بشی", "هر شب خیلی دیر بخوابی"),
    ("بتونی زمان رو متوقف کنی", "بتونی زمان رو برگردونی"),
    ("همیشه خوش‌شانس باشی ولی گمنام", "معروف باشی ولی بدشانس"),
    ("فقط بتونی آواز بخونی", "فقط بتونی برقصی"),
    ("یه ابرقهرمان باشی", "یه شرور باهوش باشی"),
]

EMOJI_RIDDLES = [
    ("🦁👑", "شیرشاه"),
    ("🕷️👨", "مرد عنکبوتی"),
    ("❄️👸", "فروزن"),
    ("🏠🎈", "بالا"),
    ("🐠🔍", "در جستجوی نمو"),
    ("🚢💔🧊", "تایتانیک"),
    ("👽📞🏠", "ای تی"),
    ("🦖🏝️", "پارک ژوراسیک"),
    ("👦🪄⚡", "هری پاتر"),
    ("🍫🏭", "چارلی و کارخانه شکلات"),
    ("🐭🧀", "موش و پنیر"),
    ("🌧️☂️😢", "روز بارونی"),
    ("🔥🐉", "اژدها"),
    ("🌙⭐😴", "شب بخیر"),
    ("🍎📱", "آیفون"),
    ("☕📖", "کتابخونه"),
    ("🎹🎶", "پیانو"),
]

FLAG_RIDDLES = [
    ("🇫🇷", "فرانسه"), ("🇯🇵", "ژاپن"), ("🇩🇪", "آلمان"), ("🇮🇹", "ایتالیا"),
    ("🇧🇷", "برزیل"), ("🇮🇷", "ایران"), ("🇹🇷", "ترکیه"), ("🇮🇳", "هند"),
    ("🇨🇦", "کانادا"), ("🇬🇧", "انگلیس"), ("🇺🇸", "آمریکا"), ("🇪🇸", "اسپانیا"),
    ("🇰🇷", "کره جنوبی"), ("🇨🇳", "چین"), ("🇷🇺", "روسیه"), ("🇪🇬", "مصر"),
    ("🇬🇷", "یونان"), ("🇲🇽", "مکزیک"), ("🇦🇺", "استرالیا"), ("🇳🇱", "هلند"),
    ("🇸🇪", "سوئد"), ("🇨🇭", "سوئیس"), ("🇦🇷", "آرژانتین"), ("🇵🇹", "پرتغال"),
]

PROVERBS = [
    ("سالی که نکوست از بهارش پیداست", "سالی که نکوست از", "بهارش پیداست"),
    ("کار نیکو کردن از پر کردن است", "کار نیکو کردن از", "پر کردن است"),
    ("باد آورده را باد میبرد", "باد آورده را", "باد میبرد"),
    ("از این ستون به آن ستون فرج است", "از این ستون به آن ستون", "فرج است"),
    ("جوجه را آخر پاییز میشمارند", "جوجه را آخر پاییز", "میشمارند"),
    ("هر که بامش بیش برفش بیشتر", "هر که بامش بیش", "برفش بیشتر"),
    ("دیوار موش دارد موش هم گوش دارد", "دیوار موش دارد", "موش هم گوش دارد"),
    ("با یک گل بهار نمیشود", "با یک گل", "بهار نمیشود"),
    ("عاقبت جوینده یابنده است", "عاقبت جوینده", "یابنده است"),
    ("گر صبر کنی ز غوره حلوا سازی", "گر صبر کنی ز غوره", "حلوا سازی"),
]

RIDDLES_BANK = [
    ("بالا میرود ولی هرگز پایین نمیآید. چیست؟", "سن", ["سن", "عمر"]),
    ("همیشه جلو میرود ولی هیچوقت جا عوض نمیکند. چیست؟", "ساعت", ["ساعت"]),
    ("بدون اینکه حرف بزند، حرف میزند. چیست؟", "کتاب", ["کتاب"]),
    ("هرچه از آن برداری بزرگتر میشود. چیست؟", "چاله", ["چاله", "گودال"]),
    ("خانه دارد ولی در ندارد. چیست؟", "قارچ", ["قارچ"]),
]

TYPERACE_PHRASES = [
    "گربه روی دیوار نشست",
    "امروز هوا خیلی قشنگه",
    "چای داغ با شکر کم",
    "فوتبال بدون تماشاچی معنی نداره",
    "کتابخونه جای آرومیه",
    "قایق روی دریاچه حرکت کرد",
    "شب یلدا بلندترین شب ساله",
    "هوش مصنوعی داره بازی میسازه",
]

CATEGORY_BANK = [
    {"category": "میوه", "accepted": ["سیب", "موز", "انگور", "هلو", "گلابی", "انار", "هندوانه", "طالبی", "کیوی", "پرتقال", "نارنگی", "آلبالو", "گیلاس", "توت", "انجیر"]},
    {"category": "حیوان", "accepted": ["گربه", "سگ", "اسب", "شیر", "ببر", "فیل", "زرافه", "گرگ", "روباه", "خرس", "گاو", "گوسفند", "مرغ", "اردک", "ماهی"]},
    {"category": "رنگ", "accepted": ["قرمز", "آبی", "سبز", "زرد", "مشکی", "سفید", "نارنجی", "بنفش", "صورتی", "قهوه ای", "خاکستری", "طلایی"]},
    {"category": "کشور", "accepted": ["ایران", "آلمان", "فرانسه", "ایتالیا", "ژاپن", "چین", "هند", "برزیل", "ترکیه", "مصر", "کانادا", "روسیه", "اسپانیا"]},
    {"category": "ورزش", "accepted": ["فوتبال", "والیبال", "بسکتبال", "تنیس", "شنا", "کشتی", "جودو", "بوکس", "شطرنج", "دوچرخه", "دو"]},
]

WHOAMI_BANK = [
    {"name": "فردوسی", "aliases": ["حکیم فردوسی"], "clues": ["شاعر ایرانی‌ام", "شاهنامه را سرودم", "از توس هستم"]},
    {"name": "حافظ", "aliases": ["خواجه حافظ"], "clues": ["غزل می‌گویم", "از شیراز هستم", "دیوانم فال گرفته می‌شود"]},
    {"name": "انیشتین", "aliases": ["اینشتین", "آلبرت اینشتین", "آلبرت انیشتین"], "clues": ["فیزیکدانم", "نسبیت را مطرح کردم", "موهای ژولیده‌ام معروف است"]},
    {"name": "پله", "aliases": [], "clues": ["فوتبالیستم", "برزیلی‌ام", "سه جام جهانی بردم"]},
    {"name": "هری پاتر", "aliases": ["هری"], "clues": ["جادوگرم", "عینک گرد دارم", "در هاگوارتز درس خواندم"]},
]
QUOTE_BANK = [
    ("می‌خواهم تنها باشم", "گوزنها", ["گوزن‌ها"]),
    ("تو نمی‌تونی این کارو با من بکنی", "کلاه قرمزی", []),
    ("من انتقام می‌گیرم", "سوپرمن", []),
    ("قدرت زیاد مسئولیت زیاد می‌آورد", "مرد عنکبوتی", ["اسپایدرمن", "اسپایدر من"]),
]
ODD_BANK = [
    {"options": ["سیب", "موز", "هلو", "گربه"], "odd": 3, "why": "گربه میوه نیست"},
    {"options": ["ایران", "فرانسه", "تهران", "ژاپن"], "odd": 2, "why": "تهران کشور نیست"},
    {"options": ["فوتبال", "والیبال", "شطرنج", "شنا"], "odd": 2, "why": "شطرنج ورزش توپی نیست"},
    {"options": ["قرمز", "آبی", "میز", "سبز"], "odd": 2, "why": "میز رنگ نیست"},
]
YEAR_BANK = [
    {"q": "پیروزی انقلاب ایران", "year": 1357},
    {"q": "اولین جام جهانی فوتبال", "year": 1930},
    {"q": "فرود انسان روی ماه", "year": 1969},
    {"q": "شروع جنگ جهانی دوم", "year": 1939},
    {"q": "تأسیس تلگرام", "year": 2013},
]
LIE_BANK = [
    {"a": "هشت پای یک اختاپوس هشت تاست", "b": "پنگوئن می‌تواند پرواز کند", "c": "الماس از کربن ساخته شده", "lie": "b"},
    {"a": "خورشید یک ستاره است", "b": "آب در صفر درجه یخ می‌زند", "c": "نهنگ یک ماهی است", "lie": "c"},
    {"a": "ایران چهار فصل دارد", "b": "قله دماوند در ترکیه است", "c": "نوروز جشن بهار است", "lie": "b"},
]

COLOR_CHOICES = [("قرمز", "🔴"), ("سبز", "🟢"), ("آبی", "🔵"), ("زرد", "🟡")]
MEMORY_EMOJIS = ["🍎", "🍌", "🍇", "🍉", "🍓", "🍒", "🥝", "🍍", "🥑", "🍑", "🍋", "🥥"]
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
HANGMAN_STAGES = ["🙂", "😐", "😟", "😨", "😰", "💀"]
TRIVIA_LETTERS = ["A", "B", "C", "D"]
RPS_BEATS = {"سنگ": "قیچی", "کاغذ": "سنگ", "قیچی": "کاغذ"}
CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
CARD_SUITS = ["♠️", "♥️", "♦️", "♣️"]


def new_session_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def parse_int(text: str):
    if text is None:
        return None
    cleaned = text.strip().translate(_FA_DIGITS)
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _normalize_fa(text: str) -> str:
    t = (text or "").strip().replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    t = t.replace("‌", "").replace("  ", " ").lower()
    return t


def _clean_word(text: str) -> str:
    return re.sub(r"\s+", "", _normalize_fa(text))


def remember_content(kind: str, value: str, limit: int = 40):
    rec = RECENT_CONTENT.setdefault(kind, [])
    rec.append(value)
    RECENT_CONTENT[kind] = rec[-limit:]


def pick_unused(items, key_fn, recent_key: str):
    recent = set(RECENT_CONTENT.get(recent_key, []))
    unused = [x for x in items if key_fn(x) not in recent]
    choice = random.choice(unused or items)
    remember_content(recent_key, key_fn(choice))
    return choice


class GroqKeyPool:
    """چرخش کلیدها: تا وقتی کلید فعلی سالمه همونو می‌زنیم؛ با 429 می‌ریم بعدی."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.index = 0
        self.cooldown_until = [0.0] * len(self.keys)

    def pick(self):
        if not self.keys:
            return -1, ""
        now = time.time()
        n = len(self.keys)
        for i in range(n):
            idx = (self.index + i) % n
            if now >= self.cooldown_until[idx]:
                self.index = idx
                return idx, self.keys[idx]
        idx = min(range(n), key=lambda i: self.cooldown_until[i])
        self.index = idx
        return idx, self.keys[idx]

    def mark_limited(self, idx: int, seconds: int = GROQ_KEY_COOLDOWN_DEFAULT):
        if 0 <= idx < len(self.keys):
            self.cooldown_until[idx] = time.time() + max(5, int(seconds))
            self.index = (idx + 1) % len(self.keys)

    def mark_ok(self, idx: int):
        if 0 <= idx < len(self.keys):
            self.index = idx


KEY_POOL = GroqKeyPool(GROQ_API_KEYS)


# ============================================================================
# ابزارهای کمکی
# ============================================================================


async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    try:
        return await update.message.reply_text(text, **kwargs)
    except BadRequest as e:
        if "not found" in str(e).lower() or "message to be replied" in str(e).lower():
            logger.warning("safe_reply: پیام اصلی پیدا نشد، بدون ریپلای فرستاده شد.")
            return await context.bot.send_message(update.effective_chat.id, text, **kwargs)
        raise


async def safe_edit(query, text: str, **kwargs):
    try:
        return await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        msg = str(e).lower()
        if "not modified" in msg or "not found" in msg or "message to edit" in msg:
            return None
        raise


async def safe_answer(query, *args, **kwargs):
    try:
        return await query.answer(*args, **kwargs)
    except Exception:
        return None


async def is_owner(update: Update) -> bool:
    owner = get_owner_id()
    return owner is not None and update.effective_user and update.effective_user.id == owner


def in_linked_group(chat_id: int) -> bool:
    gid = get_group_id()
    return gid is not None and gid == chat_id


def admin_main_menu() -> InlineKeyboardMarkup:
    ai_state = "🟢 روشن" if is_ai_enabled() else "🔴 خاموش"
    rows = [
        [InlineKeyboardButton("📢 پیام همگانی به گروه", callback_data="adm:broadcast")],
        [InlineKeyboardButton("🔗 تنظیم لینک گروه", callback_data="adm:setlink")],
        [InlineKeyboardButton("🎮 مدیریت بازی‌ها", callback_data="adm:games")],
        [InlineKeyboardButton(f"🤖 هوش مصنوعی: {ai_state}", callback_data="adm:toggle_ai")],
        [InlineKeyboardButton("👥 کاربران داستان‌دار", callback_data="adm:stories")],
        [InlineKeyboardButton("✍️ افزودن پرامپت به هوش مصنوعی", callback_data="adm:addprompt")],
        [InlineKeyboardButton("📨 درخواست‌های کاربر اصلی شدن", callback_data="adm:requests")],
    ]
    return InlineKeyboardMarkup(rows)


def games_menu() -> InlineKeyboardMarkup:
    rows = []
    for key, meta in GAMES.items():
        state = "✅" if is_game_enabled(key) else "❌"
        rows.append([InlineKeyboardButton(f"{state} {meta['title']}", callback_data=f"adm:togglegame:{key}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:back")])
    return InlineKeyboardMarkup(rows)


def stories_admin_menu() -> InlineKeyboardMarkup:
    rows = []
    for uid, name, _ in list_stories():
        rows.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"adm:storyview:{uid}")])
    rows.append([InlineKeyboardButton("➕ افزودن داستان برای کاربر جدید", callback_data="adm:storynew")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:back")])
    return InlineKeyboardMarkup(rows)


def skip_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ رد شدن / لو دادن", callback_data=prefix)]])


# ============================================================================
# هوش مصنوعی (Groq — چرخش کلید + مدل بازی)
# ============================================================================


def _key_tail(key: str) -> str:
    return key[-4:] if key and len(key) >= 4 else "????"


def _parse_retry_after(resp) -> int:
    ra = (resp.headers.get("retry-after") or "").strip()
    if ra.isdigit():
        return max(5, min(int(ra), 600))
    return GROQ_KEY_COOLDOWN_DEFAULT


async def _call_groq_once(client: httpx.AsyncClient, payload: dict, api_key: str):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = await client.post(GROQ_API_BASE, json=payload, headers=headers)
    except Exception as e:
        logger.warning("Groq: خطای شبکه — %s", e)
        return None, None, None

    if resp.status_code != 200:
        retry_after = _parse_retry_after(resp) if resp.status_code == 429 else None
        logger.warning(
            "Groq: خطای %s کلید ...%s — %s",
            resp.status_code,
            _key_tail(api_key),
            (resp.text or "")[:180],
        )
        return None, resp.status_code, retry_after

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        logger.warning("Groq: پاسخ بدون choices")
        return None, resp.status_code, None

    message = choices[0].get("message", {}) or {}
    text = (message.get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not text:
        logger.warning("Groq: متن پاسخ خالی بود")
        return None, resp.status_code, None
    return text, resp.status_code, None


async def _call_groq_rotating(client: httpx.AsyncClient, payload: dict):
    if not KEY_POOL.keys:
        return None
    n = len(KEY_POOL.keys)
    for _ in range(n):
        idx, key = KEY_POOL.pick()
        if not key:
            return None
        text, status, retry_after = await _call_groq_once(client, payload, key)
        if text:
            KEY_POOL.mark_ok(idx)
            return text
        if status == 429:
            KEY_POOL.mark_limited(idx, retry_after or GROQ_KEY_COOLDOWN_DEFAULT)
            logger.info("Groq: کلید ...%s ریت‌لیمیت شد، می‌رم سراغ بعدی", _key_tail(key))
            continue
        if status in (401, 403):
            KEY_POOL.mark_limited(idx, 3600)
            continue
        if status == 503 or status is None:
            await asyncio.sleep(1.2)
            text, status, retry_after = await _call_groq_once(client, payload, key)
            if text:
                KEY_POOL.mark_ok(idx)
                return text
            if status == 429:
                KEY_POOL.mark_limited(idx, retry_after or GROQ_KEY_COOLDOWN_DEFAULT)
            else:
                KEY_POOL.mark_limited(idx, 15)
            continue
        break
    return None


async def ask_groq(
    system_prompt: str,
    history: list,
    user_text: str,
    *,
    model: str = None,
    models=None,
    max_tokens: int = None,
    temperature: float = 0.7,
    timeout: float = 30,
):
    messages = [{"role": "system", "content": system_prompt}]
    for turn in (history or [])[-8:]:
        role = "assistant" if turn["role"] == "model" else "user"
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_text})

    model_list = list(models) if models else [model or GROQ_CHAT_MODEL]
    seen, uniq = set(), []
    for m in model_list:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for used_model in uniq:
            payload = {
                "model": used_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or AI_MAX_OUTPUT_TOKENS,
            }
            text = await _call_groq_rotating(client, payload)
            if text:
                return text, used_model
    return None, None


def extract_json_obj(text: str):
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    blob = match.group(0)
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        try:
            data = json.loads(blob.replace("'", '"'))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


async def generate_game_json(user_prompt: str):
    system = (
        "تو سازنده‌ی محتوای بازی گروهی هستی. فقط یک شیء JSON معتبر برگردان. "
        "بدون توضیح، بدون مارک‌داون، بدون متن اضافه."
    )
    text, _ = await ask_groq(
        system,
        [],
        user_prompt,
        models=[GROQ_GAME_MODEL, GROQ_CHAT_MODEL],
        max_tokens=350,
        temperature=1.05,
        timeout=18,
    )
    return extract_json_obj(text)


def _recent_hint(kind: str) -> str:
    rec = RECENT_CONTENT.get(kind) or []
    if not rec:
        return ""
    return "از این موارد دوری کن: " + " | ".join(rec[-8:])


# ============================================================================
# هندلرها: شروع، عضویت ربات در گروه، تغییر نام گروه
# ============================================================================


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    new_status = update.my_chat_member.new_chat_member.status
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    if new_status in ("member", "administrator"):
        existing = get_group_id()
        if existing is None:
            set_setting("group_id", chat.id)
            set_setting("group_title", chat.title or "گروه")
            try:
                await context.bot.set_my_name(name=(chat.title or "ربات گروه")[:64])
            except Exception as e:
                logger.warning("set_my_name failed: %s", e)
            await context.bot.send_message(
                chat.id, "سلام! من فعال شدم و از این به بعد فقط توی همین گروه کار می‌کنم. 🎉\n/start رو بزنید تا شروع کنیم."
            )
        elif existing != chat.id:
            await context.bot.send_message(chat.id, "این ربات فقط برای یک گروه خاص تنظیم شده و نمی‌تونه اینجا فعال باشه. 🙏")
            try:
                await context.bot.leave_chat(chat.id)
            except Exception:
                pass


async def on_new_chat_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not in_linked_group(chat.id):
        return
    new_title = update.message.new_chat_title
    set_setting("group_title", new_title)
    try:
        await context.bot.set_my_name(name=new_title[:64])
    except Exception as e:
        logger.warning("set_my_name failed: %s", e)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    remember_user(user)

    if chat.type == ChatType.PRIVATE:
        gid = get_group_id()
        title = get_setting("group_title", "گروه")
        link = get_setting("group_link")
        if gid is None:
            await safe_reply(update, context, "سلام! هنوز به هیچ گروهی وصل نشدم. اول من رو به عنوان ادمین به گروهت اضافه کن. 🙌")
            return
        text = f"سلام {user.first_name} 👋\nاین ربات فقط توی گروه «{title}» فعالیته و اینجا توی پیوی کاری ازم برنمیاد."
        kb = None
        if link:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ورود به گروه", url=link)]])
        await safe_reply(update, context, text, reply_markup=kb)
        return

    if not in_linked_group(chat.id):
        return
    title = get_setting("group_title", chat.title or "این گروه")

    enabled_games = [meta for key, meta in GAMES.items() if is_game_enabled(key)]
    if enabled_games:
        games_lines = "\n".join(f"• «{g['trigger']}» — {g['title']}" for g in enabled_games)
        games_block = f"🎮 <b>بازی‌های فعال</b> (کافیه اسمشون رو دقیقاً همینجوری بفرستی):\n{games_lines}"
    else:
        games_block = "🎮 الان بازی فعالی نداریم."

    text = (
        f"سلام به همه! 👋 توی گروه «{title}» هستیم.\n\n"
        f"{games_block}\n\n"
        "🤖 <b>چت با هوش مصنوعی</b>: روی هر پیامی که خود من فرستادم ریپلای بزن و باهام حرف بزن.\n\n"
        "📖 <b>داستان کاربرا</b>: با دکمه‌ی زیر می‌تونی داستان کاربرای خاص گروه رو ببینی.\n"
        "⭐️ اگه دوست داری خودتم یه داستان اختصاصی داشته باشی، درخواست بده تا بررسی بشه."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📖 لیست کاربران داستان‌دار", callback_data="grp:stories")],
            [InlineKeyboardButton("⭐️ درخواست کاربر اصلی شدن", callback_data="grp:reqmain")],
        ]
    )
    await safe_reply(update, context, text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ============================================================================
# روتر پیام‌های خصوصی
# ============================================================================


async def private_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    owner = get_owner_id()
    if owner is None:
        set_setting("owner_id", user.id)
        await safe_reply(update, context, "شما به عنوان ادمین اصلی ربات ثبت شدید ✅")
        await safe_reply(update, context, "پنل ادمین 👇", reply_markup=admin_main_menu())
    elif owner == user.id:
        await safe_reply(update, context, "پنل ادمین 👇", reply_markup=admin_main_menu())


async def private_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != get_owner_id():
        return
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    text = update.message.text.strip()

    if awaiting == "broadcast":
        gid = get_group_id()
        if gid:
            await context.bot.send_message(gid, text)
            await safe_reply(update, context, "پیام همگانی ارسال شد ✅")
        else:
            await safe_reply(update, context, "هنوز گروهی وصل نشده.")
        context.user_data["awaiting"] = None

    elif awaiting == "setlink":
        set_setting("group_link", text)
        await safe_reply(update, context, "لینک گروه ذخیره شد ✅")
        context.user_data["awaiting"] = None

    elif awaiting == "addprompt":
        add_ai_prompt(text)
        await safe_reply(update, context, "این دستور برای همیشه به شخصیت هوش مصنوعی اضافه شد ✅")
        context.user_data["awaiting"] = None

    elif awaiting == "story_new_id":
        if not text.isdigit():
            await safe_reply(update, context, "آیدی عددی کاربر (User ID) رو بفرست.")
            return
        context.user_data["story_target_id"] = int(text)
        context.user_data["awaiting"] = "story_new_text"
        await safe_reply(update, context, "حالا متن داستان این کاربر رو بفرست:")

    elif awaiting == "story_new_text":
        uid = context.user_data.get("story_target_id")
        save_story(uid, f"کاربر {uid}", "", text)
        await safe_reply(update, context, "داستان ذخیره شد ✅", reply_markup=stories_admin_menu())
        context.user_data["awaiting"] = None
        context.user_data["story_target_id"] = None

    elif awaiting == "story_approve_text":
        uid = context.user_data.get("story_target_id")
        info = context.user_data.get("story_target_info", {})
        save_story(uid, info.get("full_name", f"کاربر {uid}"), info.get("username", ""), text)
        await safe_reply(update, context, "داستان ذخیره و کاربر به لیست اضافه شد ✅")
        context.user_data["awaiting"] = None
        context.user_data["story_target_id"] = None


# ============================================================================
# کال‌بک‌های پنل ادمین
# ============================================================================


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if update.effective_user.id != get_owner_id():
        await safe_answer(query, "این بخش فقط برای ادمین ربات در دسترسه.", show_alert=True)
        return
    await safe_answer(query)

    if data == "adm:back":
        await safe_edit(query, "پنل ادمین 👇", reply_markup=admin_main_menu())

    elif data == "adm:broadcast":
        context.user_data["awaiting"] = "broadcast"
        await safe_edit(query, "متن پیام همگانی رو بفرست تا توی گروه ارسال بشه:")

    elif data == "adm:setlink":
        context.user_data["awaiting"] = "setlink"
        await safe_edit(query, "لینک دعوت گروه رو بفرست:")

    elif data == "adm:games":
        await safe_edit(query, "مدیریت بازی‌ها 👇", reply_markup=games_menu())

    elif data.startswith("adm:togglegame:"):
        key = data.split(":")[2]
        toggle_game(key)
        await safe_edit(query, "مدیریت بازی‌ها 👇", reply_markup=games_menu())

    elif data == "adm:toggle_ai":
        set_setting("ai_enabled", "0" if is_ai_enabled() else "1")
        await safe_edit(query, "پنل ادمین 👇", reply_markup=admin_main_menu())

    elif data == "adm:stories":
        await safe_edit(query, "کاربران داستان‌دار 👇", reply_markup=stories_admin_menu())

    elif data.startswith("adm:storyview:"):
        uid = int(data.split(":")[2])
        story = get_story(uid) or "(داستانی ثبت نشده)"
        rows = [
            [InlineKeyboardButton("🗑 حذف این کاربر", callback_data=f"adm:storydel:{uid}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="adm:stories")],
        ]
        await safe_edit(query, f"داستان کاربر {uid}:\n\n{story}", reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("adm:storydel:"):
        uid = int(data.split(":")[2])
        delete_story(uid)
        await safe_edit(query, "کاربران داستان‌دار 👇", reply_markup=stories_admin_menu())

    elif data == "adm:storynew":
        context.user_data["awaiting"] = "story_new_id"
        await safe_edit(query, "آیدی عددی (User ID) کاربر مورد نظر رو بفرست:")

    elif data == "adm:addprompt":
        context.user_data["awaiting"] = "addprompt"
        await safe_edit(
            query,
            "دستور یا شخصیتی که می‌خوای برای همیشه به هوش مصنوعی اضافه بشه رو بفرست.\n"
            "مثال: «تو اسمت جعفره»",
        )

    elif data == "adm:requests":
        reqs = list_story_requests()
        if not reqs:
            rows = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm:back")]]
            await safe_edit(query, "درخواستی در انتظار نیست.", reply_markup=InlineKeyboardMarkup(rows))
            return
        rows = []
        for uid, name, uname in reqs:
            rows.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"adm:reqview:{uid}")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:back")])
        await safe_edit(query, "درخواست‌های کاربر اصلی شدن 👇", reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("adm:reqview:"):
        uid = int(data.split(":")[2])
        row = _conn.execute(
            "SELECT full_name, username FROM story_requests WHERE user_id = ?", (uid,)
        ).fetchone()
        name = row[0] if row else f"کاربر {uid}"
        uname = row[1] if row else ""
        rows = [
            [InlineKeyboardButton("✅ قبول و نوشتن داستان", callback_data=f"adm:reqapprove:{uid}")],
            [InlineKeyboardButton("❌ رد درخواست", callback_data=f"adm:reqreject:{uid}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="adm:requests")],
        ]
        await safe_edit(
            query,
            f"درخواست از طرف: {name} (@{uname or '---'})\nآیدی: {uid}",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    elif data.startswith("adm:reqapprove:"):
        uid = int(data.split(":")[2])
        row = _conn.execute(
            "SELECT full_name, username FROM story_requests WHERE user_id = ?", (uid,)
        ).fetchone()
        context.user_data["story_target_id"] = uid
        context.user_data["story_target_info"] = {
            "full_name": row[0] if row else f"کاربر {uid}",
            "username": row[1] if row else "",
        }
        context.user_data["awaiting"] = "story_approve_text"
        await safe_edit(query, "متن داستان این کاربر رو بنویس:")

    elif data.startswith("adm:reqreject:"):
        uid = int(data.split(":")[2])
        reject_story_request(uid)
        await safe_edit(query, "درخواست رد شد.", reply_markup=admin_main_menu())


# ============================================================================
# کال‌بک‌های داخل گروه
# ============================================================================


async def group_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat = update.effective_chat
    user = update.effective_user

    if not in_linked_group(chat.id):
        await safe_answer(query)
        return

    if data == "grp:stories":
        stories = list_stories()
        if not stories:
            await safe_answer(query, "فعلاً کاربر داستان‌داری نداریم.", show_alert=True)
            return
        rows = [[InlineKeyboardButton(f"👤 {name}", callback_data=f"grp:storyview:{uid}")] for uid, name, _ in stories]
        rows.append([InlineKeyboardButton("🔙 بستن", callback_data="grp:close")])
        await safe_answer(query)
        await context.bot.send_message(chat.id, "لیست کاربران داستان‌دار 👇", reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("grp:storyview:"):
        uid = int(data.split(":")[2])
        story = get_story(uid) or "داستانی ثبت نشده."
        await safe_answer(query)
        await context.bot.send_message(chat.id, story)

    elif data == "grp:close":
        await safe_answer(query)

    elif data == "grp:reqmain":
        remember_user(user)
        if get_story(user.id) is not None:
            await safe_answer(query, "شما همین الان هم کاربر داستان‌دار هستید! ⭐️", show_alert=True)
            return
        added = add_story_request(user.id, user.full_name, user.username or "")
        if not added:
            await safe_answer(query, "درخواست شما قبلاً ثبت شده، صبر کن ادمین بررسی کنه.", show_alert=True)
            return
        await safe_answer(query, "درخواست شما ثبت شد ✅", show_alert=True)
        owner = get_owner_id()
        if owner:
            rows = [
                [InlineKeyboardButton("✅ قبول و نوشتن داستان", callback_data=f"adm:reqapprove:{user.id}")],
                [InlineKeyboardButton("❌ رد درخواست", callback_data=f"adm:reqreject:{user.id}")],
            ]
            try:
                await context.bot.send_message(
                    owner,
                    f"درخواست جدید برای کاربر اصلی شدن:\n👤 {user.full_name} (@{user.username or '---'})\nآیدی: {user.id}",
                    reply_markup=InlineKeyboardMarkup(rows),
                )
            except Exception as e:
                logger.warning("could not notify owner: %s", e)


# ============================================================================
# بازی‌ها
# ============================================================================


async def game_trigger_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not in_linked_group(chat.id):
        return
    text = update.message.text.strip()
    key = TRIGGER_TO_GAME.get(text)
    if key is None:
        return
    if not is_game_enabled(key):
        await safe_reply(update, context, "این بازی الان توسط ادمین غیرفعال شده.")
        raise ApplicationHandlerStop

    user = update.effective_user
    remember_user(user)

    starters = {
        "guess": start_guess_game,
        "hangman": start_hangman_game,
        "trivia": start_trivia_game,
        "math": start_math_game,
        "wyr": start_wyr_game,
        "emoji": start_emoji_game,
        "bj": start_blackjack_game,
        "scramble": start_scramble_game,
        "riddle": start_riddle_game,
        "typerace": start_typerace_game,
        "flag": start_flag_game,
        "chain": start_chain_game,
        "proverb": start_proverb_game,
        "memory": start_memory_game,
        "colors": start_color_game,
        "category": start_category_game,
        "whoami": start_whoami_game,
        "oddone": start_oddone_game,
        "quote": start_quote_game,
        "year": start_year_game,
        "codes": start_codes_game,
        "lie": start_lie_game,
    }
    starter = starters.get(key)
    if starter:
        await starter(update, context)
        raise ApplicationHandlerStop

    session_id = new_session_id()
    PENDING_CHALLENGES[session_id] = {
        "game": key,
        "initiator": user.id,
        "initiator_name": user.full_name,
        "chat_id": chat.id,
    }
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ قبول چالش", callback_data=f"join:{session_id}")]])
    await safe_reply(
        update,
        context,
        f"🎮 {user.full_name} دنبال حریف برای «{GAMES[key]['title']}» می‌گرده!\nکی قبول می‌کنه؟",
        reply_markup=kb,
    )
    raise ApplicationHandlerStop


async def game_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    session_id = query.data.split(":")[1]
    challenge = PENDING_CHALLENGES.get(session_id)
    if not challenge:
        await safe_answer(query, "این چالش دیگه معتبر نیست.", show_alert=True)
        return
    user = update.effective_user
    if user.id == challenge["initiator"]:
        await safe_answer(query, "نمی‌تونی با خودت بازی کنی! یکی دیگه باید قبول کنه.", show_alert=True)
        return

    del PENDING_CHALLENGES[session_id]
    remember_user(user)
    game_key = challenge["game"]

    if game_key == "tictactoe":
        ACTIVE_GAMES[session_id] = {
            "game": "tictactoe",
            "board": [""] * 9,
            "players": {challenge["initiator"]: "❌", user.id: "⭕️"},
            "names": {challenge["initiator"]: challenge["initiator_name"], user.id: user.full_name},
            "turn": challenge["initiator"],
        }
        await safe_answer(query)
        await safe_edit(
            query,
            f"دوز شروع شد! ❌ {challenge['initiator_name']} در برابر ⭕️ {user.full_name}\nنوبت: {challenge['initiator_name']} (❌)",
            reply_markup=render_ttt_board(session_id),
        )
    elif game_key == "rps":
        ACTIVE_GAMES[session_id] = {
            "game": "rps",
            "players": [challenge["initiator"], user.id],
            "names": {challenge["initiator"]: challenge["initiator_name"], user.id: user.full_name},
            "choices": {},
        }
        await safe_answer(query)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🪨 سنگ", callback_data=f"rps:{session_id}:سنگ"),
                    InlineKeyboardButton("📄 کاغذ", callback_data=f"rps:{session_id}:کاغذ"),
                    InlineKeyboardButton("✂️ قیچی", callback_data=f"rps:{session_id}:قیچی"),
                ]
            ]
        )
        await safe_edit(
            query,
            f"سنگ‌کاغذقیچی شروع شد بین {challenge['initiator_name']} و {user.full_name}!\nهر دو نفر مخفیانه انتخاب کنید 👇",
            reply_markup=kb,
        )
    elif game_key == "dice":
        ACTIVE_GAMES[session_id] = {
            "game": "dice",
            "players": [challenge["initiator"], user.id],
            "names": {challenge["initiator"]: challenge["initiator_name"], user.id: user.full_name},
            "rolls": {},
        }
        await safe_answer(query)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 رول کن", callback_data=f"dd:{session_id}:roll")]])
        await safe_edit(
            query,
            f"تاس شانس شروع شد بین {challenge['initiator_name']} و {user.full_name}!\nهر دو نفر تاس بریزید، بیشترین عدد می‌بره 👇",
            reply_markup=kb,
        )
    elif game_key == "coin":
        p1, p2 = challenge["initiator"], user.id
        sides = {p1: "شیر", p2: "خط"}
        result = random.choice(["شیر", "خط"])
        winner_id = p1 if sides[p1] == result else p2
        winner_name = challenge["initiator_name"] if winner_id == p1 else user.full_name
        emoji = "🦁" if result == "شیر" else "🪙"
        await safe_answer(query)
        await safe_edit(
            query,
            f"شیر یا خط: {challenge['initiator_name']} = شیر 🦁 | {user.full_name} = خط 🪙\n\n"
            f"سکه چرخید... {emoji} {result} اومد!\n\n🏆 {winner_name} برنده شد!",
        )


def check_ttt_winner(board):
    lines = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    ]
    for a, b, c in lines:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if all(board):
        return "draw"
    return None


def render_ttt_board(session_id):
    game = ACTIVE_GAMES[session_id]
    board = game["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            label = board[i] if board[i] else "・"
            row.append(InlineKeyboardButton(label, callback_data=f"ttt:{session_id}:{i}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def ttt_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, idx = query.data.split(":")
    idx = int(idx)
    game = ACTIVE_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این بازی تموم شده.", show_alert=True)
        return
    user = update.effective_user
    if user.id not in game["players"]:
        await safe_answer(query, "این بازی برای شما نیست.", show_alert=True)
        return
    if user.id != game["turn"]:
        await safe_answer(query, "نوبت شما نیست، صبر کن.", show_alert=True)
        return
    if game["board"][idx]:
        await safe_answer(query, "این خونه پره!", show_alert=True)
        return

    game["board"][idx] = game["players"][user.id]
    winner = check_ttt_winner(game["board"])
    await safe_answer(query)

    if winner == "draw":
        await safe_edit(query, "🤝 بازی مساوی شد!", reply_markup=render_ttt_board(session_id))
        del ACTIVE_GAMES[session_id]
        return
    if winner:
        winner_name = game["names"][user.id]
        await safe_edit(query, f"🏆 {winner_name} برنده شد!", reply_markup=render_ttt_board(session_id))
        del ACTIVE_GAMES[session_id]
        return

    other = [uid for uid in game["players"] if uid != user.id][0]
    game["turn"] = other
    turn_name = game["names"][other]
    turn_symbol = game["players"][other]
    await safe_edit(query, f"نوبت: {turn_name} ({turn_symbol})", reply_markup=render_ttt_board(session_id))


async def rps_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, choice = query.data.split(":")
    game = ACTIVE_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این بازی تموم شده.", show_alert=True)
        return
    user = update.effective_user
    if user.id not in game["players"]:
        await safe_answer(query, "این بازی برای شما نیست.", show_alert=True)
        return
    if user.id in game["choices"]:
        await safe_answer(query, "انتخابت قبلاً ثبت شده، منتظر حریف باش.", show_alert=True)
        return

    game["choices"][user.id] = choice
    await safe_answer(query, "انتخابت ثبت شد ✅ منتظر حریف باش.")

    if len(game["choices"]) < 2:
        return

    p1, p2 = game["players"]
    c1, c2 = game["choices"][p1], game["choices"][p2]
    n1, n2 = game["names"][p1], game["names"][p2]
    if c1 == c2:
        result = "🤝 مساوی شد!"
    elif RPS_BEATS[c1] == c2:
        result = f"🏆 {n1} برنده شد!"
    else:
        result = f"🏆 {n2} برنده شد!"

    await safe_edit(query, f"{n1} انتخاب کرد: {c1}\n{n2} انتخاب کرد: {c2}\n\n{result}")
    del ACTIVE_GAMES[session_id]


async def dice_duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, _ = query.data.split(":")
    game = ACTIVE_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این بازی تموم شده.", show_alert=True)
        return
    user = update.effective_user
    if user.id not in game["players"]:
        await safe_answer(query, "این بازی برای شما نیست.", show_alert=True)
        return
    if user.id in game["rolls"]:
        await safe_answer(query, "قبلاً رول کردی، منتظر حریف باش.", show_alert=True)
        return

    game["rolls"][user.id] = random.randint(1, 6)
    await safe_answer(query, f"🎲 عدد تو: {game['rolls'][user.id]}")

    if len(game["rolls"]) < 2:
        return

    p1, p2 = game["players"]
    r1, r2 = game["rolls"][p1], game["rolls"][p2]
    n1, n2 = game["names"][p1], game["names"][p2]

    if r1 == r2:
        game["rolls"] = {}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 رول کن (تساوی، دوباره)", callback_data=f"dd:{session_id}:roll")]])
        await safe_edit(query, f"{n1} 🎲 {r1}  |  {n2} 🎲 {r2}\n\n🤝 تساوی شد! دوباره رول کنید.", reply_markup=kb)
        return

    winner = n1 if r1 > r2 else n2
    await safe_edit(query, f"{n1} 🎲 {r1}  |  {n2} 🎲 {r2}\n\n🏆 {winner} برنده شد!")
    del ACTIVE_GAMES[session_id]


async def start_guess_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in GUESS_GAMES:
        await safe_reply(update, context, "یک بازی حدس عدد همین الان فعاله! یه عدد بین ۱ تا ۱۰۰ بفرست.")
        return
    GUESS_GAMES[chat_id] = {"number": random.randint(1, 100), "low": 1, "high": 100}
    await safe_reply(update, context, "🎲 بازی حدس عدد شروع شد! یه عدد بین ۱ تا ۱۰۰ حدس بزن (فقط با فرستادن عدد توی گروه).")


async def start_math_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in MATH_GAMES:
        await safe_reply(update, context, f"یک سوال ریاضی همین الان فعاله: {MATH_GAMES[chat_id]['question']} = ?")
        return
    op = random.choice(["+", "-", "×"])
    if op == "+":
        a, b = random.randint(10, 90), random.randint(10, 90)
        answer = a + b
    elif op == "-":
        a, b = random.randint(20, 99), random.randint(1, 19)
        answer = a - b
    else:
        a, b = random.randint(2, 12), random.randint(2, 12)
        answer = a * b
    question = f"{a} {op} {b}"
    MATH_GAMES[chat_id] = {"question": question, "answer": answer}
    await safe_reply(update, context, f"🧮 ریاضی سریع! {question} = ?\n(فقط جواب رو به‌صورت عدد بفرست)")


def render_hangman_word(game) -> str:
    return " ".join(ch if ch in game["guessed"] else "▫️" for ch in game["word"])


async def start_hangman_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in HANGMAN_GAMES:
        game = HANGMAN_GAMES[chat_id]
        await safe_reply(
            update,
            context,
            f"یک بازی حدس کلمه همین الان فعاله ({game['category']}):\n{render_hangman_word(game)}\nحرف بعدی رو بفرست 👇",
        )
        return

    wait = await safe_reply(update, context, "⏳ دارم یه کلمه‌ی تازه می‌سازم...")
    word, category = None, None
    data = await generate_game_json(
        "یک کلمه‌ی فارسی یک‌تکه برای بازی دار بساز. ۳ تا ۸ حرف، بدون فاصله و عدد و نیم‌فاصله. "
        f"{_recent_hint('hangman')} "
        'JSON: {"word":"گربه","category":"حیوانات"}'
    )
    if data:
        cand = _clean_word(str(data.get("word") or ""))
        if 3 <= len(cand) <= 10 and re.fullmatch(r"[آاأإءؤئبیپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]+", cand):
            word, category = cand, str(data.get("category") or "عمومی")[:20]

    if not word:
        pair = pick_unused(HANGMAN_WORDS, lambda x: x[0], "hangman")
        word, category = pair
    else:
        remember_content("hangman", word)

    HANGMAN_GAMES[chat_id] = {
        "word": word,
        "category": category,
        "guessed": set(),
        "wrong": 0,
        "wrong_letters": [],
    }
    text = (
        f"🔤 حدس کلمه شروع شد! (دسته: {category})\n{render_hangman_word(HANGMAN_GAMES[chat_id])}\n"
        "یک حرف فارسی بفرست، یا کل کلمه رو یکجا حدس بزن 👇"
    )
    try:
        await wait.edit_text(text, reply_markup=skip_kb("hg:reveal"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("hg:reveal"))


async def process_hangman_guess(update, context, raw: str) -> bool:
    chat_id = update.effective_chat.id
    game = HANGMAN_GAMES.get(chat_id)
    if not game or not is_game_enabled("hangman"):
        return False
    user = update.effective_user
    guess = _clean_word(raw)
    if not guess:
        return False

    if len(guess) > 1:
        if _clean_word(game["word"]) == guess:
            remember_user(user)
            await safe_reply(update, context, f"🎉 {user.full_name} کل کلمه رو حدس زد! کلمه «{game['word']}» بود.")
            del HANGMAN_GAMES[chat_id]
            return True
        return False

    letter = guess
    if not re.fullmatch(r"[آاأإءؤئبیپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]", letter):
        return False

    remember_user(user)
    if letter in game["guessed"] or letter in game["wrong_letters"]:
        await safe_reply(update, context, f"حرف «{letter}» رو قبلاً امتحان کردیم.")
        return True

    if letter in game["word"]:
        game["guessed"].add(letter)
        if all(ch in game["guessed"] for ch in game["word"]):
            await safe_reply(update, context, f"🎉 {user.full_name} کلمه رو کامل کرد! کلمه «{game['word']}» بود.")
            del HANGMAN_GAMES[chat_id]
            return True
        await safe_reply(update, context, f"✅ درست بود!\n{render_hangman_word(game)}")
        return True

    game["wrong"] += 1
    game["wrong_letters"].append(letter)
    if game["wrong"] >= len(HANGMAN_STAGES) - 1:
        await safe_reply(update, context, f"{HANGMAN_STAGES[-1]} باختید! کلمه «{game['word']}» بود.")
        del HANGMAN_GAMES[chat_id]
        return True
    stage = HANGMAN_STAGES[game["wrong"]]
    wrong_list = "، ".join(game["wrong_letters"])
    await safe_reply(update, context, f"{stage} غلط بود! (حروف غلط: {wrong_list})\n{render_hangman_word(game)}")
    return True


async def hangman_reveal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = HANGMAN_GAMES.get(chat_id)
    if not game:
        await safe_answer(query, "بازی فعالی نیست.", show_alert=True)
        return
    await safe_answer(query)
    await context.bot.send_message(chat_id, f"🏳️ کلمه لو رفت: «{game['word']}» (دسته: {game['category']})")
    del HANGMAN_GAMES[chat_id]


def render_trivia_keyboard(session_id: str, options: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{TRIVIA_LETTERS[i]}. {opt}", callback_data=f"triv:{session_id}:{i}")]
        for i, opt in enumerate(options)
    ]
    return InlineKeyboardMarkup(rows)


async def start_trivia_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for sid, g in list(TRIVIA_GAMES.items()):
        if g["chat_id"] == chat_id:
            await safe_reply(update, context, "یک کوییز همین الان فعاله، اول اونو جواب بدید.")
            return

    wait = await safe_reply(update, context, "⏳ دارم یه سوال تازه می‌سازم...")
    q = None
    data = await generate_game_json(
        "یک سوال کوییز چهارگزینه‌ای فارسی، غیرتکراری و سطح متوسط بساز. "
        "موضوع تصادفی از تاریخ ایران، علم، سینما، ورزش، جغرافیا، موسیقی یا تکنولوژی. "
        f"{_recent_hint('trivia')} "
        'JSON: {"q":"...","options":["الف","ب","ج","د"],"answer":0,"cat":"علمی"} '
        "answer ایندکس ۰ تا ۳ گزینه درست است."
    )
    if data:
        opts = data.get("options") or []
        try:
            ans = int(data.get("answer"))
        except (TypeError, ValueError):
            ans = -1
        if isinstance(opts, list) and len(opts) == 4 and 0 <= ans <= 3 and data.get("q"):
            q = {
                "q": str(data["q"])[:180],
                "options": [str(o)[:40] for o in opts],
                "answer": ans,
                "cat": str(data.get("cat") or "عمومی")[:20],
            }
            remember_content("trivia", q["q"])

    if not q:
        q = pick_unused(TRIVIA_QUESTIONS, lambda x: x["q"], "trivia")

    session_id = new_session_id()
    TRIVIA_GAMES[session_id] = {"chat_id": chat_id, "question": q, "answered_by": None}
    text = f"🧠 کوییز! (دسته: {q['cat']})\n{q['q']}"
    try:
        await wait.edit_text(text, reply_markup=render_trivia_keyboard(session_id, q["options"]))
    except Exception:
        await safe_reply(update, context, text, reply_markup=render_trivia_keyboard(session_id, q["options"]))


async def trivia_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, idx = query.data.split(":")
    idx = int(idx)
    game = TRIVIA_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این کوییز تموم شده.", show_alert=True)
        return
    if game["answered_by"] is not None:
        await safe_answer(query, "یکی دیگه زودتر جواب داد!", show_alert=True)
        return

    user = update.effective_user
    remember_user(user)
    q = game["question"]

    if idx == q["answer"]:
        game["answered_by"] = user.id
        await safe_answer(query, "درست بود! 🎉")
        correct_option = q["options"][q["answer"]]
        await safe_edit(
            query,
            f"🧠 {q['q']}\n\n✅ جواب درست: {correct_option}\n🏆 {user.full_name} اول جواب داد!",
        )
        del TRIVIA_GAMES[session_id]
    else:
        await safe_answer(query, "غلط بود، یکی دیگه امتحان کنه!", show_alert=True)


def render_wyr_keyboard(session_id: str, game: dict) -> InlineKeyboardMarkup:
    votes_a = sum(1 for v in game["votes"].values() if v == "a")
    votes_b = sum(1 for v in game["votes"].values() if v == "b")
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"1️⃣ {game['option_a']} ({votes_a})", callback_data=f"wyr:{session_id}:a")],
            [InlineKeyboardButton(f"2️⃣ {game['option_b']} ({votes_b})", callback_data=f"wyr:{session_id}:b")],
            [InlineKeyboardButton("🔒 پایان نظرسنجی", callback_data=f"wyr:{session_id}:close")],
        ]
    )


async def start_wyr_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await safe_reply(update, context, "⏳ دارم یه دوراهی تازه می‌سازم...")
    option_a = option_b = None
    data = await generate_game_json(
        "یک سوال «این یا اون» بامزه و کوتاه به فارسی بساز. "
        f"{_recent_hint('wyr')} "
        'JSON: {"a":"...","b":"..."}'
    )
    if data and data.get("a") and data.get("b"):
        option_a, option_b = str(data["a"])[:60], str(data["b"])[:60]
        remember_content("wyr", option_a)
    if not option_a:
        option_a, option_b = pick_unused(WYR_QUESTIONS, lambda x: x[0], "wyr")

    session_id = new_session_id()
    WYR_GAMES[session_id] = {
        "option_a": option_a,
        "option_b": option_b,
        "votes": {},
        "starter": update.effective_user.id,
    }
    text = f"🤔 این یا اون؟\n\n1️⃣ {option_a}\n— یا —\n2️⃣ {option_b}\n\nرأی بده 👇"
    try:
        await wait.edit_text(text, reply_markup=render_wyr_keyboard(session_id, WYR_GAMES[session_id]))
    except Exception:
        await safe_reply(update, context, text, reply_markup=render_wyr_keyboard(session_id, WYR_GAMES[session_id]))


async def wyr_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, choice = query.data.split(":")
    game = WYR_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این نظرسنجی بسته شده.", show_alert=True)
        return
    user = update.effective_user
    remember_user(user)

    if choice == "close":
        if user.id != game["starter"]:
            await safe_answer(query, "فقط کسی که این یا اون رو شروع کرده می‌تونه ببندش.", show_alert=True)
            return
        votes_a = sum(1 for v in game["votes"].values() if v == "a")
        votes_b = sum(1 for v in game["votes"].values() if v == "b")
        await safe_answer(query)
        await safe_edit(
            query,
            f"🤔 این یا اون؟\n\n1️⃣ {game['option_a']} — {votes_a} رأی\n2️⃣ {game['option_b']} — {votes_b} رأی\n\n"
            "✅ نظرسنجی بسته شد.",
        )
        del WYR_GAMES[session_id]
        return

    game["votes"][user.id] = choice
    await safe_answer(query, "رأیت ثبت شد ✅")
    try:
        await query.edit_message_reply_markup(reply_markup=render_wyr_keyboard(session_id, game))
    except BadRequest:
        pass


async def start_emoji_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in EMOJI_GAMES:
        await safe_reply(update, context, f"یک حدس اموجی همین الان فعاله: {EMOJI_GAMES[chat_id]['emojis']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه معمای اموجی تازه می‌سازم...")
    emojis = answer = None
    aliases = []
    data = await generate_game_json(
        "یک معمای حدس اموجی فارسی بساز: ۲ تا ۴ اموجی که یک فیلم، کتاب یا عبارت معروف را نشان بدهد. "
        f"{_recent_hint('emoji')} "
        'JSON: {"emojis":"🦁👑","answer":"شیرشاه","aliases":["شیر شاه"]}'
    )
    if data and data.get("emojis") and data.get("answer"):
        emojis = str(data["emojis"])[:20]
        answer = str(data["answer"])[:40]
        aliases = [str(a) for a in (data.get("aliases") or [])][:6]
        remember_content("emoji", answer)
    if not emojis:
        emojis, answer = pick_unused(EMOJI_RIDDLES, lambda x: x[1], "emoji")
        aliases = []

    EMOJI_GAMES[chat_id] = {"emojis": emojis, "answer": answer, "aliases": aliases}
    text = f"🧩 حدس اموجی!\n\n{emojis}\n\nاسم فیلم/عبارت رو بنویس 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("emj:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("emj:skip"))


def _answer_matches(guess: str, answer: str, aliases=None) -> bool:
    g = _normalize_fa(guess)
    opts = [_normalize_fa(answer)] + [_normalize_fa(a) for a in (aliases or [])]
    return g in opts


async def emoji_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = EMOJI_GAMES.get(chat_id)
    if not game:
        await safe_answer(query, "بازی فعالی نیست.", show_alert=True)
        return
    await safe_answer(query)
    await context.bot.send_message(chat_id, f"⏭️ رد شد! جواب «{game['answer']}» بود.")
    del EMOJI_GAMES[chat_id]


def _new_deck():
    deck = [(r, s) for r in CARD_RANKS for s in CARD_SUITS]
    random.shuffle(deck)
    return deck


def _card_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def _hand_value(hand: list) -> int:
    total = sum(_card_value(r) for r, _ in hand)
    aces = sum(1 for r, _ in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _fmt_hand(hand: list) -> str:
    return " ".join(f"{r}{s}" for r, s in hand)


def render_blackjack_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🃏 بگیر (Hit)", callback_data=f"bj:{session_id}:hit"),
            InlineKeyboardButton("✋ بمون (Stand)", callback_data=f"bj:{session_id}:stand"),
        ]]
    )


async def start_blackjack_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    remember_user(user)
    deck = _new_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    session_id = new_session_id()
    BLACKJACK_GAMES[session_id] = {
        "player_id": user.id,
        "player_name": user.full_name,
        "deck": deck,
        "player_hand": player_hand,
        "dealer_hand": dealer_hand,
    }

    if _hand_value(player_hand) == 21:
        await safe_reply(
            update,
            context,
            f"🃏 بلک‌جک برای {user.full_name}!\nدست تو: {_fmt_hand(player_hand)} (21) 🎉\nدست دیلر: {_fmt_hand(dealer_hand)}\n\n🏆 بردی!",
        )
        del BLACKJACK_GAMES[session_id]
        return

    await safe_reply(
        update,
        context,
        f"🃏 بلک‌جک شروع شد، {user.full_name}!\n"
        f"دست تو: {_fmt_hand(player_hand)} ({_hand_value(player_hand)})\n"
        f"دست دیلر: {dealer_hand[0][0]}{dealer_hand[0][1]} 🂠",
        reply_markup=render_blackjack_keyboard(session_id),
    )


async def blackjack_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, action = query.data.split(":")
    game = BLACKJACK_GAMES.get(session_id)
    if not game:
        await safe_answer(query, "این بازی تموم شده.", show_alert=True)
        return
    user = update.effective_user
    if user.id != game["player_id"]:
        await safe_answer(query, "این بازی برای شما نیست.", show_alert=True)
        return

    await safe_answer(query)

    if action == "hit":
        if not game["deck"]:
            game["deck"] = _new_deck()
        game["player_hand"].append(game["deck"].pop())
        value = _hand_value(game["player_hand"])
        if value > 21:
            await safe_edit(
                query,
                f"🃏 دست تو: {_fmt_hand(game['player_hand'])} ({value})\n\n💥 باختی! (بیشتر از ۲۱ شد)",
            )
            del BLACKJACK_GAMES[session_id]
            return
        if value == 21:
            action = "stand"
        else:
            await safe_edit(
                query,
                f"🃏 دست تو: {_fmt_hand(game['player_hand'])} ({value})\n"
                f"دست دیلر: {game['dealer_hand'][0][0]}{game['dealer_hand'][0][1]} 🂠",
                reply_markup=render_blackjack_keyboard(session_id),
            )
            return

    dealer_hand = game["dealer_hand"]
    while _hand_value(dealer_hand) < 17:
        if not game["deck"]:
            game["deck"] = _new_deck()
        dealer_hand.append(game["deck"].pop())

    player_value = _hand_value(game["player_hand"])
    dealer_value = _hand_value(dealer_hand)

    if dealer_value > 21 or player_value > dealer_value:
        outcome = f"🏆 {game['player_name']} برد!"
    elif player_value == dealer_value:
        outcome = "🤝 مساوی شد!"
    else:
        outcome = "💀 دیلر برد."

    await safe_edit(
        query,
        f"🃏 دست تو: {_fmt_hand(game['player_hand'])} ({player_value})\n"
        f"دست دیلر: {_fmt_hand(dealer_hand)} ({dealer_value})\n\n{outcome}",
    )
    del BLACKJACK_GAMES[session_id]


def _scramble(word: str) -> str:
    letters = list(word)
    for _ in range(8):
        random.shuffle(letters)
        if "".join(letters) != word:
            break
    return " ".join(letters)


async def start_scramble_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in SCRAMBLE_GAMES:
        await safe_reply(update, context, f"یک حروف به‌هم‌ریخته فعاله: {SCRAMBLE_GAMES[chat_id]['shown']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه کلمه قاطی می‌کنم...")
    word, hint = None, None
    data = await generate_game_json(
        "یک کلمه‌ی فارسی یک‌تکه ۴ تا ۸ حرف برای بازی حروف به‌هم‌ریخته بساز. "
        f"{_recent_hint('scramble')} "
        'JSON: {"word":"گیتار","hint":"ساز"}'
    )
    if data:
        cand = _clean_word(str(data.get("word") or ""))
        if 3 <= len(cand) <= 10:
            word, hint = cand, str(data.get("hint") or "عمومی")[:20]
            remember_content("scramble", word)
    if not word:
        word, hint = pick_unused(HANGMAN_WORDS, lambda x: x[0], "scramble")
    shown = _scramble(word)
    SCRAMBLE_GAMES[chat_id] = {"word": word, "shown": shown, "hint": hint}
    text = f"🔀 حروف به‌هم‌ریخته! (راهنما: {hint})\n\n{shown}\n\nکلمه درست رو بنویس 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("scr:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("scr:skip"))


async def start_riddle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in RIDDLE_GAMES:
        await safe_reply(update, context, f"یک چیستان فعاله:\n{RIDDLE_GAMES[chat_id]['q']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه چیستان تازه می‌سازم...")
    q = answer = None
    aliases = []
    data = await generate_game_json(
        "یک چیستان کوتاه و مناسب گروه به فارسی بساز. جواب یک کلمه‌ای باشد. "
        f"{_recent_hint('riddle')} "
        'JSON: {"q":"...","answer":"...","aliases":["..."]}'
    )
    if data and data.get("q") and data.get("answer"):
        q, answer = str(data["q"])[:200], str(data["answer"])[:40]
        aliases = [str(a) for a in (data.get("aliases") or [])][:6]
        remember_content("riddle", answer)
    if not q:
        q, answer, aliases = pick_unused(RIDDLES_BANK, lambda x: x[1], "riddle")
    RIDDLE_GAMES[chat_id] = {"q": q, "answer": answer, "aliases": aliases}
    text = f"❓ چیستان!\n\n{q}\n\nجواب رو بنویس 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("rid:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("rid:skip"))


async def start_typerace_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in TYPERACE_GAMES:
        await safe_reply(update, context, f"یک تایپ سریع فعاله:\n{TYPERACE_GAMES[chat_id]['phrase']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه جمله تازه می‌سازم...")
    phrase = None
    data = await generate_game_json(
        "یک جمله‌ی کوتاه فارسی ۴ تا ۸ کلمه، ساده و بدون علائم عجیب برای مسابقه تایپ بساز. "
        f"{_recent_hint('typerace')} "
        'JSON: {"phrase":"..."}'
    )
    if data and data.get("phrase"):
        phrase = re.sub(r"\s+", " ", str(data["phrase"])).strip()[:60]
        remember_content("typerace", phrase)
    if not phrase:
        phrase = pick_unused(TYPERACE_PHRASES, lambda x: x, "typerace")
    TYPERACE_GAMES[chat_id] = {"phrase": phrase}
    text = f"⌨️ تایپ سریع!\nاولین نفری که دقیقاً همین جمله رو بفرسته می‌بره:\n\n{phrase}"
    try:
        await wait.edit_text(text)
    except Exception:
        await safe_reply(update, context, text)


async def start_flag_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in FLAG_GAMES:
        await safe_reply(update, context, f"یک حدس پرچم فعاله: {FLAG_GAMES[chat_id]['flag']}")
        return
    flag, country = pick_unused(FLAG_RIDDLES, lambda x: x[1], "flag")
    FLAG_GAMES[chat_id] = {"flag": flag, "answer": country}
    await safe_reply(
        update,
        context,
        f"🚩 حدس پرچم!\n\n{flag}\n\nاسم کشور رو بنویس 👇",
        reply_markup=skip_kb("flg:skip"),
    )


async def start_chain_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in CHAIN_GAMES:
        g = CHAIN_GAMES[chat_id]
        await safe_reply(update, context, f"زنجیره فعاله. آخرین کلمه: {g['last']} — بعدی با «{g['need']}»")
        return
    start = random.choice(["سیب", "دریا", "کتاب", "ماه", "گل", "خانه", "دوست", "بازی"])
    need = _clean_word(start)[-1]
    CHAIN_GAMES[chat_id] = {"last": start, "need": need, "used": {_clean_word(start)}, "count": 0}
    await safe_reply(
        update,
        context,
        f"🔗 زنجیره کلمات شروع شد!\nکلمه اول: {start}\nکلمه بعدی باید با «{need}» شروع بشه.\n"
        "هر کسی می‌تونه جواب بده. کلمات تکراری قبول نیست.",
        reply_markup=skip_kb("chn:skip"),
    )


async def start_proverb_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in PROVERB_GAMES:
        await safe_reply(update, context, f"یک ضرب‌المثل فعاله:\n{PROVERB_GAMES[chat_id]['hint']} ...")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه ضرب‌المثل تازه می‌چینم...")
    full = hint = ending = None
    data = await generate_game_json(
        "یک ضرب‌المثل معروف فارسی را نصف کن. "
        f"{_recent_hint('proverb')} "
        'JSON: {"full":"...","hint":"نیمه اول","ending":"نیمه دوم"}'
    )
    if data and data.get("full") and data.get("hint") and data.get("ending"):
        full, hint, ending = str(data["full"]), str(data["hint"]), str(data["ending"])
        remember_content("proverb", full)
    if not full:
        full, hint, ending = pick_unused(PROVERBS, lambda x: x[0], "proverb")
    PROVERB_GAMES[chat_id] = {"full": full, "hint": hint, "ending": ending}
    text = f"📜 ضرب‌المثل!\n\n{hint} ...\n\nادامه‌ش رو بنویس 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("prv:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("prv:skip"))


async def start_memory_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in MEMORY_GAMES:
        await safe_reply(update, context, "یک بازی حافظه همین الان فعاله.")
        return
    seq = random.sample(MEMORY_EMOJIS, 5)
    msg = await safe_reply(update, context, "🧠 حافظه! اینارو ۵ ثانیه به خاطر بسپار:\n\n" + " ".join(seq))
    MEMORY_GAMES[chat_id] = {"seq": seq, "shown": True, "target": " ".join(seq)}
    await asyncio.sleep(5)
    game = MEMORY_GAMES.get(chat_id)
    if not game or not game.get("shown"):
        return
    game["shown"] = False
    hidden = "الان همون اموجی‌ها رو با فاصله و به همون ترتیب بنویس 👇"
    try:
        await msg.edit_text(f"🧠 حافظه!\n\n{hidden}", reply_markup=skip_kb("mem:skip"))
    except Exception:
        await context.bot.send_message(chat_id, f"🧠 حافظه!\n\n{hidden}", reply_markup=skip_kb("mem:skip"))


async def start_color_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for sid, g in list(COLOR_GAMES.items()):
        if g["chat_id"] == chat_id:
            await safe_reply(update, context, "یک رنگ سریع همین الان فعاله.")
            return
    target = random.choice(COLOR_CHOICES)
    buttons = COLOR_CHOICES[:]
    random.shuffle(buttons)
    session_id = new_session_id()
    COLOR_GAMES[session_id] = {"chat_id": chat_id, "target": target[0], "winner": None}
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"{emo} {name}", callback_data=f"clr:{session_id}:{name}")] for name, emo in buttons]
    )
    await safe_reply(update, context, f"🎨 رنگ سریع!\nاولین نفری که دکمه «{target[0]}» رو بزنه می‌بره!", reply_markup=kb)


async def color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, name = query.data.split(":")
    game = COLOR_GAMES.get(session_id)
    if not game or game.get("winner"):
        await safe_answer(query, "این دور تموم شده.", show_alert=True)
        return
    if name != game["target"]:
        await safe_answer(query, "غلط بود! رنگ درست رو بزن.", show_alert=True)
        return
    user = update.effective_user
    remember_user(user)
    game["winner"] = user.id
    await safe_answer(query, "درست بود!")
    await safe_edit(query, f"🎨 رنگ «{game['target']}»!\n🏆 {user.full_name} اول زد!")
    del COLOR_GAMES[session_id]


async def start_category_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in CATEGORY_GAMES:
        await safe_reply(update, context, f"یک کلمه در دسته فعاله: {CATEGORY_GAMES[chat_id]['category']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه دسته تازه می‌سازم...")
    category, accepted = None, []
    data = await generate_game_json(
        "یک دسته ساده فارسی برای بازی گروهی بساز و حداقل ۱۲ جواب درست کوتاه بده. "
        f"{_recent_hint('category')} "
        'JSON: {"category":"میوه","accepted":["سیب","موز"]}'
    )
    if data and data.get("category") and isinstance(data.get("accepted"), list):
        category = str(data["category"])[:30]
        accepted = [_clean_word(str(a)) for a in data["accepted"] if _clean_word(str(a))]
        remember_content("category", category)
    if not category or len(accepted) < 4:
        item = pick_unused(CATEGORY_BANK, lambda x: x["category"], "category")
        category, accepted = item["category"], [_clean_word(a) for a in item["accepted"]]
    CATEGORY_GAMES[chat_id] = {"category": category, "accepted": set(accepted), "used": set()}
    text = f"📦 کلمه در دسته!\nاولین نفری که یه «{category}» بنویسه می‌بره 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("cat:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("cat:skip"))


async def start_whoami_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in WHOAMI_GAMES:
        g = WHOAMI_GAMES[chat_id]
        shown = " / ".join(g["clues"][: g["shown"]])
        await safe_reply(update, context, f"یک «کی هستم» فعاله:\n{shown}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه شخصیت تازه می‌سازم...")
    item = None
    data = await generate_game_json(
        "یک شخصیت معروف (ایرانی یا جهانی) برای بازی کی‌هستم بساز. سه سرنخ از آسان به سخت نده؛ از مبهم به واضح. "
        f"{_recent_hint('whoami')} "
        'JSON: {"name":"...","aliases":["..."],"clues":["سرنخ1","سرنخ2","سرنخ3"]}'
    )
    if data and data.get("name") and isinstance(data.get("clues"), list) and len(data["clues"]) >= 2:
        item = {
            "name": str(data["name"])[:40],
            "aliases": [str(a) for a in (data.get("aliases") or [])][:6],
            "clues": [str(c)[:80] for c in data["clues"][:4]],
        }
        remember_content("whoami", item["name"])
    if not item:
        item = pick_unused(WHOAMI_BANK, lambda x: x["name"], "whoami")
    WHOAMI_GAMES[chat_id] = {**item, "shown": 1}
    text = f"🕵️ کی هستم؟\nسرنخ ۱: {item['clues'][0]}\n\nاسم را بنویس، یا سرنخ بعدی را بگیر."
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💡 سرنخ بعدی", callback_data="who:hint")],
            [InlineKeyboardButton("⏭️ لو دادن", callback_data="who:skip")],
        ]
    )
    try:
        await wait.edit_text(text, reply_markup=kb)
    except Exception:
        await safe_reply(update, context, text, reply_markup=kb)


async def whoami_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = WHOAMI_GAMES.get(chat_id)
    if not game:
        await safe_answer(query, "بازی فعالی نیست.", show_alert=True)
        return
    action = query.data.split(":")[1]
    if action == "skip":
        await safe_answer(query)
        await context.bot.send_message(chat_id, f"⏭️ لو رفت! جواب «{game['name']}» بود.")
        del WHOAMI_GAMES[chat_id]
        return
    if game["shown"] >= len(game["clues"]):
        await safe_answer(query, "سرنخ دیگری نمانده.", show_alert=True)
        return
    game["shown"] += 1
    clues = "\n".join(f"سرنخ {i+1}: {c}" for i, c in enumerate(game["clues"][: game["shown"]]))
    await safe_answer(query)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💡 سرنخ بعدی", callback_data="who:hint")],
            [InlineKeyboardButton("⏭️ لو دادن", callback_data="who:skip")],
        ]
    )
    await safe_edit(query, f"🕵️ کی هستم؟\n{clues}\n\nاسم را بنویس 👇", reply_markup=kb)


async def start_oddone_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for g in ODDONE_GAMES.values():
        if g["chat_id"] == chat_id:
            await safe_reply(update, context, "یک گزینه ناجور همین الان فعاله.")
            return
    wait = await safe_reply(update, context, "⏳ دارم گزینه‌ها را می‌چینم...")
    item = None
    data = await generate_game_json(
        "چهار گزینه فارسی بساز که یکی از آن‌ها با بقیه فرق داشته باشد. "
        f"{_recent_hint('oddone')} "
        'JSON: {"options":["الف","ب","ج","د"],"odd":2,"why":"چرا"} odd ایندکس ۰ تا ۳ است.'
    )
    if data and isinstance(data.get("options"), list) and len(data["options"]) == 4:
        try:
            odd = int(data.get("odd"))
        except (TypeError, ValueError):
            odd = -1
        if 0 <= odd <= 3:
            item = {
                "options": [str(o)[:30] for o in data["options"]],
                "odd": odd,
                "why": str(data.get("why") or "")[:80],
            }
            remember_content("oddone", item["options"][odd])
    if not item:
        item = pick_unused(ODD_BANK, lambda x: "|".join(x["options"]), "oddone")
    session_id = new_session_id()
    ODDONE_GAMES[session_id] = {"chat_id": chat_id, **item, "winner": None}
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(opt, callback_data=f"odd:{session_id}:{i}")] for i, opt in enumerate(item["options"])]
    )
    text = "🚫 گزینه ناجور!\nکدام یکی با بقیه فرق دارد؟"
    try:
        await wait.edit_text(text, reply_markup=kb)
    except Exception:
        await safe_reply(update, context, text, reply_markup=kb)


async def oddone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, idx = query.data.split(":")
    idx = int(idx)
    game = ODDONE_GAMES.get(session_id)
    if not game or game.get("winner"):
        await safe_answer(query, "این دور تموم شده.", show_alert=True)
        return
    if idx != game["odd"]:
        await safe_answer(query, "این یکی ناجور نیست!", show_alert=True)
        return
    user = update.effective_user
    remember_user(user)
    game["winner"] = user.id
    why = f"\n{game['why']}" if game.get("why") else ""
    await safe_answer(query, "درست بود!")
    await safe_edit(query, f"🚫 گزینه ناجور: «{game['options'][game['odd']]}»{why}\n🏆 {user.full_name}")
    del ODDONE_GAMES[session_id]


async def start_quote_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in QUOTE_GAMES:
        await safe_reply(update, context, f"یک حدس فیلم فعاله:\n«{QUOTE_GAMES[chat_id]['quote']}»")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه دیالوگ تازه می‌آورم...")
    quote = answer = None
    aliases = []
    data = await generate_game_json(
        "یک دیالوگ کوتاه معروف از فیلم یا انیمیشن بساز که برای ایرانی‌ها آشنا باشد. "
        f"{_recent_hint('quote')} "
        'JSON: {"quote":"...","answer":"نام فیلم","aliases":["..."]}'
    )
    if data and data.get("quote") and data.get("answer"):
        quote, answer = str(data["quote"])[:160], str(data["answer"])[:40]
        aliases = [str(a) for a in (data.get("aliases") or [])][:6]
        remember_content("quote", answer)
    if not quote:
        quote, answer, aliases = pick_unused(QUOTE_BANK, lambda x: x[1], "quote")
    QUOTE_GAMES[chat_id] = {"quote": quote, "answer": answer, "aliases": aliases}
    text = f"🎬 حدس فیلم!\n\n«{quote}»\n\nاسم فیلم را بنویس 👇"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("quo:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("quo:skip"))


async def start_year_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in YEAR_GAMES:
        await safe_reply(update, context, f"یک حدس سال فعاله: {YEAR_GAMES[chat_id]['q']}")
        return
    wait = await safe_reply(update, context, "⏳ دارم یه رویداد تازه می‌آورم...")
    item = None
    data = await generate_game_json(
        "یک رویداد معروف تاریخی یا ورزشی با سال میلادی درست بساز. "
        f"{_recent_hint('year')} "
        'JSON: {"q":"فرود انسان روی ماه","year":1969}'
    )
    if data and data.get("q"):
        try:
            year = int(data.get("year"))
        except (TypeError, ValueError):
            year = 0
        if 1000 <= year <= 2100:
            item = {"q": str(data["q"])[:120], "year": year}
            remember_content("year", item["q"])
    if not item:
        item = pick_unused(YEAR_BANK, lambda x: x["q"], "year")
    YEAR_GAMES[chat_id] = item
    text = f"📅 حدس سال!\n{item['q']} در چه سالی بود؟\n(فقط عدد سال را بفرست)"
    try:
        await wait.edit_text(text, reply_markup=skip_kb("yea:skip"))
    except Exception:
        await safe_reply(update, context, text, reply_markup=skip_kb("yea:skip"))


async def start_codes_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in CODE_GAMES:
        await safe_reply(update, context, f"یک کد سریع فعاله: `{CODE_GAMES[chat_id]['code']}`")
        return
    code = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    CODE_GAMES[chat_id] = {"code": code}
    await safe_reply(update, context, f"⚡ کد سریع!\nاولین نفری که دقیقاً این را بفرستد می‌برد:\n\n{code}")


async def start_lie_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for g in LIE_GAMES.values():
        if g["chat_id"] == chat_id:
            await safe_reply(update, context, "یک «دروغه کدومه» فعاله.")
            return
    wait = await safe_reply(update, context, "⏳ دارم دو حقیقت و یک دروغ می‌سازم...")
    item = None
    data = await generate_game_json(
        "سه جمله کوتاه فارسی بساز: دو تا درست، یکی غلط. مشخص کن کدام دروغ است. "
        f"{_recent_hint('lie')} "
        'JSON: {"a":"...","b":"...","c":"...","lie":"b"} lie یکی از a یا b یا c است.'
    )
    if data and data.get("a") and data.get("b") and data.get("c") and str(data.get("lie", "")).lower() in ("a", "b", "c"):
        item = {
            "a": str(data["a"])[:90],
            "b": str(data["b"])[:90],
            "c": str(data["c"])[:90],
            "lie": str(data["lie"]).lower(),
        }
        remember_content("lie", item["a"])
    if not item:
        item = pick_unused(LIE_BANK, lambda x: x["a"], "lie")
    session_id = new_session_id()
    LIE_GAMES[session_id] = {"chat_id": chat_id, **item, "winner": None}
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"A) {item['a']}", callback_data=f"lie:{session_id}:a")],
            [InlineKeyboardButton(f"B) {item['b']}", callback_data=f"lie:{session_id}:b")],
            [InlineKeyboardButton(f"C) {item['c']}", callback_data=f"lie:{session_id}:c")],
        ]
    )
    text = "🤥 دروغه کدومه؟\nروی جمله‌ی غلط بزن."
    try:
        await wait.edit_text(text, reply_markup=kb)
    except Exception:
        await safe_reply(update, context, text, reply_markup=kb)


async def lie_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, session_id, choice = query.data.split(":")
    game = LIE_GAMES.get(session_id)
    if not game or game.get("winner"):
        await safe_answer(query, "این دور تموم شده.", show_alert=True)
        return
    if choice != game["lie"]:
        await safe_answer(query, "این یکی دروغ نیست!", show_alert=True)
        return
    user = update.effective_user
    remember_user(user)
    game["winner"] = user.id
    lie_text = game[game["lie"]]
    await safe_answer(query, "درست بود!")
    await safe_edit(query, f"🤥 دروغ این بود:\n«{lie_text}»\n🏆 {user.full_name}")
    del LIE_GAMES[session_id]


async def generic_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = update.effective_chat.id
    mapping = {
        "scr:skip": (SCRAMBLE_GAMES, "word", "حروف به‌هم‌ریخته"),
        "rid:skip": (RIDDLE_GAMES, "answer", "چیستان"),
        "flg:skip": (FLAG_GAMES, "answer", "پرچم"),
        "chn:skip": (CHAIN_GAMES, "last", "زنجیره"),
        "prv:skip": (PROVERB_GAMES, "full", "ضرب‌المثل"),
        "mem:skip": (MEMORY_GAMES, "target", "حافظه"),
        "cat:skip": (CATEGORY_GAMES, "category", "دسته"),
        "quo:skip": (QUOTE_GAMES, "answer", "حدس فیلم"),
        "yea:skip": (YEAR_GAMES, "year", "حدس سال"),
    }
    info = mapping.get(data)
    if not info:
        await safe_answer(query)
        return
    store, field, title = info
    game = store.get(chat_id)
    if not game:
        await safe_answer(query, "بازی فعالی نیست.", show_alert=True)
        return
    await safe_answer(query)
    await context.bot.send_message(chat_id, f"⏭️ {title} رد شد. جواب: «{game.get(field, '')}»")
    del store[chat_id]


def _match_any(guess: str, *answers) -> bool:
    g = _normalize_fa(guess)
    return any(g == _normalize_fa(a) or _clean_word(g) == _clean_word(a) for a in answers if a)


async def active_game_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not in_linked_group(chat.id):
        return
    raw = (update.message.text or "").strip()
    if not raw or raw in TRIGGER_TO_GAME:
        return
    user = update.effective_user
    chat_id = chat.id
    value = parse_int(raw)

    if value is not None:
        math_game = MATH_GAMES.get(chat_id)
        if math_game is not None and is_game_enabled("math"):
            remember_user(user)
            if value == math_game["answer"]:
                await safe_reply(
                    update,
                    context,
                    f"🎉 {user.full_name} درست جواب داد! {math_game['question']} = {math_game['answer']}",
                )
                del MATH_GAMES[chat_id]
                raise ApplicationHandlerStop
        year_game = YEAR_GAMES.get(chat_id)
        if year_game and is_game_enabled("year") and value >= 1000:
            remember_user(user)
            if value == year_game["year"]:
                await safe_reply(update, context, f"📅 {user.full_name} درست گفت! سال {year_game['year']} بود.")
                del YEAR_GAMES[chat_id]
            elif value < year_game["year"]:
                await safe_reply(update, context, "⬆️ دیرتر / بزرگ‌تره!")
            else:
                await safe_reply(update, context, "⬇️ زودتر / کوچیک‌تره!")
            raise ApplicationHandlerStop
        guess_game = GUESS_GAMES.get(chat_id)
        if guess_game and is_game_enabled("guess"):
            remember_user(user)
            if value == guess_game["number"]:
                await safe_reply(update, context, f"🎉 {user.full_name} درست حدس زد! عدد {guess_game['number']} بود.")
                del GUESS_GAMES[chat_id]
            elif value < guess_game["number"]:
                await safe_reply(update, context, "⬆️ بزرگ‌تره!")
            else:
                await safe_reply(update, context, "⬇️ کوچیک‌تره!")
            raise ApplicationHandlerStop

    if await process_hangman_guess(update, context, raw):
        raise ApplicationHandlerStop

    if chat_id in TYPERACE_GAMES and is_game_enabled("typerace"):
        if _normalize_fa(raw) == _normalize_fa(TYPERACE_GAMES[chat_id]["phrase"]):
            remember_user(user)
            await safe_reply(update, context, f"⌨️ {user.full_name} سریع‌ترین بود!")
            del TYPERACE_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in MEMORY_GAMES and is_game_enabled("memory") and not MEMORY_GAMES[chat_id].get("shown"):
        target = MEMORY_GAMES[chat_id]["target"]
        compact = raw.replace(" ", "")
        if raw == target or compact == target.replace(" ", ""):
            remember_user(user)
            await safe_reply(update, context, f"🧠 {user.full_name} ترتیب رو درست نوشت! {target}")
            del MEMORY_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in SCRAMBLE_GAMES and is_game_enabled("scramble"):
        if _clean_word(raw) == _clean_word(SCRAMBLE_GAMES[chat_id]["word"]):
            remember_user(user)
            await safe_reply(update, context, f"🔀 {user.full_name} درست گفت! کلمه «{SCRAMBLE_GAMES[chat_id]['word']}» بود.")
            del SCRAMBLE_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in RIDDLE_GAMES and is_game_enabled("riddle"):
        g = RIDDLE_GAMES[chat_id]
        if _answer_matches(raw, g["answer"], g.get("aliases")):
            remember_user(user)
            await safe_reply(update, context, f"❓ {user.full_name} چیستان رو حل کرد! جواب «{g['answer']}» بود.")
            del RIDDLE_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in FLAG_GAMES and is_game_enabled("flag"):
        if _answer_matches(raw, FLAG_GAMES[chat_id]["answer"]):
            remember_user(user)
            await safe_reply(update, context, f"🚩 {user.full_name} درست گفت! {FLAG_GAMES[chat_id]['answer']}")
            del FLAG_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in PROVERB_GAMES and is_game_enabled("proverb"):
        g = PROVERB_GAMES[chat_id]
        if _match_any(raw, g["ending"], g["full"]) or _clean_word(raw) in (_clean_word(g["ending"]), _clean_word(g["full"])):
            remember_user(user)
            await safe_reply(update, context, f"📜 {user.full_name} درست گفت!\n{g['full']}")
            del PROVERB_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in CATEGORY_GAMES and is_game_enabled("category"):
        g = CATEGORY_GAMES[chat_id]
        word = _clean_word(raw)
        if word in g["accepted"] and word not in g["used"]:
            remember_user(user)
            await safe_reply(update, context, f"📦 {user.full_name} برد! «{raw}» یه {g['category']} بود.")
            del CATEGORY_GAMES[chat_id]
            raise ApplicationHandlerStop

    if chat_id in CHAIN_GAMES and is_game_enabled("chain"):
        g = CHAIN_GAMES[chat_id]
        word = _clean_word(raw)
        if len(word) >= 2 and word.startswith(g["need"]) and word not in g["used"]:
            remember_user(user)
            g["used"].add(word)
            g["last"] = raw.strip()
            g["need"] = word[-1]
            g["count"] += 1
            await safe_reply(
                update,
                context,
                f"🔗 {user.full_name}: {raw.strip()} ✅\nبعدی با «{g['need']}» شروع بشه.",
            )
            raise ApplicationHandlerStop

    if chat_id in EMOJI_GAMES and is_game_enabled("emoji"):
        g = EMOJI_GAMES[chat_id]
        if _answer_matches(raw, g["answer"], g.get("aliases")):
            remember_user(user)
            await safe_reply(update, context, f"🎉 {user.full_name} درست حدس زد! جواب «{g['answer']}» بود.")
            del EMOJI_GAMES[chat_id]
            raise ApplicationHandlerStop


# ============================================================================
# چت هوش مصنوعی
# ============================================================================


async def ai_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not in_linked_group(chat.id):
        return
    if not is_ai_enabled():
        return
    replied = update.message.reply_to_message
    if not replied or not replied.from_user or not replied.from_user.is_bot:
        return
    if replied.from_user.id != context.bot.id:
        return

    user = update.effective_user
    remember_user(user)
    now = time.time()

    group_last = AI_GROUP_LAST_USED.get(chat.id, 0)
    if now - group_last < AI_GROUP_COOLDOWN_SECONDS:
        return

    last = AI_LAST_USED.get(user.id, 0)
    if now - last < AI_RATE_LIMIT_SECONDS:
        wait = int(AI_RATE_LIMIT_SECONDS - (now - last))
        await safe_reply(update, context, f"⏳ لطفاً {wait} ثانیه صبر کن و دوباره امتحان کن.")
        return
    AI_LAST_USED[user.id] = now
    AI_GROUP_LAST_USED[chat.id] = now

    system_prompt = get_ai_system_prompt()
    story = get_story(user.id)
    if story:
        system_prompt += (
            f"\n\nاین کاربر که داری باهاش صحبت می‌کنی داستان زیر رو داره؛ اول اون رو در نظر بگیر و "
            f"طبق شخصیت و داستانش باهاش هم‌صحبت شو:\n{story}"
        )

    history = AI_HISTORY.setdefault(user.id, [])
    user_text = update.message.text

    await context.bot.send_chat_action(chat.id, "typing")
    answer, used_model = await ask_groq(
        system_prompt,
        history,
        user_text,
        models=[GROQ_CHAT_MODEL, GROQ_GAME_MODEL],
    )

    if answer is None:
        await safe_reply(update, context, "الان نتونستم به هوش مصنوعی وصل بشم، یکم بعد دوباره امتحان کن. 🙏")
        return

    history.append({"role": "user", "text": user_text})
    history.append({"role": "model", "text": answer})
    AI_HISTORY[user.id] = history[-16:]
    await safe_reply(update, context, answer)


# ============================================================================
# راه‌اندازی
# ============================================================================


def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise SystemExit("توکن ربات (BOT_TOKEN) درست تنظیم نشده.")
    if not GROQ_API_KEYS:
        logger.warning("هیچ کلید گراکی تنظیم نشده.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.Regex(rf"^{ADMIN_PASSCODE}$"), private_passcode)
    )
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_text_router)
    )

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_TITLE, on_new_chat_title))

    trigger_pattern = "^(" + "|".join(re.escape(t) for t in TRIGGER_TO_GAME) + ")$"
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.Regex(trigger_pattern), game_trigger_handler)
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            active_game_text_handler,
        )
    )
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.REPLY & filters.TEXT & ~filters.COMMAND, ai_reply_handler)
    )

    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(group_callbacks, pattern=r"^grp:"))
    app.add_handler(CallbackQueryHandler(game_join_callback, pattern=r"^join:"))
    app.add_handler(CallbackQueryHandler(ttt_move_callback, pattern=r"^ttt:"))
    app.add_handler(CallbackQueryHandler(rps_choice_callback, pattern=r"^rps:"))
    app.add_handler(CallbackQueryHandler(dice_duel_callback, pattern=r"^dd:"))
    app.add_handler(CallbackQueryHandler(hangman_reveal_callback, pattern=r"^hg:"))
    app.add_handler(CallbackQueryHandler(trivia_answer_callback, pattern=r"^triv:"))
    app.add_handler(CallbackQueryHandler(wyr_vote_callback, pattern=r"^wyr:"))
    app.add_handler(CallbackQueryHandler(emoji_skip_callback, pattern=r"^emj:"))
    app.add_handler(CallbackQueryHandler(blackjack_action_callback, pattern=r"^bj:"))
    app.add_handler(CallbackQueryHandler(color_callback, pattern=r"^clr:"))
    app.add_handler(CallbackQueryHandler(whoami_callback, pattern=r"^who:"))
    app.add_handler(CallbackQueryHandler(oddone_callback, pattern=r"^odd:"))
    app.add_handler(CallbackQueryHandler(lie_callback, pattern=r"^lie:"))
    app.add_handler(CallbackQueryHandler(generic_skip_callback, pattern=r"^(scr|rid|flg|chn|prv|mem|cat|quo|yea):"))

    logger.info("Bot starting with %s Groq keys...", len(GROQ_API_KEYS))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
