"""
BANDA — booking DB layer (SQLite)
Sodda qilib yozilgan, mavjud aiogram 3 backend'ingga shu faylni qo'shib,
main.py/bot.py ichida import qilib ishlatasan.

Jadval tuzilishi:
- barbers: barberlar ro'yxati (Ali, Vladimir, Ilya, Aleksey)
- services: xizmatlar (мужская стрижка narxsiz — narx barber orqali,
            qolganlari fixed narx bilan)
- barber_prices: faqat "мужская стрижка" uchun barber->narx bog'lanishi
- bookings: yozilgan mijozlar

Yordamchi funksiyalar quyida.
"""
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "banda.db"

WORK_START_HOUR = 10
WORK_END_HOUR = 22


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS barbers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        telegram_id INTEGER NOT NULL,
        channel_id INTEGER,           -- shu barberga tegishli alohida kanal ID (bildirishnomalar shu yerga boradi)
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS clients (
        telegram_id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        registered_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name_ru TEXT NOT NULL,
        duration_min INTEGER NOT NULL,
        base_price INTEGER,          -- NULL bo'lsa narx barberga qarab (мужская стрижка)
        price_depends_on_barber INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS barber_prices (
        barber_id INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        price INTEGER NOT NULL,
        PRIMARY KEY (barber_id, service_id),
        FOREIGN KEY (barber_id) REFERENCES barbers(id),
        FOREIGN KEY (service_id) REFERENCES services(id)
    );

    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_tg_id INTEGER NOT NULL,
        client_name TEXT,
        client_username TEXT,
        service_ids TEXT NOT NULL,    -- comma-separated, masalan "1,2" (soch+soqol combo)
        barber_id INTEGER NOT NULL,
        booking_date TEXT NOT NULL,   -- 'YYYY-MM-DD'
        booking_time TEXT NOT NULL,   -- 'HH:MM'
        duration_min INTEGER NOT NULL, -- combo qoidalari asosida hisoblangan umumiy vaqt
        price INTEGER NOT NULL,        -- tanlangan xizmatlar narxlarining yig'indisi
        status TEXT DEFAULT 'confirmed',  -- confirmed / cancelled
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (barber_id) REFERENCES barbers(id)
    );
    """)
    conn.commit()

    # --- seed data (faqat bo'sh bo'lsa) ---
    cur.execute("SELECT COUNT(*) FROM barbers")
    if cur.fetchone()[0] == 0:
        # TODO: telegram_id larni haqiqiy barber ID'lariga almashtir
        barbers = [
            ("Али", 1),       # TODO: haqiqiy Telegram ID bilan almashtir
            ("Владимир", 2),  # TODO
            ("Илья", 3),      # TODO
            ("Алексей", 4),   # TODO
        ]
        cur.executemany(
            "INSERT INTO barbers (name, telegram_id) VALUES (?, ?)", barbers
        )
        conn.commit()

        # Har bir barberga kanal ID: hozircha hammasiga jigarning o'z ID'si
        # qo'yilgan (test uchun) — keyinchalik har birining haqiqiy kanal
        # ID'siga almashtirasan (UPDATE barbers SET channel_id=... WHERE name=...)
        DEFAULT_TEST_CHANNEL_ID = 7434706702
        cur.execute("UPDATE barbers SET channel_id = ?", (DEFAULT_TEST_CHANNEL_ID,))
        conn.commit()

        services = [
            ("Мужская стрижка", 45, None, 1),          # narx barberga qarab
            ("Борода", 30, None, 1),                    # narx barberga qarab
            ("Детская стрижка (4-10 лет)", 45, 1250, 0),
            ("Стрижка машинкой (1-2 насадки)", 30, 850, 0),
            ("Бритьё головы (опасной бритвой)", 45, 1550, 0),
            ("Воск (2 зоны)", 15, 400, 0),
            ("Воск (комплекс)", 20, 600, 0),
            ("Патчи", 10, 300, 0),
        ]
        cur.executemany(
            "INSERT INTO services (name_ru, duration_min, base_price, price_depends_on_barber) VALUES (?,?,?,?)",
            services,
        )
        conn.commit()

        # мужская стрижка va борода narxlari barber bo'yicha
        cur.execute("SELECT id FROM services WHERE name_ru = 'Мужская стрижка'")
        haircut_service_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM services WHERE name_ru = 'Борода'")
        beard_service_id = cur.fetchone()["id"]

        cur.execute("SELECT id, name FROM barbers")
        barber_rows = {row["name"]: row["id"] for row in cur.fetchall()}

        haircut_prices = {
            "Али": 1500,
            "Владимир": 1500,
            "Илья": 1800,
            "Алексей": 2000,
        }
        beard_prices = {
            "Али": 1300,
            "Владимир": 1300,
            "Илья": 1700,
            "Алексей": 2000,
        }
        for name, price in haircut_prices.items():
            cur.execute(
                "INSERT INTO barber_prices (barber_id, service_id, price) VALUES (?,?,?)",
                (barber_rows[name], haircut_service_id, price),
            )
        for name, price in beard_prices.items():
            cur.execute(
                "INSERT INTO barber_prices (barber_id, service_id, price) VALUES (?,?,?)",
                (barber_rows[name], beard_service_id, price),
            )
        conn.commit()

    conn.close()


def get_client(telegram_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM clients WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return row


def create_or_update_client(telegram_id: int, full_name: str, phone: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO clients (telegram_id, full_name, phone) VALUES (?, ?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET full_name=excluded.full_name, phone=excluded.phone",
        (telegram_id, full_name, phone),
    )
    conn.commit()
    conn.close()


def get_services():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM services").fetchall()
    conn.close()
    return rows


def get_service(service_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    conn.close()
    return row


def get_barbers():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM barbers WHERE active=1").fetchall()
    conn.close()
    return rows


def get_barber(barber_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM barbers WHERE id=?", (barber_id,)).fetchone()
    conn.close()
    return row


def get_price(service_id: int, barber_id: int) -> int:
    """Xizmat narxini qaytaradi: agar barberga bog'liq bo'lsa barber_prices dan,
    aks holda services.base_price dan."""
    service = get_service(service_id)
    if service["price_depends_on_barber"]:
        conn = get_conn()
        row = conn.execute(
            "SELECT price FROM barber_prices WHERE service_id=? AND barber_id=?",
            (service_id, barber_id),
        ).fetchone()
        conn.close()
        return row["price"]
    return service["base_price"]


def get_booked_slots(barber_id: int, date_str: str):
    """Berilgan kunda shu barberning band vaqt oralig'lari (start time + duration)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT booking_time, duration_min FROM bookings "
        "WHERE barber_id=? AND booking_date=? AND status='confirmed'",
        (barber_id, date_str),
    ).fetchall()
    conn.close()
    return rows


def get_combo_duration_and_price(service_ids: list, barber_id: int):
    """
    Bir nechta xizmat birga tanlangan holat uchun umumiy vaqt va narxni hisoblaydi.

    Maxsus qoida (jigar so'rovi bo'yicha): agar tanlangan to'plamda
    "Мужская стрижка" VA "Борода" ikkalasi ham bo'lsa (ustiga yana
    "Воск (комплекс)" yoki boshqa vosk qo'shilgan bo'lsa ham farqi yo'q) —
    vaqt oddiy qo'shilmaydi, balki barberga qarab qat'iy belgilangan bo'ladi:
        - Алексей           -> 1 soat 45 min (105 min)
        - Али/Владимир/Илья -> 1 soat 30 min (90 min)

    Boshqa har qanday kombinatsiyada (soch+soqol juftligi bo'lmasa) —
    har bir xizmat davomiyligi shunchaki qo'shiladi.
    Narx har doim tanlangan xizmatlar narxlarining yig'indisi.
    """
    services = [get_service(sid) for sid in service_ids]
    names = {s["name_ru"] for s in services}
    barber = get_barber(barber_id)

    total_price = sum(get_price(s["id"], barber_id) for s in services)

    haircut_and_beard = {"Мужская стрижка", "Борода"}.issubset(names)

    if haircut_and_beard:
        total_duration = 105 if barber["name"] == "Алексей" else 90
    else:
        total_duration = sum(s["duration_min"] for s in services)

    return total_duration, total_price


def get_available_slots(barber_id: int, duration: int, date_str: str):
    """
    Ish vaqti 10:00-22:00 ichida, berilgan umumiy davomiylik (combo hisobga
    olingan holda) uchun band bo'lmagan slotlarni 15 daqiqalik qadam bilan
    qaytaradi. Overlap check bilan.
    """
    booked = get_booked_slots(barber_id, date_str)
    busy_intervals = []
    for b in booked:
        start = datetime.strptime(b["booking_time"], "%H:%M")
        end = start + timedelta(minutes=b["duration_min"])
        busy_intervals.append((start, end))

    slots = []
    cur_time = datetime.strptime(f"{WORK_START_HOUR}:00", "%H:%M")
    end_of_day = datetime.strptime(f"{WORK_END_HOUR}:00", "%H:%M")

    while cur_time + timedelta(minutes=duration) <= end_of_day:
        slot_end = cur_time + timedelta(minutes=duration)
        overlap = any(cur_time < b_end and slot_end > b_start for b_start, b_end in busy_intervals)
        if not overlap:
            slots.append(cur_time.strftime("%H:%M"))
        cur_time += timedelta(minutes=15)  # 15 daqiqalik qadam bilan slot taklif qilamiz

    return slots


def create_booking(client_tg_id, client_name, client_username, service_ids, barber_id,
                    date_str, time_str, duration_min, price):
    conn = get_conn()
    cur = conn.cursor()
    service_ids_str = ",".join(str(sid) for sid in service_ids)
    cur.execute(
        "INSERT INTO bookings (client_tg_id, client_name, client_username, service_ids, "
        "barber_id, booking_date, booking_time, duration_min, price) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (client_tg_id, client_name, client_username, service_ids_str, barber_id,
         date_str, time_str, duration_min, price),
    )
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id
