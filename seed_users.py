#!/usr/bin/env python3
"""
Sample data

    python seed_data.py            # add sample data
    python seed_data.py --reset    # remove the old sample data, then add it again
    python seed_data.py --no-bulk  # only the ~12 featured donors (no background pool)

Everything it creates is easy to recognise and remove:
  * every sample account uses an @example.com email
  * --reset deletes only those accounts and the sample events, rewards and
    announcements listed below. Your own accounts and data are never touched.

All sample accounts share one password:  Password123!
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import bcrypt

from database import DB_PATH, _make_slots, get_db_connection, init_db

SAMPLE_DOMAIN = "@gmail.com"
SAMPLE_PASSWORD = "123"
TODAY = date.today()
FMT = "%Y-%m-%d %H:%M:%S"


# ------------------------------------------------------------------
# small helpers
# ------------------------------------------------------------------
def day(days_ago):
    """A date `days_ago` days before today (negative = in the future)."""
    return TODAY - timedelta(days=days_ago)


def stamp(d, hour=9, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute).strftime(FMT)


def slug(text):
    return "".join(c for c in text.lower() if c.isalpha() or c == " ").replace(" ", ".")


# ------------------------------------------------------------------
# fixed sample content
# ------------------------------------------------------------------
# name, email-prefix, blood, gender, dob, IC, phone, emergency, kg, cm, address, donation days-ago
FEATURED_DONORS = [
    ("Ahmad Faiz Rahman", "ahmad.faiz", "A+", "Male", "1995-03-14", "950314-07-5231",
     "012-3456781", "013-4455667", 72.5, 172, "12 Jalan Burma, George Town, Penang", [12, 140, 260]),
    ("Nurul Aisyah", "nurul.aisyah", "O+", "Female", "1998-07-22", "980722-07-6024",
     "012-3456782", "011-22334455", 54.0, 160, "45 Lebuh Chulia, George Town, Penang", [5, 100, 200, 310]),
    ("Tan Wei Ming", "tan.weiming", "B+", "Male", "1990-11-05", "901105-07-5117",
     "012-3456783", "016-7788990", 78.0, 175, "8 Lorong Kikik, Jelutong, Penang", [20, 180]),
    ("Lim Mei Ling", "lim.meiling", "A-", "Female", "1993-02-28", "930228-07-5342",
     "012-3456784", "012-9988776", 58.5, 163, "27 Jalan Macalister, George Town, Penang", [9, 150]),
    ("Raj Kumar", "raj.kumar", "O-", "Male", "1988-09-17", "880917-07-5559",
     "012-3456785", "017-3344556", 81.0, 178, "3 Jalan Perak, Air Itam, Penang", [3, 95, 190, 290, 400]),
    ("Priya Devi", "priya.devi", "B-", "Female", "2000-01-30", "000130-07-5668",
     "012-3456786", "014-5566778", 52.0, 158, "19 Lorong Delima, Gelugor, Penang", [30]),
    ("Muhammad Hafiz", "muhammad.hafiz", "AB+", "Male", "1997-06-09", "970609-07-5013",
     "012-3456787", "019-1122334", 69.0, 170, "61 Jalan Bayan Lepas, Bayan Lepas, Penang", [130, 230]),
    ("Chong Jia Hao", "chong.jiahao", "O+", "Male", "1992-12-25", "921225-07-5275",
     "012-3456788", "012-6677889", 74.0, 173, "88 Jalan Gurney, George Town, Penang", [120, 220, 330]),
    ("Farah Amira", "farah.amira", "A+", "Female", "1999-04-11", "990411-07-5486",
     "012-3456789", "018-4455667", 56.0, 161, "5 Persiaran Bukit Jambul, Bayan Lepas, Penang", [45, 160]),
    ("Daniel Lee", "daniel.lee", "B+", "Male", "1985-08-03", "850803-07-5191",
     "012-3456790", "012-7788991", 85.0, 180, "22 Jalan Sultan Azlan Shah, Gelugor, Penang", [90, 200]),
    ("Siti Zulaikha", "siti.zulaikha", "Unknown", "Female", "2001-10-19", "011019-07-5802",
     "012-3456791", "013-9900112", 50.5, 157, "14 Jalan Tun Dr Awang, Bayan Lepas, Penang", []),
    ("Kumar Selvam", "kumar.selvam", "A+", "Male", "1994-05-21", "940521-07-5337",
     "012-3456792", "016-2233440", 77.0, 176, "9 Jalan Burma, George Town, Penang", [100, 190]),
]

# name, email-prefix, role, organisation, phone, status
STAFF = [
    ("Aisha Karim", "hospital.pgh", "hospital_staff", "Penang General Hospital", "012-9000001", "Active"),
    ("Jason Teoh", "hospital.gleneagles", "hospital_staff", "Gleneagles Hospital Penang", "012-9000002", "Active"),
    ("Farid Zainal", "hospital.island", "hospital_staff", "Island Hospital", "012-9000003", "Active"),
    ("Zainab Hassan", "bloodbank.zainab", "blood_bank_staff", "Penang Blood Bank", "012-9000004", "Active"),
    ("Kevin Ooi", "bloodbank.kevin", "blood_bank_staff", "Penang Blood Bank", "012-9000005", "Inactive"),
    ("Jayden Tan", "bloodbank.jayden", "blood_bank_staff", "Penang Blood Bank", "012-9087005", "Active")
]

NEW_DONOR_EMAIL = "newdonor" + SAMPLE_DOMAIN       # logged in but NOT registered as a donor

# Stock the dashboard should show (app threshold: <=10 Critical, 11-19 Low, 20+ Sufficient)
STOCK_TARGET = {"O+": 22, "A+": 20, "B+": 14, "A-": 11, "O-": 7, "B-": 4, "AB+": 3, "AB-": 1}
LAPSED_DONORS = 14                                  # eligible again, with upcoming bookings

# title, days from today (negative = past), start, end, place, address, notes
EVENTS = [
    ("Penang Hospital Staff Blood Drive", -45, "09:00", "15:00", "Penang General Hospital",
     "Jalan Residensi, 10990 George Town, Penang", "Past event - thank you to everyone who donated."),
    ("USM Campus Blood Drive", -20, "10:00", "16:00", "Universiti Sains Malaysia, Dewan Utama",
     "11800 Minden, Penang", "Past event organised with the student council."),
    ("Komtar Community Blood Drive", 6, "10:00", "16:00", "Komtar Atrium",
     "Jalan Penang, 10000 George Town, Penang", "Walk-ins welcome. Please eat before you donate and bring your IC."),
    ("Gurney Plaza Donation Day", 13, "11:00", "19:00", "Gurney Plaza, Concourse Level",
     "170 Persiaran Gurney, 10250 George Town, Penang", "Free parking voucher for every donor."),
    ("Bayan Lepas Industrial Park Drive", 24, "09:00", "15:00", "FIZ Community Hall",
     "Jalan Hamilton, Bayan Lepas Free Industrial Zone, Penang", "Open to all employees and the public."),
    ("Year-End Blood Drive", 40, "10:00", "17:00", "Straits Quay Convention Centre",
     "Seri Tanjung Pinang, 10470 Tanjung Tokong, Penang", "Help us keep shelves full over the holiday season."),
]

# name, description, points, stock, status, needs_phone
REWARDS = [
    ("Blood Donor T-Shirt", "Soft cotton tee with the official blood donor logo.", 300, 25, "Active", 0),
    ("Reusable Water Bottle", "750 ml stainless steel bottle. Stay hydrated after every donation.", 200, 40, "Active", 0),
    ("Donor Tote Bag", "Eco-friendly canvas tote bag.", 150, 50, "Active", 0),
    ("RM5 Mobile Top-up", "RM5 prepaid reload sent to your phone number.", 250, 30, "Active", 1),
    ("RM10 Touch 'n Go eWallet Credit", "RM10 credit sent to your eWallet phone number.", 500, 20, "Active", 1),
    ("Cinema Ticket Voucher", "One standard cinema ticket voucher.", 400, 12, "Active", 0),
    ("Basic Health Screening Voucher", "Complimentary health check-up at a partner clinic.", 800, 6, "Active", 0),
    ("Limited Edition Donor Pin", "Collectible enamel pin. Currently out of stock.", 100, 0, "Active", 0),
    ("Vintage Donor Cap", "Retired reward, no longer offered.", 350, 10, "Inactive", 0),
]

# donor email-prefix, reward name, phone, days ago
CLAIMS = [
    ("raj.kumar", "Reusable Water Bottle", None, 60),
    ("raj.kumar", "Donor Tote Bag", None, 20),
    ("nurul.aisyah", "Blood Donor T-Shirt", None, 35),
    ("chong.jiahao", "Donor Tote Bag", None, 90),
    ("ahmad.faiz", "RM5 Mobile Top-up", "012-3456781", 4),
]

# title, category, message, days ago
ANNOUNCEMENTS = [
    ("Critical Shortage: Blood Types AB+ and AB-", "Emergency",
     "Stock of AB+ and AB- is critically low. If you are one of these types, please visit the "
     "Main Donation Centre or book an appointment as soon as you can.", 1),
    ("Komtar Community Blood Drive This Week", "Event",
     "Join us at the Komtar Atrium from 10:00 AM to 4:00 PM. Book a time slot from your dashboard "
     "to skip the queue.", 3),
    ("Gurney Plaza Donation Day", "Event",
     "Donate at Gurney Plaza and receive a free parking voucher. Open 11:00 AM to 7:00 PM.", 6),
    ("Before You Donate: A Quick Checklist", "Health Tips",
     "Eat a healthy meal, drink plenty of water and bring your IC. Avoid fatty food and get a "
     "good night's sleep before your appointment.", 9),
    ("Main Centre Now Open Longer", "General",
     "The Main Donation Centre is now open from 8:00 AM to 5:00 PM every day, with appointments "
     "and walk-ins welcome.", 14),
    ("After Your Donation: Aftercare Tips", "Health Tips",
     "Rest for 10 to 15 minutes, keep drinking fluids and avoid heavy exercise for the rest of the day.", 21),
    ("New Rewards Are Here", "General",
     "Every donation earns 100 points. Visit the Rewards page to see new items, including mobile "
     "top-ups and health screening vouchers.", 28),
    ("Thank You, Penang Donors!", "News",
     "Thanks to your generosity we collected over 100 units last month. Every donation can save "
     "up to three lives.", 40),
]

HOSPITALS = {"hospital.pgh": "Penang General Hospital",
             "hospital.gleneagles": "Gleneagles Hospital Penang",
             "hospital.island": "Island Hospital"}

REQUEST_REASONS = ["Scheduled surgery", "Trauma case from road accident", "Postpartum haemorrhage",
                   "Thalassaemia transfusion", "Cancer patient treatment", "Emergency ward replenishment",
                   "Cardiac surgery", "Dengue patient with severe bleeding"]

# bulk (background) name pools
MALE = ["Ahmad", "Muhammad", "Hakim", "Irfan", "Syafiq", "Amir", "Aiman", "Haziq", "Faris", "Wei Jie",
        "Jun Hao", "Kok Wei", "Zhi Xiang", "Jia Wei", "Kah Meng", "Ravi", "Suresh", "Arjun", "Vikram",
        "Kumaran", "Dinesh", "Ethan", "Marcus", "Joshua", "Zulkifli"]
FEMALE = ["Aisyah", "Nur Izzati", "Syuhada", "Amira", "Hanis", "Balqis", "Sofea", "Alya", "Mei Xin",
          "Shu Ting", "Li Yi", "Jia Hui", "Xin Yi", "Wen Qi", "Kavitha", "Deepa", "Anita", "Lakshmi",
          "Sarah", "Rachel", "Emily", "Natasha", "Chloe", "Hannah", "Nabilah"]
LAST = ["Abdullah", "Ismail", "Yusof", "Hassan", "Ibrahim", "Tan", "Lim", "Lee", "Ong", "Chong", "Goh",
        "Teoh", "Khoo", "Chew", "Wong", "Subramaniam", "Nair", "Pillai", "Krishnan", "Raj", "Rahman",
        "Hamid", "Omar", "Khalid", "Lau", "Yap", "Ng", "Cheah", "Loh", "Sim"]
STREETS = ["Jalan Burma", "Lebuh Campbell", "Jalan Macalister", "Jalan Gurney", "Lorong Delima",
           "Jalan Perak", "Jalan Bayan Lepas", "Jalan Sultan Azlan Shah", "Persiaran Bukit Jambul"]
AREAS = ["George Town", "Bayan Lepas", "Air Itam", "Jelutong", "Gelugor", "Bukit Mertajam",
         "Butterworth", "Balik Pulau"]


# ------------------------------------------------------------------
# reset
# ------------------------------------------------------------------
def reset(conn):
    ids = [r[0] for r in conn.execute("SELECT id FROM users WHERE email LIKE ?", ("%" + SAMPLE_DOMAIN,))]
    reward_names = [r[0] for r in REWARDS]
    q_rw = ",".join("?" * len(reward_names))

    conn.execute(f"DELETE FROM reward_claims WHERE reward_id IN "
                 f"(SELECT id FROM rewards WHERE name IN ({q_rw}))", reward_names)
    if ids:
        q = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM reward_claims WHERE user_id IN ({q})", ids)
        conn.execute(f"DELETE FROM notifications WHERE user_id IN ({q})", ids)
        # donors, donations, appointments and blood_requests go with the user (ON DELETE CASCADE)
        conn.execute(f"DELETE FROM users WHERE id IN ({q})", ids)

    conn.execute(f"DELETE FROM rewards WHERE name IN ({q_rw})", reward_names)
    for title, *_ in EVENTS:
        conn.execute("DELETE FROM events WHERE title = ?", (title,))
    for title, *_ in ANNOUNCEMENTS:
        conn.execute("DELETE FROM announcements WHERE title = ?", (title,))
    print("Old sample data removed.")


# ------------------------------------------------------------------
# seed
# ------------------------------------------------------------------
def seed(conn, bulk=True):
    rng = random.Random(2026)             # same data on every run
    pw_hash = bcrypt.hashpw(SAMPLE_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    used_phones = {r[0] for r in conn.execute("SELECT phone_number FROM users WHERE phone_number IS NOT NULL")}
    used_ics = {r[0] for r in conn.execute("SELECT ic FROM donors")}
    used_emails = {r[0] for r in conn.execute("SELECT email FROM users")}
    stats = defaultdict(int)

    # ---- helpers that need conn -----------------------------------
    def add_user(name, email, role, phone=None, org=None, status="Active", created_days_ago=300):
        if email in used_emails:
            raise RuntimeError(f"{email} already exists")
        if phone and phone in used_phones:
            raise RuntimeError(f"phone {phone} already exists")
        used_emails.add(email)
        if phone:
            used_phones.add(phone)
        cur = conn.execute(
            """INSERT INTO users (full_name, email, organisation, phone_number, hashed_password,
                                  role, status, created_at, must_change_password)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (name, email, org, phone, pw_hash, role, status,
             stamp(day(created_days_ago), rng.randint(8, 18), rng.randint(0, 59))))
        stats["users"] += 1
        return cur.lastrowid

    def add_donor(user_id, name, ic, blood, dob, address, gender, emergency, kg, cm):
        used_ics.add(ic)
        cur = conn.execute(
            """INSERT INTO donors (user_id, donor_name, ic, blood_type, dob, address, gender,
                                   emergency_contact, weight, height)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, ic, blood, dob, address, gender, emergency, kg, cm))
        stats["donors"] += 1
        return cur.lastrowid

    def add_donation(donor_id, blood, days_ago):
        d = day(days_ago)
        expiry = d + timedelta(days=35)
        if days_ago <= 35:
            status = "Available"
        else:
            status = "Used" if (days_ago // 7) % 3 else "Expired"
        conn.execute(
            """INSERT INTO donations (donor_id, collection_date, expiry_date, blood_group,
                                      volume_blood, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (donor_id, stamp(d, rng.randint(8, 16), rng.choice([0, 15, 30, 45])),
             expiry.isoformat(), blood, 450.0, status))
        stats["donations"] += 1

    # ---- 1. staff and the unregistered donor ----------------------
    staff_ids = {}
    for name, prefix, role, org, phone, status in STAFF:
        staff_ids[prefix] = add_user(name, prefix + SAMPLE_DOMAIN, role, phone, org, status, 400)
    new_donor_uid = add_user(NEW_DONOR_EMAIL, NEW_DONOR_EMAIL, "donor", None, None, "Active", 2)

    # ---- 2. featured donors ---------------------------------------
    donor_ids, user_ids, blood_of = {}, {}, {}
    recent_by_type = defaultdict(int)
    for (name, prefix, blood, gender, dob, ic, phone, emergency, kg, cm, addr, donations) in FEATURED_DONORS:
        uid = add_user(name, prefix + SAMPLE_DOMAIN, "donor", phone, None, "Active", rng.randint(200, 700))
        did = add_donor(uid, name, ic, blood, dob, addr, gender, emergency, kg, cm)
        user_ids[prefix], donor_ids[prefix], blood_of[prefix] = uid, did, blood
        for days_ago in donations:
            add_donation(did, blood, days_ago)
            if days_ago <= 35:
                recent_by_type[blood] += 1

    # ---- 3. background donors (fill the stock + bookings) ---------
    bulk_donors = []                       # (donor_id, lapsed?)
    if bulk:
        used_names = set()

        def new_person(gender):
            while True:
                first = rng.choice(MALE if gender == "Male" else FEMALE)
                last = rng.choice(LAST)
                if (first, last) not in used_names:
                    used_names.add((first, last))
                    return f"{first} {last}"

        def new_ic(gender):
            while True:
                dob = date(rng.randint(1970, 2006), rng.randint(1, 12), rng.randint(1, 28))
                last_digit = rng.choice([1, 3, 5, 7, 9] if gender == "Male" else [0, 2, 4, 6, 8])
                ic = (f"{dob:%y%m%d}-{rng.choice(['07', '07', '07', '02', '03', '10', '14'])}-"
                      f"{rng.randint(100, 999)}{last_digit}")
                if ic not in used_ics:
                    return ic, dob

        def new_phone():
            while True:
                p = f"01{rng.choice([1, 2, 3, 6, 7, 9])}-{rng.randint(2000000, 9999999)}"
                if p not in used_phones:
                    return p

        def make_bg(blood, past_days):
            gender = rng.choice(["Male", "Female"])
            name = new_person(gender)
            ic, dob = new_ic(gender)
            n = stats["bg"] = stats["bg"] + 1
            uid = add_user(name, f"{slug(name)}{n}{SAMPLE_DOMAIN}", "donor", new_phone(), None,
                           "Active", rng.randint(100, 700))
            did = add_donor(uid, name, ic, blood, dob.isoformat(),
                            f"{rng.randint(1, 120)} {rng.choice(STREETS)}, {rng.choice(AREAS)}, Penang",
                            gender, new_phone(),
                            round(rng.uniform(48, 80) if gender == "Female" else rng.uniform(60, 98), 1),
                            rng.randint(150, 170) if gender == "Female" else rng.randint(163, 188))
            for d_ago in past_days:
                add_donation(did, blood, d_ago)
            return did

        # recent donors: one fresh "Available" unit each, up to the stock target
        for blood, target in STOCK_TARGET.items():
            for _ in range(max(target - recent_by_type[blood], 0)):
                recent = rng.randint(1, 34)
                older, nxt = [], recent
                for _ in range(rng.randint(0, 3)):
                    nxt += rng.randint(90, 140)
                    older.append(nxt)
                bulk_donors.append((make_bg(blood, [recent] + older), False))

        # lapsed donors: eligible again (last donation 85+ days ago), will get bookings
        types = list(STOCK_TARGET)
        weights = [4, 4, 3, 2, 2, 1, 1, 1]
        for _ in range(LAPSED_DONORS):
            blood = rng.choices(types, weights)[0]
            nxt = rng.randint(85, 150)
            days = [nxt]
            for _ in range(rng.randint(0, 2)):
                nxt += rng.randint(90, 130)
                days.append(nxt)
            bulk_donors.append((make_bg(blood, days), True))

    # ---- 4. events -------------------------------------------------
    main = conn.execute("SELECT event_id, start_time, end_time FROM events WHERE title = 'Main Donation Centre'").fetchone()
    if main is None:
        cur = conn.execute(
            """INSERT INTO events (title, event_date, start_time, end_time, place, address, notes)
               VALUES ('Main Donation Centre', ?, '08:00', '17:00', 'Main Blood Centre HQ',
                       '123 Central Health Avenue', 'Permanent Walk-in & Appointment Blood Donation Centre')""",
            (TODAY.isoformat(),))
        main = {"event_id": cur.lastrowid, "start_time": "08:00", "end_time": "17:00"}
    events = {"main": {"id": main["event_id"], "start": main["start_time"], "end": main["end_time"],
                       "date": None}}
    for title, offset, start, end, place, address, notes in EVENTS:
        d = TODAY + timedelta(days=offset)
        cur = conn.execute(
            """INSERT INTO events (title, event_date, start_time, end_time, place, address, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, d.isoformat(), start, end, place, address, notes))
        events[title] = {"id": cur.lastrowid, "start": start, "end": end, "date": d}
        stats["events"] += 1
    komtar = events["Komtar Community Blood Drive"]
    gurney = events["Gurney Plaza Donation Day"]
    bayan = events["Bayan Lepas Industrial Park Drive"]
    yearend = events["Year-End Blood Drive"]
    usm = events["USM Campus Blood Drive"]
    pgh = events["Penang Hospital Staff Blood Drive"]

    # ---- 5. appointments -----------------------------------------
    slot_use = defaultdict(int)
    for r in conn.execute("""SELECT event_id, appointment_date, appointment_time, COUNT(*) n FROM appointments
                              WHERE status != 'Cancelled' AND event_id IS NOT NULL
                              GROUP BY 1, 2, 3"""):
        slot_use[(r["event_id"], r["appointment_date"], r["appointment_time"])] = r["n"]

    def book(donor_id, ev, appt_date, appt_time, status="Booked", notes=None):
        conn.execute(
            """INSERT INTO appointments (donor_id, event_id, appointment_date, appointment_time, status, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (donor_id, ev["id"], appt_date.isoformat(), appt_time, status, notes))
        if status != "Cancelled":
            slot_use[(ev["id"], appt_date.isoformat(), appt_time)] += 1
        stats["appointments"] += 1

    book(donor_ids["tan.weiming"], usm, usm["date"], "10:30", "Completed")
    book(donor_ids["farah.amira"], pgh, pgh["date"], "09:30", "Completed")
    book(donor_ids["nurul.aisyah"], events["main"], day(10), "10:00", "Cancelled", "Not feeling well")
    book(donor_ids["farah.amira"], komtar, komtar["date"], "12:00", "Cancelled",
         "Unable to attend due to work commitment")
    book(donor_ids["muhammad.hafiz"], events["main"], TODAY + timedelta(days=8), "10:00")
    book(donor_ids["chong.jiahao"], komtar, komtar["date"], "11:00")
    book(donor_ids["daniel.lee"], events["main"], TODAY + timedelta(days=10), "14:30")
    book(donor_ids["siti.zulaikha"], gurney, gurney["date"], "14:00", notes="First-time donor")
    book(donor_ids["kumar.selvam"], bayan, bayan["date"], "09:30")

    targets = [komtar, komtar, gurney, gurney, bayan, yearend, events["main"]]
    for did, lapsed in bulk_donors:
        if not lapsed:
            continue
        ev = rng.choice(targets)
        appt_date = ev["date"] or (TODAY + timedelta(days=rng.randint(1, 14)))
        slots = _make_slots(ev["start"], ev["end"])
        rng.shuffle(slots)
        for t in slots:
            if slot_use[(ev["id"], appt_date.isoformat(), t)] < 4:      # app capacity is 5 per slot
                book(did, ev, appt_date, t)
                break

    # ---- 6. rewards and claims ----------------------------------
    reward_ids, reward_points = {}, {}
    claims_by_name = defaultdict(int)
    for prefix, rname, _phone, _d in CLAIMS:
        claims_by_name[rname] += 1
    for name, desc, points, stock, status, needs_phone in REWARDS:
        stock_left = max(stock - claims_by_name[name], 0) if stock else 0
        cur = conn.execute(
            """INSERT INTO rewards (name, desc, points, stock, status, needs_phone, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, desc, points, stock_left, status, needs_phone, stamp(day(120))))
        reward_ids[name], reward_points[name] = cur.lastrowid, points
        stats["rewards"] += 1
    for prefix, rname, phone, d_ago in CLAIMS:
        conn.execute(
            """INSERT INTO reward_claims (user_id, reward_id, reward, phone, points, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_ids[prefix], reward_ids[rname], rname, phone, reward_points[rname],
             stamp(day(d_ago), 14, 20)))
        stats["reward_claims"] += 1

    # ---- 7. blood requests --------------------------------------
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(blood_requests)")}
    statuses = ["Pending"] * 4 + ["Approved"] * 6 + ["Rejected"] * 2
    rng.shuffle(statuses)
    for i, status in enumerate(statuses):
        prefix = rng.choice(list(HOSPITALS))
        blood = rng.choice(list(STOCK_TARGET))
        values = {"hospital_name": HOSPITALS[prefix], "blood_group": blood,
                  "units_requested": rng.randint(1, 6), "reason": rng.choice(REQUEST_REASONS),
                  "status": status,
                  "request_date": stamp(day(rng.randint(0, 28)), rng.randint(8, 17), rng.randint(0, 59))}
        if "staff_id" in cols:            # only present on the newer schema
            values["staff_id"] = staff_ids[prefix]
        conn.execute(
            f"INSERT INTO blood_requests ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            list(values.values()))
        stats["blood_requests"] += 1

    # ---- 8. announcements ---------------------------------------
    for title, category, message, d_ago in ANNOUNCEMENTS:
        conn.execute(
            """INSERT INTO announcements (title, category, message, created_at, status)
               VALUES (?, ?, ?, ?, 'Published')""",
            (title, category, message, stamp(day(d_ago), 9, 0)))
        stats["announcements"] += 1

    # ---- 9. notifications ---------------------------------------
    def notify(uid, title, message, d_ago, read):
        conn.execute("""INSERT INTO notifications (user_id, title, message, is_read, created_at)
                        VALUES (?, ?, ?, ?, ?)""", (uid, title, message, read, stamp(day(d_ago), 10, 0)))
        stats["notifications"] += 1

    notify(user_ids["ahmad.faiz"], "Reward claimed", "Your RM5 Mobile Top-up has been processed.", 4, 0)
    notify(user_ids["ahmad.faiz"], "Thank you for donating!", "Your donation will help save up to three lives.", 12, 1)
    notify(user_ids["nurul.aisyah"], "Thank you for donating!", "Your donation 5 days ago is now in stock.", 5, 0)
    notify(user_ids["muhammad.hafiz"], "Appointment confirmed", "Main Donation Centre, 10:00 AM. See you there!", 1, 0)
    notify(user_ids["muhammad.hafiz"], "AB+ donors needed", "AB+ stock is critically low. Thank you for booking.", 1, 0)
    notify(user_ids["chong.jiahao"], "Appointment confirmed", "Komtar Community Blood Drive, 11:00 AM.", 2, 1)
    notify(user_ids["siti.zulaikha"], "Welcome!", "Thanks for registering. Your first appointment is booked.", 3, 0)
    notify(user_ids["kumar.selvam"], "You can donate again", "It has been over 12 weeks since your last donation.", 7, 1)
    notify(user_ids["raj.kumar"], "O- donors needed", "O- is in high demand. Thank you for being a regular donor.", 3, 0)
    for prefix in ("bloodbank.zainab", "bloodbank.kevin"):
        notify(staff_ids[prefix], "Low stock alert", "AB+, AB-, B- and O- are at critical levels.", 1, 0)
    for prefix in HOSPITALS:
        notify(staff_ids[prefix], "Request update", "One of your blood requests has been reviewed.", 2, 0)

    return stats, user_ids, new_donor_uid


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Add sample data to the blood bank database.")
    ap.add_argument("--reset", action="store_true", help="remove old sample data first")
    ap.add_argument("--no-bulk", action="store_true", help="skip the ~90 background donors")
    args = ap.parse_args()

    init_db()                              # make sure all tables/columns exist
    conn = get_db_connection()
    try:
        if args.reset:
            reset(conn)
        elif conn.execute("SELECT 1 FROM users WHERE email LIKE ? LIMIT 1", ("%" + SAMPLE_DOMAIN,)).fetchone():
            sys.exit("Sample data is already there. Run again with --reset to rebuild it.")

        stats, *_ = seed(conn, bulk=not args.no_bulk)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"\nSample data added to {DB_PATH}")
    for key in ("users", "donors", "donations", "events", "appointments", "rewards",
                "reward_claims", "blood_requests", "announcements", "notifications"):
        print(f"  {key:<15}{stats[key]}")
    print(f"\nAll sample accounts use the password:  {SAMPLE_PASSWORD}")
    print("  Donor (rich history)   raj.kumar" + SAMPLE_DOMAIN)
    print("  Donor (has bookings)   muhammad.hafiz" + SAMPLE_DOMAIN)
    print("  Donor (new, no donations) siti.zulaikha" + SAMPLE_DOMAIN)
    print("  Donor (not registered) " + NEW_DONOR_EMAIL)
    print("  Hospital staff         hospital.pgh" + SAMPLE_DOMAIN)
    print("  Blood bank staff       bloodbank.zainab" + SAMPLE_DOMAIN)
    print("  (kevin is Inactive on purpose, to show a deactivated account)")


if __name__ == "__main__":
    main()
