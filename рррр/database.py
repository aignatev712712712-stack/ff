from pathlib import Path
import sqlite3
from datetime import datetime
from decimal import Decimal

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "telegram_stars.db"

print(f"[DB] Using database file: {DB_PATH}")

def init_database():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance INTEGER DEFAULT 0,
        reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        referrer_id INTEGER DEFAULT NULL,
        invited_count INTEGER DEFAULT 0,
        invited_paid_count INTEGER DEFAULT 0,
        bonus_stars_earned INTEGER DEFAULT 0
    )
    ''')

    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'referrer_id' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
    if 'invited_count' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN invited_count INTEGER DEFAULT 0")
    if 'invited_paid_count' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN invited_paid_count INTEGER DEFAULT 0")
    if 'bonus_stars_earned' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN bonus_stars_earned INTEGER DEFAULT 0")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        order_id TEXT UNIQUE,
        stars_count INTEGER,
        amount_rub INTEGER,
        payment_id TEXT,
        payment_method TEXT DEFAULT 'yookassa',
        status TEXT DEFAULT 'waiting_payment',
        admin_notified INTEGER DEFAULT 0,
        admin_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS delivery_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER UNIQUE,
        status TEXT DEFAULT 'queued',
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (purchase_id) REFERENCES purchases (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promocodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        discount_type TEXT,
        discount_value INTEGER,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promo_activations (
        user_id INTEGER,
        promo_id INTEGER,
        activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, promo_id)
    )
    ''')

    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('price_per_star', '1.15')")
    conn.commit()
    return conn

conn = init_database()
cursor = conn.cursor()

def format_price(price_kopecks: int) -> str:
    rub = price_kopecks / 100
    return f"{rub:,.2f}".replace(',', ' ').replace('.', ',')

def get_price_per_star() -> Decimal:
    cursor.execute("SELECT value FROM config WHERE key = 'price_per_star'")
    row = cursor.fetchone()
    return Decimal(row[0]) if row else Decimal('1.15')

def set_price_per_star(price: Decimal):
    cursor.execute("UPDATE config SET value = ? WHERE key = 'price_per_star'", (str(price),))
    conn.commit()

def calc_stars_cost(stars: int) -> int:
    price = get_price_per_star()
    total = price * stars
    return int(total * 100)

def get_user_balance(user_id: int) -> int:
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row['balance'] if row else 0

def update_user_balance(user_id: int, delta_kopecks: int):
    cursor.execute('''
        INSERT INTO users (user_id, balance)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
    ''', (user_id, delta_kopecks))
    conn.commit()

def add_purchase(user_id: int, stars: int, amount_kopecks: int, payment_method: str, status: str = 'creating_payment', payment_id: str = None):
    order_id = f"{payment_method.upper()}_{user_id}_{int(datetime.now().timestamp())}"
    cursor.execute(
        '''INSERT INTO purchases (user_id, order_id, stars_count, amount_rub, payment_method, status, payment_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (user_id, order_id, stars, amount_kopecks, payment_method, status, payment_id)
    )
    conn.commit()
    return cursor.lastrowid

def get_purchase(purchase_id: int):
    cursor.execute('SELECT user_id, stars_count, amount_rub, status, payment_id, payment_method FROM purchases WHERE id = ?', (purchase_id,))
    return cursor.fetchone()

def update_purchase_status(purchase_id: int, status: str, completed_at: datetime = None):
    if completed_at:
        cursor.execute('UPDATE purchases SET status = ?, completed_at = ? WHERE id = ?', (status, completed_at.isoformat(), purchase_id))
    else:
        cursor.execute('UPDATE purchases SET status = ? WHERE id = ?', (status, purchase_id))
    conn.commit()

def try_lock_purchase(purchase_id: int, expected_status: str, new_status: str, completed_at: datetime = None) -> bool:
    if completed_at:
        cursor.execute(
            'UPDATE purchases SET status = ?, completed_at = ? WHERE id = ? AND status = ?',
            (new_status, completed_at.isoformat(), purchase_id, expected_status)
        )
    else:
        cursor.execute(
            'UPDATE purchases SET status = ? WHERE id = ? AND status = ?',
            (new_status, purchase_id, expected_status)
        )
    conn.commit()
    return cursor.rowcount > 0

def add_delivery_to_queue(purchase_id: int):
    cursor.execute(
        '''INSERT OR IGNORE INTO delivery_queue (purchase_id, status, created_at, updated_at)
           VALUES (?, 'queued', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
        (purchase_id,)
    )
    conn.commit()
    if cursor.lastrowid:
        return cursor.lastrowid
    cursor.execute('SELECT id FROM delivery_queue WHERE purchase_id = ?', (purchase_id,))
    row = cursor.fetchone()
    return row['id'] if row else None

def try_lock_delivery(queue_id: int, expected_status: str, new_status: str, last_error: str = None) -> bool:
    cursor.execute(
        'UPDATE delivery_queue SET status = ?, last_error = ?, updated_at = ? WHERE id = ? AND status = ?',
        (new_status, last_error, datetime.now().isoformat(), queue_id, expected_status)
    )
    conn.commit()
    return cursor.rowcount > 0

def get_next_queued_delivery():
    cursor.execute(
        '''SELECT id, purchase_id, attempts
           FROM delivery_queue
           WHERE status = 'queued'
           ORDER BY created_at ASC
           LIMIT 1'''
    )
    row = cursor.fetchone()
    if not row:
        return None
    if not try_lock_delivery(row['id'], 'queued', 'processing'):
        return None
    return row

def increment_delivery_attempt(queue_id: int, note: str = None):
    cursor.execute(
        'UPDATE delivery_queue SET attempts = attempts + 1, last_error = ?, updated_at = ? WHERE id = ?',
        (note, datetime.now().isoformat(), queue_id)
    )
    conn.commit()

def set_delivery_status(queue_id: int, status: str, error: str = None):
    cursor.execute(
        'UPDATE delivery_queue SET status = ?, last_error = ?, updated_at = ? WHERE id = ?',
        (status, error, datetime.now().isoformat(), queue_id)
    )
    conn.commit()
