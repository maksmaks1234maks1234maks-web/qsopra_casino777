import re
import time
import sqlite3
import random
import asyncio
import os
import sys
import subprocess
from datetime import datetime, timedelta

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, KeyboardButton, ChatMember)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ChatMemberHandler, filters, ContextTypes)

# ═══════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════
TOKEN = os.getenv('BOT_TOKEN', '8250039974:AAFXzVwyYXmymzZzBHDIQECfIvhsSr5Xu6M').strip()
MAIN_ADMIN = os.getenv('MAIN_ADMIN', 'QSOPRA_baby').strip().lstrip('@')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '0') or 0)

# Бонус за вход в указанные чаты (один раз на игрока)
JOIN_BONUS_BALANCE = 600_000_000   # 600 млн
JOIN_BONUS_CRYSTALS = 1000
# Публичные username чатов (без @), нижний регистр
JOIN_CHAT_USERNAMES = {
    'neuro1cgd',  # https://t.me/Neuro1CGD
}
# Числовые ID чатов (для приватных ссылок вроде https://t.me/+0ZgFnxFQOpkzODgy)
# Можно задать через env: JOIN_CHAT_IDS=-100123,-100456
# Или командой владельца в нужном чате: чатбонус
def _parse_join_chat_ids():
    raw = os.getenv('JOIN_CHAT_IDS', '').strip()
    ids = set()
    if raw:
        for part in raw.split(','):
            part = part.strip()
            if part.lstrip('-').isdigit():
                ids.add(int(part))
    return ids
JOIN_CHAT_IDS = _parse_join_chat_ids()

# Донат через Boosty (реальные ₽). Ссылку можно задать env BOOSTY_URL
BOOSTY_URL = os.getenv('BOOSTY_URL', 'https://boosty.to/qsopra').strip()
# Пакеты доната (цена в реальных рублях на Boosty)
DONAT_ITEMS = {
    'starter': {
        'name': 'Стартовый пак',
        'emoji': '🎁',
        'price_rub': 49,
        'desc': '5 млрд ₽ + 200💎',
        'coins': 5_000_000_000, 'crystals': 200, 'vip': 0, 'energy_full': False, 'title': '',
    },
    'coins_s': {
        'name': 'Мешок монет',
        'emoji': '💰',
        'price_rub': 79,
        'desc': '15 млрд ₽ + 100💎',
        'coins': 15_000_000_000, 'crystals': 100, 'vip': 0, 'energy_full': False, 'title': '',
    },
    'gems': {
        'name': 'Кристаллы',
        'emoji': '💎',
        'price_rub': 99,
        'desc': '3 млрд ₽ + 1 000💎',
        'coins': 3_000_000_000, 'crystals': 1000, 'vip': 0, 'energy_full': False, 'title': '',
    },
    'energy': {
        'name': 'Заряд энергии',
        'emoji': '⚡',
        'price_rub': 69,
        'desc': 'Полная ⚡ + 8 млрд ₽ + 150💎',
        'coins': 8_000_000_000, 'crystals': 150, 'vip': 0, 'energy_full': True, 'title': '',
    },
    'donor': {
        'name': 'Титул Донатер',
        'emoji': '💜',
        'price_rub': 89,
        'desc': 'Титул «Донатер» + 12 млрд ₽ + 300💎',
        'coins': 12_000_000_000, 'crystals': 300, 'vip': 0, 'energy_full': False, 'title': 'donor',
    },
    'combo': {
        'name': 'Комбо',
        'emoji': '✨',
        'price_rub': 149,
        'desc': '40 млрд ₽ + 500💎 + VIP Бронза + ⚡',
        'coins': 40_000_000_000, 'crystals': 500, 'vip': 1, 'energy_full': True, 'title': '',
    },
    'vip_gold': {
        'name': 'VIP Золото',
        'emoji': '🥇',
        'price_rub': 199,
        'desc': 'VIP Золото + 100 млрд ₽ + 1 000💎 + ⚡',
        'coins': 100_000_000_000, 'crystals': 1000, 'vip': 3, 'energy_full': True, 'title': '',
    },
    'legend': {
        'name': 'Легенда',
        'emoji': '👑',
        'price_rub': 349,
        'desc': '500 млрд ₽ + 3 000💎 + VIP Платина + титул + ⚡',
        'coins': 500_000_000_000, 'crystals': 3000, 'vip': 4, 'energy_full': True, 'title': 'legend_don',
    },
    'admin_pack': {
        'name': 'Набор Админа',
        'emoji': '🛡',
        'price_rub': 800,
        'desc': 'Права АДМИНА + 2 трлн ₽ + 10 000💎 + VIP Алмаз + титул + ⚡',
        'coins': 2_000_000_000_000, 'crystals': 10000, 'vip': 5, 'energy_full': True,
        'title': 'god', 'grant_admin': True,
    },
}

START_BALANCE = 800
START_CRYSTALS = 3
DAILY_BONUS = 300
MIN_BET = 25
# Лимит SQLite INTEGER (signed 64-bit ≈ 9.22e18). Больше — OverflowError.
MAX_BALANCE = 9_000_000_000_000_000_000
MAX_BET = MAX_BALANCE  # макс. ставка ~9×10¹⁸ ₽ (потолок SQLite / «гугл»)
PVP_MIN_BET = 300_000  # минимальная ставка на арене
PVP_FEE = 0.05         # 5% комиссия казино с банка
DB_PATH = 'casino.db'

# ── Триггеры текстовых команд ──────────────────────────────
# Короткие алиасы (1–2 символа) срабатывают ТОЛЬКО:
#   • сообщение из одного слова
#   • и (в личке ИЛИ ответ на сообщение бота)
# Полные слова — как обычные команды (первое слово).
SHORT_TRIGGERS = {
    'я', 'б', 'п', 'х', 'ап', 'бб', 'мм', 'бдж',
}
# Команды, которые в группах не слушаем как «болтовню»
# (короткие уже отфильтрованы; здесь доп. шумные слова)
GROUP_SAFE_ONLY_PRIVATE = set()  # можно добавить слова при необходимости

RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
PAGE_SIZE = 6
BETS = [50, 100, 250, 500, 1000, 2500, 5000]
CLAN_CREATE_COST = 500_000_000
ENERGY_BASE_MAX = 50
ENERGY_MAX = ENERGY_BASE_MAX  # стартовый максимум (для совместимости)
ENERGY_RESTORE_MIN = 6
ENERGY_COST = {'mines': 4, 'crash': 3, 'joker': 3, 'slots': 2, 'dice': 2,
               'dice3': 3, 'coin': 2, 'hl': 2, 'roulette': 3, 'russian': 4,
               'guess': 3, 'poker': 4, 'wheel': 4, 'lottery': 6, 'bj': 4,
               'rob': 6, 'duel': 5}
MOD_GIVE_LIMIT = 50_000  # максимальная выдача за раз для модератора

# Прокачка энергии: уровень → максимум и цена следующего уровня
ENERGY_LEVELS = {
    0: {'max': 50,  'price': 0,           'name': 'Базовый'},
    1: {'max': 70,  'price': 8_000_000,   'name': 'Усиленный'},
    2: {'max': 100, 'price': 25_000_000,  'name': 'Продвинутый'},
    3: {'max': 140, 'price': 70_000_000,  'name': 'Элитный'},
    4: {'max': 180, 'price': 180_000_000, 'name': 'Легендарный'},
    5: {'max': 250, 'price': 400_000_000, 'name': 'Мифический'},
}

VIP_LEVELS = {
    0: {'name': 'Новичок', 'emoji': '👤', 'bonus': 1.00, 'price': 0},
    1: {'name': 'Бронза', 'emoji': '🥉', 'bonus': 1.03, 'price': 150},
    2: {'name': 'Серебро', 'emoji': '🥈', 'bonus': 1.07, 'price': 400},
    3: {'name': 'Золото', 'emoji': '🥇', 'bonus': 1.12, 'price': 900},
    4: {'name': 'Платина', 'emoji': '💠', 'bonus': 1.20, 'price': 2000},
    5: {'name': 'Алмаз', 'emoji': '💎', 'bonus': 1.30, 'price': 4500},
}

MINE_PRESETS = {
    'small':  {'name': '5×5', 'size': 25, 'cols': 5, 'mines': 6, 'step': 0.32, 'energy': 4},
    'medium': {'name': '7×7', 'size': 49, 'cols': 7, 'mines': 12, 'step': 0.28, 'energy': 6},
    'large':  {'name': '9×9', 'size': 81, 'cols': 9, 'mines': 20, 'step': 0.24, 'energy': 9},
}

SLOT_SYMBOLS = ['🍒', '🍋', '🍊', '🍇', '7️⃣', '⭐']
SLOT_PAYOUTS = {
    ('7️⃣', '7️⃣', '7️⃣'): 35, ('⭐', '⭐', '⭐'): 22,
    ('🍇', '🍇', '🍇'): 14, ('🍊', '🍊', '🍊'): 10,
    ('🍋', '🍋', '🍋'): 7, ('🍒', '🍒', '🍒'): 4,
}

# ═══════════════════════════════════════════════════════════
# БД
# ═══════════════════════════════════════════════════════════
def _is_db_transient(exc):
    msg = str(exc).lower()
    return any(x in msg for x in (
        'disk i/o', 'database is locked', 'busy', 'unable to open',
        'database disk image is malformed', 'locking protocol',
    ))


def _db_connect():
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA temp_store=MEMORY')
    except Exception:
        pass
    return con


def q(sql, args=(), fetch=True, retries=5):
    last_err = None
    for attempt in range(retries):
        con = None
        try:
            con = _db_connect()
            cur = con.cursor()
            cur.execute(sql, args)
            r = cur.fetchall() if fetch else None
            con.commit()
            return r
        except Exception as e:
            last_err = e
            if con is not None:
                try:
                    con.rollback()
                except Exception:
                    pass
            if _is_db_transient(e) and attempt < retries - 1:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    if last_err:
        raise last_err
    return None


def exec_change(sql, args=(), retries=5):
    last_err = None
    for attempt in range(retries):
        con = None
        try:
            con = _db_connect()
            cur = con.cursor()
            cur.execute(sql, args)
            changed = cur.rowcount
            con.commit()
            return changed
        except Exception as e:
            last_err = e
            if con is not None:
                try:
                    con.rollback()
                except Exception:
                    pass
            if _is_db_transient(e) and attempt < retries - 1:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    if last_err:
        raise last_err
    return 0


def db_init():
    con = _db_connect()
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA wal_autocheckpoint=1000')
        try:
            # Быстрая проверка целостности; при сбое — попытка recovery
            row = con.execute('PRAGMA quick_check').fetchone()
            if row and str(row[0]).lower() not in ('ok',):
                print('DB WARNING: quick_check =', row[0])
        except Exception as e:
            print('DB WARNING: integrity check failed:', repr(e))
        con.commit()
    finally:
        con.close()
    q('''CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
        total_bet INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0,
        last_bonus TEXT, registered TEXT,
        xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
        achievements TEXT DEFAULT '',
        title TEXT DEFAULT '', quests TEXT DEFAULT '',
        quests_day TEXT DEFAULT '',
        crystals INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 100,
        last_energy TEXT,
        vip INTEGER DEFAULT 0,
        daily_streak INTEGER DEFAULT 0,
        last_daily TEXT,
        total_games INTEGER DEFAULT 0)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS admins(username TEXT PRIMARY KEY, user_id INTEGER)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS moderators(username TEXT PRIMARY KEY, user_id INTEGER)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS owners(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        granted_at TEXT DEFAULT '')''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS donat_orders(
        code TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        item_key TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT '',
        activated_at TEXT DEFAULT '',
        activated_by INTEGER)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, amount INTEGER, uses INTEGER DEFAULT 0, max_uses INTEGER)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS promo_uses(code TEXT, user_id INTEGER, PRIMARY KEY(code,user_id))''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS clans(
        clan_id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL, owner_id INTEGER NOT NULL,
        level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0, balance INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '')''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS clan_members(
        clan_id INTEGER NOT NULL, user_id INTEGER NOT NULL UNIQUE,
        role TEXT DEFAULT 'member', joined_at TEXT DEFAULT '')''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS clan_invites(
        clan_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        invited_by INTEGER NOT NULL, used INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '', PRIMARY KEY(clan_id,user_id))''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS pvp_rooms(
        room_id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER NOT NULL,
        guest_id INTEGER,
        game TEXT NOT NULL,
        bet INTEGER NOT NULL,
        status TEXT DEFAULT 'open',
        host_pick TEXT DEFAULT '',
        guest_pick TEXT DEFAULT '',
        created_at TEXT DEFAULT '')''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS join_bonus(
        user_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL,
        given_at TEXT DEFAULT '',
        PRIMARY KEY(user_id, chat_id))''', fetch=False)
    q('''CREATE TABLE IF NOT EXISTS join_bonus_chats(
        chat_id INTEGER PRIMARY KEY,
        title TEXT DEFAULT '',
        added_at TEXT DEFAULT '')''', fetch=False)
    # Подтянуть зарегистрированные чаты из БД
    try:
        for (cid,) in (q('SELECT chat_id FROM join_bonus_chats') or []):
            JOIN_CHAT_IDS.add(int(cid))
    except Exception:
        pass
    admin_cols = [row[1] for row in q('PRAGMA table_info(admins)')]
    if 'user_id' not in admin_cols:
        q('ALTER TABLE admins ADD COLUMN user_id INTEGER', fetch=False)
    existing = [row[1] for row in q("PRAGMA table_info(users)")]
    for col, ddl in [
        ('xp', "ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0"),
        ('level', "ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1"),
        ('achievements', "ALTER TABLE users ADD COLUMN achievements TEXT DEFAULT ''"),
        ('title', "ALTER TABLE users ADD COLUMN title TEXT DEFAULT ''"),
        ('quests', "ALTER TABLE users ADD COLUMN quests TEXT DEFAULT ''"),
        ('quests_day', "ALTER TABLE users ADD COLUMN quests_day TEXT DEFAULT ''"),
        ('crystals', "ALTER TABLE users ADD COLUMN crystals INTEGER DEFAULT 0"),
        ('energy', "ALTER TABLE users ADD COLUMN energy INTEGER DEFAULT 100"),
        ('last_energy', "ALTER TABLE users ADD COLUMN last_energy TEXT"),
        ('vip', "ALTER TABLE users ADD COLUMN vip INTEGER DEFAULT 0"),
        ('daily_streak', "ALTER TABLE users ADD COLUMN daily_streak INTEGER DEFAULT 0"),
        ('last_daily', "ALTER TABLE users ADD COLUMN last_daily TEXT"),
        ('total_games', "ALTER TABLE users ADD COLUMN total_games INTEGER DEFAULT 0"),
        ('energy_lvl', "ALTER TABLE users ADD COLUMN energy_lvl INTEGER DEFAULT 0"),
    ]:
        if col not in existing:
            q(ddl, fetch=False)
    q("INSERT OR IGNORE INTO admins(username,user_id) VALUES(?,?)", (MAIN_ADMIN, MAIN_ADMIN_ID or None), fetch=False)
    q("INSERT OR IGNORE INTO settings(key,value) VALUES('maintenance','0')", fetch=False)


def get_user(uid):
    r = q('SELECT user_id,username,balance,banned,wins,losses,total_bet,total_won,'
          'last_bonus,xp,level,achievements,title,quests,quests_day,'
          'crystals,energy,last_energy,vip,daily_streak,last_daily,total_games,'
          'COALESCE(energy_lvl,0) '
          'FROM users WHERE user_id=?', (uid,))
    return r[0] if r else None


def user_energy_max(uid):
    """Максимум энергии игрока с учётом прокачки."""
    if is_admin_by_id(uid):
        return ENERGY_LEVELS[max(ENERGY_LEVELS.keys())]['max']
    u = get_user(uid)
    if not u:
        return ENERGY_BASE_MAX
    lvl = int(u[22]) if len(u) > 22 else 0
    return ENERGY_LEVELS.get(lvl, ENERGY_LEVELS[0])['max']


def user_energy_level(uid):
    u = get_user(uid)
    if not u:
        return 0
    return int(u[22]) if len(u) > 22 else 0


def ensure_user(u):
    username = u.username or u.first_name or f'id{u.id}'
    old = get_user(u.id)
    if not old:
        q('INSERT OR IGNORE INTO users(user_id,username,balance,registered,energy,last_energy,crystals) VALUES(?,?,?,?,?,?,?)',
          (u.id, username, START_BALANCE, datetime.now().isoformat(), ENERGY_MAX, datetime.now().isoformat(), START_CRYSTALS), fetch=False)
    else:
        q('UPDATE users SET username=? WHERE user_id=?', (username, u.id), fetch=False)
    by_id = q('SELECT username FROM admins WHERE user_id=?', (u.id,))
    by_name = q('SELECT user_id FROM admins WHERE username=? COLLATE NOCASE', (username,))
    if by_id:
        old_name = by_id[0][0]
        if old_name != username and not by_name:
            q('UPDATE admins SET username=? WHERE user_id=?', (username, u.id), fetch=False)
    elif by_name:
        q('UPDATE admins SET user_id=? WHERE username=? COLLATE NOCASE', (u.id, username), fetch=False)
    if username.lower() == MAIN_ADMIN.lower() or (MAIN_ADMIN_ID and u.id == MAIN_ADMIN_ID):
        q('INSERT OR IGNORE INTO admins(username,user_id) VALUES(?,?)', (MAIN_ADMIN, u.id), fetch=False)
        q('UPDATE admins SET user_id=? WHERE username=? COLLATE NOCASE', (u.id, MAIN_ADMIN), fetch=False)
    return get_user(u.id)


def resolve_user(x):
    x = (x or '').strip().lstrip('@')
    r = q('SELECT user_id FROM users WHERE username=? COLLATE NOCASE', (x,))
    if r: return r[0][0]
    try: return int(x)
    except Exception: return None


def is_main_owner(u):
    """Главный владелец (MAIN_ADMIN) — нельзя снять."""
    if not u:
        return False
    if MAIN_ADMIN_ID and u.id == MAIN_ADMIN_ID:
        return True
    if u.username and u.username.lower() == MAIN_ADMIN.lower():
        return True
    return False


def is_owner(u):
    """Владелец: главный или выданный в таблице owners."""
    if not u:
        return False
    if is_main_owner(u):
        return True
    try:
        if q('SELECT 1 FROM owners WHERE user_id=?', (u.id,)):
            return True
        if u.username and q(
                'SELECT 1 FROM owners WHERE username=? COLLATE NOCASE',
                (u.username,)):
            return True
    except Exception:
        pass
    return False


def is_owner_by_id(uid):
    if MAIN_ADMIN_ID and int(uid) == MAIN_ADMIN_ID:
        return True
    try:
        if q("SELECT 1 FROM users WHERE user_id=? AND LOWER(username)=LOWER(?)",
             (uid, MAIN_ADMIN)):
            return True
        if q('SELECT 1 FROM owners WHERE user_id=?', (uid,)):
            return True
    except Exception:
        pass
    return False


def grant_owner_priv(uid, username=None):
    un = (username or '').lstrip('@')
    if not un:
        u = get_user(uid)
        un = (u[1] if u else '') or f'id{uid}'
    q('INSERT OR REPLACE INTO owners(user_id, username, granted_at) VALUES(?,?,?)',
      (uid, un, datetime.now().isoformat()), fetch=False)
    # Овнер автоматически админ
    q('INSERT OR IGNORE INTO admins(username, user_id) VALUES(?,?)', (un, uid), fetch=False)
    q('UPDATE admins SET user_id=? WHERE username=? COLLATE NOCASE', (uid, un), fetch=False)


def revoke_owner_priv(uid):
    """Снять овнера (главного MAIN_ADMIN снять нельзя)."""
    if is_owner_by_id(uid) and MAIN_ADMIN_ID and int(uid) == MAIN_ADMIN_ID:
        return False
    u = get_user(uid)
    if u and u[1] and u[1].lower() == MAIN_ADMIN.lower():
        return False
    q('DELETE FROM owners WHERE user_id=?', (uid,), fetch=False)
    return True


def is_admin(u):
    """Владелец или администратор."""
    if not u:
        return False
    if is_owner(u):
        return True
    return bool(q('SELECT 1 FROM admins WHERE user_id=? OR username=? COLLATE NOCASE',
                  (u.id, u.username or '')))


def is_mod(u):
    """Модератор (или выше)."""
    if not u:
        return False
    if is_admin(u):
        return True
    return bool(q('SELECT 1 FROM moderators WHERE user_id=? OR username=? COLLATE NOCASE',
                  (u.id, u.username or '')))


def qsopra_admin_ids():
    ids = set()
    try:
        rows = q("SELECT u.user_id FROM users u INNER JOIN admins a ON LOWER(a.username)=LOWER(u.username)")
        ids.update(int(r[0]) for r in rows)
    except Exception:
        pass
    try:
        rows = q("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (MAIN_ADMIN,))
        if rows:
            ids.add(int(rows[0][0]))
    except Exception:
        pass
    try:
        rows = q("SELECT user_id FROM admins WHERE user_id IS NOT NULL")
        ids.update(int(r[0]) for r in rows if r[0])
    except Exception:
        pass
    if MAIN_ADMIN_ID:
        ids.add(MAIN_ADMIN_ID)
    return ids


def qsopra_mod_ids():
    ids = set(qsopra_admin_ids())
    try:
        rows = q("SELECT u.user_id FROM users u INNER JOIN moderators m ON LOWER(m.username)=LOWER(u.username)")
        ids.update(int(r[0]) for r in rows)
    except Exception:
        pass
    try:
        rows = q("SELECT user_id FROM moderators WHERE user_id IS NOT NULL")
        ids.update(int(r[0]) for r in rows if r[0])
    except Exception:
        pass
    return ids


def qsopra_is_admin(uid):
    return int(uid) in qsopra_admin_ids()


def is_admin_by_id(uid):
    return qsopra_is_admin(uid)


def is_mod_by_id(uid):
    return int(uid) in qsopra_mod_ids()


def is_staff(u):
    """Любой персонал: владелец / админ / модератор."""
    return is_mod(u)


def is_banned(u):
    x = get_user(u.id)
    return bool(x and x[3] == 1)


def maintenance_on():
    r = q("SELECT value FROM settings WHERE key='maintenance'")
    return bool(r and r[0][0] == '1')


def display_balance(uid, bal):
    return "∞" if is_admin_by_id(uid) else f"{bal}"


def display_crystals(uid, cr):
    if is_admin_by_id(uid):
        return "∞"
    try:
        return f"{int(cr or 0)}"
    except (TypeError, ValueError):
        return "0"


# ═══════════════════════════════════════════════════════════
# ЭНЕРГИЯ
# ═══════════════════════════════════════════════════════════
def restore_energy(uid):
    u = get_user(uid)
    if not u or u[3]:
        return
    emax = user_energy_max(uid)
    last = u[17]
    now = datetime.now()
    if not last:
        q('UPDATE users SET last_energy=?, energy=? WHERE user_id=?',
          (now.isoformat(), emax, uid), fetch=False)
        return
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        last_dt = now
    delta_min = int((now - last_dt).total_seconds() // 60)
    if delta_min < 1:
        return
    gain = delta_min // ENERGY_RESTORE_MIN
    if gain <= 0:
        return
    new_energy = min(emax, u[16] + gain)
    new_last = now.isoformat() if new_energy >= emax else (
        last_dt + timedelta(minutes=gain * ENERGY_RESTORE_MIN)).isoformat()
    q('UPDATE users SET energy=?, last_energy=? WHERE user_id=?',
      (new_energy, new_last, uid), fetch=False)


def get_energy(uid):
    restore_energy(uid)
    u = get_user(uid)
    return u[16] if u else 0


def spend_energy(uid, cost):
    if is_admin_by_id(uid):
        return True
    restore_energy(uid)
    u = get_user(uid)
    if not u:
        return False
    if u[16] < cost:
        return False
    q('UPDATE users SET energy=energy-? WHERE user_id=?', (cost, uid), fetch=False)
    return True


CRYSTALS_MAX = 1_000_000_000  # потолок 💎 на аккаунт


def grant_crystals(uid, amount):
    """Начислить кристаллы любому игроку (включая админов/овнера)."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    if not get_user(uid):
        return False
    exec_change(
        'UPDATE users SET crystals=MIN(COALESCE(crystals,0)+?, ?) WHERE user_id=?',
        (amount, CRYSTALS_MAX, uid))
    return True


def get_crystals(uid):
    u = get_user(uid)
    if not u:
        return 0
    try:
        return int(u[15] or 0)
    except (TypeError, ValueError, IndexError):
        return 0


def safe_sum_column(col, limit=MAX_BALANCE):
    """Сумма колонки без integer overflow в SQLite."""
    try:
        rows = q(f'SELECT COALESCE({col},0) FROM users') or []
        total = 0
        for (v,) in rows:
            try:
                total += min(int(v or 0), limit)
            except Exception:
                pass
            if total > limit:
                return limit
        return total
    except Exception:
        return 0


def spend_crystals(uid, amount):
    """Списать кристаллы. Админам — без списания (считается успехом)."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    if is_admin_by_id(uid):
        return True
    changed = exec_change(
        'UPDATE users SET crystals=crystals-? WHERE user_id=? AND banned=0 AND crystals>=?',
        (amount, uid, amount))
    return bool(changed)


def exchange_crystals_to_coins(uid, cost_cr, coins):
    """Атомарный обмен: −кристаллы +монеты. Возвращает (ok, msg)."""
    try:
        cost_cr = int(cost_cr)
        coins = int(coins)
    except (TypeError, ValueError):
        return False, 'Некорректная сумма'
    if cost_cr <= 0 or coins <= 0:
        return False, 'Некорректная сумма'
    if is_admin_by_id(uid):
        safe_add_balance(uid, coins)
        return True, f'+{money(coins)}₽ (админ)'
    # Одна операция: проверка кристаллов + списание + начисление
    changed = exec_change(
        'UPDATE users SET crystals=crystals-?, balance=MIN(balance+?, ?) '
        'WHERE user_id=? AND banned=0 AND crystals>=?',
        (cost_cr, coins, MAX_BALANCE, uid, cost_cr))
    if not changed:
        u = get_user(uid)
        have = u[15] if u else 0
        return False, f'Нужно {cost_cr}💎, у тебя {have}💎'
    return True, f'+{money(coins)}₽'


# ═══════════════════════════════════════════════════════════
# ДЕНЬГИ / XP
# ═══════════════════════════════════════════════════════════
def get_vip_bonus(uid):
    u = get_user(uid)
    if not u: return 1.0
    return VIP_LEVELS.get(u[18], VIP_LEVELS[0])['bonus']


def reserve_bet(uid, amount):
    """Списать ровно amount со баланса. Никогда не обнуляет баланс «заодно»."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, "❌ Некорректная ставка"
    u = get_user(uid)
    if not u:
        return False, "❌ Юзер не найден"
    if u[3]:
        return False, "🚫 Забанен"
    if amount < MIN_BET:
        return False, f"❌ Мин. ставка {MIN_BET}₽"
    if amount > MAX_BET:
        return False, f"❌ Макс. ставка {money(MAX_BET)}₽"
    if is_admin_by_id(uid):
        return True, ""
    bal = int(u[2] or 0)
    if amount > bal:
        return False, f"❌ Недостаточно средств · у тебя {money(bal)}₽"
    # Списываем ТОЛЬКО amount; total_bet тоже ограничим потолком
    changed = exec_change(
        'UPDATE users SET balance=balance-?, '
        'total_bet=MIN(total_bet+?, ?), total_games=total_games+1 '
        'WHERE user_id=? AND banned=0 AND balance>=?',
        (amount, amount, MAX_BALANCE, uid, amount))
    if not changed:
        fresh = get_user(uid)
        return False, f"❌ У тебя {money(fresh[2] if fresh else 0)}₽"
    return True, ""


def grant_win(uid, amount):
    if amount <= 0 or is_admin_by_id(uid):
        return
    bonus = get_vip_bonus(uid)
    try:
        amount = int(amount * bonus)
    except (TypeError, ValueError, OverflowError):
        return
    if amount > MAX_BALANCE:
        amount = MAX_BALANCE
    q('UPDATE users SET balance=MIN(balance+?, ?), '
      'total_won=MIN(total_won+?, ?), wins=wins+1 WHERE user_id=?',
      (amount, MAX_BALANCE, amount, MAX_BALANCE, uid), fetch=False)
    add_xp(uid, max(5, min(amount // 100, 100000)))


def return_bet(uid, amount):
    if is_admin_by_id(uid):
        return
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return
    if amount <= 0:
        return
    q('UPDATE users SET balance=MIN(balance+?, ?), '
      'total_bet=CASE WHEN total_bet>=? THEN total_bet-? ELSE 0 END WHERE user_id=?',
      (amount, MAX_BALANCE, amount, amount, uid), fetch=False)


def register_loss(uid):
    if is_admin_by_id(uid): return
    q('UPDATE users SET losses=losses+1 WHERE user_id=?', (uid,), fetch=False)
    add_xp(uid, 2)


def xp_for_level(lvl): return 100 * lvl * lvl


def add_xp(uid, amount):
    u = get_user(uid)
    if not u: return
    xp = u[9] + amount; lvl = u[10]; old = lvl
    while xp >= xp_for_level(lvl):
        xp -= xp_for_level(lvl); lvl += 1
    if lvl > old: grant_crystals(uid, (lvl - old) * 2)
    q('UPDATE users SET xp=?, level=? WHERE user_id=?', (xp, lvl, uid), fetch=False)


def progress_bar(cur, total, length=10, fill='🟩', empty='⬛'):
    filled = int(cur / total * length) if total else 0
    return fill * filled + empty * (length - filled)


def level_badge(lvl):
    if lvl >= 50: return '👑'
    if lvl >= 30: return '💎'
    if lvl >= 15: return '🥇'
    if lvl >= 8: return '🥈'
    if lvl >= 3: return '🥉'
    return '🔰'


def crash_line(mult, length=20):
    p = min(1.0, (mult - 1.0) / 11.0)
    f = max(1, int(p * length))
    return '🟥' * f + '⬛' * (length - f)


def crash_color(mult):
    if mult < 1.5: return '🟢'
    if mult < 3: return '🟡'
    if mult < 6: return '🟠'
    if mult < 10: return '🔴'
    return '💥'


def _is_harmless_tg_error(exc):
    err = str(exc).lower()
    return (
        'not modified' in err
        or 'bad gateway' in err
        or 'query is too old' in err
        or 'query id is invalid' in err
        or 'message to edit not found' in err
        or "message can't be edited" in err
        or 'timed out' in err
        or 'timeout' in err
        or 'flood control' in err
        or 'retry after' in err
        or 'retry_after' in err
        or 'too many requests' in err
    )


async def qsopra_safe_edit(target, text, **kwargs):
    """Редактирует сообщение бота; если нельзя — отправляет новое."""
    if target is None:
        return None

    async def _reply_fallback():
        try:
            if hasattr(target, "reply_text"):
                return await target.reply_text(text, **kwargs)
            msg = getattr(target, "message", None)
            if msg and hasattr(msg, "reply_text"):
                return await msg.reply_text(text, **kwargs)
            chat = getattr(target, "chat", None)
            if chat and hasattr(target, "get_bot"):
                bot = target.get_bot()
                return await bot.send_message(chat.id, text, **kwargs)
        except Exception:
            return None
        return None

    try:
        if hasattr(target, "edit_text"):
            return await target.edit_text(text, **kwargs)
        if hasattr(target, "message") and target.message:
            return await target.message.edit_text(text, **kwargs)
    except Exception as exc:
        err = str(exc).lower()
        # Нельзя редактировать сообщение пользователя / старое — шлём новое
        if any(x in err for x in (
            "can't be edited", 'message to edit not found',
            'message is not modified', 'not modified',
        )):
            return await _reply_fallback()
        if _is_harmless_tg_error(exc):
            return None
        print("SAFE_EDIT:", repr(exc))
        return await _reply_fallback()
    return None


async def _safe_edit(msg, text, reply_markup=None):
    if not msg:
        return
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        if _is_harmless_tg_error(e):
            return
        print("SAFE_EDIT_MSG:", repr(e))


def clamp_amount(n, minimum=0, maximum=MAX_BALANCE):
    """Ограничить сумму для безопасной записи в SQLite."""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return None
    if v < minimum:
        return None
    if v > maximum:
        return maximum
    return v


def safe_add_balance(uid, amount):
    """Начислить баланс с потолком MAX_BALANCE."""
    amt = clamp_amount(amount, minimum=0)
    if amt is None or amt <= 0:
        return False
    q('UPDATE users SET balance=MIN(balance+?, ?) WHERE user_id=?',
      (amt, MAX_BALANCE, uid), fetch=False)
    return True


def safe_set_balance(uid, amount):
    """Установить баланс (0 … MAX_BALANCE)."""
    amt = clamp_amount(amount, minimum=0)
    if amt is None:
        return False
    q('UPDATE users SET balance=? WHERE user_id=?', (amt, uid), fetch=False)
    return True


def safe_sub_balance(uid, amount):
    """Списать баланс, не ниже 0."""
    amt = clamp_amount(amount, minimum=0)
    if amt is None or amt <= 0:
        return False
    q('UPDATE users SET balance=CASE WHEN balance>=? THEN balance-? ELSE 0 END WHERE user_id=?',
      (amt, amt, uid), fetch=False)
    return True


def parse_amount_text(value, minimum=0):
    """
    Сокращения до потолка «гугл» (MAX_BALANCE ≈ 9×10¹⁸):
      1к / 10к / 1кк / 10кк / 1ккк … / гугл
      латиница k/kk и кириллица к/кк
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    s = raw.lower()
    # убрать пробелы и тонкие пробелы
    for sp in (' ', '\u00a0', '\u202f', '\t'):
        s = s.replace(sp, '')
    if s in ('отмена', 'cancel', '-', '/cancel'):
        return None
    for ch in ('₽', '$', 'р.', 'руб', 'rub'):
        s = s.replace(ch, '')
    s = s.strip()
    if s in ('гугл', 'google', 'googol', 'max', 'макс', 'все', 'всё', 'all'):
        return MAX_BALANCE if MAX_BALANCE >= minimum else None

    # унификация: латинская k и похожие символы → к
    # K (kelvin), κ, к
    for ch in ('k', 'K', 'κ', 'K'):
        s = s.replace(ch.lower() if ch != 'K' else 'к', 'к')
    s = s.replace('k', 'к')

    # хвост из «к»
    k_count = 0
    while s.endswith('к'):
        k_count += 1
        s = s[:-1]
        if k_count >= 7:
            break
    if k_count:
        mult = 1000 ** k_count
    elif s.endswith('м') or s.endswith('m'):
        s = s[:-1]
        mult = 1_000_000
    elif s.endswith('тыс'):
        s = s[:-3]
        mult = 1_000
    elif s.endswith('млн'):
        s = s[:-3]
        mult = 1_000_000
    elif s.endswith('млрд'):
        s = s[:-4]
        mult = 1_000_000_000
    else:
        mult = 1

    s = s.replace(',', '.')
    if not s:
        base_num = 1
        use_float = False
        base_f = 1.0
    else:
        try:
            if '.' in s:
                use_float = True
                base_f = float(s)
                base_num = 0
            else:
                use_float = False
                base_num = int(s)
                base_f = 0.0
        except (TypeError, ValueError):
            return None

    try:
        if use_float:
            v = int(base_f * mult)
        else:
            v = int(base_num) * int(mult)
    except (OverflowError, ValueError):
        v = MAX_BALANCE

    if v < minimum:
        return None
    if v > MAX_BALANCE:
        return MAX_BALANCE
    return v


def parse_custom_amount(value, minimum=MIN_BET):
    """Обёртка для ставок/переводов с минимумом."""
    return parse_amount_text(value, minimum=minimum)


def money(n):
    """Форматирование чисел: 1234567 → 1 234 567"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n > MAX_BALANCE:
        n = MAX_BALANCE
    return f"{n:,}".replace(',', ' ')


# ═══════════════════════════════════════════════════════════
# КОНСТАНТЫ КОНТЕНТА
# ═══════════════════════════════════════════════════════════
WIN_PHRASES = ["🔥 ОГОНЬ!", "💎 КРАСАВА!", "🚀 Взлетаем!", "🍀 Фортуна!",
               "👑 Везунчик!", "🎯 В яблочко!", "🏆 Эпично!"]
LOSE_PHRASES = ["😭 Ну как так...", "💀 Казино выигрывает.", "🎭 Попробуй ещё!",
                "😅 Бывает!", "🤡 Клоунский заход!", "🥲 Держись!", "💔 Плюс опыт."]
MEMES = ["🎰 «Казино — не про деньги.»", "💸 «Ещё одна ставка» — ложь",
         "🎲 «Случайность — бог костей»", "🃏 «Вся жизнь — рулетка»",
         "💰 «Деньги — цифры»", "🦆 «Утка, утюг»", "🎯 «Важно — сколько поставил»"]
ADVICE = ["💡 Не ставь больше, чем можешь.", "💡 Выиграл — забери.",
          "💡 Если кажется — кажется.", "💡 Мартингейл работает до раза.",
          "💡 Казино не для долгов.", "💡 Сон — лучший друг."]


def pick(s): return random.choice(s)


ACHIEVEMENTS = {
    'first_bet':    ('🎯 Первая ставка', 'Сделал ставку'),
    'first_win':    ('🏆 Первая победа', 'Выиграл'),
    'ten_wins':     ('🔥 Разогрев', '10 побед'),
    'fifty_wins':   ('💎 Мастер', '50 побед'),
    'hundred_wins': ('👑 Легенда', '100 побед'),
    'millionaire':  ('💰 Миллионер', '1,000,000₽'),
    'blackjack':    ('🃏 Блэкджек!', '21 в блэкджеке'),
    'duelist':      ('⚔️ Дуэлянт', 'Победа в дуэли'),
    'shopaholic':   ('🛍 Шопоголик', 'Купил титул'),
    'vip1':         ('🥉 Bronze', 'VIP 1'),
    'vip3':         ('🥇 Gold', 'VIP 3'),
    'vip5':         ('💎 Diamond', 'VIP 5'),
    'crystal100':   ('💠 Коллекционер', '100 кристаллов'),
    'crash10':      ('🚀 Ракета', 'Краш x10+'),
}


def has_ach(uid, key):
    u = get_user(uid); return bool(u and key in (u[11] or '').split(','))


def grant_ach(uid, key):
    if has_ach(uid, key): return None
    u = get_user(uid)
    cur = (u[11] or '').strip(',')
    new = (cur + ',' + key) if cur else key
    q('UPDATE users SET achievements=? WHERE user_id=?', (new, uid), fetch=False)
    return ACHIEVEMENTS[key]


def check_ach(uid, key=None):
    new = []
    u = get_user(uid)
    if not u: return new
    if key:
        r = grant_ach(uid, key)
        if r: new.append(r)
        return new
    checks = [(u[6] > 0, 'first_bet'), (u[4] >= 1, 'first_win'),
              (u[4] >= 10, 'ten_wins'), (u[4] >= 50, 'fifty_wins'),
              (u[4] >= 100, 'hundred_wins'), (u[2] >= 1_000_000, 'millionaire'),
              (u[15] >= 100, 'crystal100'),
              (u[18] >= 1, 'vip1'), (u[18] >= 3, 'vip3'), (u[18] >= 5, 'vip5')]
    for cond, k in checks:
        if cond:
            r = grant_ach(uid, k)
            if r: new.append(r)
    return new


QUESTS_POOL = [
    {'id': 'q_bet5', 'name': 'Сделай 5 ставок', 'target': 5, 'reward': 300},
    {'id': 'q_win3', 'name': 'Победи 3 раза', 'target': 3, 'reward': 500},
    {'id': 'q_bet10', 'name': 'Сделай 10 ставок', 'target': 10, 'reward': 600},
    {'id': 'q_play_mines', 'name': 'Сыграй в мины', 'target': 1, 'reward': 200},
    {'id': 'q_play_crash', 'name': 'Сыграй в краш', 'target': 1, 'reward': 200},
    {'id': 'q_play_joker', 'name': 'Сыграй в джокер', 'target': 1, 'reward': 200},
]


def get_today(): return datetime.now().strftime('%Y-%m-%d')


def refresh_quests(uid):
    u = get_user(uid)
    if not u: return
    if u[14] != get_today():
        chosen = random.sample(QUESTS_POOL, 3)
        qs = ';'.join([f"{c['id']}:0" for c in chosen])
        q('UPDATE users SET quests=?, quests_day=? WHERE user_id=?', (qs, get_today(), uid), fetch=False)


def get_quests(uid):
    refresh_quests(uid)
    u = get_user(uid)
    if not u or not u[13]: return []
    result = []
    for pair in u[13].split(';'):
        try:
            qid, prog = pair.split(':'); prog = int(prog)
        except Exception: continue
        meta = next((c for c in QUESTS_POOL if c['id'] == qid), None)
        if meta: result.append({**meta, 'prog': prog})
    return result


def quest_progress(uid, qid, inc=1):
    refresh_quests(uid)
    u = get_user(uid)
    if not u or not u[13]: return
    new = []
    for p in u[13].split(';'):
        try:
            q_, prog = p.split(':'); prog = int(prog)
        except Exception: continue
        if q_ == qid: prog += inc
        new.append(f"{q_}:{prog}")
    q('UPDATE users SET quests=? WHERE user_id=?', (';'.join(new), uid), fetch=False)


def claim_quest(uid, qid):
    u = get_user(uid)
    if not u: return False, "Ошибка"
    new = []; claimed = False; reward = 0
    for p in u[13].split(';'):
        try:
            q_, prog = p.split(':'); prog = int(prog)
        except Exception: continue
        meta = next((c for c in QUESTS_POOL if c['id'] == q_), None)
        if q_ == qid and meta and prog >= meta['target']:
            reward = meta['reward']; new.append(f"{q_}:CLAIMED"); claimed = True
        else: new.append(p)
    if not claimed: return False, "Не выполнено"
    q('UPDATE users SET quests=? WHERE user_id=?', (';'.join(new), uid), fetch=False)
    q('UPDATE users SET balance=balance+? WHERE user_id=?', (reward, uid), fetch=False)
    grant_crystals(uid, 1)
    return True, reward


TITLES = {
    'lucky':  {'name': 'Везунчик', 'price': 5000, 'emoji': '🍀'},
    'rich':   {'name': 'Богач', 'price': 15000, 'emoji': '💰'},
    'king':   {'name': 'Король', 'price': 50000, 'emoji': '👑'},
    'legend': {'name': 'Легенда', 'price': 100000, 'emoji': '🌟'},
    'mega':   {'name': 'Мегало', 'price': 500000, 'emoji': '🚀'},
    'god':    {'name': 'Казино-Бог', 'price': 1000000, 'emoji': '⚡'},
    'donor':  {'name': 'Донатер', 'price': 0, 'emoji': '💜'},
    'legend_don': {'name': 'Меценат', 'price': 0, 'emoji': '👑'},
}

# ═══════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════
MAIN_KB = ReplyKeyboardMarkup([
    [KeyboardButton('🎮 Игры'), KeyboardButton('👤 Профиль')],
    [KeyboardButton('🏆 Топы'), KeyboardButton('🎁 Бонус')],
    [KeyboardButton('🎯 Квесты'), KeyboardButton('🛍 Магазин')],
    [KeyboardButton('💎 Обмен'), KeyboardButton('📦 Кейсы')],
    [KeyboardButton('🏅 Ачивки'), KeyboardButton('ℹ️ Помощь')],
], resize_keyboard=True)


def games_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💣 Мины', callback_data='game_mines'),
         InlineKeyboardButton('🚀 Краш', callback_data='game_crash')],
        [InlineKeyboardButton('🃏 Джокер', callback_data='game_joker'),
         InlineKeyboardButton('🎰 Слоты', callback_data='game_slots')],
        [InlineKeyboardButton('🎲 Кости', callback_data='game_dice'),
         InlineKeyboardButton('🎲 Кости×3', callback_data='game_dice3')],
        [InlineKeyboardButton('🪙 Монетка', callback_data='game_coin'),
         InlineKeyboardButton('📈 Больше/Меньше', callback_data='game_hl')],
        [InlineKeyboardButton('🎡 Рулетка', callback_data='game_roulette'),
         InlineKeyboardButton('🔫 Русская', callback_data='game_russian')],
        [InlineKeyboardButton('🃏 Блэкджек', callback_data='game_bj'),
         InlineKeyboardButton('🎟 Лотерея', callback_data='game_lottery')],
        [InlineKeyboardButton('🎲 Покер', callback_data='game_poker'),
         InlineKeyboardButton('🎡 Колесо', callback_data='game_wheel')],
        [InlineKeyboardButton('🎯 Угадай', callback_data='game_guess'),
         InlineKeyboardButton('💰 Ограбить', callback_data='game_rob')],
        [InlineKeyboardButton('⚔️ Дуэль', callback_data='game_duel'),
         InlineKeyboardButton('🏟️ Арена PvP', callback_data='menu_pvp')],
    ])


def bet_kb(game):
    rows = []; row = []
    for b in BETS:
        row.append(InlineKeyboardButton(f'{money(b)}₽', callback_data=f'bet_{game}_{b}'))
        if len(row) == 3: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton('💰 ВСЁ', callback_data=f'bet_{game}_all')])
    rows.append([InlineKeyboardButton('✏️ Своя сумма', callback_data=f'{game}_custom')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')])
    return InlineKeyboardMarkup(rows)


def back_kb(target='menu_main'):
    return InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=target)]])


HELP = (
    "🎰 <b>QSOPRA CASINO</b>\n"
    "———————————————\n\n"
    "💰 <b>Валюты</b>\n"
    "🪙 Монеты — основная\n"
    "💎 Кристаллы — премиум\n\n"
    "⚡ <b>Энергия</b>\n"
    f"Стартовый максимум: <b>{ENERGY_BASE_MAX}</b> (прокачивается)\n"
    f"Восстановление: <b>+1 / {ENERGY_RESTORE_MIN} мин</b>\n"
    "Каждая игра тратит энергию\n\n"
    "👑 <b>VIP</b>\n"
    "🥉 → 🥈 → 🥇 → 💠 → 💎\n"
    "Бонус к выигрышу до <b>×1.30</b>\n\n"
    "🎮 <b>Игры</b>\n"
    "💣 Мины · 🚀 Краш · 🎰 Слоты\n"
    "🎡 Рулетка · 🃏 Джокер · 🎲 Кости\n"
    "🪙 Монетка · 📈 Больше/Меньше\n"
    "🃏 Блэкджек · 🎲 Покер · 🎡 Колесо\n"
    "🎟 Лотерея · 🎯 Угадай · 🔫 Русская\n"
    "💰 Ограбить · ⚔️ Дуэль\n\n"
    "📌 <b>Команды</b>\n"
    "<code>б</code> баланс · <code>п</code> перевод\n"
    "<code>топ</code> · <code>бонус</code> · <code>клан</code>\n"
    "<code>админ</code> · <code>мод</code> · <code>овнер</code>\n\n"
    "<i>Виртуальное развлечение · без реальных ставок</i>"
)


# ═══════════════════════════════════════════════════════════
# КРАСИВЫЕ КАРТОЧКИ
# ═══════════════════════════════════════════════════════════
def header(emoji, text):
    return f"{emoji} <b>{text}</b>\n———————————————"


def main_menu_text(uid=None):
    """Текст главного меню с балансом и энергией."""
    line = "———————————————"
    extra = ""
    if uid:
        restore_energy(uid)
        u = get_user(uid)
        if u:
            bal = "∞" if is_admin_by_id(uid) else f"{money(u[2])}₽"
            cr = "∞" if is_admin_by_id(uid) else display_crystals(uid, u[15])
            if is_admin_by_id(uid):
                en_line = "⚡ Энергия: <b>∞</b>"
            else:
                emax = user_energy_max(uid)
                ebar = progress_bar(u[16], emax, 8, '🟦', '⬛')
                en_line = f"⚡ Энергия: <b>{u[16]}/{emax}</b>\n{ebar}"
            vip = VIP_LEVELS.get(u[18], VIP_LEVELS[0])
            extra = (
                f"\n💰 Баланс: <b>{bal}</b>\n"
                f"💎 Кристаллы: <b>{cr}</b>\n"
                f"{en_line}\n"
                f"{vip['emoji']} VIP: <b>{vip['name']}</b>\n"
            )
    return (
        f"🎰 <b>QSOPRA CASINO</b>\n"
        f"{line}"
        f"{extra}\n"
        f"Выберите раздел ниже 👇"
    )


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🎮 Игры', callback_data='menu_games'),
         InlineKeyboardButton('👤 Профиль', callback_data='menu_profile')],
        [InlineKeyboardButton('🏆 Топы', callback_data='menu_tops'),
         InlineKeyboardButton('🎁 Бонус', callback_data='menu_bonus')],
        [InlineKeyboardButton('🎯 Квесты', callback_data='menu_quests'),
         InlineKeyboardButton('🛍 Магазин', callback_data='menu_shop')],
        [InlineKeyboardButton('💸 Перевод', callback_data='menu_transfer'),
         InlineKeyboardButton('📦 Кейсы', callback_data='menu_cases')],
        [InlineKeyboardButton('💎 Обмен', callback_data='menu_exchange'),
         InlineKeyboardButton('🏅 Ачивки', callback_data='menu_ach')],
        [InlineKeyboardButton('🏰 Кланы', callback_data='menu_clans'),
         InlineKeyboardButton('⚔️ Арена', callback_data='menu_pvp')],
        [InlineKeyboardButton('💜 Донат', callback_data='menu_donat'),
         InlineKeyboardButton('ℹ️ Помощь', callback_data='menu_help')],
    ])


def bal_text(uid):
    if is_admin_by_id(uid):
        u = get_user(uid)
        title = f" {TITLES[u[12]]['emoji']} <b>{TITLES[u[12]]['name']}</b>" if u and u[12] in TITLES else ''
        un = f"@{u[1]}" if u and u[1] else f"id{uid}"
        return (header('👑', 'АДМИНИСТРАТОР') + f"\n\n"
                f"🎭 <b>{un}</b>{title}\n"
                f"💰 Баланс: <b>∞</b>\n"
                f"💎 Кристаллы: <b>∞</b>\n"
                f"⚡ Энергия: <b>∞</b>\n"
                f"👑 VIP: <b>МАКС</b>\n"
                f"⭐ Уровень: <b>{u[10] if u else 1}</b> {level_badge(u[10] if u else 1)}\n"
                f"🏆 Побед: <b>{u[4] if u else 0}</b>  💀 <b>{u[5] if u else 0}</b>")
    restore_energy(uid)
    p = get_user(uid)
    lvl = p[10]; xp = p[9]; need = xp_for_level(lvl)
    bar = progress_bar(xp, need)
    total = p[4] + p[5]; wr = round(p[4] / total * 100, 1) if total else 0
    name = f"@{p[1]}" if p[1] else f"id{p[0]}"
    title = f" {TITLES[p[12]]['emoji']} <b>{TITLES[p[12]]['name']}</b>" if p[12] in TITLES else ''
    vip = VIP_LEVELS.get(p[18], VIP_LEVELS[0])
    emax = user_energy_max(uid)
    elvl = user_energy_level(uid)
    ebar = progress_bar(p[16], emax, 10, '🟦', '⬛')
    return (header('👤', 'ПРОФИЛЬ') + f"\n\n"
            f"🎭 <b>{name}</b>{title}\n\n"
            f"💰 <b>{money(p[2])}₽</b>\n"
            f"💎 <b>{p[15]}</b> кристаллов\n"
            f"{vip['emoji']} VIP <b>{vip['name']}</b> · x{vip['bonus']}\n\n"
            f"⚡ Энергия <b>{p[16]}/{emax}</b> · ур. {elvl}\n"
            f"{ebar}\n\n"
            f"⭐ Уровень <b>{lvl}</b> {level_badge(lvl)}\n"
            f"{bar} {xp}/{need} XP\n\n"
            f"🏆 <b>{p[4]}</b> побед · 💀 <b>{p[5]}</b> поражений\n"
            f"📊 Винрейт <b>{wr}%</b>\n"
            f"🎯 Оборот <b>{money(p[6])}₽</b>\n"
            f"💸 Выиграно <b>{money(p[7])}₽</b>\n"
            f"🎮 Игр сыграно <b>{p[21]}</b>")


def top_text(category='balance'):
    admins_list = [r[0] for r in q('SELECT username FROM admins')]
    cat_map = {
        'balance':   ('💰', 'ТОП БОГАЧЕЙ', 'balance DESC'),
        'crystals':  ('💎', 'ТОП КРИСТАЛЛОВ', 'crystals DESC'),
        'wins':      ('🏆', 'ТОП ПОБЕДИТЕЛЕЙ', 'wins DESC'),
        'level':     ('⭐', 'ТОП УРОВНЯ', 'level DESC, xp DESC'),
        'total_bet': ('🎯', 'ТОП ОБОРОТА', 'total_bet DESC'),
    }
    emoji, title, order = cat_map.get(category, cat_map['balance'])
    others = q(f'SELECT user_id,username,balance,crystals,wins,level,total_bet FROM users WHERE banned=0 ORDER BY {order} LIMIT 10')
    others = [r for r in others if r[1] not in admins_list][:9]
    t = header(emoji, title) + "\n\n"
    t += f"👑 <b>@{MAIN_ADMIN}</b> — легенда казино\n\n"
    medals = ['🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    for i, (uid, name, bal, cr, wins, lvl, tb) in enumerate(others):
        mark = medals[i] if i < len(medals) else f'{i+2}.'
        if category == 'crystals': stat = f"💎 {cr}"
        elif category == 'wins': stat = f"🏆 {wins}"
        elif category == 'level': stat = f"⭐ {lvl}"
        elif category == 'total_bet': stat = f"🎯 {money(tb)}₽"
        else: stat = f"💰 {money(bal)}₽"
        u = get_user(uid)
        title_t = f" {TITLES[u[12]]['emoji']}" if u and u[12] in TITLES else ''
        t += f"{mark} <b>{name or '???'}</b>{title_t} {level_badge(lvl)}\n      {stat}\n"
    if not others: t += "\n<i>Пока никого</i>"
    return t


def top_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💰 Баланс', callback_data='top_balance'),
         InlineKeyboardButton('💎 Кристаллы', callback_data='top_crystals')],
        [InlineKeyboardButton('🏆 Победы', callback_data='top_wins'),
         InlineKeyboardButton('⭐ Уровень', callback_data='top_level')],
        [InlineKeyboardButton('🎯 Оборот', callback_data='top_total_bet')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')],
    ])


def achievements_text(uid):
    u = get_user(uid)
    owned = set((u[11] or '').split(','))
    txt = header('🏅', 'АЧИВКИ') + "\n\n"
    for key, (name, desc) in ACHIEVEMENTS.items():
        mark = '✅' if key in owned else '🔒'
        txt += f"{mark} <b>{name}</b>\n      <i>{desc}</i>\n"
    txt += f"\n📊 Прогресс <b>{len(owned)}/{len(ACHIEVEMENTS)}</b>"
    return txt


def quests_kb(uid):
    qs = get_quests(uid); rows = []; u = get_user(uid)
    for q_ in qs:
        if f"{q_['id']}:CLAIMED" in (u[13] or ''):
            rows.append([InlineKeyboardButton(f"✅ {q_['name']}", callback_data='noop')])
        elif q_['prog'] >= q_['target']:
            rows.append([InlineKeyboardButton(
                f"🎁 Забрать · {q_['name']} +{q_['reward']}₽ +1💎",
                callback_data=f'quest_{q_["id"]}')])
        else:
            rows.append([InlineKeyboardButton(
                f"⏳ {q_['name']} · {q_['prog']}/{q_['target']}",
                callback_data='noop')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')])
    return InlineKeyboardMarkup(rows)


def shop_kb(uid):
    u = get_user(uid); rows = []
    for key, t in TITLES.items():
        if t.get('price', 0) <= 0:
            continue  # донат-титулы только через Boosty
        owned = (u[12] == key)
        label = f"✅ {t['emoji']} {t['name']}" if owned else f"{t['emoji']} {t['name']} · {money(t['price'])}₽"
        rows.append([InlineKeyboardButton(label, callback_data=f'buy_{key}' if not owned else 'noop')])
    rows.append([InlineKeyboardButton('💜 Донат Boosty', callback_data='menu_donat')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')])
    return InlineKeyboardMarkup(rows)


def _donat_code():
    return 'DN' + ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))


def deliver_donat_item(uid, item_key):
    """Выдать содержимое донат-пакета."""
    item = DONAT_ITEMS.get(item_key)
    if not item:
        return False, 'Пакет не найден'
    if not get_user(uid):
        return False, 'Игрок не найден'
    if item.get('coins'):
        safe_add_balance(uid, item['coins'])
    if item.get('crystals'):
        grant_crystals(uid, item['crystals'])
    if item.get('vip'):
        u = get_user(uid)
        cur = int(u[18] or 0) if u else 0
        if item['vip'] > cur:
            q('UPDATE users SET vip=? WHERE user_id=?', (item['vip'], uid), fetch=False)
    if item.get('energy_full'):
        emax = user_energy_max(uid)
        q('UPDATE users SET energy=?, last_energy=? WHERE user_id=?',
          (emax, datetime.now().isoformat(), uid), fetch=False)
    if item.get('title') and item['title'] in TITLES:
        q('UPDATE users SET title=? WHERE user_id=?', (item['title'], uid), fetch=False)
    if item.get('grant_admin'):
        u = get_user(uid)
        un = (u[1] if u and u[1] else f'id{uid}')
        q('INSERT OR IGNORE INTO admins(username, user_id) VALUES(?,?)', (un, uid), fetch=False)
        q('UPDATE admins SET user_id=? WHERE username=? COLLATE NOCASE', (uid, un), fetch=False)
        # если username пустой — запись по user_id
        if not u or not u[1]:
            q('INSERT OR IGNORE INTO admins(username, user_id) VALUES(?,?)',
              (f'user_{uid}', uid), fetch=False)
    parts = []
    if item.get('coins'):
        parts.append(f"+{money(item['coins'])}₽")
    if item.get('crystals'):
        parts.append(f"+{item['crystals']}💎")
    if item.get('vip'):
        parts.append(f"VIP {VIP_LEVELS.get(item['vip'], {}).get('name', item['vip'])}")
    if item.get('energy_full'):
        parts.append('⚡ полная энергия')
    if item.get('title'):
        t = TITLES.get(item['title'], {})
        parts.append(f"{t.get('emoji', '')} {t.get('name', item['title'])}")
    if item.get('grant_admin'):
        parts.append('🛡 права АДМИНА')
    return True, ' · '.join(parts) if parts else 'OK'


async def donat_menu(message, uid):
    rows = []
    for key, it in DONAT_ITEMS.items():
        rows.append([InlineKeyboardButton(
            f"{it['emoji']} {it['name']} · {it['price_rub']}₽",
            callback_data=f'donat_item_{key}')])
    rows.append([InlineKeyboardButton('📜 Мои заказы', callback_data='donat_my')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')])
    txt = (
        header('💜', 'ДОНАТ BOOSTY') + "\n\n"
        "Поддержка казино через <b>Boosty</b> — реальные рубли.\n"
        "Выбери пакет → получишь код → оплати на Boosty "
        "и <b>укажи код в комментарии</b>.\n"
        "После оплаты владелец активирует заказ.\n\n"
        f"🔗 Boosty: {BOOSTY_URL}\n\n"
        "<i>Цены умеренные · награда в игровой валюте.</i>"
    )
    await qsopra_safe_edit(message, txt, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')


async def donat_item_view(message, uid, key):
    it = DONAT_ITEMS.get(key)
    if not it:
        await donat_menu(message, uid)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'🛒 Оформить · {it["price_rub"]}₽', callback_data=f'donat_buy_{key}')],
        [InlineKeyboardButton('⬅️ К пакетам', callback_data='menu_donat')],
    ])
    await qsopra_safe_edit(
        message,
        header(it['emoji'], it['name'].upper()) + f"\n\n"
        f"{it['desc']}\n\n"
        f"💵 Цена · <b>{it['price_rub']}₽</b> (Boosty)\n\n"
        f"После оплаты укажи выданный код в комментарии на Boosty.",
        reply_markup=kb, parse_mode='HTML')


async def donat_create_order(update, ctx, uid, key):
    qr = update.callback_query
    it = DONAT_ITEMS.get(key)
    if not it:
        try:
            await qr.answer('Пакет не найден', show_alert=True)
        except Exception:
            pass
        return
    # лимит активных заказов
    pending = q(
        "SELECT COUNT(*) FROM donat_orders WHERE user_id=? AND status='pending'",
        (uid,))
    if pending and pending[0][0] >= 5:
        try:
            await qr.answer('Слишком много открытых заказов (макс. 5)', show_alert=True)
        except Exception:
            pass
        return
    code = _donat_code()
    for _ in range(5):
        if not q('SELECT 1 FROM donat_orders WHERE code=?', (code,)):
            break
        code = _donat_code()
    q(
        "INSERT INTO donat_orders(code,user_id,item_key,status,created_at) VALUES(?,?,?,'pending',?)",
        (code, uid, key, datetime.now().isoformat()), fetch=False)
    try:
        await qr.answer('Заказ создан')
    except Exception:
        pass
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🔗 Открыть Boosty', url=BOOSTY_URL)],
        [InlineKeyboardButton('📜 Мои заказы', callback_data='donat_my')],
        [InlineKeyboardButton('⬅️ В магазин', callback_data='menu_donat')],
    ])
    await qsopra_safe_edit(
        qr.message,
        header('✅', 'ЗАКАЗ СОЗДАН') + f"\n\n"
        f"{it['emoji']} <b>{it['name']}</b>\n"
        f"💵 К оплате · <b>{it['price_rub']}₽</b>\n\n"
        f"🔑 Твой код:\n<code>{code}</code>\n\n"
        f"1. Открой Boosty и донать <b>{it['price_rub']}₽</b>\n"
        f"2. В комментарии напиши код <code>{code}</code>\n"
        f"3. Владелец активирует — награда придёт в бота\n\n"
        f"🔗 {BOOSTY_URL}",
        reply_markup=kb, parse_mode='HTML')


async def donat_my_orders(message, uid):
    rows = q(
        "SELECT code,item_key,status,created_at FROM donat_orders "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT 15", (uid,)) or []
    txt = header('📜', 'МОИ ДОНАТ-ЗАКАЗЫ') + "\n\n"
    if not rows:
        txt += "<i>Заказов пока нет.</i>"
    else:
        for code, key, st, ca in rows:
            it = DONAT_ITEMS.get(key, {})
            st_map = {'pending': '⏳ ждёт оплаты', 'done': '✅ выдано', 'cancel': '❌ отменён'}
            txt += (
                f"{it.get('emoji', '💜')} <b>{it.get('name', key)}</b>\n"
                f"🔑 <code>{code}</code> · {st_map.get(st, st)}\n\n"
            )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_donat')],
    ])
    await qsopra_safe_edit(message, txt, reply_markup=kb, parse_mode='HTML')


async def donat_owner_pending(message):
    rows = q(
        "SELECT code,user_id,item_key,created_at FROM donat_orders "
        "WHERE status='pending' ORDER BY created_at ASC LIMIT 20") or []
    txt = header('💜', 'ДОНАТ · ОЖИДАЮТ') + "\n\n"
    kb_rows = []
    if not rows:
        txt += "<i>Нет ожидающих заказов.</i>"
    else:
        for code, uid, key, ca in rows:
            it = DONAT_ITEMS.get(key, {})
            name = pvp_user_label(uid) if 'pvp_user_label' in dir() else f'id{uid}'
            try:
                name = pvp_user_label(uid)
            except Exception:
                u = get_user(uid)
                name = f"@{u[1]}" if u and u[1] else f"id{uid}"
            txt += (
                f"{it.get('emoji', '💜')} {it.get('name', key)} · {it.get('price_rub', '?')}₽\n"
                f"👤 {name} · <code>{code}</code>\n\n"
            )
            kb_rows.append([InlineKeyboardButton(
                f"✅ {code}", callback_data=f'donat_ok_{code}'),
                InlineKeyboardButton(
                f"❌ {code}", callback_data=f'donat_no_{code}')])
    kb_rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_menu')])
    await qsopra_safe_edit(message, txt, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode='HTML')


async def donat_activate(ctx, code, by_uid):
    rows = q(
        "SELECT user_id,item_key,status FROM donat_orders WHERE code=?", (code,))
    if not rows:
        return False, 'Код не найден'
    uid, key, status = rows[0]
    if status == 'done':
        return False, 'Уже активирован'
    if status == 'cancel':
        return False, 'Заказ отменён'
    ok, detail = deliver_donat_item(uid, key)
    if not ok:
        return False, detail
    q(
        "UPDATE donat_orders SET status='done', activated_at=?, activated_by=? WHERE code=?",
        (datetime.now().isoformat(), by_uid, code), fetch=False)
    it = DONAT_ITEMS.get(key, {})
    try:
        await ctx.bot.send_message(
            uid,
            header('💜', 'ДОНАТ АКТИВИРОВАН') + f"\n\n"
            f"{it.get('emoji', '')} <b>{it.get('name', key)}</b>\n"
            f"{detail}\n\nСпасибо за поддержку! 💜",
            parse_mode='HTML')
    except Exception:
        pass
    return True, detail


async def donat_cb(update, ctx):
    u = update.effective_user
    if not u:
        return
    uid = u.id
    qr = update.callback_query
    d = qr.data or ''
    ensure_user(u)
    try:
        if d == 'menu_donat':
            await donat_menu(qr.message, uid)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'donat_my':
            await donat_my_orders(qr.message, uid)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'donat_owner':
            if not is_owner(u):
                try:
                    await qr.answer('⛔ Только владелец', show_alert=True)
                except Exception:
                    pass
                return
            await donat_owner_pending(qr.message)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('donat_item_'):
            await donat_item_view(qr.message, uid, d[len('donat_item_'):])
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('donat_buy_'):
            await donat_create_order(update, ctx, uid, d[len('donat_buy_'):])
            return
        if d.startswith('donat_ok_'):
            if not is_owner(u):
                return
            code = d[len('donat_ok_'):]
            ok, msg = await donat_activate(ctx, code, uid)
            try:
                await qr.answer('✅ Выдано' if ok else msg, show_alert=not ok)
            except Exception:
                pass
            await donat_owner_pending(qr.message)
            return
        if d.startswith('donat_no_'):
            if not is_owner(u):
                return
            code = d[len('donat_no_'):]
            q("UPDATE donat_orders SET status='cancel' WHERE code=? AND status='pending'",
              (code,), fetch=False)
            try:
                await qr.answer('Отменён')
            except Exception:
                pass
            await donat_owner_pending(qr.message)
            return
    except Exception as e:
        print('DONAT ERR:', repr(e))
        try:
            await qr.answer('Извините, ошибка доната', show_alert=True)
        except Exception:
            pass


def transfer_kb(uid):
    is_adm = is_admin_by_id(uid)
    limit = 50 if is_adm else 20
    rows = q('SELECT user_id,username,balance FROM users WHERE user_id != ? AND banned=0 ORDER BY balance DESC LIMIT ?', (uid, limit))
    kb = []
    for tid, name, bal in rows:
        bal_txt = display_balance(tid, bal)
        label_name = f"@{name}" if name else f"id{tid}"
        kb.append([InlineKeyboardButton(f'👤 {label_name} · {bal_txt}₽', callback_data=f'tr_{tid}')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')])
    return InlineKeyboardMarkup(kb)


# ═══════════════════════════════════════════════════════════
# АКТИВНЫЕ ИГРЫ
# ═══════════════════════════════════════════════════════════
active = {}
crash_settle_locks = {}
duels = {}
pending_bets = {}
ONLINE_TIMEOUT = 300
ONLINE_USERS = {}


def qsopra_mark_online(uid): ONLINE_USERS[int(uid)] = time.time()


def qsopra_online_count():
    now = time.time()
    return sum(1 for ts in ONLINE_USERS.values() if now - ts <= ONLINE_TIMEOUT)


# ═══════════════════════════════════════════════════════════
# ИГРА: МИНЫ 2.0
# ═══════════════════════════════════════════════════════════
async def mines_preset_menu(message, uid):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🟢 5×5 · 5 мин · x0.4', callback_data='mp_small')],
        [InlineKeyboardButton('🟡 7×7 · 10 мин · x0.35', callback_data='mp_medium')],
        [InlineKeyboardButton('🔴 9×9 · 18 мин · x0.3', callback_data='mp_large')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')],
    ])
    await qsopra_safe_edit(message,
        header('💣', 'МИНЫ 2.0') + "\n\nВыбери размер поля:",
        reply_markup=kb, parse_mode='HTML')


async def render_mines(message, uid, edit):
    g = active.get(uid)
    if not g: return
    p = g['preset']; opened = g['opened']
    mult = round(1 + len(opened) * p['step'], 2)
    kb = []; row = []
    for i in range(p['size']):
        if i in opened: row.append(InlineKeyboardButton('💎', callback_data='noop'))
        else: row.append(InlineKeyboardButton('⬛', callback_data=f'm_{i}'))
        if len(row) == p['cols']: kb.append(row); row = []
    if row: kb.append(row)
    cash = int(g['bet'] * mult)
    kb.append([InlineKeyboardButton(f'💰 Забрать {money(cash)}₽', callback_data='m_cash')])
    safe_total = p['size'] - p['mines']
    bar = progress_bar(len(opened), safe_total, 10)
    txt = (header('💣', f'МИНЫ {p["name"]}') + f"\n\n"
           f"💵 Ставка · <b>{money(g['bet'])}₽</b>\n"
           f"💣 Мин · <b>{p['mines']}</b>\n"
           f"📈 Множитель · <b>x{mult}</b>\n\n"
           f"{bar}\n"
           f"💎 Открыто <b>{len(opened)}/{safe_total}</b>\n"
           f"💰 К забору · <b>{money(cash)}₽</b>")
    try:
        if edit: await message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        else: await message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    except Exception as e:
        if 'not modified' not in str(e).lower(): print("RENDER_MINES:", repr(e))


async def start_mines(message, uid, amount, preset_key='small'):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    p = MINE_PRESETS[preset_key]
    if not is_admin_by_id(uid) and not spend_energy(uid, p['energy']):
        return_bet(uid, amount)
        await message.reply_text(f"⚡ Не хватает энергии · нужно {p['energy']}"); return
    quest_progress(uid, 'q_play_mines'); quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    mines = set(random.sample(range(p['size']), p['mines']))
    active[uid] = {'game': 'mines', 'bet': amount, 'mines': mines, 'opened': set(),
                   'alive': True, 'preset': p, 'preset_key': preset_key}
    await render_mines(message, uid, False)


async def mines_click(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    g = active.get(uid)
    if not g or g['game'] != 'mines' or not g.get('alive'):
        try: await qr.answer('Не активно', show_alert=True)
        except Exception: pass
        return
    try: idx = int(qr.data.split('_')[1])
    except Exception:
        try: await qr.answer()
        except Exception: pass
        return
    if idx in g['opened']:
        try: await qr.answer('Уже открыто')
        except Exception: pass
        return
    try: await qr.answer()
    except Exception: pass
    if idx in g['mines']:
        g['alive'] = False; bet = g['bet']
        active.pop(uid, None); register_loss(uid)
        await qsopra_safe_edit(qr.message,
            header('💥', 'БУМ!') + f"\n\n💀 Мина!\n💸 Потеряно <b>{money(bet)}₽</b>\n\n<i>{pick(LOSE_PHRASES)}</i>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        return
    g['opened'].add(idx)
    p = g['preset']; safe_total = p['size'] - p['mines']
    if len(g['opened']) == safe_total:
        g['alive'] = False
        win = int(g['bet'] * (1 + safe_total * p['step']))
        active.pop(uid, None); grant_win(uid, win); quest_progress(uid, 'q_win3')
        await qsopra_safe_edit(qr.message,
            header('🎉', 'ПОБЕДА!') + f"\n\n💎 Все безопасные открыты\n💵 Выигрыш <b>+{money(win)}₽</b>\n\n<i>{pick(WIN_PHRASES)}</i>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        return
    await render_mines(qr.message, uid, True)


async def mines_cash(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    g = active.get(uid)
    if not g or g['game'] != 'mines' or not g.get('alive'):
        try: await qr.answer('Не активно', show_alert=True)
        except Exception: pass
        return
    g['alive'] = False
    p = g['preset']; mult = round(1 + len(g['opened']) * p['step'], 2)
    win = int(g['bet'] * mult); active.pop(uid, None)
    try: await qr.answer()
    except Exception: pass
    grant_win(uid, win); quest_progress(uid, 'q_win3')
    await qsopra_safe_edit(qr.message,
        header('💰', 'ЗАБРАЛ!') + f"\n\n📈 Множитель <b>x{mult}</b>\n💵 Выигрыш <b>+{money(win)}₽</b>",
        reply_markup=back_kb('menu_games'), parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# ИГРА: КРАШ 2.0
# ═══════════════════════════════════════════════════════════
def crash_text_2(g, alive=True):
    bet = g['bet']; mult = g['mult']
    color = crash_color(mult); line = crash_line(mult)
    cash = int(bet * mult); auto = g.get('autostop')
    auto_line = f"\n🎯 Авто-стоп · x{auto}" if auto else ""
    if g.get('dual'):
        risky_mult = round(1 + (mult - 1) * 2.5, 2)
        risky_cash = int(bet * risky_mult)
        return (header('🚀', 'КРАШ 2.0') + f"\n\n"
                f"💵 Ставка · <b>{money(bet)}₽</b>\n\n"
                f"🟢 Безопасная {color} x<b>{mult:.2f}</b>\n"
                f"<code>{line}</code>\n"
                f"💰 Забрать <b>{money(cash)}₽</b>\n\n"
                f"🔴 Рисковая x2.5 → x<b>{risky_mult:.2f}</b>\n"
                f"💰 Забрать <b>{money(risky_cash)}₽</b>"
                f"{auto_line}")
    return (header('🚀', 'КРАШ 2.0') + f"\n\n"
            f"💵 Ставка · <b>{money(bet)}₽</b>\n\n"
            f"{color} x<b>{mult:.2f}</b>\n"
            f"<code>{line}</code>\n\n"
            f"💰 К забору · <b>{money(cash)}₽</b>"
            f"{auto_line}")


async def crash_setup_menu(message, uid):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🎯 Без авто-стопа', callback_data='crash_auto_0')],
        [InlineKeyboardButton('x1.5', callback_data='crash_auto_1.5'),
         InlineKeyboardButton('x2', callback_data='crash_auto_2'),
         InlineKeyboardButton('x3', callback_data='crash_auto_3')],
        [InlineKeyboardButton('x5', callback_data='crash_auto_5'),
         InlineKeyboardButton('x10', callback_data='crash_auto_10')],
        [InlineKeyboardButton('🎲 Двойная линия · x2.5 риск', callback_data='crash_dual_1')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')],
    ])
    await qsopra_safe_edit(message,
        header('🚀', 'КРАШ 2.0') + "\n\n"
        "🎯 <b>Авто-стоп</b> — автоматически забрать на множителе\n"
        "🎲 <b>Двойная линия</b> — рисковая часть x2.5\n\n"
        "Настрой игру:",
        reply_markup=kb, parse_mode='HTML')


async def start_crash(message, uid, amount, autostop=None, dual=False):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not is_admin_by_id(uid) and not spend_energy(uid, ENERGY_COST['crash']):
        return_bet(uid, amount); await message.reply_text("⚡ Не хватает энергии"); return
    quest_progress(uid, 'q_play_crash'); quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    crash_point = round(random.uniform(1.05, 15.0), 2)
    active[uid] = {'game': 'crash', 'bet': amount, 'crash': crash_point,
                   'mult': 1.0, 'alive': True, 'settled': False,
                   'autostop': autostop, 'dual': dual}
    display = await message.reply_text(crash_text_2(active[uid], True), parse_mode='HTML')
    btns = [[InlineKeyboardButton('💰 Забрать', callback_data='cr_cash')]]
    if dual: btns.append([InlineKeyboardButton('🔥 Забрать рисковую', callback_data='cr_cash_risky')])
    cash_msg = await message.reply_text("💰 <b>КНОПКА ВЫВОДА</b>\nНажми когда захочешь:",
        reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
    active[uid]['display_msg'] = display
    active[uid]['cash_msg'] = cash_msg
    crash_settle_locks[uid] = asyncio.Lock()
    asyncio.create_task(crash_loop(uid, display, cash_msg))


async def crash_loop(uid, display_msg, cash_msg):
    while True:
        await asyncio.sleep(0.9)
        g = active.get(uid)
        if not g or g.get('game') != 'crash' or not g.get('alive'): return
        step = (random.uniform(0.1, 0.5) if g['mult'] < 2 else
                random.uniform(0.15, 0.6) if g['mult'] < 5 else
                random.uniform(0.2, 0.7) if g['mult'] < 8 else
                random.uniform(0.3, 1.0))
        g['mult'] = round(g['mult'] + step, 2)
        auto = g.get('autostop')
        if auto and g['mult'] >= auto and g['mult'] < g['crash']:
            g['mult'] = min(g['mult'], g['crash'] - 0.01)
            lock = crash_settle_locks.setdefault(uid, asyncio.Lock())
            async with lock:
                if not g.get('alive') or g.get('settled'): return
                g['alive'] = False; g['settled'] = True; active.pop(uid, None)
            win = int(g['bet'] * g['mult']); grant_win(uid, win); quest_progress(uid, 'q_win3')
            if g['mult'] >= 10: check_ach(uid, 'crash10')
            await _safe_edit(display_msg, header('🎯', 'АВТО-СТОП!') + f"\n\n📈 x<b>{g['mult']:.2f}</b>\n💵 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'))
            await _safe_edit(cash_msg, "✅ Забрано!", reply_markup=back_kb('menu_games'))
            crash_settle_locks.pop(uid, None); return
        if g['mult'] >= g['crash']:
            g['mult'] = g['crash']
            lock = crash_settle_locks.setdefault(uid, asyncio.Lock())
            async with lock:
                if not g.get('alive') or g.get('settled'): return
                g['alive'] = False; g['settled'] = True; active.pop(uid, None)
            register_loss(uid)
            await _safe_edit(display_msg, crash_text_2(g, False) + f"\n\n<i>{pick(LOSE_PHRASES)}</i>", reply_markup=back_kb('menu_games'))
            await _safe_edit(cash_msg, "💥 КРАШ!", reply_markup=back_kb('menu_games'))
            crash_settle_locks.pop(uid, None); return
        cash = int(g['bet'] * g['mult'])
        await _safe_edit(display_msg, crash_text_2(g, True))
        btns = [[InlineKeyboardButton(f'💰 Забрать {money(cash)}₽', callback_data='cr_cash')]]
        if g.get('dual'):
            rm = round(1 + (g['mult'] - 1) * 2.5, 2); rc = int(g['bet'] * rm)
            btns.append([InlineKeyboardButton(f'🔥 Риск x{rm:.2f} · {money(rc)}₽', callback_data='cr_cash_risky')])
        await _safe_edit(cash_msg,
            f"💰 <b>ВЫВОД</b>\n\n📈 x<b>{g['mult']:.2f}</b>\n💵 <b>{money(cash)}₽</b>",
            reply_markup=InlineKeyboardMarkup(btns))


async def crash_cash(update, ctx, risky=False):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    try: await qr.answer()
    except Exception: pass
    lock = crash_settle_locks.setdefault(uid, asyncio.Lock())
    async with lock:
        g = active.get(uid)
        if not g or g.get('game') != 'crash' or not g.get('alive') or g.get('settled'):
            try: await qr.answer('Завершено', show_alert=True)
            except Exception: pass
            return
        g['alive'] = False; g['settled'] = True; active.pop(uid, None)
        if risky and g.get('dual'):
            mult = round(1 + (g['mult'] - 1) * 2.5, 2); win = int(g['bet'] * mult)
            label = f"🔥 Рисковая x{mult:.2f}"
        else:
            mult = g['mult']; win = int(g['bet'] * mult); label = f"🟢 Безопасная x{mult:.2f}"
        grant_win(uid, win); quest_progress(uid, 'q_win3')
        if mult >= 10: check_ach(uid, 'crash10')
        try:
            await qsopra_safe_edit(qr.message,
                header('💰', 'ВЫВОД УСПЕШЕН!') + f"\n\n{label}\n💸 Забрано <b>+{money(win)}₽</b>",
                reply_markup=back_kb('menu_games'), parse_mode='HTML')
        except Exception as e: print("CRASH_CASH:", repr(e))
        display = g.get('display_msg')
        if display: await _safe_edit(display, f"💰 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'))
    crash_settle_locks.pop(uid, None)


# ═══════════════════════════════════════════════════════════
# ИГРА: СЛОТЫ 2.0
# ═══════════════════════════════════════════════════════════
async def play_slots(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not is_admin_by_id(uid) and not spend_energy(uid, ENERGY_COST['slots']):
        return_bet(uid, amount); await message.reply_text("⚡ Не хватает энергии"); return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    s1 = random.choice(SLOT_SYMBOLS); s2 = random.choice(SLOT_SYMBOLS); s3 = random.choice(SLOT_SYMBOLS)
    mult = SLOT_PAYOUTS.get((s1, s2, s3), 0)
    if not mult and (s1 == s2 or s2 == s3 or s1 == s3): mult = 1.5
    txt = (header('🎰', 'СЛОТЫ 2.0') + f"\n\n"
           f"┏━━━━━━━━━┓\n"
           f"┃  {s1}  {s2}  {s3}  ┃\n"
           f"┗━━━━━━━━━┛\n\n")
    if mult > 0:
        win = int(amount * mult); grant_win(uid, win); quest_progress(uid, 'q_win3')
        txt += f"🎉 <b>x{mult}</b>\n💵 <b>+{money(win)}₽</b>"
        await message.reply_text(txt, reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        txt += f"❌ Мимо\n💀 <b>-{money(amount)}₽</b>"
        await message.reply_text(txt, reply_markup=back_kb('menu_games'), parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# ИГРА: РУЛЕТКА 2.0
# ═══════════════════════════════════════════════════════════
async def play_roulette_menu(message, uid):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🔴 Красное · x2', callback_data='rl_kr'),
         InlineKeyboardButton('⚫ Чёрное · x2', callback_data='rl_ch')],
        [InlineKeyboardButton('🟢 Зеро · x36', callback_data='rl_ze')],
        [InlineKeyboardButton('1-18 · x2', callback_data='rl_low'),
         InlineKeyboardButton('19-36 · x2', callback_data='rl_high')],
        [InlineKeyboardButton('Чёт · x2', callback_data='rl_even'),
         InlineKeyboardButton('Нечет · x2', callback_data='rl_odd')],
        [InlineKeyboardButton('1-12 · x3', callback_data='rl_d1'),
         InlineKeyboardButton('13-24 · x3', callback_data='rl_d2'),
         InlineKeyboardButton('25-36 · x3', callback_data='rl_d3')],
        [InlineKeyboardButton('🎯 Число · x36', callback_data='rl_number')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')],
    ])
    await qsopra_safe_edit(message, header('🎡', 'РУЛЕТКА 2.0') + "\n\nВыбери тип ставки:",
        reply_markup=kb, parse_mode='HTML')


async def play_roulette_2(message, uid, amount, choice, bet_number=None):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not is_admin_by_id(uid) and not spend_energy(uid, ENERGY_COST['roulette']):
        return_bet(uid, amount); await message.reply_text("⚡ Не хватает энергии"); return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    n = random.randint(0, 36); win = 0; label = ''
    if choice == 'kr':
        if n in RED: win = amount * 2
        label = '🔴 Красное'
    elif choice == 'ch':
        if n != 0 and n not in RED: win = amount * 2
        label = '⚫ Чёрное'
    elif choice == 'ze':
        if n == 0: win = amount * 36
        label = '🟢 Зеро'
    elif choice == 'low':
        if 1 <= n <= 18: win = amount * 2
        label = '1-18'
    elif choice == 'high':
        if 19 <= n <= 36: win = amount * 2
        label = '19-36'
    elif choice == 'even':
        if n != 0 and n % 2 == 0: win = amount * 2
        label = 'Чёт'
    elif choice == 'odd':
        if n % 2 == 1: win = amount * 2
        label = 'Нечет'
    elif choice == 'd1':
        if 1 <= n <= 12: win = amount * 3
        label = '1-12'
    elif choice == 'd2':
        if 13 <= n <= 24: win = amount * 3
        label = '13-24'
    elif choice == 'd3':
        if 25 <= n <= 36: win = amount * 3
        label = '25-36'
    elif choice == 'number':
        if bet_number == n: win = amount * 36
        label = f'Число {bet_number}'
    color = '🔴' if n in RED else ('⚫' if n != 0 else '🟢')
    txt = (header('🎡', 'РУЛЕТКА 2.0') + f"\n\n"
           f"🎯 Ставка · {label}\n\n"
           f"🎲 Выпало · {color} <b>{n}</b>\n\n")
    if win:
        grant_win(uid, win); quest_progress(uid, 'q_win3')
        txt += f"💵 Выигрыш <b>+{money(win)}₽</b>\n\n<i>{pick(WIN_PHRASES)}</i>"
    else:
        register_loss(uid)
        txt += f"💀 Потеряно <b>-{money(amount)}₽</b>\n\n<i>{pick(LOSE_PHRASES)}</i>"
    await message.reply_text(txt, reply_markup=back_kb('menu_games'), parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# ПРОСТЫЕ ИГРЫ
# ═══════════════════════════════════════════════════════════
async def _energy_gate(message, uid, amount, game_key):
    if is_admin_by_id(uid): return True
    if not spend_energy(uid, ENERGY_COST.get(game_key, 1)):
        return_bet(uid, amount)
        await message.reply_text(f"⚡ Нужно {ENERGY_COST.get(game_key, 1)} энергии")
        return False
    return True


async def play_joker(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'joker'): return
    quest_progress(uid, 'q_play_joker'); quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    bad = random.randint(0, 2)
    active[uid] = {'game': 'joker', 'bet': amount, 'bad': bad, 'chosen': False}
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('1️⃣ 🃏', callback_data='jk_0'),
        InlineKeyboardButton('2️⃣ 🃏', callback_data='jk_1'),
        InlineKeyboardButton('3️⃣ 🃏', callback_data='jk_2')]])
    await message.reply_text(
        header('🃏', 'ДЖОКЕР') + f"\n\n💵 Ставка · <b>{money(amount)}₽</b>\n🎯 Множитель · <b>x4</b>\n\n"
        "⚠️ Одна из 3 — пустая",
        reply_markup=kb, parse_mode='HTML')


async def joker_click(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    g = active.get(uid)
    if not g or g['game'] != 'joker' or g.get('chosen'):
        try: await qr.answer()
        except Exception: pass
        return
    g['chosen'] = True
    idx = int(qr.data.split('_')[1]); bet = g['bet']; bad = g['bad']
    active.pop(uid, None)
    def m(i):
        if i == bad: return '💀'
        if i == idx: return '🃏'
        return '✅'
    row = '  '.join(m(i) for i in range(3))
    try: await qr.answer()
    except Exception: pass
    if idx == bad:
        register_loss(uid)
        txt = header('💀', 'ПУСТАЯ') + f"\n\n   {row}\n\n💸 <b>-{money(bet)}₽</b>"
    else:
        win = bet * 4; grant_win(uid, win); quest_progress(uid, 'q_win3')
        txt = header('🃏', 'ДЖОКЕР!') + f"\n\n   {row}\n\n💵 <b>+{money(win)}₽</b>"
    await qsopra_safe_edit(qr.message, txt, reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_dice(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'dice'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    s = await message.reply_dice(emoji='🎲'); v = s.dice.value
    if v >= 5:
        win = amount * 2; grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"🎲 <b>{v}</b>\n💵 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"🎲 {v}\n💀 <b>-{money(amount)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_dice3(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'dice3'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    d1 = await message.reply_dice(emoji='🎲')
    d2 = await message.reply_dice(emoji='🎲')
    d3 = await message.reply_dice(emoji='🎲')
    s = d1.dice.value + d2.dice.value + d3.dice.value
    if s >= 11:
        win = amount * 2; grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"🎲🎲🎲 Сумма <b>{s}</b>\n💵 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"🎲🎲🎲 Сумма <b>{s}</b>\n💀 <b>-{money(amount)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_coin(message, uid, amount, choice):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'coin'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    r = random.choice(['о', 'р'])
    label = '🦅 Орёл' if r == 'о' else '🪙 Решка'
    if choice == r:
        win = amount * 2; grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"🪙 <b>{label}</b>\n💵 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"🪙 {label}\n💀 <b>-{money(amount)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_hl(message, uid, amount, direction):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'hl'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    n = random.randint(1, 100)
    if n == 50:
        return_bet(uid, amount)
        await message.reply_text(f"⚖️ Ровно 50 · возврат {money(amount)}₽", reply_markup=back_kb('menu_games'))
        return
    won = (direction == 'more' and n > 50) or (direction == 'less' and n < 50)
    emoji = '📈' if direction == 'more' else '📉'
    if won:
        win = int(amount * 1.9); grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"{emoji} <b>{n}</b>\n💵 <b>+{money(win)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"{emoji} {n}\n💀 <b>-{money(amount)}₽</b>", reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_russian(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'russian'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    bullet = random.randint(1, 6); shot = random.randint(1, 6)
    if shot == bullet:
        register_loss(uid)
        await message.reply_text(header('🔫', 'РУССКАЯ РУЛЕТКА') + f"\n\n💥 БАБАХ!\n💀 <b>-{money(amount)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        win = amount * 3; grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(header('🔫', 'РУССКАЯ РУЛЕТКА') + f"\n\n😮‍💨 Щёлк!\n💵 <b>+{money(win)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_guess(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'guess'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    secret = random.randint(1, 100)
    active[uid] = {'game': 'guess', 'bet': amount, 'secret': secret, 'tries': 0, 'max': 7}
    kb = []
    for row_start in range(1, 101, 10):
        row = [InlineKeyboardButton(str(i), callback_data=f'g_{i}') for i in range(row_start, row_start + 10)]
        kb.append(row)
    await message.reply_text(
        header('🎯', 'УГАДАЙ 1-100') + f"\n\n💵 Ставка · <b>{money(amount)}₽</b> (x5)\n🔢 Попыток · 7",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')


async def guess_click(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    g = active.get(uid)
    if not g or g['game'] != 'guess':
        try: await qr.answer()
        except Exception: pass
        return
    num = int(qr.data.split('_')[1]); g['tries'] += 1
    try: await qr.answer()
    except Exception: pass
    if num == g['secret']:
        win = g['bet'] * 5; grant_win(uid, win); quest_progress(uid, 'q_win3')
        active.pop(uid, None)
        await qsopra_safe_edit(qr.message, header('🎯', 'УГАДАЛ!') + f"\n\nПопыток · {g['tries']}\n💵 <b>+{money(win)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        return
    if g['tries'] >= g['max']:
        register_loss(uid); active.pop(uid, None)
        await qsopra_safe_edit(qr.message, f"😭 Не угадал · число <b>{g['secret']}</b>\n💀 <b>-{money(g['bet'])}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        return
    hint = '⬆️ Больше!' if num < g['secret'] else '⬇️ Меньше!'
    bar = progress_bar(g['tries'], g['max'], 7)
    await qsopra_safe_edit(qr.message,
        f"🎯 <b>УГАДАЙ</b>\n\n{hint}\n{bar}\n🎯 {g['tries']}/7",
        reply_markup=qr.message.reply_markup, parse_mode='HTML')


async def play_poker(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'poker'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    dices = [random.randint(1, 6) for _ in range(5)]
    s = sorted(dices, reverse=True); counts = [s.count(v) for v in set(s)]; mx = max(counts)
    if mx == 5: mult, name = 10, '🎯 ПОКЕР'
    elif mx == 4: mult, name = 6, '🔥 КАРЕ'
    elif mx == 3 and 2 in counts: mult, name = 5, '🏠 ФУЛЛ-ХАУС'
    elif mx == 3: mult, name = 3, '🎲 СЕТ'
    elif counts.count(2) == 2: mult, name = 2, '✌️ ДВЕ ПАРЫ'
    elif mx == 2: mult, name = 1.5, '👥 ПАРА'
    else: mult, name = 0, '❌ Ничего'
    face = ' '.join(f'{d}️⃣' for d in dices)
    if mult:
        win = int(amount * mult); grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"🎲 <b>ПОКЕР</b>\n\n{face}\n\n{name}\n💵 <b>+{money(win)}₽</b> · x{mult}",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"🎲 <b>ПОКЕР</b>\n\n{face}\n\n{name}\n💀 <b>-{money(amount)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')


WHEEL = [(0,'💀',0),(1.5,'🪙 x1.5',40),(2,'💵 x2',30),(3,'💰 x3',15),
         (5,'💎 x5',8),(10,'🔥 x10',5),(20,'👑 x20',1.5),(100,'🏆 x100',0.5)]


async def play_wheel(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'wheel'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    total = sum(w[2] for w in WHEEL)
    r = random.uniform(0, total); acc = 0; chosen = WHEEL[0]
    for w in WHEEL:
        acc += w[2]
        if r <= acc: chosen = w; break
    mult, label, _ = chosen
    if mult > 0:
        win = int(amount * mult); grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(f"🎡 <b>КОЛЕСО</b>\n\n✨ {label}\n💵 <b>+{money(win)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(f"🎡 <b>КОЛЕСО</b>\n\n✨ {label}\n💀 <b>-{money(amount)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def play_lottery(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'lottery'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    your = sorted(random.sample(range(1, 46), 6))
    win_nums = sorted(random.sample(range(1, 46), 6))
    matched = len(set(your) & set(win_nums))
    mult = {0: 0, 1: 0, 2: 0.5, 3: 1, 4: 5, 5: 50, 6: 1000}.get(matched, 0)
    ya = ' '.join(f'{n:02d}' for n in your); wa = ' '.join(f'{n:02d}' for n in win_nums)
    if mult > 0:
        win = int(amount * mult); grant_win(uid, win); quest_progress(uid, 'q_win3')
        await message.reply_text(
            f"🎟 <b>ЛОТЕРЕЯ</b>\n\nТвои · <code>{ya}</code>\nВыпали · <code>{wa}</code>\n\n"
            f"✅ Совпало <b>{matched}</b>\n💵 <b>+{money(win)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
    else:
        register_loss(uid)
        await message.reply_text(
            f"🎟 <b>ЛОТЕРЕЯ</b>\n\nТвои · <code>{ya}</code>\nВыпали · <code>{wa}</code>\n\n"
            f"✅ Совпало <b>{matched}</b>\n💀 <b>-{money(amount)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')


def bj_deck():
    d = ['2','3','4','5','6','7','8','9','10','В','Д','К','Т'] * 4
    random.shuffle(d); return d


def bj_value(hand):
    total = 0; aces = 0
    for c in hand:
        if c in ('В', 'Д', 'К'): total += 10
        elif c == 'Т': total += 11; aces += 1
        else: total += int(c)
    while total > 21 and aces: total -= 10; aces -= 1
    return total


async def play_blackjack(message, uid, amount):
    ok, msg = reserve_bet(uid, amount)
    if not ok: await message.reply_text(msg); return
    if not await _energy_gate(message, uid, amount, 'bj'): return
    quest_progress(uid, 'q_bet5'); quest_progress(uid, 'q_bet10')
    deck = bj_deck(); p = [deck.pop(), deck.pop()]; d = [deck.pop(), deck.pop()]
    active[uid] = {'game': 'bj', 'bet': amount, 'player': p, 'dealer': d, 'deck': deck, 'done': False}
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('🃏 Ещё', callback_data='bj_hit'),
        InlineKeyboardButton('✋ Хватит', callback_data='bj_stop')]])
    await message.reply_text(
        header('🃏', 'БЛЭКДЖЕК') + f"\n\n💵 Ставка · <b>{money(amount)}₽</b>\n\n"
        f"👤 {' '.join(p)} = <b>{bj_value(p)}</b>\n🎩 {d[0]} ❓",
        reply_markup=kb, parse_mode='HTML')


async def bj_hit(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    g = active.get(uid)
    if not g or g['game'] != 'bj' or g['done']:
        try: await qr.answer('Не активно')
        except Exception: pass
        return
    g['player'].append(g['deck'].pop())
    val = bj_value(g['player'])
    if val > 21:
        bet = g['bet']; active.pop(uid, None); register_loss(uid)
        try: await qr.answer()
        except Exception: pass
        await qsopra_safe_edit(qr.message, f"💥 Перебор! {val}\n💀 <b>-{money(bet)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        return
    if val == 21:
        try: await qr.answer()
        except Exception: pass
        await bj_dealer_finish(qr, uid); return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('🃏 Ещё', callback_data='bj_hit'),
        InlineKeyboardButton('✋ Хватит', callback_data='bj_stop')]])
    try: await qr.answer()
    except Exception: pass
    await qsopra_safe_edit(qr.message,
        f"🃏 <b>БЛЭКДЖЕК</b>\n💵 {money(g['bet'])}₽\n\n"
        f"👤 {' '.join(g['player'])} = <b>{val}</b>\n🎩 {g['dealer'][0]} ❓",
        reply_markup=kb, parse_mode='HTML')


async def bj_stop(update, ctx):
    qr = update.callback_query
    try: await qr.answer()
    except Exception: pass
    await bj_dealer_finish(qr, update.effective_user.id)


async def bj_dealer_finish(qr, uid):
    g = active.get(uid)
    if not g: return
    while bj_value(g['dealer']) < 17: g['dealer'].append(g['deck'].pop())
    pv = bj_value(g['player']); dv = bj_value(g['dealer'])
    if dv > 21 or pv > dv:
        win = int(g['bet'] * 2); grant_win(uid, win); quest_progress(uid, 'q_win3')
        if pv == 21: check_ach(uid, 'blackjack')
        txt = (f"🎉 <b>ПОБЕДА!</b>\n\n👤 {' '.join(g['player'])} = <b>{pv}</b>\n"
               f"🎩 {' '.join(g['dealer'])} = <b>{dv}</b>\n\n💵 <b>+{money(win)}₽</b>")
    elif pv == dv:
        return_bet(uid, g['bet'])
        txt = (f"⚖️ <b>Ничья</b>\n\n👤 {' '.join(g['player'])} = <b>{pv}</b>\n"
               f"🎩 {' '.join(g['dealer'])} = <b>{dv}</b>\n\n💰 Возврат {money(g['bet'])}₽")
    else:
        register_loss(uid)
        txt = (f"💀 <b>Проигрыш</b>\n\n👤 {' '.join(g['player'])} = <b>{pv}</b>\n"
               f"🎩 {' '.join(g['dealer'])} = <b>{dv}</b>\n\n💀 <b>-{money(g['bet'])}₽</b>")
    active.pop(uid, None)
    await qsopra_safe_edit(qr.message, txt, reply_markup=back_kb('menu_games'), parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# ОГРАБЛЕНИЕ / ДУЭЛЬ
# ═══════════════════════════════════════════════════════════
async def play_rob_menu(message, uid):
    rows = q('SELECT user_id,username FROM users WHERE user_id != ? AND banned=0 ORDER BY balance DESC LIMIT 20', (uid,))
    kb = []
    for tid, name in rows:
        if is_admin_by_id(tid): continue
        label = f'👤 @{name}' if name else f'👤 id{tid}'
        kb.append([InlineKeyboardButton(label, callback_data=f'rob_t_{tid}')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')])
    if len(kb) == 1:
        await message.reply_text('❌ Нет целей', reply_markup=back_kb('menu_games')); return
    await qsopra_safe_edit(message, header('💰', 'ОГРАБЛЕНИЕ') + "\n\nВыбери жертву:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')


async def rob_pick(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    tid = int(qr.data.split('_')[2])
    tu = get_user(tid)
    if not tu:
        try: await qr.answer('Не найден')
        except Exception: pass
        return
    ctx.user_data['rob_target'] = tid
    try: await qr.answer()
    except Exception: pass
    await qsopra_safe_edit(qr.message, f"💰 Ограбить @{tu[1] or tid}\n\nВыбери ставку:",
        reply_markup=bet_kb('rob'), parse_mode='HTML')


async def play_rob(update, ctx, uid, amount):
    msg_obj = update.callback_query.message if update.callback_query else update.message
    tid = ctx.user_data.get('rob_target')
    if not tid: return
    tu = get_user(tid)
    if not tu or is_admin_by_id(tid):
        await qsopra_safe_edit(msg_obj, '❌ Нельзя', reply_markup=back_kb('menu_games')); return
    ok, msg = reserve_bet(uid, amount)
    if not ok:
        await qsopra_safe_edit(msg_obj, msg, reply_markup=back_kb('menu_games')); return
    if not is_admin_by_id(uid) and not spend_energy(uid, ENERGY_COST['rob']):
        return_bet(uid, amount)
        await qsopra_safe_edit(msg_obj, '⚡ Нужно 5 энергии', reply_markup=back_kb('menu_games')); return
    if random.random() < 0.4:
        stolen = min(amount * 2, tu[2])
        if stolen <= 0:
            return_bet(uid, amount)
            await qsopra_safe_edit(msg_obj, '❌ Пусто', reply_markup=back_kb('menu_games')); return
        q('UPDATE users SET balance=balance-? WHERE user_id=?', (stolen, tid), fetch=False)
        q('UPDATE users SET balance=balance+? WHERE user_id=?', (stolen, uid), fetch=False)
        await qsopra_safe_edit(msg_obj,
            header('💰', 'УДАЛОСЬ!') + f"\n\n🎯 @{tu[1] or tid}\n💵 Украдено <b>{money(stolen)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')
        try: await ctx.bot.send_message(tid, f'🚨 Тебя ограбили! -{money(stolen)}₽', parse_mode='HTML')
        except Exception: pass
    else:
        register_loss(uid)
        await qsopra_safe_edit(msg_obj, header('🚔', 'ПРОВАЛ!') + f"\n\n💀 Штраф <b>{money(amount)}₽</b>",
            reply_markup=back_kb('menu_games'), parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# PvP АРЕНА — онлайн-соревнования на свои деньги
# ═══════════════════════════════════════════════════════════
PVP_GAMES = {
    'coin': {'name': 'Монетка', 'emoji': '🪙', 'hint': 'Орёл или решка. Победитель забирает банк.'},
    'dice': {'name': 'Кости', 'emoji': '🎲', 'hint': 'У кого больше на кубике — тот победил.'},
    'rps':  {'name': 'КНБ', 'emoji': '✂️', 'hint': 'Камень · Ножницы · Бумага.'},
    'num':  {'name': 'Число', 'emoji': '🎯', 'hint': 'Случайное число 1–100. Больше — победа.'},
    'bank': {'name': 'Банк-викторина', 'emoji': '🧠', 'hint': 'ALL-IN: весь баланс в банк. 3 вопроса, победитель забирает всё.'},
}
PVP_BETS = [300_000, 500_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000]

QUIZ_BANK_Q = [
    {'q': 'Сколько будет 12 × 12?', 'opts': ['124', '144', '132', '120'], 'a': 1},
    {'q': 'Столица Франции?', 'opts': ['Берлин', 'Мадрид', 'Париж', 'Рим'], 'a': 2},
    {'q': 'Сколько сторон у треугольника?', 'opts': ['2', '3', '4', '5'], 'a': 1},
    {'q': '2 + 2 × 2 = ?', 'opts': ['6', '8', '4', '2'], 'a': 0},
    {'q': 'Какой газ нужен для дыхания?', 'opts': ['Азот', 'Кислород', 'Гелий', 'CO₂'], 'a': 1},
    {'q': 'Сколько дней в неделе?', 'opts': ['5', '6', '7', '8'], 'a': 2},
    {'q': 'Первая планета от Солнца?', 'opts': ['Венера', 'Земля', 'Меркурий', 'Марс'], 'a': 2},
    {'q': 'HTML — это…', 'opts': ['Язык разметки', 'База данных', 'ОС', 'Браузер'], 'a': 0},
]


def pvp_pot(bet):
    """Банк после комиссии."""
    total = bet * 2
    fee = int(total * PVP_FEE)
    return total - fee, fee


def pvp_user_label(uid):
    u = get_user(uid)
    if not u:
        return f'id{uid}'
    return f'@{u[1]}' if u[1] else f'id{uid}'


def pvp_cleanup_stale():
    """Закрыть висящие комнаты старше 30 минут."""
    try:
        q("DELETE FROM pvp_rooms WHERE status='open' AND created_at < datetime('now', '-30 minutes')",
          fetch=False)
    except Exception:
        pass


async def pvp_menu(message, uid):
    pvp_cleanup_stale()
    rooms = q(
        "SELECT room_id, host_id, game, bet FROM pvp_rooms WHERE status='open' "
        "ORDER BY room_id DESC LIMIT 15")
    kb = [
        [InlineKeyboardButton('➕ Создать комнату', callback_data='pvp_create')],
        [InlineKeyboardButton('🔄 Обновить', callback_data='menu_pvp')],
    ]
    txt = header('⚔️', 'АРЕНА PvP') + "\n\n"
    txt += f"Мин. ставка · <b>{money(PVP_MIN_BET)}₽</b>\n"
    txt += f"Комиссия · <b>{int(PVP_FEE * 100)}%</b> с банка\n"
    txt += "Играй против живых игроков на свои деньги.\n\n"
    if not rooms:
        txt += "<i>Открытых комнат нет — создай первую.</i>"
    else:
        txt += "<b>Открытые комнаты:</b>\n"
        for rid, host, game, bet in rooms:
            g = PVP_GAMES.get(game, {})
            host_name = pvp_user_label(host)
            mark = " (ты)" if host == uid else ""
            txt += f"#{rid} {g.get('emoji', '⚔️')} {g.get('name', game)} · {money(bet)}₽ · {host_name}{mark}\n"
            if host != uid:
                kb.append([InlineKeyboardButton(
                    f"▶️ Войти #{rid} · {money(bet)}₽",
                    callback_data=f'pvp_join_{rid}')])
            else:
                kb.append([InlineKeyboardButton(
                    f"🗑 Отменить #{rid}",
                    callback_data=f'pvp_cancel_{rid}')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')])
    await qsopra_safe_edit(message, txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')


async def pvp_create_menu(message, uid):
    rows = []
    for key, g in PVP_GAMES.items():
        rows.append([InlineKeyboardButton(
            f"{g['emoji']} {g['name']}",
            callback_data=f'pvp_game_{key}')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_pvp')])
    txt = header('➕', 'СОЗДАТЬ КОМНАТУ') + "\n\nВыбери игру:"
    for g in PVP_GAMES.values():
        txt += f"\n{g['emoji']} <b>{g['name']}</b> — {g['hint']}"
    await qsopra_safe_edit(message, txt, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')


async def pvp_bet_menu(message, uid, game):
    g = PVP_GAMES.get(game)
    if not g:
        await pvp_menu(message, uid)
        return
    if game == 'bank':
        u = get_user(uid)
        bal = int(u[2] or 0) if u else 0
        rows = [[InlineKeyboardButton(
            f'🧠 ALL-IN · {money(bal)}₽',
            callback_data=f'pvp_mk_bank_allin')]]
        rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='pvp_create')])
        await qsopra_safe_edit(
            message,
            header('🧠', 'БАНК-ВИКТОРИНА') + f"\n\n"
            f"{g['hint']}\n\n"
            f"Твой баланс · <b>{money(bal)}₽</b>\n"
            f"Мин. для входа · <b>{money(PVP_MIN_BET)}₽</b>\n\n"
            f"Весь баланс уходит в общий банк.\n"
            f"3 вопроса. Кто умнее — забирает всё (комиссия {int(PVP_FEE*100)}%).",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode='HTML')
        return
    rows = []
    for b in PVP_BETS:
        rows.append([InlineKeyboardButton(
            f"{money(b)}₽",
            callback_data=f'pvp_mk_{game}_{b}')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='pvp_create')])
    pot, fee = pvp_pot(PVP_MIN_BET)
    await qsopra_safe_edit(
        message,
        header(g['emoji'], g['name'].upper()) + f"\n\n"
        f"{g['hint']}\n\n"
        f"Мин. ставка · <b>{money(PVP_MIN_BET)}₽</b>\n"
        f"Пример банка (при {money(PVP_MIN_BET)}₽) · <b>{money(pot)}₽</b> "
        f"(комиссия {money(fee)}₽)\n\n"
        f"Выбери ставку — сумма спишется сразу:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML')


async def pvp_make_room(update, ctx, uid, game, bet):
    qr = update.callback_query
    if game not in PVP_GAMES:
        try:
            await qr.answer('Игра не найдена', show_alert=True)
        except Exception:
            pass
        return
    if bet < PVP_MIN_BET:
        try:
            await qr.answer(f'Мин. {money(PVP_MIN_BET)}₽', show_alert=True)
        except Exception:
            pass
        return
    # Уже есть открытая комната?
    existing = q("SELECT room_id FROM pvp_rooms WHERE host_id=? AND status='open'", (uid,))
    if existing:
        try:
            await qr.answer('Сначала закрой свою комнату', show_alert=True)
        except Exception:
            pass
        await pvp_menu(qr.message, uid)
        return
    ok, msg = reserve_bet(uid, bet)
    if not ok:
        try:
            await qr.answer(msg, show_alert=True)
        except Exception:
            pass
        return
    q("INSERT INTO pvp_rooms(host_id, game, bet, status, created_at) VALUES(?,?,?,'open',?)",
      (uid, game, bet, datetime.now().isoformat()), fetch=False)
    rid = q("SELECT room_id FROM pvp_rooms WHERE host_id=? AND status='open' ORDER BY room_id DESC LIMIT 1",
            (uid,))
    room_id = rid[0][0] if rid else '?'
    g = PVP_GAMES[game]
    try:
        await qr.answer('Комната создана')
    except Exception:
        pass
    await qsopra_safe_edit(
        qr.message,
        header('✅', 'КОМНАТА СОЗДАНА') + f"\n\n"
        f"#{room_id} {g['emoji']} <b>{g['name']}</b>\n"
        f"Ставка · <b>{money(bet)}₽</b> (заморожена)\n"
        f"Жди соперника в списке арены.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🗑 Отменить', callback_data=f'pvp_cancel_{room_id}')],
            [InlineKeyboardButton('⚔️ К арене', callback_data='menu_pvp')],
        ]),
        parse_mode='HTML')


async def pvp_cancel_room(update, ctx, uid, room_id):
    qr = update.callback_query
    rows = q("SELECT host_id, bet, status FROM pvp_rooms WHERE room_id=?", (room_id,))
    if not rows:
        try:
            await qr.answer('Комната не найдена', show_alert=True)
        except Exception:
            pass
        await pvp_menu(qr.message, uid)
        return
    host, bet, status = rows[0]
    if host != uid:
        try:
            await qr.answer('Это не твоя комната', show_alert=True)
        except Exception:
            pass
        return
    if status != 'open':
        try:
            await qr.answer('Уже началась', show_alert=True)
        except Exception:
            pass
        return
    q("UPDATE pvp_rooms SET status='cancelled' WHERE room_id=?", (room_id,), fetch=False)
    return_bet(uid, bet)
    try:
        await qr.answer('Комната отменена, ставка возвращена')
    except Exception:
        pass
    await pvp_menu(qr.message, uid)


async def pvp_join_room(update, ctx, uid, room_id):
    qr = update.callback_query
    rows = q(
        "SELECT host_id, guest_id, game, bet, status FROM pvp_rooms WHERE room_id=?",
        (room_id,))
    if not rows:
        try:
            await qr.answer('Комната не найдена', show_alert=True)
        except Exception:
            pass
        await pvp_menu(qr.message, uid)
        return
    host, guest, game, bet, status = rows[0]
    if status != 'open':
        try:
            await qr.answer('Комната закрыта', show_alert=True)
        except Exception:
            pass
        await pvp_menu(qr.message, uid)
        return
    if host == uid:
        try:
            await qr.answer('Нельзя войти в свою комнату', show_alert=True)
        except Exception:
            pass
        return
    # Для банк-викторины гость ставит ВЕСЬ свой баланс
    join_amount = bet
    if game == 'bank':
        gu = get_user(uid)
        join_amount = int(gu[2] or 0) if gu else 0
        if not is_admin_by_id(uid) and join_amount < PVP_MIN_BET:
            try:
                await qr.answer(f'Нужно минимум {money(PVP_MIN_BET)}₽', show_alert=True)
            except Exception:
                pass
            return
        if is_admin_by_id(uid):
            join_amount = max(join_amount, PVP_MIN_BET)
    ok, msg = reserve_bet(uid, join_amount)
    if not ok:
        try:
            await qr.answer(msg if msg else 'Извините, не удалось войти', show_alert=True)
        except Exception:
            pass
        return
    changed = exec_change(
        "UPDATE pvp_rooms SET guest_id=?, status='playing' WHERE room_id=? AND status='open'",
        (uid, room_id))
    if not changed:
        return_bet(uid, join_amount)
        try:
            await qr.answer('Кто-то уже вошёл', show_alert=True)
        except Exception:
            pass
        await pvp_menu(qr.message, uid)
        return

    g = PVP_GAMES.get(game, {})
    # Уведомить хоста
    try:
        await ctx.bot.send_message(
            host,
            f"⚔️ В твою комнату #{room_id} вошёл <b>{pvp_user_label(uid)}</b>!\n"
            f"{g.get('emoji', '')} {g.get('name', game)} · ставка {money(bet)}₽",
            parse_mode='HTML')
    except Exception:
        pass

    if game == 'bank':
        pot_total = bet + join_amount
        qs = random.sample(QUIZ_BANK_Q, k=min(3, len(QUIZ_BANK_Q)))
        active[f'quiz_{room_id}'] = {
            'host': host, 'guest': uid,
            'h_bet': bet, 'g_bet': join_amount, 'pot': pot_total,
            'qs': qs, 'idx': 0,
            'h_score': 0, 'g_score': 0,
            'h_ans': None, 'g_ans': None,
        }
        await pvp_quiz_send_question(ctx, room_id)
        try:
            await qr.answer('Викторина началась!')
        except Exception:
            pass
        return

    if game == 'rps':
        # Оба выбирают ход
        kb_h = InlineKeyboardMarkup([[
            InlineKeyboardButton('🪨', callback_data=f'pvp_pick_{room_id}_rock'),
            InlineKeyboardButton('📄', callback_data=f'pvp_pick_{room_id}_paper'),
            InlineKeyboardButton('✂️', callback_data=f'pvp_pick_{room_id}_scissors'),
        ]])
        txt = (
            header('✂️', 'КНБ') + f"\n\n"
            f"Комната #{room_id}\n"
            f"{pvp_user_label(host)} vs {pvp_user_label(uid)}\n"
            f"Ставка · <b>{money(bet)}₽</b>\n\n"
            f"Выбери ход:"
        )
        try:
            await ctx.bot.send_message(host, txt, reply_markup=kb_h, parse_mode='HTML')
        except Exception:
            pass
        await qsopra_safe_edit(qr.message, txt, reply_markup=kb_h, parse_mode='HTML')
        try:
            await qr.answer('Выбирай ход!')
        except Exception:
            pass
        return

    if game == 'coin':
        # Хост выбирает сторону, гость автоматически противоположная
        kb_h = InlineKeyboardMarkup([[
            InlineKeyboardButton('🦅 Орёл', callback_data=f'pvp_pick_{room_id}_o'),
            InlineKeyboardButton('🪙 Решка', callback_data=f'pvp_pick_{room_id}_r'),
        ]])
        try:
            await ctx.bot.send_message(
                host,
                header('🪙', 'МОНЕТКА') + f"\n\nСоперник: {pvp_user_label(uid)}\nВыбери сторону:",
                reply_markup=kb_h, parse_mode='HTML')
        except Exception:
            pass
        await qsopra_safe_edit(
            qr.message,
            header('🪙', 'МОНЕТКА') + f"\n\n"
            f"Ожидаем выбор стороны от {pvp_user_label(host)}…",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚔️ Арена', callback_data='menu_pvp')]]),
            parse_mode='HTML')
        try:
            await qr.answer('Жди выбор хоста')
        except Exception:
            pass
        return

    # dice / num — мгновенный ролл
    await pvp_resolve_auto(ctx, room_id)


async def pvp_pick(update, ctx, uid, room_id, pick):
    qr = update.callback_query
    rows = q(
        "SELECT host_id, guest_id, game, bet, status, host_pick, guest_pick "
        "FROM pvp_rooms WHERE room_id=?", (room_id,))
    if not rows:
        try:
            await qr.answer('Комната не найдена', show_alert=True)
        except Exception:
            pass
        return
    host, guest, game, bet, status, hp, gp = rows[0]
    if status not in ('playing', 'open'):
        try:
            await qr.answer('Игра уже окончена', show_alert=True)
        except Exception:
            pass
        return
    if uid not in (host, guest):
        try:
            await qr.answer('Ты не в этой игре', show_alert=True)
        except Exception:
            pass
        return

    if game == 'coin':
        if uid != host:
            try:
                await qr.answer('Сторону выбирает создатель комнаты', show_alert=True)
            except Exception:
                pass
            return
        if pick not in ('o', 'r'):
            return
        q("UPDATE pvp_rooms SET host_pick=? WHERE room_id=?", (pick, room_id), fetch=False)
        await pvp_resolve_coin(ctx, room_id)
        try:
            await qr.answer('Монетка подброшена!')
        except Exception:
            pass
        return

    if game == 'rps':
        if pick not in ('rock', 'paper', 'scissors'):
            return
        if uid == host:
            if hp:
                try:
                    await qr.answer('Уже выбран', show_alert=True)
                except Exception:
                    pass
                return
            q("UPDATE pvp_rooms SET host_pick=? WHERE room_id=?", (pick, room_id), fetch=False)
        else:
            if gp:
                try:
                    await qr.answer('Уже выбран', show_alert=True)
                except Exception:
                    pass
                return
            q("UPDATE pvp_rooms SET guest_pick=? WHERE room_id=?", (pick, room_id), fetch=False)
        try:
            await qr.answer('Ход принят')
        except Exception:
            pass
        await qsopra_safe_edit(
            qr.message,
            header('✂️', 'ХОД ПРИНЯТ') + "\n\nЖдём соперника…",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚔️ Арена', callback_data='menu_pvp')]]),
            parse_mode='HTML')
        # Проверяем оба хода
        rows2 = q("SELECT host_pick, guest_pick FROM pvp_rooms WHERE room_id=?", (room_id,))
        if rows2 and rows2[0][0] and rows2[0][1]:
            await pvp_resolve_rps(ctx, room_id)
        return


async def pvp_finish(ctx, room_id, winner, loser, bet, detail):
    pot, fee = pvp_pot(bet)
    q("UPDATE pvp_rooms SET status='done' WHERE room_id=?", (room_id,), fetch=False)
    if winner:
        # Ставки уже списаны у обоих; победителю банк
        safe_add_balance(winner, pot)
        try:
            quest_progress(winner, 'q_win3')
            check_ach(winner, 'duelist')
        except Exception:
            pass
        for pid, is_win in ((winner, True), (loser, False)):
            if not pid:
                continue
            try:
                if is_win:
                    await ctx.bot.send_message(
                        pid,
                        header('🏆', 'ПОБЕДА НА АРЕНЕ') + f"\n\n"
                        f"{detail}\n"
                        f"💵 Банк · <b>+{money(pot)}₽</b>\n"
                        f"🏛 Комиссия · {money(fee)}₽",
                        parse_mode='HTML')
                else:
                    await ctx.bot.send_message(
                        pid,
                        header('💀', 'ПОРАЖЕНИЕ НА АРЕНЕ') + f"\n\n"
                        f"{detail}\n"
                        f"💸 −{money(bet)}₽",
                        parse_mode='HTML')
            except Exception:
                pass
    else:
        # Ничья — вернуть ставки
        if winner is None and loser:
            pass
        rows = q("SELECT host_id, guest_id FROM pvp_rooms WHERE room_id=?", (room_id,))
        if rows:
            h, g = rows[0]
            return_bet(h, bet)
            if g:
                return_bet(g, bet)
            for pid in (h, g):
                if not pid:
                    continue
                try:
                    await ctx.bot.send_message(
                        pid,
                        header('🤝', 'НИЧЬЯ') + f"\n\n{detail}\nСтавки возвращены.",
                        parse_mode='HTML')
                except Exception:
                    pass


async def pvp_resolve_coin(ctx, room_id):
    rows = q(
        "SELECT host_id, guest_id, bet, host_pick FROM pvp_rooms WHERE room_id=?",
        (room_id,))
    if not rows:
        return
    host, guest, bet, hp = rows[0]
    flip = random.choice(['o', 'r'])
    flip_name = '🦅 Орёл' if flip == 'o' else '🪙 Решка'
    host_name = '🦅 Орёл' if hp == 'o' else '🪙 Решка'
    if hp == flip:
        winner, loser = host, guest
        detail = f"Выпало: {flip_name}\nХост выбрал {host_name} — победа!"
    else:
        winner, loser = guest, host
        detail = f"Выпало: {flip_name}\nХост выбрал {host_name} — проигрыш хоста."
    await pvp_finish(ctx, room_id, winner, loser, bet, detail)


async def pvp_resolve_rps(ctx, room_id):
    rows = q(
        "SELECT host_id, guest_id, bet, host_pick, guest_pick FROM pvp_rooms WHERE room_id=?",
        (room_id,))
    if not rows:
        return
    host, guest, bet, hp, gp = rows[0]
    names = {'rock': '🪨 Камень', 'paper': '📄 Бумага', 'scissors': '✂️ Ножницы'}
    beats = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
    detail = f"{pvp_user_label(host)}: {names.get(hp, hp)}\n{pvp_user_label(guest)}: {names.get(gp, gp)}"
    if hp == gp:
        await pvp_finish(ctx, room_id, None, host, bet, detail + "\nНичья!")
        return
    if beats.get(hp) == gp:
        await pvp_finish(ctx, room_id, host, guest, bet, detail)
    else:
        await pvp_finish(ctx, room_id, guest, host, bet, detail)


async def pvp_resolve_auto(ctx, room_id):
    rows = q(
        "SELECT host_id, guest_id, game, bet FROM pvp_rooms WHERE room_id=?",
        (room_id,))
    if not rows:
        return
    host, guest, game, bet = rows[0]
    if game == 'dice':
        h_roll = random.randint(1, 6)
        g_roll = random.randint(1, 6)
        detail = f"🎲 {pvp_user_label(host)}: <b>{h_roll}</b>\n🎲 {pvp_user_label(guest)}: <b>{g_roll}</b>"
        if h_roll > g_roll:
            await pvp_finish(ctx, room_id, host, guest, bet, detail)
        elif g_roll > h_roll:
            await pvp_finish(ctx, room_id, guest, host, bet, detail)
        else:
            await pvp_finish(ctx, room_id, None, host, bet, detail + "\nНичья!")
    else:  # num
        h_roll = random.randint(1, 100)
        g_roll = random.randint(1, 100)
        detail = f"🎯 {pvp_user_label(host)}: <b>{h_roll}</b>\n🎯 {pvp_user_label(guest)}: <b>{g_roll}</b>"
        if h_roll > g_roll:
            await pvp_finish(ctx, room_id, host, guest, bet, detail)
        elif g_roll > h_roll:
            await pvp_finish(ctx, room_id, guest, host, bet, detail)
        else:
            await pvp_finish(ctx, room_id, None, host, bet, detail + "\nНичья!")


async def pvp_quiz_send_question(ctx, room_id):
    st = active.get(f'quiz_{room_id}')
    if not st:
        return
    idx = st['idx']
    if idx >= len(st['qs']):
        await pvp_quiz_finish(ctx, room_id)
        return
    st['h_ans'] = None
    st['g_ans'] = None
    item = st['qs'][idx]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f'pvp_quiz_{room_id}_{idx}_{i}')]
        for i, opt in enumerate(item['opts'])
    ])
    txt = (
        header('🧠', f'ВОПРОС {idx + 1}/{len(st["qs"])}') + f"\n\n"
        f"{item['q']}\n\n"
        f"Банк · <b>{money(st['pot'])}₽</b>\n"
        f"Счёт · {pvp_user_label(st['host'])} {st['h_score']} : {st['g_score']} {pvp_user_label(st['guest'])}"
    )
    for pid in (st['host'], st['guest']):
        try:
            await ctx.bot.send_message(pid, txt, reply_markup=kb, parse_mode='HTML')
        except Exception:
            pass


async def pvp_quiz_answer(update, ctx, uid, room_id, qidx, opt):
    qr = update.callback_query
    st = active.get(f'quiz_{room_id}')
    if not st or qidx != st['idx']:
        try:
            await qr.answer('Этот вопрос уже не активен', show_alert=True)
        except Exception:
            pass
        return
    if uid == st['host']:
        if st['h_ans'] is not None:
            try:
                await qr.answer('Уже ответил')
            except Exception:
                pass
            return
        st['h_ans'] = opt
    elif uid == st['guest']:
        if st['g_ans'] is not None:
            try:
                await qr.answer('Уже ответил')
            except Exception:
                pass
            return
        st['g_ans'] = opt
    else:
        try:
            await qr.answer('Ты не в этой игре', show_alert=True)
        except Exception:
            pass
        return
    try:
        await qr.answer('Ответ принят')
    except Exception:
        pass
    try:
        await qr.edit_message_text('✅ Ответ принят. Ждём соперника…')
    except Exception:
        pass
    if st['h_ans'] is None or st['g_ans'] is None:
        return
    # оба ответили
    correct = st['qs'][qidx]['a']
    if st['h_ans'] == correct:
        st['h_score'] += 1
    if st['g_ans'] == correct:
        st['g_score'] += 1
    st['idx'] += 1
    if st['idx'] >= len(st['qs']):
        await pvp_quiz_finish(ctx, room_id)
    else:
        await pvp_quiz_send_question(ctx, room_id)


async def pvp_quiz_finish(ctx, room_id):
    st = active.pop(f'quiz_{room_id}', None)
    if not st:
        return
    host, guest = st['host'], st['guest']
    pot = st['pot']
    fee = int(pot * PVP_FEE)
    win_sum = pot - fee
    hs, gs = st['h_score'], st['g_score']
    detail = f"Счёт {hs} : {gs}\nБанк был {money(pot)}₽"
    q("UPDATE pvp_rooms SET status='done' WHERE room_id=?", (room_id,), fetch=False)
    if hs > gs:
        safe_add_balance(host, win_sum)
        try:
            await ctx.bot.send_message(host, header('🏆', 'БАНК ТВОЙ') + f"\n\n{detail}\n💵 +{money(win_sum)}₽", parse_mode='HTML')
            await ctx.bot.send_message(guest, header('💀', 'БАНК ПРОИГРАН') + f"\n\n{detail}", parse_mode='HTML')
        except Exception:
            pass
    elif gs > hs:
        safe_add_balance(guest, win_sum)
        try:
            await ctx.bot.send_message(guest, header('🏆', 'БАНК ТВОЙ') + f"\n\n{detail}\n💵 +{money(win_sum)}₽", parse_mode='HTML')
            await ctx.bot.send_message(host, header('💀', 'БАНК ПРОИГРАН') + f"\n\n{detail}", parse_mode='HTML')
        except Exception:
            pass
    else:
        # ничья — вернуть ставки
        return_bet(host, st['h_bet'])
        return_bet(guest, st['g_bet'])
        try:
            await ctx.bot.send_message(host, header('🤝', 'НИЧЬЯ') + f"\n\n{detail}\nСтавки возвращены.", parse_mode='HTML')
            await ctx.bot.send_message(guest, header('🤝', 'НИЧЬЯ') + f"\n\n{detail}\nСтавки возвращены.", parse_mode='HTML')
        except Exception:
            pass


async def pvp_cb(update, ctx):
    u = update.effective_user
    if not u:
        return
    uid = u.id
    qr = update.callback_query
    d = qr.data or ''
    ensure_user(u)
    if is_banned(u):
        return
    try:
        if d == 'menu_pvp':
            await pvp_menu(qr.message, uid)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'pvp_create':
            await pvp_create_menu(qr.message, uid)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('pvp_game_'):
            game = d[len('pvp_game_'):]
            await pvp_bet_menu(qr.message, uid, game)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('pvp_mk_'):
            parts = d.split('_')
            if len(parts) < 4:
                return
            game = parts[2]
            if game == 'bank' and parts[3] == 'allin':
                u = get_user(uid)
                bet = int(u[2] or 0) if u else 0
                if is_admin_by_id(uid):
                    bet = max(bet, PVP_MIN_BET)
            else:
                try:
                    bet = int(parts[3])
                except Exception:
                    try:
                        await qr.answer('Извините, не понял ставку', show_alert=True)
                    except Exception:
                        pass
                    return
            await pvp_make_room(update, ctx, uid, game, bet)
            return
        if d.startswith('pvp_quiz_'):
            # pvp_quiz_{room}_{qidx}_{opt}
            parts = d.split('_')
            try:
                rid, qidx, opt = int(parts[2]), int(parts[3]), int(parts[4])
            except Exception:
                try:
                    await qr.answer('Извините, что-то пошло не так', show_alert=True)
                except Exception:
                    pass
                return
            await pvp_quiz_answer(update, ctx, uid, rid, qidx, opt)
            return
        if d.startswith('pvp_cancel_'):
            rid = int(d.rsplit('_', 1)[1])
            await pvp_cancel_room(update, ctx, uid, rid)
            return
        if d.startswith('pvp_join_'):
            rid = int(d.rsplit('_', 1)[1])
            await pvp_join_room(update, ctx, uid, rid)
            return
        if d.startswith('pvp_pick_'):
            # pvp_pick_{rid}_{pick}
            parts = d.split('_')
            rid = int(parts[2])
            pick = parts[3]
            await pvp_pick(update, ctx, uid, rid, pick)
            return
    except Exception as e:
        print('PVP ERR:', repr(e))
        try:
            await qr.answer('Ошибка арены', show_alert=True)
        except Exception:
            pass


async def duel_menu(message, uid):
    rows = q('SELECT user_id,username FROM users WHERE user_id != ? AND banned=0 ORDER BY balance DESC LIMIT 20', (uid,))
    kb = []
    for tid, name in rows:
        label = f'👤 @{name}' if name else f'👤 id{tid}'
        kb.append([InlineKeyboardButton(label, callback_data=f'duel_t_{tid}')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_games')])
    if len(kb) == 1:
        await message.reply_text('❌ Нет игроков', reply_markup=back_kb('menu_games')); return
    await qsopra_safe_edit(message, header('⚔️', 'ДУЭЛЬ') + "\n\nВыбери противника:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')


async def duel_pick(update, ctx):
    u = update.effective_user
    if not u: return
    qr = update.callback_query
    tid = int(qr.data.split('_')[2])
    tu = get_user(tid)
    if not tu:
        try: await qr.answer('Не найден')
        except Exception: pass
        return
    ctx.user_data['duel_target'] = tid
    try: await qr.answer()
    except Exception: pass
    await qsopra_safe_edit(qr.message, f"⚔️ Дуэль с @{tu[1] or tid}\n\nВыбери ставку:",
        reply_markup=bet_kb('duel'), parse_mode='HTML')


async def do_duel_challenge(update, ctx, uid, tid, amount):
    tu = get_user(tid)
    if not tu: return
    ok, msg = reserve_bet(uid, amount)
    if not ok:
        await qsopra_safe_edit(update.callback_query.message, msg, reply_markup=back_kb('menu_games')); return
    if tid in duels:
        return_bet(uid, amount)
        try: await update.callback_query.answer('Уже вызов', show_alert=True)
        except Exception: pass
        return
    duels[tid] = {'from': uid, 'bet': amount, 'name_from': update.effective_user.first_name}
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ Принять', callback_data=f'duel_yes_{uid}'),
        InlineKeyboardButton('❌ Отклонить', callback_data=f'duel_no_{uid}')]])
    try:
        await ctx.bot.send_message(tid,
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n👤 {update.effective_user.first_name}\n💵 {money(amount)}₽",
            reply_markup=kb, parse_mode='HTML')
    except Exception: pass
    await qsopra_safe_edit(update.callback_query.message,
        f"⚔️ Вызов отправлен @{tu[1] or tid}",
        reply_markup=back_kb('menu_games'), parse_mode='HTML')


async def duel_accept(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query; d = qr.data
    if d.startswith('duel_no_'):
        from_id = int(d.split('_')[2]); duel = duels.pop(uid, None)
        if duel: return_bet(from_id, duel['bet'])
        await qsopra_safe_edit(qr.message, '❌ Отклонено')
        try: await ctx.bot.send_message(from_id, '❌ Отклонена')
        except Exception: pass
        try: await qr.answer()
        except Exception: pass
        return
    if d.startswith('duel_yes_'):
        from_id = int(d.split('_')[2]); duel = duels.pop(uid, None)
        if not duel:
            try: await qr.answer('Не найдена', show_alert=True)
            except Exception: pass
            return
        bet = duel['bet']
        ok, msg = reserve_bet(uid, bet)
        if not ok:
            return_bet(from_id, bet)
            try: await qr.answer(msg, show_alert=True)
            except Exception: pass
            return
        winner = random.choice([uid, from_id])
        loser = uid if winner == from_id else from_id
        win_amount = bet * 2
        grant_win(winner, win_amount); register_loss(loser)
        quest_progress(winner, 'q_win3'); check_ach(winner, 'duelist')
        try: await qr.answer()
        except Exception: pass
        await qsopra_safe_edit(qr.message,
            f"⚔️ <b>ДУЭЛЬ!</b>\n\n🏆 {'Вы' if winner == uid else 'Противник'}\n💵 <b>+{money(win_amount)}₽</b>",
            parse_mode='HTML')
        try:
            await ctx.bot.send_message(from_id,
                f"⚔️ <b>ДУЭЛЬ</b>\n🏆 {'Победа!' if winner == from_id else 'Проигрыш'}\n"
                f"💵 {'+' if winner == from_id else '-'}{money(bet)}₽", parse_mode='HTML')
        except Exception: pass


# ═══════════════════════════════════════════════════════════
# КЕЙСЫ
# ═══════════════════════════════════════════════════════════
CASES = {
    'bronze': {'name': '🥉 Бронзовый', 'cost': 2_500, 'drops': [
        ('💀 Пусто', 58, 0), ('🪙 x1.3', 22, 1.3), ('💵 x1.8', 12, 1.8),
        ('💰 x2.5', 5.5, 2.5), ('💎 x4', 2, 4), ('👑 x8', 0.5, 8)]},
    'silver': {'name': '🥈 Серебряный', 'cost': 12_000, 'drops': [
        ('💀 Пусто', 52, 0), ('🪙 x1.4', 24, 1.4), ('💵 x2', 13, 2),
        ('💰 x3', 7, 3), ('💎 x5', 3, 5), ('👑 x9', 0.8, 9), ('🏆 x30', 0.2, 30)]},
    'gold': {'name': '🥇 Золотой', 'cost': 45_000, 'drops': [
        ('💀 Пусто', 48, 0), ('💵 x1.8', 24, 1.8), ('💰 x2.5', 14, 2.5),
        ('💎 x4', 8, 4), ('👑 x8', 4.5, 8), ('🔥 x15', 1.2, 15), ('🏆 x60', 0.3, 60)]},
    'diamond': {'name': '💎 Алмазный', 'cost': 180_000, 'drops': [
        ('💀 Пусто', 42, 0), ('💰 x2.5', 26, 2.5), ('💎 x4', 16, 4),
        ('👑 x8', 10, 8), ('🔥 x18', 4, 18), ('🏆 x50', 1.5, 50), ('🌟 x200', 0.5, 200)]},
}


async def open_case(query_msg, uid, key):
    case = CASES.get(key)
    if not case: return
    ok, msg = reserve_bet(uid, case['cost'])
    if not ok:
        await qsopra_safe_edit(query_msg, msg, reply_markup=back_kb('menu_cases')); return
    total = sum(d[1] for d in case['drops'])
    r = random.uniform(0, total); acc = 0; chosen = case['drops'][0]
    for d in case['drops']:
        acc += d[1]
        if r <= acc: chosen = d; break
    label, _, mult = chosen
    crystal_bonus = random.randint(1, 5) if random.random() < 0.05 else 0
    if mult > 0:
        win = int(case['cost'] * mult); grant_win(uid, win); quest_progress(uid, 'q_win3')
        if crystal_bonus: grant_crystals(uid, crystal_bonus)
        txt = header(case['name'].split()[0], case['name'].split()[1]) + f"\n\n🎁 {label}\n💵 <b>+{money(win)}₽</b>"
        if crystal_bonus: txt += f"\n💎 <b>+{crystal_bonus} кристаллов!</b>"
        await qsopra_safe_edit(query_msg, txt, reply_markup=back_kb('menu_cases'), parse_mode='HTML')
    else:
        register_loss(uid)
        await qsopra_safe_edit(query_msg,
            header(case['name'].split()[0], case['name'].split()[1]) + f"\n\n🎁 {label}\n💀 <b>-{money(case['cost'])}₽</b>",
            reply_markup=back_kb('menu_cases'), parse_mode='HTML')


def cases_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🥉 Бронза · 2 500₽', callback_data='case_bronze')],
        [InlineKeyboardButton('🥈 Серебро · 12 000₽', callback_data='case_silver')],
        [InlineKeyboardButton('🥇 Золото · 45 000₽', callback_data='case_gold')],
        [InlineKeyboardButton('💎 Алмаз · 180 000₽', callback_data='case_diamond')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')],
    ])


# ═══════════════════════════════════════════════════════════
# ОБМЕН / VIP
# ═══════════════════════════════════════════════════════════
EXCHANGE_RATES = {
    'cr_3':   {'cost': 3,   'get_coins': 25_000},
    'cr_10':  {'cost': 10,  'get_coins': 100_000},
    'cr_50':  {'cost': 50,  'get_coins': 600_000},
    'cr_100': {'cost': 100, 'get_coins': 1_500_000},
    'cr_500': {'cost': 500, 'get_coins': 10_000_000},
}

# Покупка энергии за монеты (дорого)
ENERGY_PACKS = {
    'en_10':  {'energy': 10,  'cost': 8_000_000,   'label': '+10⚡'},
    'en_25':  {'energy': 25,  'cost': 18_000_000,  'label': '+25⚡'},
    'en_50':  {'energy': 50,  'cost': 35_000_000,  'label': '+50⚡'},
    'en_full': {'energy': -1, 'cost': 60_000_000,  'label': 'До максимума'},  # -1 = до личного max
}


async def exchange_menu(message, uid):
    restore_energy(uid)
    u = get_user(uid)
    en = "∞" if is_admin_by_id(uid) else f"{u[16]}/{user_energy_max(uid)}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('3 💎 → 25 000₽', callback_data='ex_cr_3')],
        [InlineKeyboardButton('10 💎 → 100 000₽', callback_data='ex_cr_10')],
        [InlineKeyboardButton('50 💎 → 600 000₽', callback_data='ex_cr_50')],
        [InlineKeyboardButton('100 💎 → 1 500 000₽', callback_data='ex_cr_100')],
        [InlineKeyboardButton('500 💎 → 10 000 000₽', callback_data='ex_cr_500')],
        [InlineKeyboardButton('⚡ Купить энергию', callback_data='energy_shop')],
        [InlineKeyboardButton('👑 VIP-магазин', callback_data='vip_menu')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='menu_main')],
    ])
    cr_show = display_crystals(uid, u[15] if u else 0)
    bal_show = display_balance(uid, u[2] if u else 0)
    txt = (header('💎', 'ОБМЕННИК') + f"\n\n"
           f"💎 Кристаллы · <b>{cr_show}</b>\n"
           f"💰 Баланс · <b>{bal_show}₽</b>\n"
           f"⚡ Энергия · <b>{en}</b>\n\n"
           f"Нажми пакет — кристаллы сразу обменяются на монеты.")
    await qsopra_safe_edit(message, txt, reply_markup=kb, parse_mode='HTML')


async def energy_shop_menu(message, uid):
    restore_energy(uid)
    u = get_user(uid)
    emax = user_energy_max(uid)
    elvl = user_energy_level(uid)
    lvl_info = ENERGY_LEVELS.get(elvl, ENERGY_LEVELS[0])
    if is_admin_by_id(uid):
        en_line = "⚡ Энергия: <b>∞</b> (персонал)"
    else:
        ebar = progress_bar(u[16], emax, 8, '🟦', '⬛')
        en_line = (
            f"⚡ Энергия: <b>{u[16]}/{emax}</b>\n{ebar}\n"
            f"🔋 Уровень: <b>{elvl}</b> · {lvl_info['name']}"
        )
    rows = []
    for key, pack in ENERGY_PACKS.items():
        rows.append([InlineKeyboardButton(
            f"{pack['label']} · {money(pack['cost'])}₽",
            callback_data=f'buy_en_{key}')])
    next_lvl = elvl + 1
    if next_lvl in ENERGY_LEVELS and not is_admin_by_id(uid):
        nxt = ENERGY_LEVELS[next_lvl]
        rows.append([InlineKeyboardButton(
            f"⬆️ Прокачать → {nxt['max']}⚡ · {money(nxt['price'])}₽",
            callback_data='en_upgrade')])
    elif elvl >= max(ENERGY_LEVELS.keys()):
        rows.append([InlineKeyboardButton('✅ Макс. прокачка', callback_data='noop')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_exchange')])
    txt = (
        header('⚡', 'ЭНЕРГИЯ') + f"\n\n"
        f"{en_line}\n"
        f"💰 Баланс: <b>{display_balance(uid, u[2])}₽</b>\n\n"
        f"<b>Покупка</b> — дорогое пополнение запаса.\n"
        f"<b>Прокачка</b> — навсегда увеличивает максимум."
    )
    await qsopra_safe_edit(message, txt, reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')


async def buy_energy_cb(update, ctx):
    u = update.effective_user
    if not u:
        return
    uid = u.id
    qr = update.callback_query
    d = qr.data or ''

    if d == 'en_upgrade':
        if is_admin_by_id(uid):
            try:
                await qr.answer('Персонал не нуждается в прокачке', show_alert=True)
            except Exception:
                pass
            return
        elvl = user_energy_level(uid)
        next_lvl = elvl + 1
        if next_lvl not in ENERGY_LEVELS:
            try:
                await qr.answer('Уже максимальный уровень', show_alert=True)
            except Exception:
                pass
            return
        nxt = ENERGY_LEVELS[next_lvl]
        price = nxt['price']
        user = get_user(uid)
        if not user or user[2] < price:
            try:
                await qr.answer(f'Нужно {money(price)}₽', show_alert=True)
            except Exception:
                pass
            return
        changed = exec_change(
            'UPDATE users SET balance=balance-?, energy_lvl=? WHERE user_id=? AND banned=0 AND balance>=?',
            (price, next_lvl, uid, price))
        if not changed:
            try:
                await qr.answer('❌ Недостаточно средств', show_alert=True)
            except Exception:
                pass
            return
        try:
            await qr.answer(
                f'✅ Уровень {next_lvl}! Максимум {nxt["max"]}⚡',
                show_alert=True)
        except Exception:
            pass
        await energy_shop_menu(qr.message, uid)
        return

    # buy_en_en_10 → key en_10
    key = d[len('buy_en_'):] if d.startswith('buy_en_') else ''
    pack = ENERGY_PACKS.get(key)
    if not pack:
        try:
            await qr.answer('Пакет не найден', show_alert=True)
        except Exception:
            pass
        return
    if is_admin_by_id(uid):
        try:
            await qr.answer('У персонала энергия бесконечна', show_alert=True)
        except Exception:
            pass
        return
    restore_energy(uid)
    user = get_user(uid)
    if not user:
        return
    emax = user_energy_max(uid)
    if user[16] >= emax:
        try:
            await qr.answer('Энергия уже полная', show_alert=True)
        except Exception:
            pass
        return
    cost = pack['cost']
    if user[2] < cost:
        try:
            await qr.answer(f'Нужно {money(cost)}₽', show_alert=True)
        except Exception:
            pass
        return
    gain = pack['energy']
    if gain < 0:
        actual = emax - user[16]
    else:
        actual = min(gain, emax - user[16])
    if actual <= 0:
        try:
            await qr.answer('Энергия уже полная', show_alert=True)
        except Exception:
            pass
        return
    changed = exec_change(
        'UPDATE users SET balance=balance-?, energy=energy+? WHERE user_id=? AND banned=0 AND balance>=?',
        (cost, actual, uid, cost))
    if not changed:
        try:
            await qr.answer('❌ Недостаточно средств', show_alert=True)
        except Exception:
            pass
        return
    q('UPDATE users SET energy=? WHERE user_id=? AND energy>?',
      (emax, uid, emax), fetch=False)
    try:
        await qr.answer(f'✅ +{actual}⚡ за {money(cost)}₽', show_alert=True)
    except Exception:
        pass
    await energy_shop_menu(qr.message, uid)


async def exchange_cb(update, ctx):
    u = update.effective_user
    if not u:
        return
    uid = u.id
    qr = update.callback_query
    d = (qr.data or '') if qr else ''

    if d == 'vip_menu':
        await vip_menu(qr.message, uid)
        try:
            await qr.answer()
        except Exception:
            pass
        return
    if d == 'energy_shop':
        await energy_shop_menu(qr.message, uid)
        try:
            await qr.answer()
        except Exception:
            pass
        return

    # callback: ex_cr_10 → key cr_10
    key = None
    if d.startswith('ex_'):
        key = d[3:]  # cr_10
    elif d.startswith('exch_'):
        key = d[5:]
    rate = EXCHANGE_RATES.get(key) if key else None
    if not rate:
        try:
            await qr.answer('Пакет не найден', show_alert=True)
        except Exception:
            pass
        return

    try:
        ok, msg = exchange_crystals_to_coins(uid, rate['cost'], rate['get_coins'])
        if not ok:
            try:
                await qr.answer(f'❌ {msg}', show_alert=True)
            except Exception:
                pass
            return
        try:
            await qr.answer(f'✅ {msg}', show_alert=True)
        except Exception:
            pass
        try:
            await exchange_menu(qr.message, uid)
        except Exception:
            pass
    except Exception as e:
        print('EXCHANGE ERR:', repr(e))
        try:
            if _is_db_transient(e):
                await qr.answer('⏳ База занята, нажми ещё раз', show_alert=True)
            else:
                await qr.answer('❌ Ошибка обмена, попробуй позже', show_alert=True)
        except Exception:
            pass


async def vip_menu(message, uid):
    u = get_user(uid); vip = u[18]; rows = []
    for lvl, info in VIP_LEVELS.items():
        if lvl <= vip or lvl == 0: continue
        rows.append([InlineKeyboardButton(
            f"{info['emoji']} {info['name']} · x{info['bonus']} · {info['price']}💎",
            callback_data=f'vip_buy_{lvl}')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_exchange')])
    cur = VIP_LEVELS.get(vip, VIP_LEVELS[0])
    await qsopra_safe_edit(message,
        header('👑', 'VIP-МАГАЗИН') + f"\n\n"
        f"Твой VIP · {cur['emoji']} <b>{cur['name']}</b>\n"
        f"Бонус к выигрышу · <b>x{cur['bonus']}</b>\n"
        f"💎 Кристаллов · <b>{display_crystals(uid, u[15])}</b>\n\n"
        f"Прокачай VIP для большего бонуса!",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')


async def vip_buy_cb(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    try: lvl = int(qr.data.split('_')[-1])
    except Exception:
        try: await qr.answer()
        except Exception: pass
        return
    info = VIP_LEVELS.get(lvl)
    if not info:
        try: await qr.answer('Ошибка')
        except Exception: pass
        return
    cur = get_user(uid)
    if cur[18] >= lvl:
        try: await qr.answer('Уже есть', show_alert=True)
        except Exception: pass
        return
    if not spend_crystals(uid, info['price']):
        try: await qr.answer('❌ Недостаточно кристаллов', show_alert=True)
        except Exception: pass
        return
    q('UPDATE users SET vip=? WHERE user_id=?', (lvl, uid), fetch=False)
    check_ach(uid)
    try: await qr.answer(f'✅ VIP {info["name"]}!', show_alert=True)
    except Exception: pass
    await vip_menu(qr.message, uid)


# ═══════════════════════════════════════════════════════════
# БОНУС / ПЕРЕВОД / КВЕСТ / МАГАЗИН
# ═══════════════════════════════════════════════════════════
async def send_bonus(update):
    u = get_user(update.effective_user.id)
    now = datetime.now()
    if u[8]:
        try:
            last = datetime.fromisoformat(u[8])
            if now - last < timedelta(hours=24):
                left = timedelta(hours=24) - (now - last)
                h = int(left.total_seconds() // 3600); m = int((left.total_seconds() % 3600) // 60)
                await update.message.reply_text(f"🎁 Бонус через <b>{h}ч {m}м</b>",
                    reply_markup=back_kb('menu_main'), parse_mode='HTML')
                return
        except Exception: pass
    streak = u[19]
    if u[20]:
        try:
            last_dt = datetime.fromisoformat(u[20])
            streak = min(streak + 1, 30) if (now - last_dt).days <= 2 else 1
        except Exception: streak = 1
    else: streak = 1
    bonus = DAILY_BONUS + (streak * 100)
    cb = 1 + (streak // 5)
    q('UPDATE users SET balance=balance+?, last_bonus=?, daily_streak=?, last_daily=? WHERE user_id=?',
      (bonus, now.isoformat(), streak, now.isoformat(), u[0]), fetch=False)
    grant_crystals(u[0], cb); add_xp(u[0], 20)
    await update.message.reply_text(
        header('🎁', 'БОНУС') + f"\n\n"
        f"🔥 Streak · <b>{streak} дней</b>\n\n"
        f"💵 Получено · <b>+{money(bonus)}₽</b>\n"
        f"💎 Кристаллов · <b>+{cb}</b>\n"
        f"✨ Опыта · +20",
        reply_markup=back_kb('menu_main'), parse_mode='HTML')


async def bonus_cb(update, ctx):
    qr = update.callback_query
    u = get_user(update.effective_user.id)
    now = datetime.now()
    if u[8]:
        try:
            last = datetime.fromisoformat(u[8])
            if now - last < timedelta(hours=24):
                left = timedelta(hours=24) - (now - last)
                h = int(left.total_seconds() // 3600); m = int((left.total_seconds() % 3600) // 60)
                try: await qr.answer(f"Через {h}ч {m}м", show_alert=True)
                except Exception: pass
                return
        except Exception: pass
    streak = u[19]
    if u[20]:
        try:
            last_dt = datetime.fromisoformat(u[20])
            streak = min(streak + 1, 30) if (now - last_dt).days <= 2 else 1
        except Exception: streak = 1
    else: streak = 1
    bonus = DAILY_BONUS + (streak * 100)
    cb = 1 + (streak // 5)
    q('UPDATE users SET balance=balance+?, last_bonus=?, daily_streak=?, last_daily=? WHERE user_id=?',
      (bonus, now.isoformat(), streak, now.isoformat(), u[0]), fetch=False)
    grant_crystals(u[0], cb); add_xp(u[0], 20)
    try: await qr.answer(f'✅ Streak {streak}! +{money(bonus)}₽ +{cb}💎', show_alert=True)
    except Exception: pass


def transfer_money(uid, tid, amount):
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, '❌ Некорректная сумма'
    if uid == tid:
        return False, '❌ Себе нельзя'
    if amount < 1:
        return False, '❌ Сумма должна быть > 0'
    if amount > MAX_BALANCE:
        amount = MAX_BALANCE
    u = get_user(uid)
    tu = get_user(tid)
    if not u or not tu or tu[3]:
        return False, '❌ Получатель недоступен'
    if not is_admin_by_id(uid):
        changed = exec_change(
            'UPDATE users SET balance=balance-? WHERE user_id=? AND banned=0 AND balance>=?',
            (amount, uid, amount))
        if not changed:
            fresh = get_user(uid)
            return False, f'❌ У тебя {money(fresh[2] if fresh else 0)}₽'
    safe_add_balance(tid, amount)
    name = f"@{tu[1]}" if tu[1] else f"id{tu[0]}"
    return True, f'✅ <b>Перевод!</b>\n💸 {money(amount)}₽ → {name}'


async def transfer_pick(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query; d = qr.data
    if d == 'cancel_state':
        ctx.user_data['transfer_target'] = None
        await qsopra_safe_edit(qr.message, '❌ Отменено')
        try: await qr.answer()
        except Exception: pass
        return
    tid = int(d.split('_')[1])
    tu = get_user(tid)
    if not tu or tu[3]:
        try: await qr.answer('Недоступен', show_alert=True)
        except Exception: pass
        return
    u2 = get_user(uid); is_adm = is_admin_by_id(uid)
    rows = []
    for b in BETS:
        if not is_adm and b > u2[2]: continue
        rows.append([InlineKeyboardButton(f'💸 {money(b)}₽', callback_data=f'trsend_{tid}_{b}')])
    if not is_adm and u2[2] > 0:
        rows.append([InlineKeyboardButton(f'💰 ВСЁ ({money(u2[2])}₽)', callback_data=f'trsend_{tid}_all')])
    rows.append([InlineKeyboardButton('✏️ Своя сумма', callback_data=f'trsend_{tid}_custom')])
    rows.append([InlineKeyboardButton('⬅️ Назад', callback_data='menu_transfer')])
    name = f"@{tu[1]}" if tu[1] else f"id{tu[0]}"
    try: await qr.answer()
    except Exception: pass
    await qsopra_safe_edit(qr.message,
        f"💸 <b>Перевод</b>\n\n👤 <b>{name}</b>\n💰 У него · <b>{display_balance(tid, tu[2])}₽</b>\n\nВыбери сумму:",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML')


async def transfer_send(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    parts = qr.data.split('_'); tid = int(parts[1]); val = parts[2]
    u2 = get_user(uid); tu = get_user(tid)
    if not u2 or not tu:
        try: await qr.answer('Ошибка', show_alert=True)
        except Exception: pass
        return
    is_adm = is_admin_by_id(uid)
    if val == 'all': amt = u2[2]
    elif val == 'custom':
        ctx.user_data['transfer_target'] = tid
        ctx.user_data['custom_amount_target'] = {
            'target': 'transfer', 'user_id': tid, 'game': None}
        # сбросить чужие стейты, чтобы не перехватили ввод
        ctx.user_data.pop('rl_wait_number', None)
        ctx.user_data.pop('adm_state', None)
        await qsopra_safe_edit(
            qr.message,
            '✍️ <b>Введи сумму перевода</b>\n'
            '<i>Примеры: 1к · 10к · 1кк · 10кк · 500 · гугл</i>\n'
            'или «отмена»',
            parse_mode='HTML')
        try:
            await qr.answer()
        except Exception:
            pass
        return
    else: amt = int(val)
    if amt < 1:
        try: await qr.answer('Мин 1', show_alert=True)
        except Exception: pass
        return
    ok, result = transfer_money(uid, tid, amt)
    if not ok:
        try: await qr.answer(result.replace('<b>', '').replace('</b>', ''), show_alert=True)
        except Exception: pass
        return
    try: await qr.answer()
    except Exception: pass
    await qsopra_safe_edit(qr.message, result, reply_markup=back_kb('menu_main'), parse_mode='HTML')
    try: await ctx.bot.send_message(tid, f'💰 <b>+{money(amt)}₽</b>', parse_mode='HTML')
    except Exception: pass


async def try_transfer(update, ctx):
    u = update.effective_user
    if not u:
        return False
    uid = u.id
    tid = ctx.user_data.get('transfer_target')
    if not tid:
        return False
    txt = (update.message.text or '').strip()
    low = txt.lower()
    if low in ('отмена', 'cancel', '/cancel'):
        ctx.user_data['transfer_target'] = None
        await update.message.reply_text('❌ Отменено')
        return True
    amt = parse_amount_text(txt, minimum=1)
    if amt is None:
        await update.message.reply_text(
            '❌ Сумма или «отмена»\n'
            '<i>Примеры: 500, 10к, 1кк, 2ккк, гугл</i>',
            parse_mode='HTML')
        return True
    ctx.user_data['transfer_target'] = None
    ok, result = transfer_money(uid, tid, amt)
    await update.message.reply_text(result, reply_markup=MAIN_KB, parse_mode='HTML')
    if ok:
        try:
            await ctx.bot.send_message(tid, f'💰 <b>+{money(amt)}₽</b>', parse_mode='HTML')
        except Exception:
            pass
    return True


async def quest_cb(update, ctx):
    qr = update.callback_query; uid = update.effective_user.id
    qid = qr.data.split('_', 1)[1]
    ok, res = claim_quest(uid, qid)
    if ok:
        try: await qr.answer(f"✅ +{money(res)}₽ +1💎", show_alert=True)
        except Exception: pass
        try: await qr.message.edit_reply_markup(reply_markup=quests_kb(uid))
        except Exception: pass
    else:
        try: await qr.answer(res, show_alert=True)
        except Exception: pass


async def shop_cb(update, ctx):
    qr = update.callback_query; uid = update.effective_user.id
    key = qr.data[4:]
    t = TITLES.get(key)
    if not t:
        try: await qr.answer('Нет')
        except Exception: pass
        return
    u = get_user(uid)
    if is_admin_by_id(uid):
        q('UPDATE users SET title=? WHERE user_id=?', (key, uid), fetch=False)
        try: await qr.answer(f"✅ {t['name']}", show_alert=True)
        except Exception: pass
        try: await qr.message.edit_reply_markup(reply_markup=shop_kb(uid))
        except Exception: pass
        return
    if u[2] < t['price']:
        try: await qr.answer(f"❌ Нужно {money(t['price'])}₽", show_alert=True)
        except Exception: pass
        return
    q('UPDATE users SET balance=balance-?, title=? WHERE user_id=?', (t['price'], key, uid), fetch=False)
    check_ach(uid, 'shopaholic')
    try: await qr.answer('✅', show_alert=True)
    except Exception: pass
    try: await qr.message.edit_reply_markup(reply_markup=shop_kb(uid))
    except Exception: pass


# ═══════════════════════════════════════════════════════════
# АДМИНКА / МОДЕРАЦИЯ / ВЛАДЕЛЕЦ
# ═══════════════════════════════════════════════════════════
def admin_header(status=None):
    status = status or ('🟢 Онлайн' if not maintenance_on() else '🟠 Обслуживание')
    return header('👑', 'QSOPRA ADMIN') + f"\n{status}"


def mod_header():
    return header('🛡', 'QSOPRA MODERATOR')


def owner_header():
    return header('🌟', 'QSOPRA OWNER')


def adm_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Статистика', callback_data='adm_stats'),
         InlineKeyboardButton('👥 Игроки', callback_data='adm_users_0')],
        [InlineKeyboardButton('👑 Админы', callback_data='adm_admin_menu'),
         InlineKeyboardButton('🛡 Модераторы', callback_data='adm_mod_menu')],
        [InlineKeyboardButton('🎫 Промокоды', callback_data='adm_promos'),
         InlineKeyboardButton('💰 Выдать всем', callback_data='adm_give_all')],
        [InlineKeyboardButton('📢 Рассылка', callback_data='adm_bc'),
         InlineKeyboardButton('🔧 Обслуживание', callback_data='adm_maint')],
        [InlineKeyboardButton('🔄 Обновить', callback_data='adm_main'),
         InlineKeyboardButton('❌ Закрыть', callback_data='adm_close')],
    ])


def mod_main_kb():
    """Ограниченное меню модератора."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Статистика', callback_data='mod_stats'),
         InlineKeyboardButton('👥 Игроки', callback_data='mod_users_0')],
        [InlineKeyboardButton('💰 Выдать (лимит)', callback_data='mod_give_menu')],
        [InlineKeyboardButton('❌ Закрыть', callback_data='adm_close')],
    ])


def owner_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Статистика', callback_data='adm_stats'),
         InlineKeyboardButton('🛡 Персонал', callback_data='adm_main')],
        [InlineKeyboardButton('🌟 Выдача овнера', callback_data='owner_priv_menu'),
         InlineKeyboardButton('💰 Экономика', callback_data='owner_eco_menu')],
        [InlineKeyboardButton('💜 Донаты Boosty', callback_data='donat_owner'),
         InlineKeyboardButton('📢 Рассылка', callback_data='adm_bc')],
        [InlineKeyboardButton('💥 Вайп', callback_data='owner_wipe'),
         InlineKeyboardButton('🔧 Обслуживание', callback_data='adm_maint')],
        [InlineKeyboardButton('🏰 Кланы', callback_data='menu_clans'),
         InlineKeyboardButton('❌ Закрыть', callback_data='adm_close')],
    ])


def owner_eco_kb():
    """Панель экономики владельца: выдача / снятие / кристаллы."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ Выдать всем ₽', callback_data='owner_give_all_menu'),
         InlineKeyboardButton('➖ Снять со всех ₽', callback_data='owner_take_all_menu')],
        [InlineKeyboardButton('➕ Выдать игроку ₽', callback_data='owner_give_menu'),
         InlineKeyboardButton('➖ Снять с игрока ₽', callback_data='owner_take_menu')],
        [InlineKeyboardButton('💎 Выдать кристаллы', callback_data='owner_cr_menu'),
         InlineKeyboardButton('💎 Снять кристаллы', callback_data='owner_cr_take_menu')],
        [InlineKeyboardButton('💎 Кристаллы всем', callback_data='owner_cr_all_menu')],
        [InlineKeyboardButton('✏️ Установить баланс', callback_data='owner_set_menu'),
         InlineKeyboardButton('⚡ +Энергия игроку', callback_data='owner_en_menu')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='owner_menu')],
    ])


OWNER_CR_PACKS = [10, 50, 100, 500, 1000, 5000, 10000]
OWNER_MONEY_PACKS = [10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]


def adm_users_kb(page=0):
    page = max(0, int(page))
    rows = q('SELECT user_id,username,balance,banned FROM users ORDER BY balance DESC, user_id ASC')
    total = len(rows); pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE); page = min(page, pages - 1)
    chunk = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    kb = []
    for uid, name, bal, ban in chunk:
        mark = '🚫' if ban else ('👑' if is_admin_by_id(uid) else '👤')
        label_name = f'@{name}' if name else f'id{uid}'
        kb.append([InlineKeyboardButton(f'{mark} {label_name} · {display_balance(uid, bal)}₽', callback_data=f'adm_u_{uid}')])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton('⬅️', callback_data=f'adm_users_{page-1}'))
    if page + 1 < pages: nav.append(InlineKeyboardButton('➡️', callback_data=f'adm_users_{page+1}'))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton(f'📄 {page+1}/{pages}', callback_data='noop')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='adm_main')])
    return InlineKeyboardMarkup(kb)


def adm_user_card_kb(uid):
    u = get_user(uid)
    if not u: return back_kb('adm_users_0')
    banned = u[3] == 1; admin = is_admin_by_id(uid)
    is_main = (MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID) or (u[1] and u[1].lower() == MAIN_ADMIN.lower())
    admin_cb = 'noop' if is_main else (f'adm_revoke_{uid}' if admin else f'adm_promote_{uid}')
    ban_cb = 'noop' if is_main else (f'adm_unban_{uid}' if banned else f'adm_ban_{uid}')
    del_cb = 'noop' if is_main else f'adm_del_{uid}'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💰 Пополнить', callback_data=f'adm_give_{uid}'),
         InlineKeyboardButton('✏️ Установить', callback_data=f'adm_set_{uid}')],
        [InlineKeyboardButton('💎 Кристаллы', callback_data=f'adm_cr_{uid}')],
        [InlineKeyboardButton('👑 Сделать админом' if not admin else '❌ Снять',
                              callback_data=admin_cb)],
        [InlineKeyboardButton('✅ Разбан' if banned else '🚫 Бан', callback_data=ban_cb)],
        [InlineKeyboardButton('🗑 Удалить', callback_data=del_cb)],
        [InlineKeyboardButton('⬅️ Назад', callback_data='adm_users_0')],
    ])


def adm_user_card_text(uid):
    u = get_user(uid)
    if not u: return '❌ Не найден'
    total = u[4] + u[5]; wr = round(u[4] / total * 100, 1) if total else 0
    adm = '👑 ДА' if is_admin_by_id(uid) else '❌ НЕТ'
    bal_txt = display_balance(uid, u[2]); cr_txt = display_crystals(uid, u[15])
    vip = VIP_LEVELS.get(u[18], VIP_LEVELS[0])
    main = ' 🌟' if ((MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID) or (u[1] and u[1].lower() == MAIN_ADMIN.lower())) else ''
    name = f'@{u[1]}' if u[1] else f'id{u[0]}'
    return (f'👤 <b>{name}</b>{main}\n<code>{u[0]}</code>\n\n'
            f'💰 Баланс · <b>{bal_txt}₽</b>\n'
            f'💎 Кристаллы · <b>{cr_txt}</b>\n'
            f'{vip["emoji"]} VIP · <b>{vip["name"]}</b>\n'
            f'⚡ Энергия · <b>{u[16]}/{user_energy_max(uid)}</b>\n'
            f'⭐ Ур. <b>{u[10]}</b> {level_badge(u[10])}\n'
            f'🏆 {u[4]} · 💀 {u[5]} · WR {wr}%\n'
            f'🎯 Оборот · {money(u[6])}₽\n'
            f'👑 Админ · {adm}\n'
            f'🚫 Бан · {"ДА" if u[3] else "НЕТ"}')


def adm_admins_kb():
    rows = q('SELECT username,user_id FROM admins ORDER BY username COLLATE NOCASE')
    kb = []
    for un, uid in rows:
        is_main = (un and un.lower() == MAIN_ADMIN.lower()) or (MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID)
        mark = '👑' if is_main else '⭐'
        kb.append([InlineKeyboardButton(f'{mark} @{un or uid}', callback_data='noop' if is_main else f'adm_admin_{uid or 0}')])
    kb.append([InlineKeyboardButton('➕ Добавить', callback_data='adm_add_admin')])
    kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='adm_main')])
    return InlineKeyboardMarkup(kb)


async def show_admin_panel(message):
    if not is_admin(message.from_user):
        await message.reply_text('⛔'); return
    await message.reply_text(admin_header(), reply_markup=adm_main_kb(), parse_mode='HTML')


async def adm_cb(update, ctx):
    u = update.effective_user
    if not u:
        return
    qr = update.callback_query
    d = qr.data or ''

    # Права доступа:
    # - mod_* и adm_close → модератор и выше
    # - ownall_ / owner_give_menu → только владелец
    # - остальные adm_* → админ и выше (владелец тоже админ)
    if d.startswith('mod_') or d == 'adm_close':
        if not is_mod(qr.from_user):
            try:
                await qr.answer('⛔ Недостаточно прав', show_alert=True)
            except Exception:
                pass
            return
    elif (d.startswith('ownall_') or d.startswith('owntake_')
          or d.startswith('owngive_') or d.startswith('owngv_')
          or d.startswith('owntk_') or d.startswith('ownset_')
          or d in ('owner_give_menu', 'owner_give_all_menu', 'owner_give_custom',
                   'owner_eco_menu', 'owner_take_all_menu', 'owner_take_menu',
                   'owner_set_menu', 'ownall_custom', 'owntake_custom',
                   'owner_cr_menu', 'owner_cr_take_menu', 'owner_cr_all_menu',
                   'owner_en_menu', 'owner_priv_menu', 'owner_priv_add',
                   'owner_priv_list')):
        if not is_owner(qr.from_user):
            try:
                await qr.answer('⛔ Только владелец', show_alert=True)
            except Exception:
                pass
            return
    else:
        if not is_admin(qr.from_user):
            try:
                await qr.answer('⛔ Недостаточно прав', show_alert=True)
            except Exception:
                pass
            return
    try:
        # ── Действия модератора ──
        if d == 'mod_stats':
            c, bal, w, l, tb, tw = q(
                'SELECT COUNT(*),COALESCE(SUM(balance),0),COALESCE(SUM(wins),0),'
                'COALESCE(SUM(losses),0),COALESCE(SUM(total_bet),0),COALESCE(SUM(total_won),0) FROM users')[0]
            await qsopra_safe_edit(qr.message,
                header('📊', 'СТАТИСТИКА') + f"\n\n"
                f"👥 Игроков · <b>{c}</b>\n"
                f"💰 В экономике · <b>{money(bal)}₽</b>\n"
                f"🏆 Побед · <b>{money(w)}</b> · 💀 <b>{money(l)}</b>\n"
                f"🎯 Оборот · <b>{money(tb)}₽</b>",
                reply_markup=back_kb('mod_main'), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'mod_main':
            await qsopra_safe_edit(qr.message, mod_header(), reply_markup=mod_main_kb(), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('mod_users_'):
            page = int(d.rsplit('_', 1)[1])
            page = max(0, page)
            rows = q('SELECT user_id,username,balance,banned FROM users ORDER BY balance DESC, user_id ASC')
            total = len(rows or [])
            pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(page, pages - 1)
            chunk = (rows or [])[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            kb = []
            for uid_, name, bal, ban in chunk:
                mark = '🚫' if ban else ('👑' if is_admin_by_id(uid_) else ('🛡' if is_mod_by_id(uid_) else '👤'))
                label = f'@{name}' if name else f'id{uid_}'
                kb.append([InlineKeyboardButton(
                    f'{mark} {label} · {display_balance(uid_, bal)}₽',
                    callback_data=f'mod_u_{uid_}')])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton('⬅️', callback_data=f'mod_users_{page-1}'))
            if page + 1 < pages:
                nav.append(InlineKeyboardButton('➡️', callback_data=f'mod_users_{page+1}'))
            if nav:
                kb.append(nav)
            kb.append([InlineKeyboardButton(f'📄 {page+1}/{pages}', callback_data='noop')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='mod_main')])
            await qsopra_safe_edit(qr.message, '👥 <b>Игроки</b> (модерация)',
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('mod_u_'):
            target = int(d.rsplit('_', 1)[1])
            if is_admin_by_id(target) or is_owner_by_id(target):
                try:
                    await qr.answer('⛔ Нельзя управлять персоналом', show_alert=True)
                except Exception:
                    pass
                return
            txt = adm_user_card_text(target)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('💰 Выдать (лимит)', callback_data=f'mod_give_{target}')],
                [InlineKeyboardButton('🚫 Бан', callback_data=f'mod_ban_{target}'),
                 InlineKeyboardButton('✅ Разбан', callback_data=f'mod_unban_{target}')],
                [InlineKeyboardButton('⬅️ Назад', callback_data='mod_users_0')],
            ])
            await qsopra_safe_edit(qr.message, txt, reply_markup=kb, parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('mod_ban_'):
            target = int(d.rsplit('_', 1)[1])
            if is_admin_by_id(target) or is_owner_by_id(target):
                try:
                    await qr.answer('⛔', show_alert=True)
                except Exception:
                    pass
                return
            q('UPDATE users SET banned=1 WHERE user_id=?', (target,), fetch=False)
            active.pop(target, None)
            await qsopra_safe_edit(qr.message, adm_user_card_text(target),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('⬅️ Назад', callback_data='mod_users_0')]]), parse_mode='HTML')
            try:
                await ctx.bot.send_message(target, '🚫 Вы заблокированы модератором')
            except Exception:
                pass
            try:
                await qr.answer('🚫')
            except Exception:
                pass
            return
        if d.startswith('mod_unban_'):
            target = int(d.rsplit('_', 1)[1])
            q('UPDATE users SET banned=0 WHERE user_id=?', (target,), fetch=False)
            await qsopra_safe_edit(qr.message, adm_user_card_text(target),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('⬅️ Назад', callback_data='mod_users_0')]]), parse_mode='HTML')
            try:
                await qr.answer('✅')
            except Exception:
                pass
            return
        if d == 'mod_give_menu':
            await qsopra_safe_edit(qr.message,
                header('💰', 'ВЫДАЧА МОДЕРАТОРА') + f"\n\n"
                f"Лимит за одну операцию: <b>{money(MOD_GIVE_LIMIT)}₽</b>\n"
                "Выберите игрока через список «Игроки».",
                reply_markup=back_kb('mod_main'), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('mod_give_'):
            target = int(d.rsplit('_', 1)[1])
            if is_admin_by_id(target) or is_owner_by_id(target):
                try:
                    await qr.answer('⛔', show_alert=True)
                except Exception:
                    pass
                return
            ctx.user_data['adm_state'] = ('mod_give', target)
            await qsopra_safe_edit(qr.message,
                f"💰 Введите сумму (макс. {money(MOD_GIVE_LIMIT)}₽) или «отмена»:")
            try:
                await qr.answer()
            except Exception:
                pass
            return

        if d == 'adm_main':
            ctx.user_data['adm_state'] = None
            await qsopra_safe_edit(qr.message, admin_header(), reply_markup=adm_main_kb(), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'adm_close':
            ctx.user_data['adm_state'] = None
            try: await qr.message.delete()
            except Exception: pass
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_stats':
            try:
                c = (q('SELECT COUNT(*) FROM users') or [[0]])[0][0]
                banned = (q('SELECT COUNT(*) FROM users WHERE banned=1') or [[0]])[0][0]
                admins = (q('SELECT COUNT(*) FROM admins') or [[0]])[0][0]
                mods = (q('SELECT COUNT(*) FROM moderators') or [[0]])[0][0]
                bal = safe_sum_column('balance')
                cr = safe_sum_column('crystals', 100_000_000)
                en = safe_sum_column('energy', 10_000_000)
                w = safe_sum_column('wins', 10_000_000_000)
                l = safe_sum_column('losses', 10_000_000_000)
                tb = safe_sum_column('total_bet')
                tw = safe_sum_column('total_won')
                online = qsopra_online_count()
                open_pvp = (q("SELECT COUNT(*) FROM pvp_rooms WHERE status='open'") or [[0]])[0][0]
                await qsopra_safe_edit(
                    qr.message,
                    header('📊', 'СТАТИСТИКА') + f"\n\n"
                    f"🟢 Онлайн · <b>{online}</b>\n"
                    f"👥 Игроков · <b>{c}</b>\n"
                    f"🚫 Забанено · <b>{banned}</b>\n"
                    f"👑 Админов · <b>{admins}</b> · 🛡 Модов · <b>{mods}</b>\n"
                    f"⚔️ Открытых PvP · <b>{open_pvp}</b>\n\n"
                    f"💰 В экономике · <b>{money(bal)}₽</b>\n"
                    f"💎 Кристаллов · <b>{money(cr)}</b>\n"
                    f"⚡ Энергии · <b>{money(en)}</b>\n\n"
                    f"🏆 Побед · <b>{money(w)}</b> · 💀 <b>{money(l)}</b>\n"
                    f"🎯 Оборот · <b>{money(tb)}₽</b>\n"
                    f"💸 Выплачено · <b>{money(tw)}₽</b>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🔄 Обновить', callback_data='adm_stats')],
                        [InlineKeyboardButton('⬅️ Назад', callback_data='owner_menu'
                            if is_owner(qr.from_user) else 'adm_main')],
                    ]),
                    parse_mode='HTML')
            except Exception as e:
                print('STATS ERR:', repr(e))
                await qsopra_safe_edit(
                    qr.message,
                    header('📊', 'СТАТИСТИКА') + "\n\n"
                    "Извините, статистику сейчас не удалось посчитать.\nПопробуйте позже.",
                    reply_markup=back_kb('owner_menu'), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('adm_users_'):
            page = int(d.rsplit('_', 1)[1])
            await qsopra_safe_edit(qr.message, '👥 <b>Игроки</b>', reply_markup=adm_users_kb(page), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('adm_u_'):
            uid = int(d.rsplit('_', 1)[1])
            if not get_user(uid):
                try: await qr.answer('Удалён', show_alert=True)
                except Exception: pass
                return
            await qsopra_safe_edit(qr.message, adm_user_card_text(uid), reply_markup=adm_user_card_kb(uid), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_give_all':
            # Обрабатывается ниже отдельным блоком — не путать с adm_give_{uid}
            pass
        elif d.startswith('adm_give_'):
            tail = d.rsplit('_', 1)[1]
            if not tail.isdigit():
                # Не ID игрока (например, старый callback) — пропускаем дальше
                pass
            else:
                uid = int(tail)
                if not get_user(uid):
                    try:
                        await qr.answer('Нет', show_alert=True)
                    except Exception:
                        pass
                    return
                kb = [[InlineKeyboardButton(f'+{money(b)}₽', callback_data=f'admgv_{uid}_{b}')] for b in BETS]
                kb += [[InlineKeyboardButton('✍️ Другая', callback_data=f'admgv_{uid}_custom')],
                       [InlineKeyboardButton('⬅️', callback_data=f'adm_u_{uid}')]]
                await qsopra_safe_edit(qr.message, f'💰 Пополнить <code>{uid}</code>:',
                    reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                try:
                    await qr.answer()
                except Exception:
                    pass
                return
        if d.startswith('admgv_'):
            _, uid_s, val = d.split('_', 2); uid = int(uid_s)
            if not get_user(uid):
                try: await qr.answer('Нет', show_alert=True)
                except Exception: pass
                return
            if val == 'custom':
                ctx.user_data['adm_state'] = ('give', uid)
                await qsopra_safe_edit(qr.message, "💰 Сумма или 'отмена':")
                try: await qr.answer()
                except Exception: pass
                return
            amt = int(val)
            if amt <= 0: raise ValueError('>0')
            q('UPDATE users SET balance=balance+? WHERE user_id=?', (amt, uid), fetch=False)
            await qsopra_safe_edit(qr.message, f'✅ <b>+{money(amt)}₽</b> → <code>{uid}</code>',
                reply_markup=back_kb(f'adm_u_{uid}'), parse_mode='HTML')
            try: await ctx.bot.send_message(uid, f'💰 <b>+{money(amt)}₽</b>', parse_mode='HTML')
            except Exception: pass
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('adm_cr_'):
            uid = int(d.rsplit('_', 1)[1])
            if not get_user(uid):
                try: await qr.answer('Нет', show_alert=True)
                except Exception: pass
                return
            ctx.user_data['adm_state'] = ('give_cr', uid)
            await qsopra_safe_edit(qr.message, f"💎 Кристаллы для <code>{uid}</code>:")
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('adm_set_'):
            uid = int(d.rsplit('_', 1)[1])
            if not get_user(uid):
                try: await qr.answer('Нет', show_alert=True)
                except Exception: pass
                return
            vals = sorted(set(BETS + [0]))
            kb = [[InlineKeyboardButton(f'= {money(b)}₽', callback_data=f'admset_{uid}_{b}')] for b in vals]
            kb += [[InlineKeyboardButton('✍️ Другая', callback_data=f'admset_{uid}_custom')],
                   [InlineKeyboardButton('⬅️', callback_data=f'adm_u_{uid}')]]
            await qsopra_safe_edit(qr.message, f'✏️ Баланс <code>{uid}</code>:',
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('admset_'):
            _, uid_s, val = d.split('_', 2); uid = int(uid_s)
            if not get_user(uid):
                try: await qr.answer('Нет', show_alert=True)
                except Exception: pass
                return
            if val == 'custom':
                ctx.user_data['adm_state'] = ('set', uid)
                await qsopra_safe_edit(qr.message, "✏️ Число ≥ 0 или 'отмена':")
                try: await qr.answer()
                except Exception: pass
                return
            amt = int(val)
            if amt < 0: raise ValueError('<0')
            q('UPDATE users SET balance=? WHERE user_id=?', (amt, uid), fetch=False)
            await qsopra_safe_edit(qr.message, f'✅ Баланс = <b>{money(amt)}₽</b>',
                reply_markup=back_kb(f'adm_u_{uid}'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('adm_promote_'):
            uid = int(d.rsplit('_', 1)[1]); u2 = get_user(uid)
            if not u2 or not u2[1]:
                try: await qr.answer('Нет username', show_alert=True)
                except Exception: pass
                return
            q('INSERT OR IGNORE INTO admins(username,user_id) VALUES(?,?)', (u2[1], uid), fetch=False)
            q('UPDATE admins SET username=? WHERE user_id=?', (u2[1], uid), fetch=False)
            await qsopra_safe_edit(qr.message, adm_user_card_text(uid), reply_markup=adm_user_card_kb(uid), parse_mode='HTML')
            try: await ctx.bot.send_message(uid, '👑 Админка!', parse_mode='HTML')
            except Exception: pass
            try: await qr.answer('✅')
            except Exception: pass
            return
        if d.startswith('adm_revoke_'):
            uid = int(d.rsplit('_', 1)[1]); u2 = get_user(uid)
            if not u2:
                try: await qr.answer('Нет')
                except Exception: pass
                return
            if (MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID) or (u2[1] and u2[1].lower() == MAIN_ADMIN.lower()):
                try: await qr.answer('❌ Главного нельзя', show_alert=True)
                except Exception: pass
                return
            q('DELETE FROM admins WHERE user_id=? OR username=?', (uid, u2[1] or ''), fetch=False)
            await qsopra_safe_edit(qr.message, adm_user_card_text(uid), reply_markup=adm_user_card_kb(uid), parse_mode='HTML')
            try: await qr.answer('❌')
            except Exception: pass
            return
        if d.startswith('adm_ban_'):
            uid = int(d.rsplit('_', 1)[1]); u2 = get_user(uid)
            if not u2:
                try: await qr.answer('Нет')
                except Exception: pass
                return
            if (MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID) or (u2[1] and u2[1].lower() == MAIN_ADMIN.lower()):
                try: await qr.answer('❌ Главного нельзя', show_alert=True)
                except Exception: pass
                return
            q('UPDATE users SET banned=1 WHERE user_id=?', (uid,), fetch=False)
            active.pop(uid, None); duels.pop(uid, None); pending_bets.pop(uid, None)
            await qsopra_safe_edit(qr.message, adm_user_card_text(uid), reply_markup=adm_user_card_kb(uid), parse_mode='HTML')
            try: await ctx.bot.send_message(uid, '🚫 Заблокирован', parse_mode='HTML')
            except Exception: pass
            try: await qr.answer('🚫')
            except Exception: pass
            return
        if d.startswith('adm_unban_'):
            uid = int(d.rsplit('_', 1)[1])
            q('UPDATE users SET banned=0 WHERE user_id=?', (uid,), fetch=False)
            await qsopra_safe_edit(qr.message, adm_user_card_text(uid), reply_markup=adm_user_card_kb(uid), parse_mode='HTML')
            try: await qr.answer('✅')
            except Exception: pass
            return
        if d.startswith('adm_del_'):
            uid = int(d.rsplit('_', 1)[1]); u2 = get_user(uid)
            if not u2:
                try: await qr.answer('Уже удалён')
                except Exception: pass
                return
            if (MAIN_ADMIN_ID and uid == MAIN_ADMIN_ID) or (u2[1] and u2[1].lower() == MAIN_ADMIN.lower()):
                try: await qr.answer('❌ Главного нельзя', show_alert=True)
                except Exception: pass
                return
            q('DELETE FROM admins WHERE user_id=? OR username=?', (uid, u2[1] or ''), fetch=False)
            q('DELETE FROM promo_uses WHERE user_id=?', (uid,), fetch=False)
            q('DELETE FROM users WHERE user_id=?', (uid,), fetch=False)
            active.pop(uid, None); duels.pop(uid, None); pending_bets.pop(uid, None)
            await qsopra_safe_edit(qr.message, '🗑 Удалён', reply_markup=back_kb('adm_users_0'), parse_mode='HTML')
            try: await qr.answer('🗑')
            except Exception: pass
            return
        if d == 'adm_admin_menu':
            await qsopra_safe_edit(qr.message, '👑 <b>АДМИНЫ</b>', reply_markup=adm_admins_kb(), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('adm_admin_'):
            uid = int(d[len('adm_admin_'):]); u2 = get_user(uid)
            if not u2:
                try: await qr.answer('Нет')
                except Exception: pass
                return
            await qsopra_safe_edit(qr.message, f'👑 <b>@{u2[1] or uid}</b>\n<code>{uid}</code>',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('❌ Снять', callback_data=f'adm_revoke_{uid}')],
                    [InlineKeyboardButton('⬅️', callback_data='adm_admin_menu')]]), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_add_admin':
            ctx.user_data['adm_state'] = ('add_admin', None)
            await qsopra_safe_edit(qr.message, "👑 @username или ID (или 'отмена'):")
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_give_all':
            kb = [[InlineKeyboardButton(f'🎁 +{money(b)}₽', callback_data=f'admall_{b}')] for b in BETS]
            kb.append([InlineKeyboardButton('✏️ Своя сумма', callback_data='admall_custom')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='adm_main')])
            await qsopra_safe_edit(qr.message,
                header('🎁', 'ВЫДАЧА ВСЕМ') + "\n\n"
                "Средства будут начислены всем <b>незабаненным</b> игрокам,\n"
                "кроме администрации и владельца.\n\nВыберите сумму:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'admall_custom':
            ctx.user_data['adm_state'] = ('give_all', None)
            await qsopra_safe_edit(qr.message, "🎁 Введите сумму (или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('admall_'):
            tail = d.rsplit('_', 1)[1]
            if not tail.isdigit():
                try:
                    await qr.answer('Некорректная сумма', show_alert=True)
                except Exception:
                    pass
                return
            amt = int(tail)
            if amt <= 0:
                try:
                    await qr.answer('Сумма должна быть > 0', show_alert=True)
                except Exception:
                    pass
                return
            # Исключаем владельца, админов и модераторов
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                placeholders = ','.join('?' * len(staff_ids))
                params_upd = tuple([amt] + staff_ids)
                params_sel = tuple(staff_ids)
                q(f'UPDATE users SET balance=balance+? WHERE banned=0 AND user_id NOT IN ({placeholders})',
                  params_upd, fetch=False)
                users = q(f'SELECT user_id FROM users WHERE banned=0 AND user_id NOT IN ({placeholders})',
                          params_sel)
            else:
                q('UPDATE users SET balance=balance+? WHERE banned=0', (amt,), fetch=False)
                users = q('SELECT user_id FROM users WHERE banned=0')
            ok = 0
            for (target,) in (users or []):
                try:
                    await ctx.bot.send_message(
                        target,
                        f'🎁 <b>+{money(amt)}₽</b> от администрации',
                        parse_mode='HTML')
                    ok += 1
                    await asyncio.sleep(0.035)
                except Exception:
                    pass
            await qsopra_safe_edit(
                qr.message,
                header('✅', 'ВЫДАЧА ЗАВЕРШЕНА') + f"\n\n"
                f"Сумма · <b>{money(amt)}₽</b>\n"
                f"Получили · <b>{ok}</b> игроков",
                reply_markup=back_kb('adm_main'),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        # ── Модераторы: меню управления ──
        if d == 'adm_mod_menu':
            rows = q('SELECT username,user_id FROM moderators ORDER BY username COLLATE NOCASE')
            kb = []
            for un, uid in (rows or []):
                kb.append([InlineKeyboardButton(f'🛡 @{un or uid}',
                    callback_data=f'adm_mod_view_{uid or 0}')])
            kb.append([InlineKeyboardButton('➕ Добавить модератора', callback_data='adm_add_mod')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='adm_main')])
            await qsopra_safe_edit(qr.message, header('🛡', 'МОДЕРАТОРЫ'),
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'adm_add_mod':
            ctx.user_data['adm_state'] = ('add_mod', None)
            await qsopra_safe_edit(qr.message, "🛡 Введите @username или ID (или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('adm_mod_view_'):
            try:
                muid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            u2 = get_user(muid)
            name = f"@{u2[1]}" if u2 and u2[1] else f"id{muid}"
            await qsopra_safe_edit(qr.message,
                f"🛡 <b>{name}</b>\n<code>{muid}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('❌ Снять модератора', callback_data=f'adm_mod_revoke_{muid}')],
                    [InlineKeyboardButton('⬅️ Назад', callback_data='adm_mod_menu')]]),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('adm_mod_revoke_'):
            try:
                muid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            u2 = get_user(muid)
            q('DELETE FROM moderators WHERE user_id=? OR username=?',
              (muid, (u2[1] if u2 else '') or ''), fetch=False)
            await qsopra_safe_edit(qr.message, '❌ Модератор снят',
                reply_markup=back_kb('adm_mod_menu'), parse_mode='HTML')
            try:
                await qr.answer('❌')
            except Exception:
                pass
            return
        # ── Панель выдачи овнера ──
        # ── Выдача привилегии ОВНЕР ──
        if d == 'owner_priv_menu':
            if not is_main_owner(qr.from_user):
                try:
                    await qr.answer('⛔ Только главный владелец', show_alert=True)
                except Exception:
                    pass
                return
            rows = q('SELECT user_id, username, granted_at FROM owners ORDER BY granted_at DESC') or []
            txt = owner_header() + "\n\n<b>Выдача овнера</b>\n"
            txt += "Выдать игроку права <b>владельца</b> (меню «овнер»).\n\n"
            txt += f"Главный · <b>@{MAIN_ADMIN}</b> (нельзя снять)\n\n"
            if rows:
                txt += "<b>Доп. владельцы:</b>\n"
                for oid, un, ga in rows:
                    label = f'@{un}' if un else f'id{oid}'
                    txt += f"· {label} · <code>{oid}</code>\n"
            else:
                txt += "<i>Дополнительных владельцев нет.</i>\n"
            kb = [
                [InlineKeyboardButton('➕ Выдать овнера', callback_data='owner_priv_add')],
                [InlineKeyboardButton('📋 Список', callback_data='owner_priv_menu')],
            ]
            for oid, un, ga in rows[:15]:
                label = f'@{un}' if un else f'id{oid}'
                kb.append([InlineKeyboardButton(
                    f'🗑 Снять {label}',
                    callback_data=f'owner_priv_del_{oid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_menu')])
            await qsopra_safe_edit(
                qr.message, txt,
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'owner_priv_add':
            if not is_main_owner(qr.from_user):
                return
            ctx.user_data['adm_state'] = ('owner_priv_grant', None)
            await qsopra_safe_edit(
                qr.message,
                "🌟 Введите @username или ID игрока для выдачи овнера\n"
                "(или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owner_priv_del_'):
            if not is_main_owner(qr.from_user):
                return
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            if not revoke_owner_priv(tid):
                try:
                    await qr.answer('Нельзя снять главного владельца', show_alert=True)
                except Exception:
                    pass
                return
            try:
                await qr.answer('Овнер снят')
            except Exception:
                pass
            try:
                await ctx.bot.send_message(tid, '⚠️ С вас сняты права владельца казино.')
            except Exception:
                pass
            # refresh menu
            qr.data = 'owner_priv_menu'
            # fall through by recursive edit
            rows = q('SELECT user_id, username, granted_at FROM owners ORDER BY granted_at DESC') or []
            txt = owner_header() + "\n\n<b>Выдача овнера</b>\nПрава сняты.\n"
            if rows:
                for oid, un, ga in rows:
                    label = f'@{un}' if un else f'id{oid}'
                    txt += f"· {label}\n"
            else:
                txt += "<i>Доп. владельцев нет.</i>"
            kb = [
                [InlineKeyboardButton('➕ Выдать овнера', callback_data='owner_priv_add')],
                [InlineKeyboardButton('⬅️ Назад', callback_data='owner_menu')],
            ]
            for oid, un, ga in rows[:15]:
                label = f'@{un}' if un else f'id{oid}'
                kb.append([InlineKeyboardButton(f'🗑 Снять {label}', callback_data=f'owner_priv_del_{oid}')])
            await qsopra_safe_edit(qr.message, txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            return

        if d == 'owner_eco_menu':
            if not is_owner(qr.from_user):
                try:
                    await qr.answer('⛔ Только владелец', show_alert=True)
                except Exception:
                    pass
                return
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Экономика</b>\n"
                "Монеты, кристаллы, энергия — фиксированные пакеты.",
                reply_markup=owner_eco_kb(),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Кристаллы: выдать игроку ──
        if d == 'owner_cr_menu':
            rows = q(
                'SELECT user_id,username,crystals FROM users WHERE banned=0 '
                'ORDER BY crystals DESC LIMIT 20')
            kb = []
            for tid, name, cr in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'💎 {label} · {cr}',
                    callback_data=f'owncr_{tid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Выдать кристаллы</b>\nВыберите игрока:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owncr_') and not d.startswith('owncrall_') and not d.startswith('owncrt_'):
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            kb = [[InlineKeyboardButton(f'+{n}💎', callback_data=f'owncrg_{tid}_{n}')]
                  for n in OWNER_CR_PACKS]
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_cr_menu')])
            await qsopra_safe_edit(
                qr.message,
                header('💎', 'ВЫДАТЬ КРИСТАЛЛЫ') + f"\n\nИгрок <code>{tid}</code>\nВыберите пакет:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owncrg_'):
            parts = d.split('_')
            try:
                tid, amt = int(parts[1]), int(parts[2])
            except Exception:
                return
            if amt not in OWNER_CR_PACKS:
                try:
                    await qr.answer('Недопустимый пакет', show_alert=True)
                except Exception:
                    pass
                return
            if not get_user(tid):
                try:
                    await qr.answer('Игрок не найден', show_alert=True)
                except Exception:
                    pass
                return
            grant_crystals(tid, amt)
            now_cr = get_crystals(tid)
            await qsopra_safe_edit(
                qr.message,
                header('✅', 'КРИСТАЛЛЫ') + f"\n\n<code>{tid}</code> · <b>+{amt}💎</b>\n"
                f"Сейчас · <b>{now_cr}</b>",
                reply_markup=back_kb('owner_eco_menu'), parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid, f'💎 <b>+{amt}</b> от владельца (всего {now_cr})', parse_mode='HTML')
            except Exception:
                pass
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Кристаллы всем ──
        if d == 'owner_cr_all_menu':
            kb = [[InlineKeyboardButton(f'+{n}💎 всем', callback_data=f'owncrall_{n}')]
                  for n in OWNER_CR_PACKS]
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Кристаллы всем</b>\nПакет всем незабаненным:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owncrall_'):
            try:
                amt = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            if amt not in OWNER_CR_PACKS:
                return
            q('UPDATE users SET crystals=MIN(COALESCE(crystals,0)+?, ?) WHERE banned=0',
              (amt, CRYSTALS_MAX), fetch=False)
            await qsopra_safe_edit(
                qr.message,
                header('✅', 'КРИСТАЛЛЫ ВСЕМ') + f"\n\n<b>+{amt}💎</b> всем игрокам (вкл. персонал)",
                reply_markup=back_kb('owner_eco_menu'), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Снять кристаллы ──
        if d == 'owner_cr_take_menu':
            rows = q(
                'SELECT user_id,username,crystals FROM users WHERE banned=0 AND crystals>0 '
                'ORDER BY crystals DESC LIMIT 20')
            kb = []
            for tid, name, cr in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'💎 {label} · {cr}',
                    callback_data=f'owncrt_{tid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Снять кристаллы</b>",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owncrt_'):
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            kb = [[InlineKeyboardButton(f'−{n}💎', callback_data=f'owncrts_{tid}_{n}')]
                  for n in OWNER_CR_PACKS]
            kb.append([InlineKeyboardButton('🗑 Обнулить 💎', callback_data=f'owncrts_{tid}_zero')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_cr_take_menu')])
            await qsopra_safe_edit(
                qr.message,
                header('💎', 'СНЯТЬ КРИСТАЛЛЫ') + f"\n\nИгрок <code>{tid}</code>",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owncrts_'):
            parts = d.split('_')
            try:
                tid = int(parts[1])
                val = parts[2]
            except Exception:
                return
            tu = get_user(tid)
            if not tu:
                return
            if val == 'zero':
                q('UPDATE users SET crystals=0 WHERE user_id=?', (tid,), fetch=False)
                msg = f'💎 Обнулены у <code>{tid}</code>'
            else:
                amt = int(val)
                q('UPDATE users SET crystals=CASE WHEN crystals>=? THEN crystals-? ELSE 0 END WHERE user_id=?',
                  (amt, amt, tid), fetch=False)
                msg = f'💎 −{amt} у <code>{tid}</code>'
            await qsopra_safe_edit(
                qr.message, header('✅', 'ГОТОВО') + f"\n\n{msg}",
                reply_markup=back_kb('owner_eco_menu'), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Энергия игроку ──
        if d == 'owner_en_menu':
            rows = q(
                'SELECT user_id,username,energy FROM users WHERE banned=0 '
                'ORDER BY energy ASC LIMIT 20')
            kb = []
            for tid, name, en in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'⚡ {label} · {en}',
                    callback_data=f'ownen_{tid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Энергия игроку</b>\nПолное восстановление:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('ownen_'):
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            emax = user_energy_max(tid)
            q('UPDATE users SET energy=?, last_energy=? WHERE user_id=?',
              (emax, datetime.now().isoformat(), tid), fetch=False)
            await qsopra_safe_edit(
                qr.message,
                header('⚡', 'ЭНЕРГИЯ') + f"\n\n<code>{tid}</code> → <b>{emax}⚡</b>",
                reply_markup=back_kb('owner_eco_menu'), parse_mode='HTML')
            try:
                await ctx.bot.send_message(tid, f'⚡ Энергия восстановлена овнером: <b>{emax}</b>', parse_mode='HTML')
            except Exception:
                pass
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Снять со всех ──
        if d == 'owner_take_all_menu':
            amounts = [10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000]
            kb = [[InlineKeyboardButton(f'➖ −{money(b)}₽', callback_data=f'owntake_{b}')]
                  for b in amounts]
            kb.append([InlineKeyboardButton('✏️ Своя сумма', callback_data='owntake_custom')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Снять со всех</b>\n"
                "Списание у всех игроков (кроме персонала).\n"
                "Баланс не уйдёт ниже 0.",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'owntake_custom':
            ctx.user_data['adm_state'] = ('owner_take_all', None)
            await qsopra_safe_edit(qr.message, "➖ Сумма снятия со всех (или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owntake_'):
            tail = d.rsplit('_', 1)[1]
            if not tail.isdigit():
                return
            amt = int(tail)
            if amt <= 0:
                return
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                ph = ','.join('?' * len(staff_ids))
                q(f'UPDATE users SET balance=CASE WHEN balance>=? THEN balance-? ELSE 0 END '
                  f'WHERE banned=0 AND user_id NOT IN ({ph})',
                  tuple([amt, amt] + staff_ids), fetch=False)
                users = q(
                    f'SELECT user_id FROM users WHERE banned=0 AND user_id NOT IN ({ph})',
                    tuple(staff_ids))
            else:
                q('UPDATE users SET balance=CASE WHEN balance>=? THEN balance-? ELSE 0 END WHERE banned=0',
                  (amt, amt), fetch=False)
                users = q('SELECT user_id FROM users WHERE banned=0')
            ok = 0
            for (target,) in (users or []):
                try:
                    await ctx.bot.send_message(
                        target,
                        f'➖ <b>−{money(amt)}₽</b> — снятие овнером',
                        parse_mode='HTML')
                    ok += 1
                    await asyncio.sleep(0.035)
                except Exception:
                    pass
            await qsopra_safe_edit(
                qr.message,
                header('➖', 'СНЯТИЕ ОВНЕРА') + f"\n\n"
                f"Сумма · <b>−{money(amt)}₽</b>\n"
                f"Затронуто · <b>{ok}</b> игроков",
                reply_markup=back_kb('owner_eco_menu'),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Снять с игрока ──
        if d == 'owner_take_menu':
            rows = q(
                'SELECT user_id,username,balance FROM users WHERE banned=0 '
                'ORDER BY balance DESC LIMIT 25')
            kb = []
            for tid, name, bal in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'👤 {label} · {display_balance(tid, bal)}₽',
                    callback_data=f'owntk_{tid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Снять с игрока</b>\nВыберите игрока:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owntk_') and not d.startswith('owntake_'):
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            tu = get_user(tid)
            if not tu:
                try:
                    await qr.answer('Не найден', show_alert=True)
                except Exception:
                    pass
                return
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            presets = [1000, 5000, 10000, 50000, 100000, 1_000_000]
            kb = [[InlineKeyboardButton(f'−{money(b)}₽', callback_data=f'owntkv_{tid}_{b}')]
                  for b in presets]
            kb.append([InlineKeyboardButton('✏️ Своя сумма', callback_data=f'owntkv_{tid}_custom')])
            kb.append([InlineKeyboardButton('🗑 Обнулить', callback_data=f'owntkv_{tid}_zero')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_take_menu')])
            await qsopra_safe_edit(
                qr.message,
                header('➖', 'СНЯТЬ С ИГРОКА') + f"\n\n"
                f"👤 <b>{name}</b>\n💰 Сейчас · <b>{display_balance(tid, tu[2])}₽</b>",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owntkv_'):
            parts = d.split('_')
            try:
                tid = int(parts[1])
                val = parts[2]
            except Exception:
                return
            tu = get_user(tid)
            if not tu:
                return
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            if val == 'custom':
                ctx.user_data['adm_state'] = ('owner_take', tid)
                await qsopra_safe_edit(qr.message, "➖ Сумма снятия (или «отмена»):")
                try:
                    await qr.answer()
                except Exception:
                    pass
                return
            if val == 'zero':
                q('UPDATE users SET balance=0 WHERE user_id=?', (tid,), fetch=False)
                await qsopra_safe_edit(
                    qr.message,
                    header('✅', 'ОБНУЛЕНО') + f"\n\n👤 {name}\n💰 Баланс = <b>0₽</b>",
                    reply_markup=back_kb('owner_eco_menu'),
                    parse_mode='HTML')
                try:
                    await ctx.bot.send_message(tid, '➖ Баланс обнулён овнером', parse_mode='HTML')
                except Exception:
                    pass
                try:
                    await qr.answer()
                except Exception:
                    pass
                return
            if not val.isdigit():
                return
            amt = int(val)
            new_bal = max(0, tu[2] - amt)
            q('UPDATE users SET balance=? WHERE user_id=?', (new_bal, tid), fetch=False)
            await qsopra_safe_edit(
                qr.message,
                header('✅', 'СНЯТО') + f"\n\n👤 {name}\n💵 <b>−{money(amt)}₽</b>\n💰 Остаток · <b>{money(new_bal)}₽</b>",
                reply_markup=back_kb('owner_eco_menu'),
                parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid, f'➖ <b>−{money(amt)}₽</b> — снятие овнером', parse_mode='HTML')
            except Exception:
                pass
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Установить баланс игроку ──
        if d == 'owner_set_menu':
            rows = q(
                'SELECT user_id,username,balance FROM users WHERE banned=0 '
                'ORDER BY balance DESC LIMIT 25')
            kb = []
            for tid, name, bal in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'👤 {label} · {display_balance(tid, bal)}₽',
                    callback_data=f'ownset_{tid}')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Установить баланс</b>\nВыберите игрока:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('ownset_'):
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            tu = get_user(tid)
            if not tu:
                return
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            ctx.user_data['adm_state'] = ('owner_set', tid)
            await qsopra_safe_edit(
                qr.message,
                f"✏️ Баланс для <b>{name}</b>\nСейчас · {display_balance(tid, tu[2])}₽\n"
                f"Введите новое значение ≥ 0 (или «отмена»):",
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Выдача владельца: одному игроку ──
        if d == 'owner_give_menu':
            if not is_owner(qr.from_user):
                try:
                    await qr.answer('⛔ Только владелец', show_alert=True)
                except Exception:
                    pass
                return
            rows = q(
                'SELECT user_id,username,balance FROM users WHERE banned=0 '
                'ORDER BY balance DESC LIMIT 25')
            kb = []
            for tid, name, bal in (rows or []):
                label = f'@{name}' if name else f'id{tid}'
                kb.append([InlineKeyboardButton(
                    f'👤 {label} · {display_balance(tid, bal)}₽',
                    callback_data=f'owngive_{tid}')])
            kb.append([InlineKeyboardButton('✏️ По @username / ID', callback_data='owner_give_custom')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Выдать игроку</b>\n"
                "Выберите получателя (без лимита суммы):",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'owner_give_custom':
            if not is_owner(qr.from_user):
                return
            ctx.user_data['adm_state'] = ('owner_give_find', None)
            await qsopra_safe_edit(
                qr.message,
                "🌟 Введите @username или ID игрока (или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owngive_'):
            if not is_owner(qr.from_user):
                return
            try:
                tid = int(d.rsplit('_', 1)[1])
            except Exception:
                return
            tu = get_user(tid)
            if not tu:
                try:
                    await qr.answer('Игрок не найден', show_alert=True)
                except Exception:
                    pass
                return
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            presets = [1000, 5000, 10000, 50000, 100000, 1_000_000, 10_000_000]
            kb = [[InlineKeyboardButton(f'+{money(b)}₽', callback_data=f'owngv_{tid}_{b}')]
                  for b in presets]
            kb.append([InlineKeyboardButton('✏️ Своя сумма', callback_data=f'owngv_{tid}_custom')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_give_menu')])
            await qsopra_safe_edit(
                qr.message,
                header('🌟', 'ВЫДАТЬ ИГРОКУ') + f"\n\n"
                f"👤 <b>{name}</b>\n"
                f"💰 Сейчас · <b>{display_balance(tid, tu[2])}₽</b>\n\n"
                f"Выберите сумму:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('owngv_'):
            if not is_owner(qr.from_user):
                return
            parts = d.split('_')
            # owngv_{tid}_{val}
            try:
                tid = int(parts[1])
                val = parts[2]
            except Exception:
                return
            if val == 'custom':
                ctx.user_data['adm_state'] = ('owner_give', tid)
                await qsopra_safe_edit(qr.message, "🌟 Введите сумму (или «отмена»):")
                try:
                    await qr.answer()
                except Exception:
                    pass
                return
            if not val.isdigit():
                return
            amt = int(val)
            if amt <= 0:
                return
            tu = get_user(tid)
            if not tu:
                try:
                    await qr.answer('Игрок не найден', show_alert=True)
                except Exception:
                    pass
                return
            amt = clamp_amount(amt, minimum=1)
            if amt is None:
                try:
                    await qr.answer('Слишком большая сумма', show_alert=True)
                except Exception:
                    pass
                return
            safe_add_balance(tid, amt)
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            await qsopra_safe_edit(
                qr.message,
                header('✅', 'ВЫДАЧА') + f"\n\n"
                f"👤 {name}\n💵 <b>+{money(amt)}₽</b>",
                reply_markup=back_kb('owner_give_menu'),
                parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid,
                    f'🌟 <b>+{money(amt)}₽</b> от владельца',
                    parse_mode='HTML')
            except Exception:
                pass
            try:
                await qr.answer()
            except Exception:
                pass
            return

        # ── Выдача владельца: всем игрокам ──
        if d == 'owner_give_all_menu':
            if not is_owner(qr.from_user):
                try:
                    await qr.answer('⛔ Только владелец', show_alert=True)
                except Exception:
                    pass
                return
            amounts = [10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]
            kb = [[InlineKeyboardButton(f'🌟 +{money(b)}₽', callback_data=f'ownall_{b}')]
                  for b in amounts]
            kb.append([InlineKeyboardButton('✏️ Своя сумма', callback_data='ownall_custom')])
            kb.append([InlineKeyboardButton('⬅️ Назад', callback_data='owner_eco_menu')])
            await qsopra_safe_edit(
                qr.message,
                owner_header() + "\n\n<b>Выдать всем</b>\n"
                "Массовое начисление всем игрокам\n"
                "(кроме персонала).\n\nВыберите сумму:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'ownall_custom':
            if not is_owner(qr.from_user):
                return
            ctx.user_data['adm_state'] = ('owner_give_all', None)
            await qsopra_safe_edit(qr.message, "🌟 Сумма выдачи овнера (или «отмена»):")
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('ownall_'):
            if not is_owner(qr.from_user):
                try:
                    await qr.answer('⛔', show_alert=True)
                except Exception:
                    pass
                return
            tail = d.rsplit('_', 1)[1]
            if not tail.isdigit():
                return
            amt = clamp_amount(int(tail), minimum=1)
            if amt is None:
                try:
                    await qr.answer(f'Макс. сумма {money(MAX_BALANCE)}₽', show_alert=True)
                except Exception:
                    pass
                return
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                placeholders = ','.join('?' * len(staff_ids))
                q(f'UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0 AND user_id NOT IN ({placeholders})',
                  tuple([amt, MAX_BALANCE] + staff_ids), fetch=False)
                users = q(
                    f'SELECT user_id FROM users WHERE banned=0 AND user_id NOT IN ({placeholders})',
                    tuple(staff_ids))
            else:
                q('UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0',
                  (amt, MAX_BALANCE), fetch=False)
                users = q('SELECT user_id FROM users WHERE banned=0')
            ok = 0
            for (target,) in (users or []):
                try:
                    await ctx.bot.send_message(
                        target,
                        f'🌟 <b>+{money(amt)}₽</b> — выдача овнера',
                        parse_mode='HTML')
                    ok += 1
                    await asyncio.sleep(0.035)
                except Exception:
                    pass
            await qsopra_safe_edit(
                qr.message,
                header('🌟', 'ВЫДАЧА ОВНЕРА') + f"\n\n"
                f"Сумма · <b>{money(amt)}₽</b>\n"
                f"Получили · <b>{ok}</b> игроков",
                reply_markup=back_kb('owner_eco_menu'),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'adm_bc':
            ctx.user_data['adm_state'] = ('bc', None)
            await qsopra_safe_edit(qr.message, "📢 Текст или 'отмена':")
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_maint':
            new = '0' if maintenance_on() else '1'
            q("INSERT OR REPLACE INTO settings(key,value) VALUES('maintenance',?)", (new,), fetch=False)
            await qsopra_safe_edit(qr.message,
                f'{admin_header("🟠 Обслуживание" if new == "1" else "🟢 Онлайн")}\n\n🔧 <b>{"ВКЛ" if new == "1" else "ВЫКЛ"}</b>',
                reply_markup=adm_main_kb(), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_promos':
            rows = q('SELECT code,amount,uses,max_uses FROM promos ORDER BY code')
            txt = header('🎫', 'ПРОМОКОДЫ') + "\n\n"
            if not rows: txt += 'Пусто.'
            else:
                for c, a, used, mx in rows: txt += f'🎫 <b>{c}</b> · {money(a)}₽ · {used}/{mx}\n'
            kb = [[InlineKeyboardButton('➕', callback_data='adm_promo_add')],
                  [InlineKeyboardButton('🗑', callback_data='adm_promo_del')],
                  [InlineKeyboardButton('⬅️', callback_data='adm_main')]]
            await qsopra_safe_edit(qr.message, txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_promo_add':
            ctx.user_data['adm_state'] = ('promo_add', None)
            await qsopra_safe_edit(qr.message, "🎫 <code>КОД СУММА ЛИМИТ</code>", parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'adm_promo_del':
            ctx.user_data['adm_state'] = ('promo_del', None)
            await qsopra_safe_edit(qr.message, "🗑 Код или 'отмена':")
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'noop':
            try: await qr.answer()
            except Exception: pass
            return
        try: await qr.answer()
        except Exception: pass
    except Exception as e:
        if _is_harmless_tg_error(e) or _is_db_transient(e):
            try:
                await qr.answer('⏳ Попробуй ещё раз')
            except Exception:
                pass
            return
        print('ADMIN_CB ERR:', repr(e))
        try:
            await qr.answer(f'❌ {str(e)[:180]}', show_alert=True)
        except Exception:
            pass


async def handle_admin_state(update, ctx):
    u = update.effective_user
    if not u:
        return False
    st = ctx.user_data.get('adm_state')
    if not st or not update.message:
        return False
    # Модераторы могут выполнять только ограниченные состояния
    if not is_staff(u):
        ctx.user_data['adm_state'] = None
        return False
    t = (update.message.text or '').strip()
    if t.lower() in ('отмена', 'cancel', '/cancel'):
        ctx.user_data['adm_state'] = None
        ctx.user_data['transfer_target'] = None
        await update.message.reply_text('❌ Отменено', reply_markup=MAIN_KB)
        return True
    state, extra = st
    # Ограничения для модераторов
    mod_only_states = {'mod_give'}
    admin_states = {'give', 'give_cr', 'set', 'give_all', 'bc', 'promo_add', 'promo_del',
                    'add_admin', 'add_mod', 'owner_give_all', 'owner_give', 'owner_give_find',
                    'owner_take_all', 'owner_take', 'owner_set', 'owner_priv_grant'}
    if state in admin_states and not is_admin(u):
        if state != 'mod_give':
            await update.message.reply_text('⛔ Недостаточно прав')
            ctx.user_data['adm_state'] = None
            return True
    try:
        if state == 'give':
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 (можно 10к, 1кк…)')
            safe_add_balance(extra, amt)
            await update.message.reply_text(f'✅ +{money(amt)}₽', reply_markup=MAIN_KB)
        elif state == 'owner_give':
            if not is_owner(u):
                raise ValueError('только владелец')
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 (можно 10к, 1кк…)')
            tid = extra
            tu = get_user(tid)
            if not tu:
                raise ValueError('игрок не найден')
            safe_add_balance(tid, amt)
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            await update.message.reply_text(
                f'🌟 Выдано <b>+{money(amt)}₽</b> → {name}',
                reply_markup=MAIN_KB, parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid, f'🌟 <b>+{money(amt)}₽</b> от владельца', parse_mode='HTML')
            except Exception:
                pass
        elif state == 'owner_give_find':
            if not is_owner(u):
                raise ValueError('только владелец')
            target = t.lstrip('@').strip()
            if t.isdigit():
                rows = q("SELECT user_id,username FROM users WHERE user_id=?", (int(t),))
            else:
                rows = q(
                    "SELECT user_id,username FROM users WHERE LOWER(username)=LOWER(?)",
                    (target,))
            if not rows:
                raise ValueError('игрок не найден')
            tid, un = rows[0][0], rows[0][1]
            name = f"@{un}" if un else f"id{tid}"
            ctx.user_data['adm_state'] = ('owner_give', tid)
            await update.message.reply_text(
                f'🌟 Игрок <b>{name}</b>\nВведите сумму выдачи (или «отмена»):',
                parse_mode='HTML')
            return True
        elif state == 'mod_give':
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError('сумма должна быть > 0 (можно 10к, 1кк…)')
            if amt > MOD_GIVE_LIMIT:
                raise ValueError(f'лимит модератора — {money(MOD_GIVE_LIMIT)}₽')
            if is_admin_by_id(extra) or is_owner_by_id(extra):
                raise ValueError('нельзя выдавать персоналу')
            q('UPDATE users SET balance=balance+? WHERE user_id=?', (amt, extra), fetch=False)
            await update.message.reply_text(f'✅ Модератор выдал +{money(amt)}₽', reply_markup=MAIN_KB)
            try:
                await ctx.bot.send_message(extra, f'💰 <b>+{money(amt)}₽</b> от модератора', parse_mode='HTML')
            except Exception:
                pass
        elif state == 'give_cr':
            amt = parse_amount_text(t, minimum=1)
            if amt is None or amt > CRYSTALS_MAX:
                raise ValueError(f'кристаллы от 1 до {CRYSTALS_MAX} (можно 10к, 1кк…)')
            if not get_user(extra):
                raise ValueError('игрок не найден')
            grant_crystals(extra, amt)
            now_cr = get_crystals(extra)
            await update.message.reply_text(
                f'✅ +{amt}💎 → сейчас <b>{now_cr}</b>',
                reply_markup=MAIN_KB, parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    extra, f'💎 <b>+{amt}</b> (всего {now_cr})', parse_mode='HTML')
            except Exception:
                pass
        elif state == 'set':
            amt = parse_amount_text(t, minimum=0)
            if amt is None:
                raise ValueError(f'сумма от 0 до {money(MAX_BALANCE)}')
            safe_set_balance(extra, amt)
            await update.message.reply_text(f'✅ Баланс = {money(amt)}₽', reply_markup=MAIN_KB)
        elif state == 'give_all':
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 до {money(MAX_BALANCE)}')
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                ph = ','.join('?' * len(staff_ids))
                q(f'UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0 AND user_id NOT IN ({ph})',
                  tuple([amt, MAX_BALANCE] + staff_ids), fetch=False)
            else:
                q('UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0',
                  (amt, MAX_BALANCE), fetch=False)
            await update.message.reply_text(f'✅ {money(amt)}₽ выдано всем игрокам', reply_markup=MAIN_KB)
        elif state == 'owner_give_all':
            if not is_owner(u):
                raise ValueError('только владелец')
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 до {money(MAX_BALANCE)}')
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                ph = ','.join('?' * len(staff_ids))
                q(f'UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0 AND user_id NOT IN ({ph})',
                  tuple([amt, MAX_BALANCE] + staff_ids), fetch=False)
            else:
                q('UPDATE users SET balance=MIN(balance+?, ?) WHERE banned=0',
                  (amt, MAX_BALANCE), fetch=False)
            await update.message.reply_text(
                f'🌟 Выдача овнера: <b>{money(amt)}₽</b> всем игрокам',
                reply_markup=MAIN_KB, parse_mode='HTML')
        elif state == 'owner_take_all':
            if not is_owner(u):
                raise ValueError('только владелец')
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 до {money(MAX_BALANCE)}')
            staff_ids = list(qsopra_mod_ids())
            if staff_ids:
                ph = ','.join('?' * len(staff_ids))
                q(f'UPDATE users SET balance=CASE WHEN balance>=? THEN balance-? ELSE 0 END '
                  f'WHERE banned=0 AND user_id NOT IN ({ph})',
                  tuple([amt, amt] + staff_ids), fetch=False)
            else:
                q('UPDATE users SET balance=CASE WHEN balance>=? THEN balance-? ELSE 0 END WHERE banned=0',
                  (amt, amt), fetch=False)
            await update.message.reply_text(
                f'➖ Снятие овнера: <b>−{money(amt)}₽</b> со всех',
                reply_markup=MAIN_KB, parse_mode='HTML')
        elif state == 'owner_take':
            if not is_owner(u):
                raise ValueError('только владелец')
            amt = parse_amount_text(t, minimum=1)
            if amt is None:
                raise ValueError(f'сумма от 1 до {money(MAX_BALANCE)}')
            tid = extra
            tu = get_user(tid)
            if not tu:
                raise ValueError('игрок не найден')
            safe_sub_balance(tid, amt)
            fresh = get_user(tid)
            new_bal = fresh[2] if fresh else 0
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            await update.message.reply_text(
                f'➖ Снято <b>−{money(amt)}₽</b> с {name}\nОстаток · {money(new_bal)}₽',
                reply_markup=MAIN_KB, parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid, f'➖ <b>−{money(amt)}₽</b> — снятие овнером', parse_mode='HTML')
            except Exception:
                pass
        elif state == 'owner_set':
            if not is_owner(u):
                raise ValueError('только владелец')
            amt = parse_amount_text(t, minimum=0)
            if amt is None:
                raise ValueError(f'сумма от 0 до {money(MAX_BALANCE)}')
            tid = extra
            tu = get_user(tid)
            if not tu:
                raise ValueError('игрок не найден')
            safe_set_balance(tid, amt)
            name = f"@{tu[1]}" if tu[1] else f"id{tid}"
            await update.message.reply_text(
                f'✏️ Баланс {name} = <b>{money(amt)}₽</b>',
                reply_markup=MAIN_KB, parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid, f'✏️ Баланс установлен овнером: <b>{money(amt)}₽</b>', parse_mode='HTML')
            except Exception:
                pass
        elif state == 'owner_priv_grant':
            if not is_main_owner(u):
                raise ValueError('только главный владелец')
            target = t.lstrip('@').strip()
            if t.isdigit():
                rows = q("SELECT user_id,username FROM users WHERE user_id=?", (int(t),))
            else:
                rows = q(
                    "SELECT user_id,username FROM users WHERE LOWER(username)=LOWER(?)",
                    (target,))
            if not rows:
                raise ValueError('игрок не найден — пусть сначала напишет боту /start')
            tid, un = rows[0][0], rows[0][1]
            if is_main_owner(type('U', (), {'id': tid, 'username': un})()):
                raise ValueError('это уже главный владелец')
            grant_owner_priv(tid, un)
            name = f"@{un}" if un else f"id{tid}"
            await update.message.reply_text(
                f"🌟 Овнер выдан: <b>{name}</b>\n"
                f"Теперь у игрока команда <code>овнер</code>",
                reply_markup=MAIN_KB, parse_mode='HTML')
            try:
                await ctx.bot.send_message(
                    tid,
                    "🌟 Вам выданы права <b>владельца</b> казино!\n"
                    "Команда: <code>овнер</code>",
                    parse_mode='HTML')
            except Exception:
                pass
        elif state == 'bc':
            users = q('SELECT user_id FROM users WHERE banned=0')
            ok = 0
            for (target,) in (users or []):
                try:
                    await ctx.bot.send_message(target, t)
                    ok += 1
                    await asyncio.sleep(0.04)
                except Exception:
                    pass
            await update.message.reply_text(f'✅ Доставлено: {ok}/{len(users or [])}', reply_markup=MAIN_KB)
        elif state == 'promo_add':
            p = t.split()
            if len(p) != 3:
                raise ValueError('формат: КОД СУММА ЛИМИТ')
            code = p[0].upper()
            amt, mx = int(p[1]), int(p[2])
            if amt <= 0 or mx <= 0:
                raise ValueError('значения должны быть > 0')
            q('INSERT OR REPLACE INTO promos(code,amount,uses,max_uses) VALUES(?,?,0,?)',
              (code, amt, mx), fetch=False)
            q('DELETE FROM promo_uses WHERE code=?', (code,), fetch=False)
            await update.message.reply_text(f'✅ Промокод {code} создан', reply_markup=MAIN_KB)
        elif state == 'promo_del':
            code = t.upper()
            q('DELETE FROM promo_uses WHERE code=?', (code,), fetch=False)
            q('DELETE FROM promos WHERE code=?', (code,), fetch=False)
            await update.message.reply_text(f'🗑 {code} удалён', reply_markup=MAIN_KB)
        elif state == 'add_admin':
            target = t.lstrip('@')
            if t.isdigit():
                rows = q("SELECT username,user_id FROM users WHERE user_id=?", (int(t),))
            else:
                rows = q("SELECT username,user_id FROM users WHERE LOWER(username)=LOWER(?)", (target,))
            if not rows:
                if target and target.replace('_', '').isalnum():
                    q('INSERT OR IGNORE INTO admins(username,user_id) VALUES(?,NULL)', (target,), fetch=False)
                    await update.message.reply_text(f'✅ Админ @{target} добавлен', reply_markup=MAIN_KB)
                else:
                    await update.message.reply_text('❌ Пользователь не найден', reply_markup=MAIN_KB)
            else:
                un, uid = rows[0][0], rows[0][1]
                if un and un.lower() == MAIN_ADMIN.lower():
                    await update.message.reply_text('👑 Это владелец', reply_markup=MAIN_KB)
                else:
                    q('INSERT OR IGNORE INTO admins(username,user_id) VALUES(?,?)', (un, uid), fetch=False)
                    await update.message.reply_text(f'✅ Админ @{un} добавлен', reply_markup=MAIN_KB)
        elif state == 'add_mod':
            target = t.lstrip('@')
            if t.isdigit():
                rows = q("SELECT username,user_id FROM users WHERE user_id=?", (int(t),))
            else:
                rows = q("SELECT username,user_id FROM users WHERE LOWER(username)=LOWER(?)", (target,))
            if not rows:
                if target and target.replace('_', '').isalnum():
                    q('INSERT OR IGNORE INTO moderators(username,user_id) VALUES(?,NULL)', (target,), fetch=False)
                    await update.message.reply_text(f'✅ Модератор @{target} добавлен', reply_markup=MAIN_KB)
                else:
                    await update.message.reply_text('❌ Пользователь не найден', reply_markup=MAIN_KB)
            else:
                un, uid = rows[0][0], rows[0][1]
                q('INSERT OR IGNORE INTO moderators(username,user_id) VALUES(?,?)', (un, uid), fetch=False)
                await update.message.reply_text(f'✅ Модератор @{un} добавлен', reply_markup=MAIN_KB)
                try:
                    await ctx.bot.send_message(uid, '🛡 Вам выданы права модератора!')
                except Exception:
                    pass
        else:
            raise ValueError('неизвестное состояние')
        ctx.user_data['adm_state'] = None
    except Exception as e:
        await update.message.reply_text(f'❌ {e}\nПовторите ввод или напишите «отмена»')
    return True


# ═══════════════════════════════════════════════════════════
# КЛАНЫ
# ═══════════════════════════════════════════════════════════
def clan_get(uid):
    rows = q("""SELECT c.clan_id,c.tag,c.name,c.owner_id,c.level,c.xp,c.balance,cm.role
                FROM clans c JOIN clan_members cm ON cm.clan_id=c.clan_id WHERE cm.user_id=?""", (uid,))
    return rows[0] if rows else None


def clan_xp_need(level): return max(100_000, int(100_000 * (int(level) ** 2.15)))


def clan_kb(uid):
    c = clan_get(uid)
    if not c:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🏰 Создать", callback_data="clan_new")],
            [InlineKeyboardButton("📨 Приглашения", callback_data="clan_invites")],
            [InlineKeyboardButton("🔎 Найти", callback_data="clan_find")],
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu_main")]])
    rows = [
        [InlineKeyboardButton("👥 Участники", callback_data="clan_members"),
         InlineKeyboardButton("📨 Пригласить", callback_data="clan_invite")],
        [InlineKeyboardButton("📬 Приглашения", callback_data="clan_invites"),
         InlineKeyboardButton("📈 Уровень", callback_data="clan_level")]]
    if c[7] == "owner":
        rows.append([InlineKeyboardButton("🗑 Удалить", callback_data="clan_delete")])
    else:
        rows.append([InlineKeyboardButton("🚪 Выйти", callback_data="clan_leave")])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


async def clan_callback(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id; qr = update.callback_query
    try: await qr.answer()
    except Exception: pass
    d = qr.data
    if d == "clan_new":
        ctx.user_data["clan_create_new"] = True
        is_adm = is_admin_by_id(uid)
        cost_line = "Создание <b>бесплатно</b> (админ)." if is_adm else f"Стоимость · <b>{money(CLAN_CREATE_COST)}₽</b>"
        await qsopra_safe_edit(qr.message,
            header('🏰', 'СОЗДАНИЕ КЛАНА') + f"\n\n{cost_line}\n\nНапиши: <code>TAG Название</code>", parse_mode="HTML")
        return
    if d == "clan_find":
        rows = q("SELECT tag,name,level FROM clans ORDER BY level DESC LIMIT 20")
        msg = header('🔎', 'КЛАНЫ') + "\n\n" + "\n".join(f"🏰 <b>{r[1]}</b> [{r[0]}] Lv.{r[2]}" for r in rows) if rows else "🔎 Кланов нет."
        await qsopra_safe_edit(qr.message, msg, reply_markup=clan_kb(uid), parse_mode="HTML")
        return
    c = clan_get(uid)
    if d == "clan_invites":
        rows = q("SELECT i.clan_id,c.tag,c.name FROM clan_invites i JOIN clans c ON c.clan_id=i.clan_id WHERE i.user_id=? AND i.used=0", (uid,))
        if not rows:
            await qsopra_safe_edit(qr.message, "📬 Нет приглашений.", reply_markup=clan_kb(uid)); return
        kb = [[InlineKeyboardButton(f"✅ {name} [{tag}]", callback_data=f"clan_yes:{cid}"),
               InlineKeyboardButton("❌", callback_data=f"clan_no:{cid}")] for cid, tag, name in rows[:15]]
        kb.append([InlineKeyboardButton("⬅️", callback_data="menu_clans")])
        await qsopra_safe_edit(qr.message, "📨", reply_markup=InlineKeyboardMarkup(kb)); return
    if d == "clan_members":
        if not c: await qsopra_safe_edit(qr.message, "❌", reply_markup=clan_kb(uid)); return
        rows = q("SELECT u.username,cm.user_id,cm.role FROM clan_members cm JOIN users u ON u.user_id=cm.user_id WHERE cm.clan_id=? ORDER BY cm.role DESC", (c[0],))
        lines = [f"👥 <b>{c[2]} [{c[1]}]</b>"] + [f"• @{name or mid} — {role}" for name, mid, role in rows[:50]]
        await qsopra_safe_edit(qr.message, "\n".join(lines), reply_markup=clan_kb(uid), parse_mode="HTML"); return
    if d == "clan_level":
        if not c: await qsopra_safe_edit(qr.message, "❌", reply_markup=clan_kb(uid)); return
        need = clan_xp_need(c[4])
        await qsopra_safe_edit(qr.message, f"📈 <b>{c[2]}</b>\n\nLv. <b>{c[4]}</b>\nXP · <b>{money(c[5])}/{money(need)}</b>",
            reply_markup=clan_kb(uid), parse_mode="HTML"); return
    if d == "clan_invite":
        if not c or c[7] not in ("owner", "officer"):
            await qsopra_safe_edit(qr.message, "⛔", reply_markup=clan_kb(uid)); return
        ctx.user_data["clan_invite_id"] = c[0]
        await qsopra_safe_edit(qr.message, "📨 @username:", parse_mode="HTML"); return
    if d == "clan_leave":
        if c and c[3] != uid:
            q("DELETE FROM clan_members WHERE user_id=?", (uid,), fetch=False)
            await qsopra_safe_edit(qr.message, "🚪", reply_markup=clan_kb(uid))
        return
    if d == "clan_delete":
        if c and c[3] == uid:
            q("DELETE FROM clan_members WHERE clan_id=?", (c[0],), fetch=False)
            q("DELETE FROM clan_invites WHERE clan_id=?", (c[0],), fetch=False)
            q("DELETE FROM clans WHERE clan_id=?", (c[0],), fetch=False)
            await qsopra_safe_edit(qr.message, "🗑", reply_markup=clan_kb(uid))
        return
    if d.startswith("clan_yes:"):
        cid = int(d.split(":")[1])
        if clan_get(uid):
            try: await qr.answer("Уже в клане", show_alert=True)
            except Exception: pass
            return
        q("INSERT INTO clan_members(clan_id,user_id,role,joined_at) VALUES(?,?,?,?)", (cid, uid, "member", datetime.now().isoformat()), fetch=False)
        q("UPDATE clan_invites SET used=1 WHERE clan_id=? AND user_id=?", (cid, uid), fetch=False)
        await qsopra_safe_edit(qr.message, "✅ Вступил!", reply_markup=clan_kb(uid)); return
    if d.startswith("clan_no:"):
        cid = int(d.split(":")[1])
        q("UPDATE clan_invites SET used=1 WHERE clan_id=? AND user_id=?", (cid, uid), fetch=False)
        await qsopra_safe_edit(qr.message, "❌", reply_markup=clan_kb(uid)); return


async def clan_text_state(update, ctx):
    if not update.message or not update.effective_user: return False
    raw = (update.message.text or "").strip(); uid = update.effective_user.id
    if ctx.user_data.get("clan_create_new"):
        ctx.user_data.pop("clan_create_new", None)
        parts = raw.split(maxsplit=1)
        if len(parts) != 2:
            await update.message.reply_text("❌ <code>TAG Название</code>", parse_mode="HTML"); return True
        tag = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_]", "", parts[0]).upper()[:12]
        name = parts[1].strip()[:32]
        if len(tag) < 2 or len(name) < 2:
            await update.message.reply_text("❌ Минимум 2"); return True
        if clan_get(uid):
            await update.message.reply_text("❌ Уже в клане"); return True
        if q("SELECT clan_id FROM clans WHERE UPPER(tag)=UPPER(?)", (tag,)):
            await update.message.reply_text(f"❌ Тег занят"); return True
        is_adm = is_admin_by_id(uid)
        if not is_adm:
            row = q("SELECT balance FROM users WHERE user_id=?", (uid,))
            bal = int(row[0][0]) if row else 0
            if bal < CLAN_CREATE_COST:
                await update.message.reply_text(f"❌ Нужно {money(CLAN_CREATE_COST)}₽"); return True
        now = datetime.now().isoformat(timespec="seconds")
        try:
            if not is_adm:
                q("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (CLAN_CREATE_COST, uid, CLAN_CREATE_COST), fetch=False)
            q("INSERT INTO clans(tag,name,owner_id,level,xp,balance,created_at) VALUES(?,?,?,?,?,?,?)", (tag, name, uid, 1, 0, 0, now), fetch=False)
            cid = int(q("SELECT clan_id FROM clans WHERE UPPER(tag)=UPPER(?) AND owner_id=?", (tag, uid))[0][0])
            q("INSERT INTO clan_members(clan_id,user_id,role,joined_at) VALUES(?,?,?,?)", (cid, uid, "owner", now), fetch=False)
            await update.message.reply_text(f"🏰 <b>{name}</b> [{tag}] создан!", reply_markup=clan_kb(uid), parse_mode="HTML")
        except Exception:
            try:
                q("DELETE FROM clan_members WHERE clan_id IN (SELECT clan_id FROM clans WHERE owner_id=? AND UPPER(tag)=UPPER(?))", (uid, tag), fetch=False)
                q("DELETE FROM clans WHERE owner_id=? AND UPPER(tag)=UPPER(?)", (uid, tag), fetch=False)
                if not is_adm:
                    q("UPDATE users SET balance=balance+? WHERE user_id=?", (CLAN_CREATE_COST, uid), fetch=False)
            except Exception: pass
            await update.message.reply_text("❌ Ошибка")
        return True
    if ctx.user_data.get("clan_invite_id"):
        cid = int(ctx.user_data.pop("clan_invite_id"))
        username = raw.lstrip("@").strip()
        row = q("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (username,))
        if not row:
            await update.message.reply_text("❌ Не найден"); return True
        target = int(row[0][0])
        if target == uid:
            await update.message.reply_text("❌ Себе"); return True
        my = clan_get(uid)
        if not my or my[7] not in ("owner", "officer"):
            await update.message.reply_text("⛔"); return True
        if clan_get(target):
            await update.message.reply_text("❌ Уже в клане"); return True
        q("INSERT OR REPLACE INTO clan_invites(clan_id,user_id,invited_by,used,created_at) VALUES(?,?,?,0,?)",
          (cid, target, uid, datetime.now().isoformat(timespec="seconds")), fetch=False)
        await update.message.reply_text("📨 Отправлено")
        try: await ctx.bot.send_message(target, "🏰 Приглашение в клан!")
        except Exception: pass
        return True
    return False


# ═══════════════════════════════════════════════════════════
# WORD-КОМАНДЫ
# ═══════════════════════════════════════════════════════════
async def qsopra_word_commands(update, ctx):
    if not update.message or not update.effective_user:
        return False
    raw = (update.message.text or "").strip().lower()
    uid = update.effective_user.id
    if raw == "проверка":
        if not is_owner(update.effective_user):
            await update.message.reply_text("⛔")
            return True
        tables = q("SELECT name FROM sqlite_master WHERE type='table'")
        users = q("SELECT COUNT(*) FROM users")[0][0]
        clans = q("SELECT COUNT(*) FROM clans")[0][0]
        await update.message.reply_text(
            f"🧪 Юзеров · <b>{users}</b>\nКланов · <b>{clans}</b>\nТаблиц · <b>{len(tables)}</b>\n\n✅",
            parse_mode="HTML")
        return True
    if raw == "клан":
        await update.message.reply_text("🏰 <b>КЛАНЫ</b>", reply_markup=clan_kb(uid), parse_mode="HTML")
        return True
    if raw in ("админ", "admin"):
        if not is_admin(update.effective_user):
            await update.message.reply_text("⛔ Недостаточно прав")
            return True
        await update.message.reply_text(admin_header(), reply_markup=adm_main_kb(), parse_mode="HTML")
        return True
    if raw in ("мод", "модер", "mod", "модератор"):
        if not is_mod(update.effective_user):
            await update.message.reply_text("⛔ Недостаточно прав")
            return True
        await update.message.reply_text(
            mod_header() + "\n\nОграниченные права модератора.",
            reply_markup=mod_main_kb(), parse_mode="HTML")
        return True
    if raw in ("овнер", "owner", "владелец"):
        if not is_owner(update.effective_user):
            await update.message.reply_text("⛔ Только владелец")
            return True
        await update.message.reply_text(owner_header(), reply_markup=owner_main_kb(), parse_mode="HTML")
        return True
    if raw in ("донат", "boosty", "донаты"):
        await donat_menu(update.message, uid)
        return True
    if raw.startswith("донат ") or raw.startswith("donat "):
        if not is_owner(update.effective_user):
            await update.message.reply_text("⛔ Активация только у владельца")
            return True
        code = raw.split(None, 1)[1].strip().upper()
        ok, msg = await donat_activate(ctx, code, uid)
        await update.message.reply_text(
            f"{'✅' if ok else '❌'} {msg}", parse_mode='HTML')
        return True
    if raw in ("онлайн", "online", "ктоонлайн"):
        n = qsopra_online_count()
        total = (q('SELECT COUNT(*) FROM users WHERE banned=0') or [[0]])[0][0]
        open_pvp = (q("SELECT COUNT(*) FROM pvp_rooms WHERE status IN ('open','playing')") or [[0]])[0][0]
        await update.message.reply_text(
            header('🟢', 'ОНЛАЙН') + f"\n\n"
            f"Сейчас в казино · <b>{n}</b>\n"
            f"Игроков в базе · <b>{total}</b>\n"
            f"Активных PvP · <b>{open_pvp}</b>\n\n"
            f"<i>Онлайн = активность за последние {ONLINE_TIMEOUT // 60} мин.</i>",
            parse_mode='HTML')
        return True
    if raw in ("чатбонус", "joinbonus", "бонусчат"):
        if not is_owner(update.effective_user):
            await update.message.reply_text("⛔ Только владелец")
            return True
        chat = update.effective_chat
        if not chat or chat.type == 'private':
            await update.message.reply_text(
                "Напиши эту команду <b>внутри нужного чата/канала</b>, "
                "чтобы включить бонус за вход.\n"
                f"Сейчас: {money(JOIN_BONUS_BALANCE)}₽ + {JOIN_BONUS_CRYSTALS}💎",
                parse_mode='HTML')
            return True
        register_join_bonus_chat(chat)
        await update.message.reply_text(
            f"✅ Чат привязан к бонусу за вход.\n"
            f"ID: <code>{chat.id}</code>\n"
            f"Бонус: <b>{money(JOIN_BONUS_BALANCE)}₽</b> + <b>{JOIN_BONUS_CRYSTALS}💎</b>\n"
            f"(один раз на игрока)",
            parse_mode='HTML')
        return True
    return False


async def qsopra_owner_wipe_callback(update, ctx):
    u = update.effective_user
    if not u:
        return
    qr = update.callback_query
    if not is_owner(u):
        try:
            await qr.answer("⛔", show_alert=True)
        except Exception:
            pass
        return
    try:
        await qr.answer()
    except Exception:
        pass
    await qsopra_safe_edit(qr.message,
        header('⚠️', 'ПОЛНЫЙ ВАЙП') + "\n\nСбросит всё, каждому 20 000₽ + 10💎.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 ПОДТВЕРДИТЬ", callback_data="owner_wipe_confirm")],
            [InlineKeyboardButton("⬅️", callback_data="owner_menu")]]), parse_mode="HTML")


async def qsopra_owner_wipe_confirm(update, ctx):
    u = update.effective_user
    if not u:
        return
    qr = update.callback_query
    if not is_owner(u):
        try:
            await qr.answer("⛔", show_alert=True)
        except Exception:
            pass
        return
    try:
        await qr.answer("Вайп...")
    except Exception:
        pass
    try:
        q("UPDATE users SET balance=20000, crystals=10, level=1, xp=0, energy=?",
          (ENERGY_MAX,), fetch=False)
        code = "WIPE" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        prize = random.randint(10_000_000, 1_000_000_000)
        q('INSERT OR REPLACE INTO promos(code,amount,uses,max_uses) VALUES(?,?,0,1)', (code, prize), fetch=False)
        await qsopra_safe_edit(qr.message,
            f"✅ Вайп! 20 000₽ + 10💎\n\n🎁 Промо · <code>{code}</code> ({money(prize)}₽)",
            reply_markup=back_kb("owner_menu"), parse_mode="HTML")
    except Exception as e:
        await qsopra_safe_edit(qr.message, f"❌ {e}", reply_markup=back_kb("owner_menu"))


async def qsopra_owner_menu_callback(update, ctx):
    u = update.effective_user
    if not u:
        return
    qr = update.callback_query
    if not is_owner(u):
        try:
            await qr.answer("⛔ Только владелец", show_alert=True)
        except Exception:
            pass
        return
    try:
        await qr.answer()
    except Exception:
        pass
    await qsopra_safe_edit(qr.message, owner_header(),
        reply_markup=owner_main_kb(), parse_mode="HTML")


# ═══════════════════════════════════════════════════════════
# РОУТЕР КНОПОК
# ═══════════════════════════════════════════════════════════
async def menu_cb(update, ctx):
    u = update.effective_user
    if not u: return
    uid = u.id
    qr = update.callback_query
    if not qr: return
    d = qr.data or ''
    if d.startswith('clan_'):
        await clan_callback(update, ctx); return
    if d == 'owner_wipe': await qsopra_owner_wipe_callback(update, ctx); return
    if d == 'owner_wipe_confirm': await qsopra_owner_wipe_confirm(update, ctx); return
    if d == 'owner_menu': await qsopra_owner_menu_callback(update, ctx); return
    if d == 'menu_clans':
        try:
            await qr.answer()
        except Exception:
            pass
        await qsopra_safe_edit(
            qr.message,
            header('🏰', 'КЛАНЫ') + "\n\nУправление кланом:",
            reply_markup=clan_kb(uid),
            parse_mode="HTML")
        return
    if d.startswith('vip_buy_'):
        await vip_buy_cb(update, ctx)
        return
    if d.startswith('buy_en_') or d == 'en_upgrade':
        await buy_energy_cb(update, ctx)
        return
    if d.startswith('ex_cr_') or d in ('vip_menu', 'energy_shop'):
        await exchange_cb(update, ctx)
        return
    if d == 'menu_pvp' or d.startswith('pvp_'):
        await pvp_cb(update, ctx)
        return
    if d == 'menu_donat' or d.startswith('donat_'):
        await donat_cb(update, ctx)
        return
    if (d.startswith('adm_') or d.startswith('admgv_') or d.startswith('admset_')
            or d.startswith('admall_') or d.startswith('adm_cr_')
            or d.startswith('ownall_') or d.startswith('owner_')
            or d.startswith('owngive_') or d.startswith('owngv_')
            or d.startswith('owntake_') or d.startswith('owntk_')
            or d.startswith('owntkv_') or d.startswith('ownset_')
            or d.startswith('owncr_') or d.startswith('owncrg_')
            or d.startswith('owncrall_') or d.startswith('owncrt_')
            or d.startswith('owncrts_') or d.startswith('ownen_')
            or d.startswith('mod_')):
        await adm_cb(update, ctx)
        return
    try:
        if d == 'menu_main':
            await qsopra_safe_edit(
                qr.message,
                main_menu_text(uid),
                reply_markup=main_menu_kb(),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_games':
            restore_energy(uid)
            en = get_energy(uid)
            en_txt = "∞" if is_admin_by_id(uid) else f"{en}/{user_energy_max(uid)}"
            await qsopra_safe_edit(
                qr.message,
                header('🎮', 'ИГРЫ') + f"\n\n⚡ Энергия: <b>{en_txt}</b>\n\nВыберите игру:",
                reply_markup=games_kb(),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_profile':
            await qsopra_safe_edit(qr.message, bal_text(uid), reply_markup=back_kb('menu_main'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'menu_tops':
            await qsopra_safe_edit(
                qr.message,
                header('🏆', 'ТОПЫ') + "\n\nВыберите категорию:",
                reply_markup=top_menu_kb(),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d.startswith('top_'):
            cat = d[4:]
            await qsopra_safe_edit(qr.message, top_text(cat), reply_markup=top_menu_kb(), parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_bonus':
            await bonus_cb(update, ctx)
            return
        if d == 'menu_quests':
            await qsopra_safe_edit(
                qr.message,
                header('🎯', 'КВЕСТЫ') + "\n\nЕжедневные задания:",
                reply_markup=quests_kb(uid),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_shop':
            u2 = get_user(uid)
            await qsopra_safe_edit(
                qr.message,
                header('🛍', 'МАГАЗИН') + f"\n\n💰 Баланс: <b>{display_balance(uid, u2[2])}₽</b>",
                reply_markup=shop_kb(uid),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_exchange':
            await exchange_menu(qr.message, uid)
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_transfer':
            await qsopra_safe_edit(
                qr.message,
                header('💸', 'ПЕРЕВОД') + "\n\nВыберите получателя:",
                reply_markup=transfer_kb(uid),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_cases':
            await qsopra_safe_edit(
                qr.message,
                header('📦', 'КЕЙСЫ') + "\n\nОткройте кейс и испытайте удачу:",
                reply_markup=cases_kb(),
                parse_mode='HTML')
            try:
                await qr.answer()
            except Exception:
                pass
            return
        if d == 'menu_ach':
            await qsopra_safe_edit(qr.message, achievements_text(uid), reply_markup=back_kb('menu_main'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'menu_help':
            await qsopra_safe_edit(qr.message, HELP, reply_markup=back_kb('menu_main'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('case_'):
            key = d.split('_')[1]
            try: await qr.answer('🎁')
            except Exception: pass
            await open_case(qr.message, uid, key); return
        if d.startswith('quest_'): await quest_cb(update, ctx); return
        if d.startswith('buy_'): await shop_cb(update, ctx); return
        if d == 'cancel_state':
            ctx.user_data['transfer_target'] = None
            await qsopra_safe_edit(qr.message, '❌ Отменено', reply_markup=back_kb('menu_main'))
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('trsend_'): await transfer_send(update, ctx); return
        if d.startswith('tr_'): await transfer_pick(update, ctx); return
        if d.startswith('game_'):
            game = d[5:]
            if game == 'rob':
                try: await qr.answer()
                except Exception: pass
                await play_rob_menu(qr.message, uid); return
            if game == 'duel':
                try: await qr.answer()
                except Exception: pass
                await duel_menu(qr.message, uid); return
            if game == 'crash':
                try: await qr.answer()
                except Exception: pass
                await crash_setup_menu(qr.message, uid); return
            if game == 'mines':
                try: await qr.answer()
                except Exception: pass
                await mines_preset_menu(qr.message, uid); return
            if game == 'roulette':
                try: await qr.answer()
                except Exception: pass
                await play_roulette_menu(qr.message, uid); return
            await qsopra_safe_edit(qr.message, f"🎮 <b>{game.upper()}</b>", reply_markup=bet_kb(game), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('rob_t_'): await rob_pick(update, ctx); return
        if d.startswith('duel_t_'): await duel_pick(update, ctx); return
        if d.startswith('duel_yes_') or d.startswith('duel_no_'): await duel_accept(update, ctx); return
        if d.startswith('mp_'):
            preset = d[3:]
            ctx.user_data['mines_preset'] = preset
            await qsopra_safe_edit(qr.message, f"💣 <b>{MINE_PRESETS[preset]['name']}</b>\nВыбери ставку:", reply_markup=bet_kb('mines'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('crash_auto_') or d.startswith('crash_dual_'):
            if d.startswith('crash_auto_'):
                val = d.split('_')[2]
                ctx.user_data['crash_auto'] = float(val) if val != '0' else None
                ctx.user_data['crash_dual'] = False
            else:
                ctx.user_data['crash_auto'] = None
                ctx.user_data['crash_dual'] = True
            await qsopra_safe_edit(qr.message, "🚀 <b>КРАШ 2.0</b>\nВыбери ставку:", reply_markup=bet_kb('crash'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d == 'rl_number':
            ctx.user_data['rl_wait_number'] = True
            await qsopra_safe_edit(qr.message, "🎯 Введи число 0-36 (или 'отмена')")
            try: await qr.answer()
            except Exception: pass
            return
        if d.startswith('rl_'):
            choice = d[3:]
            ctx.user_data['roulette_choice'] = choice
            await qsopra_safe_edit(qr.message, f"🎡 <b>{choice.upper()}</b>\nВыбери ставку:",
                reply_markup=bet_kb('roulette'), parse_mode='HTML')
            try: await qr.answer()
            except Exception: pass
            return
        if d.endswith('_custom') and not d.startswith('trsend_'):
            game = d[:-7]
            if game in ('mines', 'crash', 'joker', 'slots', 'dice', 'dice3', 'coin', 'hl',
                        'roulette', 'russian', 'bj', 'lottery', 'poker', 'wheel',
                        'guess', 'rob', 'duel'):
                ctx.user_data['custom_amount_target'] = {'target': 'game', 'game': game, 'user_id': None}
                try: await qr.answer()
                except Exception: pass
                await qsopra_safe_edit(qr.message, '💰 <b>Введи сумму</b>\n<i>Можно: 500, 10к, 1кк, 2ккк…</i>', parse_mode='HTML')
                return
        if d.startswith('bet_'):
            parts = d.split('_'); game = parts[1]; val = parts[2]
            u2 = get_user(uid); is_adm = is_admin_by_id(uid)
            bal = int(u2[2] or 0) if u2 else 0
            if val == 'all':
                # Всё — но не больше MAX_BET
                amt = min(bal, MAX_BET) if not is_adm else min(1_000_000, MAX_BET)
            else:
                try:
                    amt = int(val)
                except Exception:
                    try:
                        await qr.answer('❌ Некорректная ставка', show_alert=True)
                    except Exception:
                        pass
                    return
            if amt > MAX_BET:
                try:
                    await qr.answer(f'❌ Макс. ставка {money(MAX_BET)}₽', show_alert=True)
                except Exception:
                    pass
                return
            if not is_adm and amt > bal and game not in ('rob', 'duel'):
                try:
                    await qr.answer(f'❌ У тебя {money(bal)}₽', show_alert=True)
                except Exception:
                    pass
                return
            if amt < MIN_BET:
                try:
                    await qr.answer(f'❌ Мин. {MIN_BET}₽', show_alert=True)
                except Exception:
                    pass
                return
            msg = qr.message
            try:
                await qr.answer()
            except Exception:
                pass
            if game == 'mines':
                preset = ctx.user_data.get('mines_preset', 'small')
                await _safe_edit(msg, '💣')
                await start_mines(msg, uid, amt, preset)
            elif game == 'crash':
                auto = ctx.user_data.get('crash_auto')
                dual = ctx.user_data.get('crash_dual', False)
                await _safe_edit(msg, '🚀')
                await start_crash(msg, uid, amt, auto, dual)
            elif game == 'joker':
                await _safe_edit(msg, '🃏')
                await play_joker(msg, uid, amt)
            elif game == 'slots':
                await _safe_edit(msg, '🎰')
                await play_slots(msg, uid, amt)
            elif game == 'dice':
                await _safe_edit(msg, '🎲')
                await play_dice(msg, uid, amt)
            elif game == 'dice3':
                await _safe_edit(msg, '🎲')
                await play_dice3(msg, uid, amt)
            elif game == 'coin':
                await _safe_edit(
                    msg,
                    f"🪙 {money(amt)}₽:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🦅 Орёл', callback_data=f'cn_{amt}_o'),
                         InlineKeyboardButton('🪙 Решка', callback_data=f'cn_{amt}_r')],
                        [InlineKeyboardButton('⬅️', callback_data='menu_games')]]))
            elif game == 'hl':
                await _safe_edit(
                    msg,
                    f"📈 {money(amt)}₽:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('📈 БОЛЬШЕ', callback_data=f'hl_{amt}_more'),
                         InlineKeyboardButton('📉 МЕНЬШЕ', callback_data=f'hl_{amt}_less')],
                        [InlineKeyboardButton('⬅️', callback_data='menu_games')]]))
            elif game == 'roulette':
                ch = ctx.user_data.get('roulette_choice', 'kr')
                num = ctx.user_data.get('rl_number')
                await _safe_edit(msg, '🎡')
                await play_roulette_2(msg, uid, amt, ch, num)
            elif game == 'russian':
                await _safe_edit(msg, '🔫')
                await play_russian(msg, uid, amt)
            elif game == 'guess':
                await _safe_edit(msg, '🎯')
                await play_guess(msg, uid, amt)
            elif game == 'poker':
                await _safe_edit(msg, '🎲')
                await play_poker(msg, uid, amt)
            elif game == 'wheel':
                await _safe_edit(msg, '🎡')
                await play_wheel(msg, uid, amt)
            elif game == 'lottery':
                await _safe_edit(msg, '🎟')
                await play_lottery(msg, uid, amt)
            elif game == 'bj':
                await _safe_edit(msg, '🃏')
                await play_blackjack(msg, uid, amt)
            elif game == 'rob':
                await play_rob(update, ctx, uid, amt)
            elif game == 'duel':
                tid = ctx.user_data.get('duel_target')
                if tid:
                    await do_duel_challenge(update, ctx, uid, tid, amt)
            return
        if d.startswith('cn_'):
            parts = d.split('_'); amt = int(parts[1]); ch = parts[2]
            try: await qr.answer()
            except Exception: pass
            await play_coin(qr.message, uid, amt, ch); return
        if d.startswith('hl_'):
            parts = d.split('_'); amt = int(parts[1]); dir_ = parts[2]
            try: await qr.answer()
            except Exception: pass
            await play_hl(qr.message, uid, amt, dir_); return
        if d == 'm_cash': await mines_cash(update, ctx); return
        if d.startswith('m_'): await mines_click(update, ctx); return
        if d == 'cr_cash': await crash_cash(update, ctx, False); return
        if d == 'cr_cash_risky': await crash_cash(update, ctx, True); return
        if d.startswith('jk_'): await joker_click(update, ctx); return
        if d.startswith('g_') and not d.startswith('game_'): await guess_click(update, ctx); return
        if d == 'bj_hit': await bj_hit(update, ctx); return
        if d == 'bj_stop': await bj_stop(update, ctx); return
        if d == 'noop':
            try: await qr.answer()
            except Exception: pass
            return
        try: await qr.answer()
        except Exception: pass
    except Exception as e:
        if _is_harmless_tg_error(e) or _is_db_transient(e):
            try:
                await qr.answer('⏳ Попробуй ещё раз', show_alert=False)
            except Exception:
                pass
            return
        print('MENU_CB ERR:', repr(e))
        try:
            await qr.answer(f'Ошибка: {str(e)[:120]}', show_alert=True)
        except Exception:
            pass


async def reply_button(update, ctx):
    u = update.effective_user
    if not u or not update.message:
        return
    ensure_user(u)
    if is_banned(u):
        return
    if maintenance_on() and not is_staff(u):
        return
    text = update.message.text or ''
    if text == '🎮 Игры':
        restore_energy(u.id)
        en = get_energy(u.id)
        en_txt = "∞" if is_admin_by_id(u.id) else f"{en}/{user_energy_max(u.id)}"
        await update.message.reply_text(
            header('🎮', 'ИГРЫ') + f"\n\n⚡ Энергия: <b>{en_txt}</b>\n\nВыберите игру:",
            reply_markup=games_kb(),
            parse_mode='HTML')
    elif text == '👤 Профиль':
        await update.message.reply_text(bal_text(u.id), parse_mode='HTML')
    elif text == '🏆 Топы':
        await update.message.reply_text("🏆 <b>ТОПЫ</b>", reply_markup=top_menu_kb(), parse_mode='HTML')
    elif text == '🎁 Бонус': await send_bonus(update)
    elif text == '🎯 Квесты':
        await update.message.reply_text("🎯", reply_markup=quests_kb(u.id), parse_mode='HTML')
    elif text == '🛍 Магазин':
        uu = get_user(u.id)
        await update.message.reply_text(f"🛍 {display_balance(u.id, uu[2])}₽", reply_markup=shop_kb(u.id), parse_mode='HTML')
    elif text == '💎 Обмен':
        await exchange_menu(update.message, u.id)
    elif text == '📦 Кейсы':
        await update.message.reply_text("📦", reply_markup=cases_kb(), parse_mode='HTML')
    elif text == '🏅 Ачивки':
        await update.message.reply_text(achievements_text(u.id), parse_mode='HTML')
    elif text == 'ℹ️ Помощь':
        await update.message.reply_text(HELP, reply_markup=MAIN_KB, parse_mode='HTML')


# ═══════════════════════════════════════════════════════════
# ТЕКСТОВЫЙ РОУТЕР
# ═══════════════════════════════════════════════════════════
async def text_router(update, ctx):
    u = update.effective_user
    if not u or not update.message:
        return
    uid = u.id
    try:
        qsopra_mark_online(uid)
    except Exception:
        pass
    # ── Перевод / своя сумма — ПЕРВЫМИ, до рулетки и админки ──
    raw_txt = (update.message.text or '').strip()
    low_txt = raw_txt.lower()

    if ctx.user_data.get('transfer_target') or (
            ctx.user_data.get('custom_amount_target') or {}).get('target') == 'transfer':
        if low_txt in ('отмена', 'cancel', '/cancel'):
            ctx.user_data.pop('transfer_target', None)
            ctx.user_data.pop('custom_amount_target', None)
            await update.message.reply_text('❌ Отменено', reply_markup=MAIN_KB)
            return
        if await try_transfer(update, ctx):
            ctx.user_data.pop('custom_amount_target', None)
            return

    if await qsopra_word_commands(update, ctx):
        return
    if await clan_text_state(update, ctx):
        return

    if ctx.user_data.get('rl_wait_number'):
        txt = low_txt
        if txt == 'отмена':
            ctx.user_data['rl_wait_number'] = None
            await update.message.reply_text('❌ Отменено', reply_markup=MAIN_KB); return
        try:
            n = int(txt)
            if not 0 <= n <= 36:
                await update.message.reply_text('❌ 0-36'); return
            ctx.user_data['rl_wait_number'] = None
            ctx.user_data['roulette_choice'] = 'number'
            ctx.user_data['roulette_number'] = n
            await update.message.reply_text(f'🎯 Число {n} выбрано. Теперь ставка:',
                reply_markup=bet_kb('roulette'))
            return
        except Exception:
            await update.message.reply_text('❌ Число рулетки 0-36 или "отмена"'); return

    custom = ctx.user_data.get('custom_amount_target')
    if custom:
        if low_txt in ('отмена', 'cancel', '/cancel'):
            ctx.user_data.pop('custom_amount_target', None)
            await update.message.reply_text('❌ Отменено', reply_markup=MAIN_KB)
            return
        min_amt = 1 if custom.get('target') == 'transfer' else MIN_BET
        amount = parse_amount_text(raw_txt, minimum=min_amt)
        if amount is None:
            await update.message.reply_text(
                f'❌ Не понял сумму (мин. {min_amt}₽)\n'
                f'<i>Примеры: 1к · 10к · 1кк · 10кк · 500 · гугл</i>',
                parse_mode='HTML')
            return
        if custom.get('target') != 'transfer' and amount > MAX_BET:
            amount = MAX_BET
        # Проверка баланса ДО запуска игры (кроме rob/duel)
        game_preview = custom.get('game')
        if custom.get('target') == 'game' and game_preview not in ('rob', 'duel'):
            if not is_admin_by_id(uid):
                uu = get_user(uid)
                bal = int(uu[2] or 0) if uu else 0
                if amount > bal:
                    await update.message.reply_text(
                        f'❌ Недостаточно средств · у тебя {money(bal)}₽\n'
                        f'Ставка не принята, баланс не изменён.',
                        reply_markup=MAIN_KB)
                    ctx.user_data.pop('custom_amount_target', None)
                    return
        ctx.user_data.pop('custom_amount_target', None)
        ctx.user_data.pop('transfer_target', None)
        target = custom.get('target')
        if target == 'transfer':
            tid = custom.get('user_id')
            ok, msg = transfer_money(uid, tid, amount)
            await update.message.reply_text(msg, reply_markup=MAIN_KB, parse_mode='HTML')
            if ok:
                try:
                    await ctx.bot.send_message(tid, f'💰 <b>+{money(amount)}₽</b>', parse_mode='HTML')
                except Exception:
                    pass
            return
        game = custom.get('game')
        if game:
            msg = update.message
            if game == 'coin':
                await msg.reply_text(f'🪙 {money(amount)}₽:',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('🦅 Орёл', callback_data=f'cn_{amount}_o'),
                         InlineKeyboardButton('🪙 Решка', callback_data=f'cn_{amount}_r')],
                        [InlineKeyboardButton('⬅️', callback_data='menu_games')]]))
            elif game == 'hl':
                await msg.reply_text(f'📈 {money(amount)}₽:',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('📈 БОЛЬШЕ', callback_data=f'hl_{amount}_more'),
                         InlineKeyboardButton('📉 МЕНЬШЕ', callback_data=f'hl_{amount}_less')],
                        [InlineKeyboardButton('⬅️', callback_data='menu_games')]]))
            elif game == 'rob':
                await play_rob(update, ctx, uid, amount)
            elif game == 'duel':
                tid = ctx.user_data.get('duel_target')
                if tid: await do_duel_challenge(update, ctx, uid, tid, amount)
            else:
                funcs = {
                    'mines': lambda m, i, a: start_mines(m, i, a, ctx.user_data.get('mines_preset', 'small')),
                    'crash': lambda m, i, a: start_crash(m, i, a, ctx.user_data.get('crash_auto'), ctx.user_data.get('crash_dual', False)),
                    'joker': play_joker, 'slots': play_slots, 'dice': play_dice, 'dice3': play_dice3,
                    'russian': play_russian, 'guess': play_guess, 'poker': play_poker,
                    'wheel': play_wheel, 'lottery': play_lottery, 'bj': play_blackjack,
                }
                fn = funcs.get(game)
                if fn: await fn(msg, uid, amount)
                else: await msg.reply_text('❌')
            return

    ensure_user(u)
    if is_banned(u): return
    if maintenance_on() and not is_staff(u): return
    if is_staff(u) and ctx.user_data.get('adm_state'):
        if await handle_admin_state(update, ctx):
            return
    if ctx.user_data.get('transfer_target'):
        if await try_transfer(update, ctx): return
    if update.message.text in ('🎮 Игры', '👤 Профиль', '🏆 Топы', '🎁 Бонус',
                               '🎯 Квесты', '🛍 Магазин', '💎 Обмен',
                               '📦 Кейсы', '🏅 Ачивки', 'ℹ️ Помощь'):
        await reply_button(update, ctx); return
    text = (update.message.text or '').strip()
    parts = text.split()
    if not parts:
        return
    cmd = parts[0].lower()
    args = parts[1:]
    single = len(parts) == 1
    chat = update.effective_chat
    is_private = bool(chat and chat.type == 'private')
    # Ответ на сообщение бота — можно коротких алиасов и в группе
    reply_to_bot = False
    try:
        rt = update.message.reply_to_message
        if rt and rt.from_user and rt.from_user.id == ctx.bot.id:
            reply_to_bot = True
    except Exception:
        pass

    def allow_short():
        """Короткие триггеры (я, б, п…) — не в середине фразы и не в групповой болтовне."""
        if not single:
            return False
        if cmd not in SHORT_TRIGGERS:
            return True
        return is_private or reply_to_bot

    if not allow_short():
        # Сообщение вроде «я пошёл» / «п завтра» в группе — игнор
        if cmd in SHORT_TRIGGERS and (not single or not (is_private or reply_to_bot)):
            return

    if cmd in ('баланс', 'профиль') or (single and cmd in ('б', 'я') and allow_short()):
        await update.message.reply_text(bal_text(uid), parse_mode='HTML')
        return
    if cmd in ('хелп', 'помощь', 'help') or (single and cmd == 'х' and allow_short()):
        await update.message.reply_text(HELP, reply_markup=MAIN_KB, parse_mode='HTML')
        return
    if cmd in ('меню', 'menu'):
        await cmd_menu(update, ctx)
        return
    if cmd == 'перевод' or (single and cmd == 'п' and allow_short()):
        await update.message.reply_text("💸", reply_markup=transfer_kb(uid), parse_mode='HTML')
        return
    if cmd in ('топ', 'top') and (single or not args):
        await update.message.reply_text(top_text('balance'), reply_markup=top_menu_kb(), parse_mode='HTML')
        return
    if cmd == 'бонус' and single:
        await send_bonus(update)
        return
    if cmd in ('квесты', 'квест') and single:
        await update.message.reply_text("🎯", reply_markup=quests_kb(uid), parse_mode='HTML')
        return
    if cmd in ('магазин', 'титул') and single:
        await update.message.reply_text("🛍", reply_markup=shop_kb(uid), parse_mode='HTML')
        return
    if cmd in ('обмен', 'обменник') and single:
        await exchange_menu(update.message, uid)
        return
    if cmd in ('кейс', 'кейсы') and single:
        await update.message.reply_text("📦", reply_markup=cases_kb(), parse_mode='HTML')
        return
    if cmd in ('админ', 'admin') or (single and cmd == 'ап' and allow_short()):
        if is_admin(u):
            await show_admin_panel(update.message)
        return
    if cmd == 'мем' and single:
        await update.message.reply_text(f"😎 {pick(MEMES)}")
        return
    if cmd == 'совет' and single:
        await update.message.reply_text(f"💡 {pick(ADVICE)}")
        return
    if cmd in ('отмена', 'cancel') and single:
        ctx.user_data['transfer_target'] = None
        ctx.user_data['adm_state'] = None
        ctx.user_data.pop('custom_amount_target', None)
        await update.message.reply_text('❌ Отменено', reply_markup=MAIN_KB)
        return

    def pa():
        if not args:
            return None
        # ставки с сокращениями 10к / 1кк
        return parse_amount_text(args[0], minimum=MIN_BET)

    # Игровые команды: только если есть ставка, иначе не глотаем чат
    game_map = {
        'мины': lambda a: start_mines(update.message, uid, a, 'small'),
        'краш': lambda a: start_crash(update.message, uid, a, None, False),
        'джокер': lambda a: play_joker(update.message, uid, a),
        'слоты': lambda a: play_slots(update.message, uid, a),
        'кости': lambda a: play_dice(update.message, uid, a),
        'кубик': lambda a: play_dice(update.message, uid, a),
        'кости3': lambda a: play_dice3(update.message, uid, a),
        'угадай': lambda a: play_guess(update.message, uid, a),
        'покер': lambda a: play_poker(update.message, uid, a),
        'лотерея': lambda a: play_lottery(update.message, uid, a),
        'рулетка': lambda a: play_roulette_2(update.message, uid, a, 'kr'),
        'колесо': lambda a: play_wheel(update.message, uid, a),
        'рулетка2': lambda a: play_wheel(update.message, uid, a),
        'рулетка_р': lambda a: play_russian(update.message, uid, a),
        'ррулетка': lambda a: play_russian(update.message, uid, a),
    }
    if cmd in game_map:
        a = pa()
        if a:
            await game_map[cmd](a)
        elif single and is_private:
            await update.message.reply_text(
                f'Формат: <code>{cmd} сумма</code>\n'
                f'Пример: <code>{cmd} 10к</code>',
                parse_mode='HTML')
        return
    if cmd == 'монетка':
        a = pa()
        ch = args[1].lower() if len(args) > 1 else ''
        if a and ch in ('о', 'р', 'o', 'p'):
            await play_coin(update.message, uid, a, 'о' if ch in ('о', 'o') else 'р')
        elif single and is_private:
            await update.message.reply_text(
                'Формат: <code>монетка сумма о/р</code>\n'
                'Пример: <code>монетка 10к о</code>',
                parse_mode='HTML')
        return
    if cmd in ('больше',) or (single and cmd == 'бб' and allow_short()):
        a = pa()
        if a:
            await play_hl(update.message, uid, a, 'more')
        elif single and is_private:
            await update.message.reply_text('Формат: <code>больше 10к</code>', parse_mode='HTML')
        return
    if cmd in ('меньше',) or (single and cmd == 'мм' and allow_short()):
        a = pa()
        if a:
            await play_hl(update.message, uid, a, 'less')
        elif single and is_private:
            await update.message.reply_text('Формат: <code>меньше 10к</code>', parse_mode='HTML')
        return
    if cmd in ('блэкджек',) or (single and cmd == 'бдж' and allow_short()):
        a = pa()
        if a:
            await play_blackjack(update.message, uid, a)
        elif single and is_private:
            await update.message.reply_text('Формат: <code>блэкджек 10к</code>', parse_mode='HTML')
        return
    if cmd == 'промо':
        if args:
            code = args[0].upper()
            r = q('SELECT amount,uses,max_uses FROM promos WHERE code=?', (code,))
            if not r:
                await update.message.reply_text('Извините, такой промокод не найден.'); return
            amt, uses, mx = r[0]
            if uses >= mx:
                await update.message.reply_text('Извините, лимит активаций исчерпан.'); return
            if q('SELECT 1 FROM promo_uses WHERE code=? AND user_id=?', (code, uid)):
                await update.message.reply_text('Извините, вы уже активировали этот промокод.'); return
            q('INSERT OR IGNORE INTO promo_uses(code,user_id) VALUES(?,?)', (code, uid), fetch=False)
            q('UPDATE promos SET uses=uses+1 WHERE code=?', (code,), fetch=False)
            safe_add_balance(uid, amt)
            await update.message.reply_text(f"🎫 <b>{code}</b>\n💵 +{money(amt)}₽", parse_mode='HTML')
        else:
            await update.message.reply_text('Напишите: промо КОД')
        return

    # Обычные сообщения не трогаем. «Не понял» — только в личке и только на короткие «командоподобные» слова
    chat = update.effective_chat
    if not chat or chat.type != 'private':
        return
    stripped = (text or '').strip()
    if not stripped:
        return
    # Длинный текст / несколько слов = обычное сообщение
    if len(stripped) > 24 or len(parts) > 1:
        return
    # Только одно короткое слово (или /команда)
    if stripped.startswith('/') or stripped.replace('_', '').isalnum():
        await update.message.reply_text(
            "Извините, я не понял эту команду.\n"
            "Напишите <b>меню</b> или /start.",
            parse_mode='HTML')
    return


# ═══════════════════════════════════════════════════════════
# ПЕРЕЗАПУСК / СТАРТ / MAIN
# ═══════════════════════════════════════════════════════════
async def cmd_restart(update, ctx):
    u = update.effective_user
    if not u or not is_admin(u): return
    msg = await update.message.reply_text("🔄 <b>ПЕРЕЗАПУСК...</b>", parse_mode='HTML')
    await asyncio.sleep(1.5)
    subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    sys.exit(0)


def is_join_bonus_chat(chat):
    """Проверка: чат участвует в бонусе за вход."""
    if not chat:
        return False
    if chat.id in JOIN_CHAT_IDS:
        return True
    un = (chat.username or '').lower().lstrip('@')
    if un and un in JOIN_CHAT_USERNAMES:
        return True
    # Зарегистрированные в БД
    try:
        if q('SELECT 1 FROM join_bonus_chats WHERE chat_id=?', (chat.id,)):
            JOIN_CHAT_IDS.add(chat.id)
            return True
    except Exception:
        pass
    return False


def register_join_bonus_chat(chat):
    """Добавить чат в список бонусных (для приватных ссылок)."""
    if not chat:
        return
    JOIN_CHAT_IDS.add(chat.id)
    title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat.id)
    q('INSERT OR REPLACE INTO join_bonus_chats(chat_id, title, added_at) VALUES(?,?,?)',
      (chat.id, title, datetime.now().isoformat()), fetch=False)


def give_join_bonus(uid, chat_id):
    """Выдать бонус один раз за этот чат. Возвращает (ok, already)."""
    if q('SELECT 1 FROM join_bonus WHERE user_id=? AND chat_id=?', (uid, chat_id)):
        return False, True
    u = get_user(uid)
    if not u:
        return False, False
    if u[3]:  # banned
        return False, False
    # INSERT OR IGNORE — если уже есть, rowcount 0
    changed = exec_change(
        'INSERT OR IGNORE INTO join_bonus(user_id, chat_id, given_at) VALUES(?,?,?)',
        (uid, chat_id, datetime.now().isoformat()))
    if not changed:
        return False, True
    safe_add_balance(uid, JOIN_BONUS_BALANCE)
    q('UPDATE users SET crystals=crystals+? WHERE user_id=?',
      (JOIN_BONUS_CRYSTALS, uid), fetch=False)
    return True, False


def ensure_user_from_member(m):
    """Создать пользователя из ChatMember/User."""
    class _U:
        pass
    fake = _U()
    fake.id = m.id
    fake.username = getattr(m, 'username', None)
    fake.first_name = getattr(m, 'first_name', None) or 'Игрок'
    ensure_user(fake)
    return m.id


async def _deliver_join_bonus(ctx, chat, user, announce_message=None):
    """Сразу выдать бонус при входе в бонусный чат."""
    if not user or getattr(user, 'is_bot', False):
        return
    if user.id == ctx.bot.id:
        return
    ensure_user_from_member(user)
    name = user.first_name or 'Игрок'
    ok, already = give_join_bonus(user.id, chat.id)
    text_ok = (
        f"👋 <b>{name}</b>!\n\n"
        f"🎁 <b>Бонус за вход начислен сразу:</b>\n"
        f"💰 <b>+{money(JOIN_BONUS_BALANCE)}₽</b>\n"
        f"💎 <b>+{JOIN_BONUS_CRYSTALS}</b>"
    )
    text_already = f"👋 {name}! Бонус за этот чат уже был получен."

    if ok:
        if announce_message is not None:
            try:
                await announce_message.reply_text(text_ok, parse_mode='HTML')
            except Exception:
                try:
                    await ctx.bot.send_message(chat.id, text_ok, parse_mode='HTML')
                except Exception:
                    pass
        else:
            try:
                await ctx.bot.send_message(chat.id, text_ok, parse_mode='HTML')
            except Exception:
                pass
        try:
            await ctx.bot.send_message(
                user.id,
                f"🎁 Бонус за вход в чат начислен!\n"
                f"💰 <b>+{money(JOIN_BONUS_BALANCE)}₽</b>\n"
                f"💎 <b>+{JOIN_BONUS_CRYSTALS}</b>",
                parse_mode='HTML')
        except Exception:
            pass
    elif already:
        if announce_message is not None:
            try:
                await announce_message.reply_text(text_already, parse_mode='HTML')
            except Exception:
                pass


async def welcome_new(update, ctx):
    """Мгновенный бонус при new_chat_members (группы)."""
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    bonus_chat = is_join_bonus_chat(chat)

    for m in update.message.new_chat_members:
        if m.id == ctx.bot.id:
            tip = (
                f"🎰 Бот в чате.\nID: <code>{chat.id}</code>\n"
            )
            if bonus_chat:
                tip += "✅ Бонус за вход активен — награда выдаётся сразу при заходе."
            else:
                tip += "Владелец: напиши здесь <code>чатбонус</code>"
            try:
                await update.message.reply_text(tip, parse_mode='HTML')
            except Exception:
                pass
            continue
        if m.is_bot:
            continue
        if bonus_chat:
            await _deliver_join_bonus(ctx, chat, m, announce_message=update.message)
        else:
            ensure_user_from_member(m)
            try:
                await update.message.reply_text(
                    f"👋 {m.first_name or 'Игрок'}!",
                    parse_mode='HTML')
            except Exception:
                pass


def _member_just_joined(old_status, new_status):
    """True, если человек только что вошёл в чат."""
    left_like = {
        ChatMember.LEFT,
        ChatMember.BANNED,
        'left', 'kicked', 'banned',
    }
    member_like = {
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
        ChatMember.OWNER,
        ChatMember.RESTRICTED,
        'member', 'administrator', 'creator', 'restricted',
    }
    # Иногда old может быть None при первом апдейте
    old = old_status
    new = new_status
    if hasattr(old, 'status'):
        old = old.status
    if hasattr(new, 'status'):
        new = new.status
    if new is None:
        return False
    if old in left_like or old is None:
        return new in member_like
    # переход restricted без прав → member тоже вход
    return False


async def on_chat_member_update(update, ctx):
    """
    Надёжный мгновенный бонус при входе (группы и супергруппы).
    Бот должен быть админом с правом видеть участников.
    """
    result = update.chat_member or update.my_chat_member
    if not result:
        return
    chat = result.chat
    if not is_join_bonus_chat(chat):
        # Если добавили самого бота — подсказка
        if update.my_chat_member:
            new = result.new_chat_member
            if new and new.user and new.user.id == ctx.bot.id:
                try:
                    await ctx.bot.send_message(
                        chat.id,
                        f"🎰 Бот добавлен.\nID чата: <code>{chat.id}</code>\n"
                        f"Владелец: <code>чатбонус</code> — включить награду за вход.",
                        parse_mode='HTML')
                except Exception:
                    pass
        return

    old = result.old_chat_member
    new = result.new_chat_member
    if not new or not new.user:
        return
    if not _member_just_joined(old, new):
        return
    await _deliver_join_bonus(ctx, chat, new.user, announce_message=None)


async def cmd_start(update, ctx):
    ensure_user(update.effective_user)
    u = get_user(update.effective_user.id)
    if u[3] == 1:
        await update.message.reply_text('🚫')
        return
    restore_energy(u[0])
    name = update.effective_user.first_name or "Игрок"
    await update.message.reply_text(
        f"👋 Привет, <b>{name}</b>!\n\n" + main_menu_text(u[0]),
        reply_markup=MAIN_KB,
        parse_mode='HTML')
    await update.message.reply_text(
        main_menu_text(u[0]),
        reply_markup=main_menu_kb(),
        parse_mode='HTML')


async def cmd_menu(update, ctx):
    """Команда «меню» — чистое главное меню."""
    ensure_user(update.effective_user)
    u = get_user(update.effective_user.id)
    if not u or u[3] == 1:
        return
    restore_energy(u[0])
    await update.message.reply_text(
        main_menu_text(u[0]),
        reply_markup=main_menu_kb(),
        parse_mode='HTML')


async def cmd_help_slash(update, ctx):
    ensure_user(update.effective_user)
    await update.message.reply_text(HELP, reply_markup=MAIN_KB, parse_mode='HTML')


async def cmd_balance_slash(update, ctx):
    ensure_user(update.effective_user)
    await update.message.reply_text(bal_text(update.effective_user.id), parse_mode='HTML')


async def cmd_top_slash(update, ctx):
    await update.message.reply_text(top_text('balance'), reply_markup=top_menu_kb(), parse_mode='HTML')


async def qsopra_callback_error_handler(update, ctx):
    try:
        err = str(getattr(ctx, "error", "") or "")
        low = err.lower()
        # Тихие / ожидаемые ошибки — не засоряем лог
        if any(x in low for x in (
            'bad gateway', 'not modified', 'query is too old',
            'timed out', 'timeout', 'flood control', 'retry after',
            'disk i/o', 'database is locked', 'busy',
            'nonetype', "has no attribute 'text'",
            'message is not modified', 'too many requests',
        )):
            return
        print("HANDLER ERROR:", err)
    except Exception:
        pass


def main():
    if not TOKEN: raise RuntimeError('BOT_TOKEN не задан')
    db_init()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CallbackQueryHandler(clan_callback, pattern=r'^clan_'))
    app.add_handler(CallbackQueryHandler(qsopra_owner_wipe_callback, pattern=r'^owner_wipe$'))
    app.add_handler(CallbackQueryHandler(qsopra_owner_wipe_confirm, pattern=r'^owner_wipe_confirm$'))
    app.add_handler(CallbackQueryHandler(qsopra_owner_menu_callback, pattern=r'^owner_menu$'))
    app.add_handler(CallbackQueryHandler(menu_cb))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new))
    # Мгновенный бонус при смене статуса участника (вход в чат)
    app.add_handler(ChatMemberHandler(on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(on_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('help', cmd_help_slash))
    app.add_handler(CommandHandler('balance', cmd_balance_slash))
    app.add_handler(CommandHandler('top', cmd_top_slash))
    app.add_handler(CommandHandler('menu', cmd_menu))
    app.add_handler(CommandHandler('qsopra_restart', cmd_restart))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(qsopra_callback_error_handler)
    print('✅ QSOPRA CASINO 5.3 запущен! (умные триггеры · донат · арена)')
    # chat_member обязателен, иначе бонус «при входе» не сработает
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
