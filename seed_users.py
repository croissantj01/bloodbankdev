import sqlite3
import os
from datetime import datetime, date, timedelta
import bcrypt

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bloodbank.db"
)


def _hash_password(plain_password):
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_database():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    default_password = _hash_password("Password123")

    # 1. --- USERS & DONORS (20 Users) ---
    # Using exact role strings ('donor', 'blood_bank_staff', 'hospital_staff') matching verification.py
    users_data = [
        # --- 10 DONORS ---
        ("Alice Smith", "alice.donor@example.com", "0123456781", "donor", None, "Alice Smith", "IC000001", "O+",
         "1995-04-12", "123 Maple Street", "Female", "0129999991", 65.0, 170.0),
        ("Bob Johnson", "bob.donor@example.com", "0123456782", "donor", None, "Bob Johnson", "IC000002", "A+",
         "1990-08-22", "456 Oak Avenue", "Male", "0129999992", 75.0, 178.0),
        ("Charlie Brown", "charlie.donor@example.com", "0123456783", "donor", None, "Charlie Brown", "IC000003", "B+",
         "1998-11-05", "789 Pine Road", "Male", "0129999993", 70.0, 172.0),
        ("Diana Prince", "diana.donor@example.com", "0123456784", "donor", None, "Diana Prince", "IC000004", "AB+",
         "1992-02-14", "321 Elm Street", "Female", "0129999994", 60.0, 165.0),
        ("Ethan Hunt", "ethan.donor@example.com", "0123456785", "donor", None, "Ethan Hunt", "IC000005", "O-",
         "1988-07-30", "654 Cedar Lane", "Male", "0129999995", 80.0, 180.0),
        ("Fiona Gallagher", "fiona.donor@example.com", "0123456786", "donor", None, "Fiona Gallagher", "IC000006", "A-",
         "1996-09-19", "987 Birch Court", "Female", "0129999996", 58.0, 160.0),
        ("George Clark", "george.donor@example.com", "0123456787", "donor", None, "George Clark", "IC000007", "B-",
         "1985-12-03", "111 Walnut Way", "Male", "0129999997", 82.0, 175.0),
        ("Hannah Abbott", "hannah.donor@example.com", "0123456788", "donor", None, "Hannah Abbott", "IC000008", "AB-",
         "1994-05-25", "222 Chestnut Dr", "Female", "0129999998", 62.0, 168.0),
        ("Ian Wright", "ian.donor@example.com", "0123456789", "donor", None, "Ian Wright", "IC000009", "O+",
         "1991-03-11", "333 Spruce St", "Male", "0129999999", 78.0, 182.0),
        ("Julia Roberts", "julia.donor@example.com", "0123456790", "donor", None, "Julia Roberts", "IC000010", "A+",
         "1997-10-31", "444 Ash Boulevard", "Female", "0129999910", 55.0, 163.0),

        # --- 7 BLOOD BANK STAFF ---
        ("Staff One", "staff1@bloodbank.com", "0123456791", "blood_bank_staff", "Central Blood HQ", None, None, None,
         None, None, None, None, None, None),
        ("Staff Two", "staff2@bloodbank.com", "0123456792", "blood_bank_staff", "Central Blood HQ", None, None, None,
         None, None, None, None, None, None),
        ("Staff Three", "staff3@bloodbank.com", "0123456793", "blood_bank_staff", "North Branch", None, None, None,
         None, None, None, None, None, None),
        ("Staff Four", "staff4@bloodbank.com", "0123456794", "blood_bank_staff", "North Branch", None, None, None, None,
         None, None, None, None, None),
        ("Staff Five", "staff5@bloodbank.com", "0123456795", "blood_bank_staff", "East Wing", None, None, None, None,
         None, None, None, None, None),
        ("Staff Six", "staff6@bloodbank.com", "0123456796", "blood_bank_staff", "East Wing", None, None, None, None,
         None, None, None, None, None),
        ("Staff Seven", "staff7@bloodbank.com", "0123456797", "blood_bank_staff", "Mobile Unit", None, None, None, None,
         None, None, None, None, None),

        # --- 3 HOSPITAL STAFF ---
        ("Dr. Hospital A", "hospital.a@medical.com", "0123456798", "hospital_staff", "Penang General Hospital", None,
         None, None, None, None, None, None, None, None),
        ("Dr. Hospital B", "hospital.b@medical.com", "0123456799", "hospital_staff", "Gleneagles Hospital Penang", None,
         None, None, None, None, None, None, None, None),
        ("Dr. Hospital C", "hospital.c@medical.com", "0123456800", "hospital_staff", "Island Hospital Penang", None,
         None, None, None, None, None, None, None, None),
    ]

    users_added = 0
    for row in users_data:
        full_name, email, phone, role, org, d_name, ic, b_type, dob, addr, gender, ec, weight, height = row
        existing = cursor.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            continue

        cursor.execute("""
            INSERT INTO users (full_name, email, phone_number, hashed_password, role, organisation, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Active', datetime('now'))
        """, (full_name, email, phone, default_password, role, org))

        user_id = cursor.lastrowid

        if role == "donor":
            cursor.execute("""
                INSERT INTO donors (user_id, donor_name, ic, blood_type, dob, address, gender, emergency_contact, weight, height)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, d_name, ic, b_type, dob, addr, gender, ec, weight, height))
        users_added += 1

    # 2. --- EVENTS ---
    today = date.today()
    events_data = [
        ("Tanjung Tokong Spring Drive", (today - timedelta(days=15)).isoformat(), "09:00", "16:00",
         "Precinct 10 Penang", "Jalan Tanjong Tokong, 10470 George Town, Penang",
         "Successfully concluded community drive.", None),
        ("Penangite Lifeline Initiative", (today - timedelta(days=7)).isoformat(), "10:00", "17:00",
         "St. Jo's Gurney Paragon", "163d Persiaran Gurney, 10250 George Town, Penang",
         "Past successful blood collection campaign.", None),
        ("Penang Island Community Drive", (today + timedelta(days=2)).isoformat(), "09:00", "17:00",
         "Gurney Plaza Atrium", "Persiaran Gurney, 10250 George Town, Penang",
         "Annual charity drive supported by local community volunteers.", None),
        ("Bayan Lepas Mega Blood Campaign", (today + timedelta(days=5)).isoformat(), "10:00", "18:00", "Queensbay Mall",
         "100 Persiaran Bayan Indah, 11900 Bayan Lepas, Penang",
         "Special weekend donation campaign with free medical check-ups.", None),
        ("USM Campus Blood Donation Week", (today + timedelta(days=9)).isoformat(), "09:30", "16:30",
         "Universiti Sains Malaysia (USM)", "11800 USM, Gelugor, Penang",
         "Targeting students and staff at the Dewan Budaya foyer.", None),
    ]

    events_added = 0
    for title, ev_date, start, end, place, address, notes, img in events_data:
        existing = cursor.execute("SELECT event_id FROM events WHERE title = ?", (title,)).fetchone()
        if not existing:
            cursor.execute("""
                INSERT INTO events (title, event_date, start_time, end_time, place, address, notes, image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, ev_date, start, end, place, address, notes, img))
            events_added += 1

    # 3. --- APPOINTMENTS ---
    cursor.execute("SELECT donor_id FROM donors")
    donor_rows = cursor.fetchall()

    cursor.execute("SELECT event_id, event_date FROM events")
    event_rows = cursor.fetchall()

    appointments_added = 0
    if donor_rows and event_rows:
        times = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "14:00", "14:30", "15:00", "15:30"]
        for i, donor in enumerate(donor_rows):
            donor_id = donor[0]
            event = event_rows[i % len(event_rows)]
            event_id = event[0]
            event_date_str = event[1]
            appt_time = times[i % len(times)]

            event_date_obj = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            if event_date_obj < today:
                appt_status = "Completed"
                appt_notes = "Donation successfully completed. Vitals normal."
            else:
                appt_status = "Booked"
                appt_notes = "Pre-booked upcoming session."

            existing_appt = cursor.execute("""
                SELECT appointment_id FROM appointments 
                WHERE donor_id = ? AND event_id = ? AND appointment_date = ?
            """, (donor_id, event_id, event_date_str)).fetchone()

            if not existing_appt:
                cursor.execute("""
                    INSERT INTO appointments (donor_id, event_id, appointment_date, appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (donor_id, event_id, event_date_str, appt_time, appt_status, appt_notes))
                appointments_added += 1

    # 4. --- ANNOUNCEMENTS ---
    announcements_data = [
        ("Urgent O- Blood Shortage in Penang", "Alert",
         "We are currently experiencing a critical shortage of O- blood type supplies across all Penang hospitals. Walk-ins are highly encouraged.",
         None),
        ("Penang Mega Donation Drive 2026", "Event",
         "Join us this weekend at Gurney Plaza for our annual mega donation drive with free health screenings and food vouchers.",
         None),
        ("New Reward Tiers Unlocked", "Perks",
         "We have updated our reward system! Check out the new eWallet vouchers and merchandise now available for redemption using your donation points.",
         None),
        ("Safety Guidelines Update", "Notice",
         "Please remember to stay well-hydrated and get at least 6 hours of sleep prior to booking your blood donation appointment.",
         None),
        ("Thank You to Our Penang Donors", "News",
         "A heartfelt thank you to all corporate and individual partners across the island and mainland who contributed over 500 pints last month!",
         None),
    ]

    announcements_added = 0
    for title, category, message, img in announcements_data:
        existing = cursor.execute("SELECT announcement_id FROM announcements WHERE title = ?", (title,)).fetchone()
        if not existing:
            cursor.execute("""
                INSERT INTO announcements (title, category, message, image_filename, status, created_at)
                VALUES (?, ?, ?, ?, 'Published', datetime('now'))
            """, (title, category, message, img))
            announcements_added += 1

    # 5. --- REWARDS ---
    rewards_data = [
        ("Free Health Check Up", "Up to 3 free medication check per year!", 150, 50, 1),
        ("eWallet Rewards", "Redeem up to RM50 eWallet rewards!", 300, 30, 1),
        ("Exclusive Blood Donor Merchandise", "Get free exclusive tote bags, stickers and much more!", 100, 100, 0),
    ]

    rewards_added = 0
    for name, desc, points, stock, needs_phone in rewards_data:
        existing = cursor.execute("SELECT id FROM rewards WHERE name = ?", (name,)).fetchone()
        if not existing:
            cursor.execute("""
                INSERT INTO rewards (name, desc, points, stock, status, needs_phone, created_at)
                VALUES (?, ?, ?, ?, 'Active', ?, datetime('now'))
            """, (name, desc, points, stock, needs_phone))
            rewards_added += 1

    conn.commit()
    conn.close()
    print("Database re-seeded successfully with correct role names!")


if __name__ == "__main__":
    seed_database()