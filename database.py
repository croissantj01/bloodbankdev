import sqlite3

def get_db_connection():
    conn = sqlite3.connect('bloodbank.db')
    conn.row_factory = sqlite3.Row
    return conn

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

    conn.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            appointment_date DATE NOT NULL,
            status TEXT NOT NULL,
            
            FOREIGN KEY (donor_id)
                REFERENCES donors(donor_id)
                ON DELETE CASCADE
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
            
            FOREIGN KEY(donor_id)
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
            status TEXT DEFAULT 'Pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY(staff_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

    print('Database created!')


def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return user

init_db()