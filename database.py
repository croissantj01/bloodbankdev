import os
import sqlite3
from datetime import datetime, date, timedelta

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bloodbank.db"
)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def add_image_column():
    conn = get_db_connection()
    try:
        columns = conn.execute(
            "PRAGMA table_info(events)"
        ).fetchall()

        if not any(column["name"] == "image" for column in columns):
            conn.execute("ALTER TABLE events ADD COLUMN image TEXT")
            conn.commit()
            print("Added image column to events table.")
        else:
            print("The image column already exists.")
    finally:
        conn.close()

def _fix_old_users_table():

    conn = sqlite3.connect(DB_PATH)
    try:
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        phone_col = next((c for c in columns if c[1] == "phone_number"), None)

        if phone_col is not None and phone_col[3] == 1:
            print("Fixing old users table (phone_number was NOT NULL)...")
            conn.executescript("""
                BEGIN;
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT,
                    email TEXT UNIQUE NOT NULL,
                    phone_number TEXT UNIQUE,
                    hashed_password TEXT NOT NULL,
                    role TEXT NOT NULL
                );
                INSERT INTO users_new (id, full_name, email, phone_number, hashed_password, role)
                    SELECT id, full_name, email, phone_number, hashed_password, role FROM users;
                DROP TABLE users;
                ALTER TABLE users_new RENAME TO users;
                COMMIT;
            """)
    finally:
        conn.close()


def _upgrade_appointments_table():

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(appointments)").fetchall()}

        if "event_id" not in cols:
            conn.execute("""ALTER TABLE appointments
                            ADD COLUMN event_id INTEGER
                            REFERENCES events(event_id) ON DELETE SET NULL""")
        if "appointment_time" not in cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN appointment_time TEXT")
        if "notes" not in cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN notes TEXT")

        # A donor can only hold one active booking per event
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_appt_donor_event
                        ON appointments(donor_id, event_id)
                        WHERE status != 'Cancelled' AND event_id IS NOT NULL""")
        conn.commit()
    finally:
        conn.close()


def _migrate_announcements(conn):
    """
    SQLite table names are case-insensitive, so an old 'Announcements' table
    (details / date / user_id) silently blocked the real 'announcements' table
    (category / message / image_filename / status) from ever being created.
    An empty old table is dropped; one holding rows is renamed, not lost.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(announcements)").fetchall()}
    if cols and "category" not in cols:
        rows = conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
        if rows == 0:
            conn.execute("DROP TABLE announcements")
        else:
            conn.execute("ALTER TABLE announcements RENAME TO announcements_old")
            print("Old announcements table kept as announcements_old")


def _add_missing_columns():
    """CREATE TABLE IF NOT EXISTS never adds columns to an existing table."""
    wanted = {
        "users": {
            "status": "TEXT NOT NULL DEFAULT 'Active'",
            "organisation": "TEXT",
            "created_at": "TEXT",
            "must_change_password": "INTEGER NOT NULL DEFAULT 0",
        },
        "blood_requests": {"reason": "TEXT"},
    }
    conn = sqlite3.connect(DB_PATH)
    try:
        for table, columns in wanted.items():
            have = {c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, definition in columns.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    print(f"Added missing column: {table}.{name}")
        conn.commit()
    finally:
        conn.close()


def init_db():
    conn = get_db_connection()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            email TEXT UNIQUE NOT NULL,
            phone_number TEXT UNIQUE,
            hashed_password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')

    conn.execute("""
                CREATE TABLE IF NOT EXISTS Admin (
                    admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

    conn.execute('''
        CREATE TABLE IF NOT EXISTS donors (
            donor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            donor_name TEXT,
            ic TEXT NOT NULL UNIQUE,
            blood_type TEXT NOT NULL,
            dob TEXT NOT NULL,
            address TEXT NOT NULL,
            gender TEXT NOT NULL,
            emergency_contact TEXT NOT NULL,
            weight FLOAT NOT NULL,
            height FLOAT NOT NULL,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    ''')
    # Add missing columns to an existing donors table
    # Add missing columns to an existing donors table
    donor_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(donors)").fetchall()
    }

    missing_donor_columns = {
        "donor_name": "TEXT",
        "weight": "FLOAT",
        "height": "FLOAT",
    }

    for column_name, column_type in missing_donor_columns.items():
        if column_name not in donor_columns:
            conn.execute(
                f"ALTER TABLE donors ADD COLUMN {column_name} {column_type}"
            )
            print(f"Added missing column: {column_name}")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            event_id INTEGER,
            appointment_date DATE NOT NULL,
            appointment_time TEXT,
            status TEXT NOT NULL,
            notes TEXT,

            FOREIGN KEY (donor_id)
                REFERENCES donors(donor_id)
                ON DELETE CASCADE,
            FOREIGN KEY (event_id)
                REFERENCES events(event_id)
                ON DELETE SET NULL
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS donations (
            donation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            collection_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expiry_date DATE NOT NULL,
            blood_group TEXT NOT NULL,
            volume_blood FLOAT NOT NULL,
            status TEXT NOT NULL,

            FOREIGN KEY (donor_id)
                REFERENCES donors(donor_id)
                ON DELETE CASCADE
        )
    ''')


    conn.execute('''
        CREATE TABLE IF NOT EXISTS blood_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_name TEXT NOT NULL,
            staff_id INTEGER NOT NULL,
            blood_group TEXT NOT NULL,
            units_requested INTEGER NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'Pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (staff_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_date DATE NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            place TEXT NOT NULL,
            address TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    _migrate_announcements(conn)

    conn.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            image_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'Published'
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            desc TEXT,
            points INTEGER NOT NULL,
            stock INTEGER NOT NULL,
            status TEXT DEFAULT 'Active',
            needs_phone INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')

    conn.execute('''
            CREATE TABLE IF NOT EXISTS reward_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reward_id INTEGER,
                reward TEXT,
                phone TEXT,
                points INTEGER,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (reward_id) REFERENCES rewards(id)
            )
        ''')

    conn.commit()
    conn.close()
    add_image_column()


    # Repair a leftover old users table, if there is one
    _fix_old_users_table()
    _upgrade_appointments_table()
    _add_missing_columns()

    print("Database ready:", DB_PATH)


def get_user_by_email(email):
    email = (email or "").strip().lower()
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------
# Events (blood donation events managed by the admin)
# ---------------------------------------------------------------
def get_all_events():
    """Every event as a dict shaped for the Manage Events page."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                event_id AS id,
                title,
                event_date AS "date",
                start_time AS "start",
                end_time AS "end",
                place,
                address,
                COALESCE(notes, '') AS notes,
                image,
                (SELECT COUNT(*) FROM appointments a
                  WHERE a.event_id = events.event_id
                    AND a.status = 'Booked') AS booked_count
            FROM events
            ORDER BY event_date, start_time
            """
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_event(title, event_date, start_time, end_time,
              place, address, notes, image=None):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO events
                   (title, event_date, start_time, end_time,
                    place, address, notes, image)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, event_date, start_time, end_time,
             place, address, notes or None, image),
        )
        conn.commit()
    finally:
        conn.close()

def update_event(
    event_id, title, event_date, start_time, end_time,
    place, address, notes, image=None
):
    """
    Returns True if updated, False if the event doesn't exist.
    Raises ValueError if donors have booked and the date, time or
    location would change.
    """
    conn = get_db_connection()
    try:
        old = conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if old is None:
            return False

        booked = conn.execute(
            """SELECT COUNT(*) FROM appointments
                WHERE event_id = ? AND status = 'Booked'""",
            (event_id,),
        ).fetchone()[0]

        if booked:
            before = (old["event_date"], old["start_time"], old["end_time"],
                      old["place"], old["address"])
            after = (event_date, start_time, end_time, place, address)
            if before != after:
                raise ValueError(
                    f"{booked} donor(s) have booked this event, so the date, "
                    "time and location can't be changed. You can still edit "
                    "the name, notes and image."
                )

        if image:
            conn.execute(
                """UPDATE events
                      SET title = ?, event_date = ?, start_time = ?,
                          end_time = ?, place = ?, address = ?, notes = ?,
                          image = ?
                    WHERE event_id = ?""",
                (title, event_date, start_time, end_time,
                 place, address, notes or None, image, event_id),
            )
        else:
            conn.execute(
                """UPDATE events
                      SET title = ?, event_date = ?, start_time = ?,
                          end_time = ?, place = ?, address = ?, notes = ?
                    WHERE event_id = ?""",
                (title, event_date, start_time, end_time,
                 place, address, notes or None, event_id),
            )

        conn.commit()
        return True
    finally:
        conn.close()


def delete_event(event_id):
    """Returns True if an event was deleted, False if the id does not exist."""
    conn = get_db_connection()
    try:
        # Donors who booked this event keep a record, marked as cancelled
        conn.execute("UPDATE appointments SET status = 'Cancelled' "
                     "WHERE event_id = ? AND status = 'Booked'", (event_id,))
        cur = conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------
# Donor appointments (donors book a time at an admin-created event)
# ---------------------------------------------------------------
SLOT_MINUTES  = 30   # length of one appointment time
SLOT_CAPACITY = 5    # donors allowed per time slot


def _time_label(hhmm):
    """'14:30' -> '2:30 PM'"""
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def _make_slots(start, end):
    cur  = datetime.strptime(start, "%H:%M")
    last = datetime.strptime(end, "%H:%M")
    step = timedelta(minutes=SLOT_MINUTES)
    slots = []
    while cur + step <= last:
        slots.append(cur.strftime("%H:%M"))
        cur += step
    return slots


def get_donor_by_email(email):
    """The donors row for this login email, or None if not registered as a donor."""
    email = (email or "").strip().lower()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT d.donor_id
                 FROM donors d JOIN users u ON d.user_id = u.id
                WHERE u.email = ?""", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_bookable_events(donor_id=None):
    """
    Upcoming events shaped for donor/make_appointment.html, each with its
    appointment times and how many places are left. Events this donor has
    already booked are left out.
    """
    now   = datetime.now()
    today = now.date().isoformat()
    conn  = get_db_connection()
    try:
        events = conn.execute(
            "SELECT * FROM events WHERE event_date >= ? ORDER BY event_date, start_time",
            (today,)).fetchall()

        taken = {}
        for r in conn.execute(
                """SELECT event_id, appointment_time, COUNT(*) AS n
                     FROM appointments
                    WHERE event_id IS NOT NULL AND status != 'Cancelled'
                    GROUP BY event_id, appointment_time"""):
            taken[(r["event_id"], r["appointment_time"])] = r["n"]

        mine = set()
        if donor_id:
            mine = {r["event_id"] for r in conn.execute(
                """SELECT event_id FROM appointments
                    WHERE donor_id = ? AND status != 'Cancelled'
                      AND event_id IS NOT NULL""", (donor_id,))}

        result = []
        for e in events:
            if e["event_id"] in mine:
                continue

            ev_date = datetime.strptime(e["event_date"], "%Y-%m-%d").date()
            slots = []
            for s in _make_slots(e["start_time"], e["end_time"]):
                if ev_date == now.date() and s <= now.strftime("%H:%M"):
                    continue                      # this time has already started
                left = SLOT_CAPACITY - taken.get((e["event_id"], s), 0)
                slots.append({"time": s, "label": _time_label(s), "available": max(left, 0)})

            if not slots:
                continue                          # nothing left to book

            result.append({
                "id": e["event_id"],
                "name": e["title"],
                "location": e["place"],
                "address": e["address"],
                "event_date": ev_date,
                "start_time": _time_label(e["start_time"]),
                "end_time": _time_label(e["end_time"]),
                "description": e["notes"] or "",
                "image": e["image"],
                "available_times": slots,
            })
        return result
    finally:
        conn.close()

def _parse_dt(value):
    """'2026-10-24 09:30:00' or '2026-10-24' -> (datetime or None, has_time)"""
    if not value:
        return None, False
    text = str(value).strip()
    for fmt, has_time in (("%Y-%m-%d %H:%M:%S", True),
                          ("%Y-%m-%d %H:%M", True),
                          ("%Y-%m-%d", False)):
        try:
            return datetime.strptime(text, fmt), has_time
        except ValueError:
            continue
    return None, False


def get_donation_history(donor_id):
    """Everything the donation_history.html page needs for one donor."""
    conn = get_db_connection()
    try:
        donor = conn.execute(
            "SELECT blood_type FROM donors WHERE donor_id = ?", (donor_id,)
        ).fetchone()
        donor_group = donor["blood_type"] if donor else "—"

        donation_rows = conn.execute(
            """SELECT donation_id, collection_date, blood_group, volume_blood
                 FROM donations
                WHERE donor_id = ?""",
            (donor_id,),
        ).fetchall()

        cancelled_rows = conn.execute(
            """SELECT a.appointment_id, a.appointment_date,
                      a.appointment_time, a.notes, e.title
                 FROM appointments a
                 LEFT JOIN events e ON a.event_id = e.event_id
                WHERE a.donor_id = ? AND a.status = 'Cancelled'""",
            (donor_id,),
        ).fetchall()
    finally:
        conn.close()

    entries = []          # (sort_key, record)
    donation_dates = []

    # ---- completed donations ----
    for r in donation_rows:
        dt, has_time = _parse_dt(r["collection_date"])
        if dt is None:
            continue
        donation_dates.append(dt)

        volume = r["volume_blood"]
        volume_text = f"{volume:g} ml" if volume is not None else "—"

        entries.append((dt, {
            "status": "completed",
            "date": dt.strftime("%d %b %Y"),
            "date_iso": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%I:%M %p").lstrip("0") if has_time else "",
            "title": "Blood Donation",
            "blood_group": r["blood_group"],
            "volume": volume_text,
            "notes": "",
        }))

    # ---- cancelled appointments ----
    for r in cancelled_rows:
        dt, _ = _parse_dt(r["appointment_date"])
        if dt is None:
            continue

        time_label = ""
        if r["appointment_time"]:
            try:
                time_label = _time_label(r["appointment_time"])
                dt = datetime.strptime(
                    f'{r["appointment_date"]} {r["appointment_time"]}',
                    "%Y-%m-%d %H:%M",
                )
            except ValueError:
                pass

        entries.append((dt, {
            "status": "cancelled",
            "date": dt.strftime("%d %b %Y"),
            "date_iso": dt.strftime("%Y-%m-%d"),
            "time": time_label,
            "title": r["title"] or "Blood donation event",
            "blood_group": donor_group,
            "volume": "—",
            "notes": r["notes"] or "",
        }))

    entries.sort(key=lambda item: item[0], reverse=True)   # newest first
    records = [rec for _, rec in entries]

    donation_dates.sort(reverse=True)
    this_year = date.today().year
    last = donation_dates[0] if donation_dates else None

    return {
        "records": records,
        "total_donations": len(donation_dates),
        "year_donations": sum(1 for d in donation_dates if d.year == this_year),
        "current_year": this_year,
        "last_donation_day": last.strftime("%d %b") if last else "—",
        "last_donation_year": str(last.year) if last else "No donations yet",
    }

def get_user_details(user_id):
    """Full profile for the Manage Users 'View' popup (donor or staff)."""
    conn = get_db_connection()
    try:
        u = conn.execute(
            """SELECT u.id, u.full_name, u.email, u.phone_number, u.role,
                      u.status, u.organisation, u.created_at,
                      d.donor_id, d.donor_name, d.ic, d.blood_type, d.dob,
                      d.address, d.gender, d.emergency_contact,
                      d.weight, d.height
                 FROM users u
                 LEFT JOIN donors d ON d.user_id = u.id
                WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
        if u is None:
            return None

        donation_count, last_donation, upcoming = 0, None, 0
        if u["donor_id"]:
            donation_count = conn.execute(
                "SELECT COUNT(*) FROM donations WHERE donor_id = ?",
                (u["donor_id"],),
            ).fetchone()[0]
            last_donation = conn.execute(
                "SELECT MAX(collection_date) FROM donations WHERE donor_id = ?",
                (u["donor_id"],),
            ).fetchone()[0]
            upcoming = conn.execute(
                """SELECT COUNT(*) FROM appointments
                    WHERE donor_id = ? AND status = 'Booked'
                      AND appointment_date >= ?""",
                (u["donor_id"], date.today().isoformat()),
            ).fetchone()[0]
    finally:
        conn.close()

    def fmt(value):
        if not value:
            return ""
        text = str(value)[:10]
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return str(value)

    age = ""
    if u["dob"]:
        try:
            born = datetime.strptime(u["dob"], "%Y-%m-%d").date()
            today = date.today()
            age = today.year - born.year - (
                (today.month, today.day) < (born.month, born.day))
        except ValueError:
            pass

    is_donor = (u["role"] or "").strip().lower() == "donor"
    weight = u["weight"] if u["weight"] else None
    height = u["height"] if u["height"] else None

    return {
        "id": u["id"],
        "is_donor": is_donor,
        "registered": bool(u["donor_id"]),
        "name": u["donor_name"] or u["full_name"] or "",
        "email": u["email"] or "",
        "phone": u["phone_number"] or "",
                "role": (u["role"] or "").title(),
        "status": u["status"],
        "organisation": u["organisation"] or "",
        "created": fmt(u["created_at"]),
        "ic": u["ic"] or "",
        "dob": fmt(u["dob"]),
        "age": age,
        "gender": u["gender"] or "",
        "blood_type": u["blood_type"] or "",
        "address": u["address"] or "",
        "emergency_contact": u["emergency_contact"] or "",
        "weight": f"{weight:g} kg" if weight else "",
        "height": f"{height:g} cm" if height else "",
        "donation_count": donation_count,
        "last_donation": fmt(last_donation),
        "upcoming": upcoming,
    }

def create_appointment(donor_id, event_id, appt_time, notes=""):
    """
    Book a time slot. Returns (True, message) or (False, reason).
    Everything is re-checked here, so a tampered form cannot book a
    full slot, a past event or a time that does not exist.
    """
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")   # lock so two donors cannot take the last place

        ev = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not ev:
            return False, "That event no longer exists."

        now = datetime.now()
        ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        if ev_date < now.date():
            return False, "That event has already taken place."

        if appt_time not in _make_slots(ev["start_time"], ev["end_time"]):
            return False, "Please choose one of the available times."
        if ev_date == now.date() and appt_time <= now.strftime("%H:%M"):
            return False, "That time has already passed."

        already = conn.execute(
            """SELECT 1 FROM appointments
                WHERE donor_id = ? AND event_id = ? AND status != 'Cancelled'""",
            (donor_id, event_id)).fetchone()
        if already:
            return False, "You have already booked this event."

        used = conn.execute(
            """SELECT COUNT(*) FROM appointments
                WHERE event_id = ? AND appointment_time = ? AND status != 'Cancelled'""",
            (event_id, appt_time)).fetchone()[0]
        if used >= SLOT_CAPACITY:
            return False, "Sorry, that time is now full. Please choose another time."

        conn.execute(
            """INSERT INTO appointments
                   (donor_id, event_id, appointment_date, appointment_time, status, notes)
               VALUES (?, ?, ?, ?, 'Booked', ?)""",
            (donor_id, event_id, ev["event_date"], appt_time, notes or None))
        conn.commit()

        return True, "Appointment confirmed: %s on %s at %s." % (
            ev["title"], ev_date.strftime("%d %b %Y"), _time_label(appt_time))

    except sqlite3.IntegrityError:
        return False, "You have already booked this event."
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def get_donor_upcoming_appointments(donor_id):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT a.appointment_id, a.appointment_date, a.appointment_time,
                      e.title, e.place
                 FROM appointments a
                 LEFT JOIN events e ON a.event_id = e.event_id
                WHERE a.donor_id = ? AND a.status = 'Booked'
                  AND a.appointment_date >= ?
                ORDER BY a.appointment_date, a.appointment_time""",
            (donor_id, date.today().isoformat())).fetchall()

        return [{
            "appointment_id": r["appointment_id"],
            "appointment_date": datetime.strptime(r["appointment_date"], "%Y-%m-%d").date(),
            "time_label": _time_label(r["appointment_time"]) if r["appointment_time"] else "",
            "title": r["title"],
            "place": r["place"],
        } for r in rows]
    finally:
        conn.close()


def cancel_donor_appointment(appointment_id, donor_id):
    """A donor can only cancel their own upcoming booked appointment."""
    conn = get_db_connection()
    try:
        cur = conn.execute(
            """UPDATE appointments SET status = 'Cancelled'
                WHERE appointment_id = ? AND donor_id = ?
                  AND status = 'Booked' AND appointment_date >= ?""",
            (appointment_id, donor_id, date.today().isoformat()))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()