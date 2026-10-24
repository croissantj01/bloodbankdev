import io
import os
import re
import secrets
import smtplib
import sqlite3
import uuid
from datetime import datetime, date
from pathlib import Path

import bcrypt
from email.message import EmailMessage
from flask import Flask, render_template, url_for, redirect, session, request, flash, send_file, jsonify, current_app
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from werkzeug.utils import secure_filename

from database import (get_user_by_email, get_all_events,
                      add_event, update_event, delete_event, get_donor_by_email, create_appointment,
                      get_donor_upcoming_appointments, get_bookable_events, cancel_donor_appointment, get_db_connection,
                      get_donation_history, get_user_details)
import random

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a-very-secure-permanent-fallback-key')

oauth = OAuth(app)


def _hash_password(plain_password):
    """bcrypt hash - the same format login() verifies with bcrypt.checkpw."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def register_user(email, plain_password):
    email = email.strip().lower()

    hashed_password = bcrypt.hashpw(
        plain_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    conn = get_db_connection()

    try:
        conn.execute(
            """
            INSERT INTO users (
                full_name,
                email,
                hashed_password,
                role,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (email, email, hashed_password, "donor",
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

        conn.commit()
        print("Registration successful!")
        return True

    except sqlite3.IntegrityError as e:
        print("Registration failed:", e)
        return False

    except sqlite3.Error as e:
        print("Database error:", e)
        return False

    finally:
        conn.close()


oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

oauth.register(
    name='facebook',
    client_id=os.getenv('FACEBOOK_CLIENT_ID'),
    client_secret=os.getenv('FACEBOOK_CLIENT_SECRET'),
    access_token_url='https://graph.facebook.com/v18.0/oauth/access_token',
    authorize_url='https://www.facebook.com/v18.0/dialog/oauth',
    api_base_url='https://graph.facebook.com/v18.0/',
    client_kwargs={'scope': 'email public_profile'}
)

oauth.register(
    name='x',
    client_id=os.getenv('X_CLIENT_ID'),
    api_base_url='https://api.x.com/2/',
    authorize_url='https://x.com/i/oauth2/authorize',
    access_token_url='https://api.x.com/2/oauth2/token',
    client_kwargs={
        'scope': 'tweet.read users.read offline.access',
        'code_challenge_method': 'S256'
    }
)


@app.route('/login/<provider>')
def oauth_login(provider):
    if provider in ['google', 'facebook', 'x']:
        redirect_uri = url_for('oauth_authorize', provider=provider, _external=True)
        client = getattr(oauth, provider)
        return client.authorize_redirect(redirect_uri)

    return "Provider not found", 400


@app.route('/authorize/<provider>')
def oauth_authorize(provider):
    if provider == 'google':
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        email = user_info['email']
        name = user_info['name']
    elif provider == 'facebook':
        token = oauth.facebook.authorize_access_token()
        resp = oauth.facebook.get('me?fields=id,name,email')
        profile = resp.json()
        email = profile.get('email')
        name = profile.get('name')
    elif provider == 'x':
        token = oauth.x.authorize_access_token()
        resp = oauth.x.get('me?fields=id,name,email')
        profile = resp.json()
        email = profile.get('email')
        name = profile.get('name')
    else:
        return "Unsupported Provider", 400

    session['user_email'] = email
    session['user_name'] = name

    return f"Successfully authenticated via {provider.capitalize()}! Welcome, {name} ({email})."


@app.route("/")
def index():
    return render_template("general/index.html")


@app.route("/about")
def about():
    return render_template("general/about.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.pop('is_reset_flow', None)
    next_page = request.args.get('next') or request.form.get('next')

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD") or ""

        if email == admin_email and password == admin_password:
            otp = str(random.randint(100000, 999999))

            session['pending_email'] = email
            session['pending_otp'] = otp
            session['pending_name'] = "Admin"
            session['pending_role'] = "admin"
            session['next_page'] = next_page

            send_otp_email(email, otp)

            return render_template("general/verification.html")

        user = get_user_by_email(email)

        if not user:
            return render_template("general/login.html", error_popup="Invalid credentials.")

        stored_hash = None
        if isinstance(user, dict):
            stored_hash = user.get('hashed_password')
        else:
            try:
                stored_hash = user['hashed_password']
            except (KeyError, IndexError):
                stored_hash = None

        if stored_hash:
            password_bytes = password.encode('utf-8')
            hashed_bytes = stored_hash.encode('utf-8') if isinstance(stored_hash, str) else stored_hash

            if bcrypt.checkpw(password_bytes, hashed_bytes):
                account_status = user['status'] if 'status' in user.keys() else 'Active'
                if str(account_status or 'Active').strip().lower() == 'inactive':
                    return render_template(
                        "general/login.html",
                        error_popup="Your account has been deactivated. Please contact the administrator.")

                otp = str(random.randint(100000, 999999))

                user_name = user['full_name'] if ('full_name' in user.keys() and user['full_name']) else email
                role = user['role'] if ('role' in user.keys() and user['role']) else 'donor'

                user_role = str(role).strip().lower().replace(' ', '_')

                session['pending_email'] = email
                session['pending_otp'] = otp
                session['next_page'] = next_page
                session['pending_name'] = user_name
                session['pending_role'] = user_role

                send_otp_email(email, otp)

                return render_template("general/verification.html")

        return render_template("general/login.html", error="Invalid credentials.")

    return render_template("general/login.html", next=next_page)


@app.route("/check_email", methods=["GET", "POST"])
def check_email():
    if request.method == "POST":
        entered_email = request.form.get('email')
        user = get_user_by_email(entered_email)

        admin_email = os.getenv('ADMIN_EMAIL')

        if entered_email == admin_email:
            return render_template("general/check_email.html",
                                   error_popup="Admin password can't be reset here! Contact IT department!")

        if not user:
            return render_template("general/check_email.html", error_popup="No email found! Please try again.")
        else:
            otp = str(random.randint(100000, 999999))

            session['pending_email'] = entered_email
            session['pending_otp'] = otp
            session['is_reset_flow'] = True

            send_otp_email(entered_email, otp)

            return render_template("general/verification.html")
    return render_template("general/check_email.html")


def update_password(email, new_password):
    hashed_password = bcrypt.hashpw(
        new_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    conn = get_db_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE users
            SET hashed_password = ?
            WHERE email = ?
            """,
            (hashed_password, email.strip().lower())
        )

        conn.commit()

        if cursor.rowcount == 0:
            print("No account found for password update.")
    finally:
        conn.close()


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if not session.get('otp_verified') or not session.get('pending_email'):
        return redirect(url_for('check_email'))

    if request.method == "POST":
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_new_password')

        if new_password != confirm_password:
            return render_template("general/reset_password.html", error_popup="The password does not match!")

        email = session.get('pending_email')
        update_password(email, new_password)

        session.pop('pending_email', None)
        session.pop('is_reset_flow', None)
        session.pop('otp_verified', None)

        return redirect(url_for('login'))

    return render_template("general/reset_password.html")


def send_otp_email(to_email, otp):
    # verification otp bypass for testing
    print(f"This is the test otp: {otp}")
    message = EmailMessage()
    message.set_content(
        f"Your verification code is: {otp} \nThis code will expire shortly. Do not share it with anyone. ")
    message['Subject'] = "Blood Bank Management System Verification Code"
    message['From'] = os.getenv('MAIL_USERNAME')
    message['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(os.getenv('MAIL_USERNAME'), os.getenv('MAIL_PASSWORD'))
            server.send_message(message)
        return True
    except Exception as e:
        return False


@app.route("/signup", methods=["GET", "POST"])
def signup():
    session.pop("is_reset_flow", None)

    next_page = request.args.get("next") or request.form.get("next")

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not email or not password:
            return render_template(
                "general/signup.html",
                error_popup="Please enter your email and password."
            )

        if password != confirm_password:
            return render_template(
                "general/signup.html",
                error_popup="Passwords do not match!"
            )

        # Check whether the email is already registered
        if get_user_by_email(email):
            return render_template(
                "general/signup.html",
                error_popup="This email is already registered. Please log in."
            )

        otp = str(random.randint(100000, 999999))

        session["pending_email"] = email
        session["pending_password"] = password
        session["pending_otp"] = otp

        if next_page:
            session["next_page"] = next_page

        send_otp_email(email, otp)

        return render_template("general/verification.html")

    return render_template("general/signup.html", next=next_page)


@app.route("/verification", methods=["POST"])
def verification():
    entered_otp = (request.form.get("otp") or "").strip()
    generated_otp = session.get("pending_otp")

    if not generated_otp or entered_otp != generated_otp:
        return render_template(
            "general/verification.html",
            error_popup="Invalid OTP. Try again!"
        )

    session.pop("pending_otp", None)

    # Password reset flow
    if session.get("is_reset_flow"):
        session["otp_verified"] = True
        return redirect(url_for("reset_password"))

    pending_password = session.get("pending_password")
    email = session.get("pending_email")

    # Create the account only after OTP verification
    if pending_password and email:
        if not register_user(email, pending_password):
            session.pop("pending_password", None)
            session.pop("pending_email", None)

            return render_template(
                "general/signup.html",
                error_popup=(
                    "Registration failed. Please try logging in "
                    "or signing up with another email."
                )
            )

        session.pop("pending_password", None)
        session.pop("pending_email", None)

        session["user_email"] = email
        session["user_name"] = "User"
        session["role"] = "donor"

    else:
        # Handle other OTP flows that already have a pending user
        email = session.pop("pending_email", None)
        name = session.pop("pending_name", "User")
        role = session.pop("pending_role", "donor")

        if not email:
            return redirect(url_for("login"))

        session["user_email"] = email
        session["user_name"] = name
        session["role"] = role

    target_page = session.pop("next_page", None)

    if not target_page or target_page == "None":
        role = session.get("role", "donor")

        if role == "admin":
            target_page = "admin_dashboard"
        elif role == "hospital_staff":
            target_page = "hospital_staff_dashboard"
        elif role == "blood_bank_staff":
            target_page = "blood_bank_staff_dashboard"
        else:
            target_page = "donor_dashboard"

    try:
        return redirect(url_for(target_page))
    except Exception:
        return redirect(url_for("donor_dashboard"))


@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    return render_template("general/quiz.html")


@app.route('/donor_quiz', methods=['GET', 'POST'])
def donor_quiz():
    return render_template("donor/donor_quiz.html")


@app.route('/donor_faq', methods=['GET', 'POST'])
def donor_faq():
    return render_template("donor/donor_faq.html")


from datetime import datetime  # put with your other imports at the top


def _parse_dt(value):
    text = str(value or "")
    for fmt, has_time in (("%Y-%m-%d %H:%M:%S", True), ("%Y-%m-%d", False)):
        try:
            return datetime.strptime(text[:19] if has_time else text[:10], fmt), has_time
        except ValueError:
            continue
    return None, False


def _format_volume(value):
    try:
        return f"{float(value):g} ml"
    except (TypeError, ValueError):
        return "—"


@app.route('/donation_history')
def donation_history():
    donor = get_donor_by_email(session.get("email"))

    if donor:
        history = get_donation_history(donor["donor_id"])
    else:
        history = {
            "records": [],
            "total_donations": 0,
            "year_donations": 0,
            "current_year": date.today().year,
            "last_donation_day": "—",
            "last_donation_year": "No donations yet",
        }

    return render_template("donor/donation_history.html", **history)


@app.route('/donor_announcements', methods=['GET', 'POST'])
def donor_announcements():
    return render_template("donor/donor_announcements.html")



@app.route('/staff_report/<report_type>', methods=['GET'])
def staff_report_details(report_type):
    allowed_reports = [
        'blood_stock',
        'low_stock',
        'blood_request',
        'users',
        'donations'
    ]

    if report_type not in allowed_reports:
        return "Report not found", 404

    # Reuse the existing Admin report calculations.
    from_date = request.args.get('from_date') or ''
    to_date = request.args.get('to_date') or ''

    d_clause, d_params = _date_clause(
        'collection_date', from_date, to_date
    )
    r_clause, r_params = _date_clause(
        'request_date', from_date, to_date
    )

    conn = get_db_connection()

    try:
        # Current blood stock
        stock_rows = conn.execute("""
            SELECT blood_group, COUNT(*) AS units
            FROM donations
            WHERE status = 'Available'
              AND date(expiry_date) >= date('now')
            GROUP BY blood_group
        """).fetchall()

        stock = {
            row['blood_group']: row['units']
            for row in stock_rows
        }

        stock_units = [stock.get(t, 0) for t in BLOOD_TYPES]

        critical = [
            t for t in BLOOD_TYPES
            if stock.get(t, 0) <= MIN_THRESHOLD * 0.5
        ]

        low = [
            t for t in BLOOD_TYPES
            if MIN_THRESHOLD * 0.5 < stock.get(t, 0) < MIN_THRESHOLD
        ]

        below = critical + low

        # Blood request statistics
        req_rows = conn.execute(
            f"""
            SELECT status, COUNT(*) AS n
            FROM blood_requests
            WHERE 1=1 {r_clause}
            GROUP BY status
            """,
            r_params
        ).fetchall()

        req = {row['status']: row['n'] for row in req_rows}

        # Donation statistics
        total_donations = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM donations
            WHERE 1=1 {d_clause}
            """,
            d_params
        ).fetchone()[0]

        donations_this_month = conn.execute("""
            SELECT COUNT(*)
            FROM donations
            WHERE strftime('%Y-%m', collection_date)
                = strftime('%Y-%m', 'now')
        """).fetchone()[0]

        month_rows = conn.execute(
            f"""
            SELECT strftime('%Y-%m', collection_date) AS m,
                   COUNT(*) AS n
            FROM donations
            WHERE 1=1 {d_clause}
            GROUP BY m
            ORDER BY m DESC
            LIMIT 6
            """,
            d_params
        ).fetchall()[::-1]

        type_rows = conn.execute(
            f"""
            SELECT blood_group, COUNT(*) AS n
            FROM donations
            WHERE 1=1 {d_clause}
            GROUP BY blood_group
            """,
            d_params
        ).fetchall()

        by_type = {
            row['blood_group']: row['n']
            for row in type_rows
        }

        # Donor statistics
        total_donors = conn.execute(
            "SELECT COUNT(*) FROM donors"
        ).fetchone()[0]

        active_users = conn.execute("""
            SELECT COUNT(DISTINCT donor_id)
            FROM donations
            WHERE date(collection_date) >= date('now', '-365 day')
        """).fetchone()[0]

    finally:
        conn.close()

    # All report data is passed to the same HTML template.
    return render_template(
        "blood_bank_staff/staff_report_details.html",
        report_type=report_type,
        from_date=from_date,
        to_date=to_date,

        total_units=sum(stock_units),
        stock_labels=BLOOD_TYPES,
        stock_units=stock_units,
        sufficient_count=len(BLOOD_TYPES) - len(below),
        low_count=len(low),
        critical_count=len(critical),

        alerts_triggered=len(below),
        alerts_notified="N/A",
        most_low_type=(
            min(BLOOD_TYPES, key=lambda t: stock.get(t, 0))
            if below else '-'
        ),
        alert_labels=below,
        alert_counts=[stock.get(t, 0) for t in below],

        total_requests=sum(req.values()),
        approved_requests=req.get('Approved', 0),
        rejected_requests=req.get('Rejected', 0),
        pending_requests=req.get('Pending', 0),
        auto_closed_requests=req.get('Auto-Closed', 0),

        total_donors=total_donors,
        new_registrations="N/A",
        active_users=active_users,
        inactive_users=max(total_donors - active_users, 0),

        total_donations=total_donations,
        donations_this_month=donations_this_month,
        top_donated_type=(
            max(by_type, key=by_type.get) if by_type else '-'
        ),
        donation_months=[row['m'] for row in month_rows],
        donation_counts=[row['n'] for row in month_rows],
        donation_type_labels=BLOOD_TYPES,
        donation_type_counts=[
            by_type.get(t, 0) for t in BLOOD_TYPES
        ]
    )


@app.route('/blood_request', methods=['GET'])
def blood_request():
    conn = get_db_connection()

    try:
        requests = conn.execute("""
            SELECT
                request_id AS id,
                hospital_name,
                blood_group AS blood_type,
                units_requested AS quantity,
                request_date AS requested_date,
                reason,
                status
            FROM blood_requests
            ORDER BY request_date DESC
        """).fetchall()

    finally:
        conn.close()

    return render_template(
        "blood_bank_staff/blood_request.html",
        requests=requests
    )

@app.route('/approve_blood_request/<int:request_id>', methods=['POST'])
def approve_blood_request(request_id):
    conn = get_db_connection()

    try:
        conn.execute("""
            UPDATE blood_requests
            SET status = 'Approved'
            WHERE request_id = ?
              AND status = 'Pending'
        """, (request_id,))

        conn.commit()

    finally:
        conn.close()

    return redirect(url_for('blood_request'))


@app.route('/reject_blood_request/<int:request_id>', methods=['POST'])
def reject_blood_request(request_id):
    conn = get_db_connection()

    try:
        conn.execute("""
            UPDATE blood_requests
            SET status = 'Rejected'
            WHERE request_id = ?
              AND status = 'Pending'
        """, (request_id,))

        conn.commit()

    finally:
        conn.close()

    return redirect(url_for('blood_request'))


@app.route('/view_blood_request', methods=['GET'])
def view_blood_request():
    conn = get_db_connection()

    try:
        requests = conn.execute("""
            SELECT
                request_id AS id,
                hospital_name,
                blood_group AS blood_type,
                units_requested AS quantity,
                request_date AS requested_date,
                reason,
                status
            FROM blood_requests
            ORDER BY request_date DESC
        """).fetchall()
    finally:
        conn.close()

    return render_template(
        "hospital_staff/view_blood_request.html",
        requests=requests
    )


def send_credentials_email(to_email, full_name, temp_password):
    message = EmailMessage()
    message['Subject'] = "Blood Bank Management System - Account Creation"
    message['From'] = os.getenv('MAIL_USERNAME')
    message['To'] = to_email

    body = f"""    Hello {full_name},
    Your blood bank management system staff account has been created.

    Here are your login credentials:
    Email: {to_email}
    Temporary Password: {temp_password}

    Please log in to the system and change your password after your first log in. Thank you!
    """

    message.set_content(body)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(os.getenv('MAIL_USERNAME'), os.getenv('MAIL_PASSWORD'))
            server.send_message(message)
        return True
    except Exception as e:
        return False


def register_staff_user(full_name, email, phone_number, role, password):
    hashed_password = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    normalized_role = str(role).strip().lower().replace(" ", "_")
    email = email.strip().lower()
    conn = get_db_connection()

    try:
        conn.execute(
            """
            INSERT INTO users
                (full_name, email, phone_number, hashed_password, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                full_name,
                email,
                phone_number,
                hashed_password,
                normalized_role,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        return True

    except sqlite3.IntegrityError as e:
        print(f"Staff registration failed: {e}")
        return False

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return False

    finally:
        conn.close()


@app.route('/add_rewards/<int:reward_id>/toggle', methods=['POST'])
def toggle_reward_status(reward_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='add_rewards'))

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    reward = conn.execute("SELECT * FROM rewards WHERE id = ?", (reward_id,)).fetchone()

    if reward:
        current_status = reward['status']
        new_status = 'Inactive' if current_status == 'Active' else 'Active'
        conn.execute("UPDATE rewards SET status = ? WHERE id = ?", (new_status, reward_id))
        conn.commit()
        flash(f"Reward '{reward['name']}' status updated to {new_status}.", "success")
    else:
        flash("Reward not found.", "error")

    conn.close()
    return redirect(url_for('add_rewards'))


@app.route('/faq', methods=['GET', 'POST'])
def faq():
    return render_template("general/faq.html")


@app.route('/hospital_staff_dashboard', methods=['GET', 'POST'])
def hospital_staff_dashboard():
    return render_template("hospital_staff/hospital_staff_dashboard.html")


MIN_THRESHOLD = 20
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


@app.route('/view_blood_info', methods=['GET', 'POST'])
def view_blood_info():
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT blood_group,
                   COUNT(*) AS units,
                   MAX(collection_date) AS last_updated
            FROM donations
            WHERE status = 'Available'
              AND date(expiry_date) >= date('now')
            GROUP BY blood_group
        """).fetchall()
    finally:
        conn.close()

    stock = {r['blood_group']: r for r in rows}

    inventory = []
    for blood_type in BLOOD_TYPES:
        row = stock.get(blood_type)
        inventory.append({
            "type": blood_type,
            "units": row['units'] if row else 0,
            "updated": (row['last_updated'] or "")[:10] if row else "No stock yet",
        })

    return render_template(
        "admin/view_blood_info.html",
        inventory=inventory,
        min_threshold=MIN_THRESHOLD,
    )


@app.route('/staff_report', methods=['GET', 'POST'])
def staff_report():
    return render_template("blood_bank_staff/staff_report.html")

from datetime import datetime

@app.template_filter('fmt_date')
def fmt_date(value, fmt='%d %b %Y'):
    if not value:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], '%Y-%m-%d')
        except ValueError:
            return value
    return value.strftime(fmt)


@app.route('/make_announcement', methods=['GET', 'POST'])
def make_announcement():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        message = request.form.get('message', '').strip()

        image = request.files.get('announcement_image')
        image_filename = None

        # Validate required fields
        if not title or not category or not message:
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('make_announcement'))

        # Handle optional image upload
        if image and image.filename:
            if image.mimetype not in ('image/jpeg', 'image/png'):
                flash('Please upload a JPG or PNG image.', 'error')
                return redirect(url_for('make_announcement'))

            image_filename = secure_filename(image.filename)

            # Avoid overwriting an existing image with the same filename
            name, extension = os.path.splitext(image_filename)
            image_filename = f"{name}_{os.urandom(4).hex()}{extension}"

            image.save(
                os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            )

        # Save announcement to the existing SQLite database
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO announcements
                    (title, category, message, image_filename, status)
                VALUES (?, ?, ?, ?, 'Published')
                """,
                (title, category, message, image_filename)
            )
            conn.commit()
        except Exception:
            conn.rollback()

            # Remove uploaded image if saving the announcement fails
            if image_filename:
                image_path = os.path.join(
                    app.config['UPLOAD_FOLDER'], image_filename
                )
                if os.path.exists(image_path):
                    os.remove(image_path)

            flash('Unable to publish the announcement. Please try again.', 'error')
            return redirect(url_for('make_announcement'))
        finally:
            conn.close()

        flash('Announcement published successfully!', 'success')
        return redirect(url_for('make_announcement'))

    return render_template('blood_bank_staff/make_announcement.html')


@app.route("/donor_dashboard", methods=['GET', 'POST'])
def donor_dashboard():
    return render_template("donor/donor_dashboard.html")


@app.route("/registration", methods=['GET', 'POST'])
def registration():
    if 'user_email' not in session:
        return redirect(url_for('login', next='registration'))

    if request.method == 'POST':
        name = request.form.get('name')
        ic = request.form.get('ic').strip()
        dob = request.form.get('dob')
        gender = request.form.get('gender')
        blood_type = request.form.get('blood_type')
        phone = request.form.get('phone')
        emergency_contact = request.form.get('emergency_contact')
        address = request.form.get('address')

        weight = 0.0
        height = 0.0

        user_email = session.get('user_email')
        conn = get_db_connection()
        user = conn.execute("SELECT id FROM users WHERE email = ?", (user_email,)).fetchone()

        if not user:
            conn.close()
            flash("User session not found. Please log in again.", "error")
            return redirect(url_for('login'))

        user_id = user['id']

        try:
            conn.execute('''
                INSERT INTO donors (user_id, donor_name, ic, blood_type, dob, address, gender, emergency_contact, weight, height)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, name, ic, blood_type, dob, address, gender, emergency_contact, weight, height))

            conn.execute('''
                UPDATE users SET full_name = ?, phone_number = ? WHERE id = ?
            ''', (name, phone, user_id))

            conn.commit()
            conn.close()

            flash("Donor registration successful!", "success")
            return redirect(url_for('donor_dashboard'))

        except sqlite3.IntegrityError as e:
            conn.close()
            flash("This IC number is already registered to another account.", "error")
            return render_template("donor/registration.html")

    return render_template("donor/registration.html")


@app.route("/manage_profile", methods=['GET', 'POST'])
def manage_profile():
    if 'user_email' not in session:
        return redirect(url_for('login', next='manage_profile'))

    user_email = session.get('user_email')
    conn = get_db_connection()

    user = conn.execute("SELECT id FROM users WHERE email = ?", (user_email,)).fetchone()
    if not user:
        conn.close()
        return redirect(url_for('login'))

    user_id = user['id']

    donor = conn.execute('''
        SELECT d.*, u.full_name, u.phone_number 
        FROM donors d
        JOIN users u ON d.user_id = u.id
        WHERE d.user_id = ?
    ''', (user_id,)).fetchone()

    user_info = conn.execute("SELECT full_name, phone_number FROM users WHERE id = ?", (user_id,)).fetchone()

    if request.method == 'POST':
        name = request.form.get('name')
        dob = request.form.get('dob')
        gender = request.form.get('gender')
        blood_type = request.form.get('blood_type')
        phone = request.form.get('phone')
        emergency_contact = request.form.get('emergency_contact')
        address = request.form.get('address')

        if donor:
            conn.execute('''
                UPDATE donors 
                SET blood_type = ?, dob = ?, address = ?, gender = ?, emergency_contact = ?
                WHERE user_id = ?
            ''', (blood_type, dob, address, gender, emergency_contact, user_id))
            flash("Profile updated successfully!", "success")
        else:
            ic = request.form.get('ic', '').strip()
            try:
                conn.execute('''
                    INSERT INTO donors (user_id, ic, blood_type, dob, address, gender, emergency_contact, weight, height)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0)
                ''', (user_id, ic, blood_type, dob, address, gender, emergency_contact))
                flash("Registration completed successfully!", "success")
            except sqlite3.IntegrityError:
                flash("This IC number is already registered to another account.", "error")
                conn.close()
                return redirect(url_for('manage_profile'))

        conn.execute('''
            UPDATE users SET full_name = ?, phone_number = ? WHERE id = ?
        ''', (name, phone, user_id))

        conn.commit()
        conn.close()
        return redirect(url_for('manage_profile'))

    conn.close()
    return render_template("donor/manage_profile.html", donor=donor, user=user_info)



@app.route("/admin_dashboard")
def admin_dashboard():
    return render_template("admin/admin_dashboard.html")

@app.route('/manage_users/<int:user_id>/view')
def view_user(user_id):
    # add the same admin-only check you use on your other manage_users routes
    details = get_user_details(user_id)
    if details is None:
        return jsonify(ok=False, error="User not found."), 404
    return jsonify(ok=True, user=details)


@app.route("/index")
def logout():
    session.clear()
    return render_template("general/index.html")


def _clean_event_form(form, is_new):
    """Read and validate the event form. Returns (data_tuple, error_message)."""
    title = (form.get('title') or '').strip()
    ev_date = (form.get('date') or '').strip()
    start = (form.get('start') or '').strip()
    end = (form.get('end') or '').strip()
    place = (form.get('place') or '').strip()
    address = (form.get('address') or '').strip()
    notes = (form.get('notes') or '').strip()

    if not (title and ev_date and start and end and place and address):
        return None, "Please fill in all the required fields."

    if len(title) > 120 or len(place) > 120 or len(address) > 200 or len(notes) > 500:
        return None, "One of the fields is too long."

    try:
        parsed_date = datetime.strptime(ev_date, "%Y-%m-%d").date()
        t_start = datetime.strptime(start, "%H:%M")
        t_end = datetime.strptime(end, "%H:%M")
    except ValueError:
        return None, "Invalid date or time."

    if t_end <= t_start:
        return None, "End time must be after the start time."

    if is_new and parsed_date < date.today():
        return None, "New events cannot be set in the past."

    return (title, ev_date, start, end, place, address, notes), None

from werkzeug.exceptions import RequestEntityTooLarge

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE + 512 * 1024  # headroom for form fields


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    flash("Image size must not exceed 5 MB.", "error")
    return redirect(url_for("manage_events"))


def _looks_like_image(header: bytes) -> bool:
    return (
        header.startswith(b"\xff\xd8\xff")                          # JPEG
        or header.startswith(b"\x89PNG\r\n\x1a\n")                  # PNG
        or (header[:4] == b"RIFF" and header[8:12] == b"WEBP")      # WebP
    )


def save_event_image(file):
    """Save a validated event image and return its filename (or None)."""
    if not file or not file.filename:
        return None

    # Don't rely on secure_filename for the extension (it drops non-ASCII names)
    extension = Path(file.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Only JPG, JPEG, PNG, and WebP images are allowed.")

    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)

    if size == 0:
        raise ValueError("The selected image is empty.")
    if size > MAX_IMAGE_SIZE:
        raise ValueError("Image size must not exceed 5 MB.")

    header = file.stream.read(12)
    file.stream.seek(0)
    if not _looks_like_image(header):
        raise ValueError("The selected file is not a valid image.")

    filename = f"{uuid.uuid4().hex}.{extension}"
    upload_folder = Path(current_app.static_folder) / "uploads" / "events"
    upload_folder.mkdir(parents=True, exist_ok=True)
    file.save(upload_folder / filename)

    return filename

@app.route('/manage_events', methods=['GET', 'POST'])
def manage_events():

    if request.method == 'POST':
        action = request.form.get('action')
        event_id = request.form.get('event_id', type=int)

        if action == 'delete':
            if event_id and delete_event(event_id):
                flash("Event deleted.", "success")
            else:
                flash("Event not found.", "error")

        elif action in ('add', 'edit'):
            data, error = _clean_event_form(
                request.form,
                is_new=(action == 'add')
            )

            if error:
                flash(error, "error")
                return redirect(url_for('manage_events'))

            image_file = request.files.get('image')

            try:
                image_filename = save_event_image(image_file)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for('manage_events'))

            if action == 'add':
                # Requires add_event() to support the image parameter.
                add_event(*data, image=image_filename)
                flash("Event added.", "success")


            elif event_id:

                try:

                    updated = update_event(event_id, *data, image=image_filename)

                except ValueError as exc:

                    flash(str(exc), "error")

                    return redirect(url_for('manage_events'))

                flash("Event updated." if updated else "Event not found.",

                      "success" if updated else "error")

            else:

                flash("Event not found.", "error")

        return redirect(url_for('manage_events'))

    return render_template(
        "admin/manage_events.html",
        events=get_all_events()
    )



POINTS_PER_DONATION = 100
REWARD_STATUSES = ("Active", "Inactive")


# ------------------------------------------------------------
# Tables
#   rewards        what the admin adds (stock NULL = unlimited)
#   reward_claims  what donors claimed. The reward name is copied in, so the
#                  history survives even if the admin deletes the reward.
# ------------------------------------------------------------
def ensure_reward_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rewards (
            reward_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            points_cost INTEGER NOT NULL CHECK (points_cost > 0),
            stock       INTEGER CHECK (stock IS NULL OR stock >= 0),
            status      TEXT NOT NULL DEFAULT 'Active',
            created_at  TEXT,
            needs_phone INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reward_claims (
            claim_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            reward_id    INTEGER,
            donor_id     INTEGER NOT NULL,
            reward_name  TEXT NOT NULL,
            points_spent INTEGER NOT NULL,
            claimed_at   TEXT NOT NULL,
            phone        TEXT,
            FOREIGN KEY (reward_id) REFERENCES rewards(reward_id) ON DELETE SET NULL,
            FOREIGN KEY (donor_id)  REFERENCES donors(donor_id)   ON DELETE CASCADE
        )
    """)
    # tables created by the first version of this file get the new columns
    for table, column, ddl in (("rewards", "needs_phone", "INTEGER NOT NULL DEFAULT 0"),
                               ("reward_claims", "phone", "TEXT")):
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        if column not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
    conn.commit()


# ------------------------------------------------------------
# TNG phone number (Malaysian mobile). Stored as digits: 0123456789
# Accepts 012-345 6789, 0123456789, +6012 345 6789, 60123456789 ...
# ------------------------------------------------------------
def normalize_my_phone(raw):
    digits = re.sub(r"[\s\-()]", "", (raw or "").strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("60"):
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"01\d{8,9}", digits) else None


def format_my_phone(digits):
    digits = digits or ""
    if len(digits) == 10:
        return "%s-%s %s" % (digits[:3], digits[3:6], digits[6:])
    if len(digits) == 11:
        return "%s-%s %s" % (digits[:3], digits[3:7], digits[7:])
    return digits


def _reward_conn():
    conn = get_db_connection()
    ensure_reward_tables(conn)
    return conn


def _rw_error(message, code=400):
    return jsonify(ok=False, error=message), code


def _rw_admin_denied():
    """An error response when the caller is not the admin, else None."""
    if session.get('role') != 'admin':
        return _rw_error("Your session has expired. Please log in again.", 403)
    return None


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ------------------------------------------------------------
# Admin: validate the add / edit form
# ------------------------------------------------------------
def _read_reward_form(conn, reward_id=None):
    f = request.form
    name = (f.get("name") or "").strip()
    description = (f.get("description") or "").strip()
    points_raw = (f.get("points_cost") or "").strip()
    stock_raw = (f.get("stock") or "").strip()
    status = (f.get("status") or "Active").strip()
    needs_phone = 1 if f.get("needs_phone") in ("1", "on", "true") else 0

    if not name:
        return None, "Reward name is required."
    if len(name) > 80:
        return None, "Reward name must be 80 characters or fewer."
    if len(description) > 200:
        return None, "Description must be 200 characters or fewer."

    try:
        points = int(points_raw)
    except ValueError:
        return None, "Points cost must be a whole number."
    if not 1 <= points <= 100000:
        return None, "Points cost must be between 1 and 100,000."

    stock = None                      # blank = unlimited
    if stock_raw != "":
        try:
            stock = int(stock_raw)
        except ValueError:
            return None, "Stock must be a whole number (leave it blank for unlimited)."
        if not 0 <= stock <= 100000:
            return None, "Stock must be between 0 and 100,000."

    if status not in REWARD_STATUSES:
        return None, "Invalid status."

    duplicate = conn.execute(
        "SELECT 1 FROM rewards WHERE LOWER(name) = LOWER(?) AND reward_id != ?",
        (name, reward_id or 0)).fetchone()
    if duplicate:
        return None, "A reward with this name already exists."

    return dict(name=name, description=description or None,
                points=points, stock=stock, status=status,
                needs_phone=needs_phone), None


# ------------------------------------------------------------
# Admin: the Add Rewards page
# ------------------------------------------------------------
@app.route('/add_rewards')
def add_rewards():
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='add_rewards'))

    conn = _reward_conn()
    try:
        reward_rows = conn.execute("""
            SELECT r.reward_id, r.name, r.description, r.points_cost, r.stock,
                   r.status, r.created_at, r.needs_phone,
                   (SELECT COUNT(*) FROM reward_claims c
                     WHERE c.reward_id = r.reward_id) AS claimed
              FROM rewards r
             ORDER BY r.reward_id DESC
        """).fetchall()

        claim_rows = conn.execute("""
            SELECT c.claimed_at, c.reward_name, c.points_spent, c.phone,
                   COALESCE(d.donor_name, u.full_name, u.email, 'Unknown donor') AS donor,
                   u.email AS email
              FROM reward_claims c
              LEFT JOIN donors d ON d.donor_id = c.donor_id
              LEFT JOIN users  u ON u.id = d.user_id
             ORDER BY c.claim_id DESC
             LIMIT 100
        """).fetchall()

        total_claims = conn.execute("SELECT COUNT(*) FROM reward_claims").fetchone()[0]
    finally:
        conn.close()

    rewards_list = [{
        "id": r["reward_id"],
        "name": r["name"],
        "description": r["description"] or "",
        "points": r["points_cost"],
        "stock": r["stock"],                       # None = unlimited
        "status": r["status"],
        "needs_phone": bool(r["needs_phone"]),
        "claimed": r["claimed"],
        "date": (r["created_at"] or "")[:10] or "-",
    } for r in reward_rows]

    claims = [{
        "date": (c["claimed_at"] or "")[:16],
        "reward": c["reward_name"],
        "points": c["points_spent"],
        "donor": c["donor"],
        "email": c["email"] or "",
        "phone": format_my_phone(c["phone"]),
    } for c in claim_rows]

    return render_template(
        'admin/add_rewards.html',
        rewards=rewards_list,
        claims=claims,
        total_claims=total_claims,
        active_count=sum(1 for r in rewards_list if r["status"] == "Active"),
        inactive_count=sum(1 for r in rewards_list if r["status"] != "Active"),
        points_per_donation=POINTS_PER_DONATION,
    )


@app.route('/add_rewards/add', methods=['POST'])
def add_reward():
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='add_rewards'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    points_cost = request.form.get('points_cost')
    stock = request.form.get('stock')
    status = request.form.get('status', 'Active')
    needs_phone = 1 if request.form.get('needs_phone') == '1' else 0

    if not name or not points_cost:
        flash("Reward name and points cost are required.", "error")
        return redirect(url_for('add_rewards'))

    stock_val = int(stock) if stock and stock.strip() != '' else None

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO rewards (name, desc, points, stock, status, needs_phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (name, description, int(points_cost), stock_val, status, needs_phone))
        conn.commit()
        flash(f"Reward '{name}' added successfully!", "success")
    except Exception as e:
        flash(f"Error adding reward: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('add_rewards'))


@app.route('/add_rewards/<int:reward_id>/edit', methods=['POST'])
def edit_reward(reward_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='add_rewards'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    points_cost = request.form.get('points_cost')
    stock = request.form.get('stock')
    status = request.form.get('status', 'Active')
    needs_phone = 1 if request.form.get('needs_phone') == '1' else 0

    if not name or not points_cost:
        flash("Reward name and points cost are required.", "error")
        return redirect(url_for('add_rewards'))

    stock_val = int(stock) if stock and stock.strip() != '' else None

    conn = get_db_connection()
    try:
        conn.execute("""
            UPDATE rewards 
            SET name = ?, desc = ?, points = ?, stock = ?, status = ?, needs_phone = ?
            WHERE id = ?
        """, (name, description, int(points_cost), stock_val, status, needs_phone, reward_id))
        conn.commit()
        flash(f"Reward '{name}' updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating reward: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('add_rewards'))


@app.route('/add_rewards/<int:reward_id>/toggle', methods=['POST'])
def admin_toggle_reward(reward_id):
    """Active <-> Inactive. Inactive rewards are hidden from donors."""
    denied = _rw_admin_denied()
    if denied:
        return denied

    conn = _reward_conn()
    try:
        reward = conn.execute("SELECT name, status FROM rewards WHERE reward_id = ?",
                              (reward_id,)).fetchone()
        if not reward:
            return _rw_error("Reward not found.", 404)

        new_status = "Inactive" if reward["status"] == "Active" else "Active"
        conn.execute("UPDATE rewards SET status = ? WHERE reward_id = ?",
                     (new_status, reward_id))
        conn.commit()
        return jsonify(ok=True, status=new_status, message='"%s" is now %s.' % (
            reward["name"], new_status.lower()))
    finally:
        conn.close()


@app.route('/add_rewards/<int:reward_id>/delete', methods=['POST'])
def delete_reward(reward_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='add_rewards'))

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    reward = conn.execute("SELECT * FROM rewards WHERE id = ?", (reward_id,)).fetchone()

    if reward:
        conn.execute("DELETE FROM rewards WHERE id = ?", (reward_id,))
        conn.commit()
        flash(f"Reward '{reward['name']}' deleted successfully.", "success")
    else:
        flash("Reward not found.", "error")

    conn.close()
    return redirect(url_for('add_rewards'))


# ------------------------------------------------------------
# Donor: points + claiming
# ------------------------------------------------------------
def _donor_points(conn, donor_id):
    """(donations, points_claimed, balance). A donor with no row has nothing."""
    if not donor_id:
        return 0, 0, 0
    donations = conn.execute(
        "SELECT COUNT(*) FROM donations WHERE donor_id = ?", (donor_id,)).fetchone()[0]
    spent = conn.execute(
        "SELECT COALESCE(SUM(points_spent), 0) FROM reward_claims WHERE donor_id = ?",
        (donor_id,)).fetchone()[0]
    return donations, spent, donations * POINTS_PER_DONATION - spent


def claim_reward(donor_id, reward_id, phone_raw=None):
    """Returns (True, message) or (False, reason). Every rule is re-checked
    here inside one locked transaction, so a tampered form, a double click or
    two donors racing for the last item cannot overspend points or stock."""
    if not donor_id:
        return False, "Please complete your donor registration before claiming rewards."
    if not reward_id:
        return False, "Please choose a reward."

    conn = _reward_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")

        reward = conn.execute(
            "SELECT * FROM rewards WHERE reward_id = ? AND status = 'Active'",
            (reward_id,)).fetchone()
        if not reward:
            return False, "That reward is no longer available."
        if reward["stock"] is not None and reward["stock"] <= 0:
            return False, "Sorry, this reward is out of stock."

        phone = None
        if reward["needs_phone"]:
            phone = normalize_my_phone(phone_raw)
            if not phone:
                return False, ("Please enter a valid Malaysian mobile number for your TNG "
                               "eWallet (for example 012-345 6789).")

        _, _, balance = _donor_points(conn, donor_id)
        if balance < reward["points_cost"]:
            return False, "You do not have enough points for this reward."

        conn.execute("""
            INSERT INTO reward_claims
                (reward_id, donor_id, reward_name, points_spent, claimed_at, phone)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (reward["reward_id"], donor_id, reward["name"],
              reward["points_cost"], _now(), phone))
        if reward["stock"] is not None:
            conn.execute("UPDATE rewards SET stock = stock - 1 WHERE reward_id = ?",
                         (reward["reward_id"],))
        conn.commit()
        message = 'You claimed "%s" for %d points.' % (reward["name"], reward["points_cost"])
        if phone:
            message += " The admin will transfer it to your TNG number %s." % format_my_phone(phone)
        return True, message

    except sqlite3.Error as e:
        print("Claim failed:", e)
        return False, "Could not claim this reward. Please try again."
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


@app.route('/rewards', methods=['GET', 'POST'])
def rewards():
    if session.get('role') != 'donor':
        return redirect(url_for('login', next='rewards'))

    donor = get_donor_by_email(session.get('user_email'))
    donor_id = donor['donor_id'] if donor else None

    if request.method == 'POST':
        ok, message = claim_reward(donor_id, request.form.get('reward_id', type=int),
                                   request.form.get('phone'))
        flash(message, "success" if ok else "error")
        return redirect(url_for('rewards'))

    conn = _reward_conn()
    try:
        donations, points_claimed, balance = _donor_points(conn, donor_id)

        reward_rows = conn.execute("""
            SELECT reward_id, name, description, points_cost, stock, needs_phone
              FROM rewards WHERE status = 'Active'
             ORDER BY points_cost ASC, reward_id ASC
        """).fetchall()

        history = []
        if donor_id:
            for d in conn.execute(
                    "SELECT collection_date, blood_group FROM donations WHERE donor_id = ?",
                    (donor_id,)):
                history.append({
                    "when": str(d["collection_date"] or "")[:19],
                    "activity": "Blood donation (%s)" % d["blood_group"],
                    "points": POINTS_PER_DONATION,
                })
            for c in conn.execute(
                    "SELECT claimed_at, reward_name, points_spent, phone "
                    "FROM reward_claims WHERE donor_id = ?", (donor_id,)):
                history.append({
                    "when": str(c["claimed_at"] or "")[:19],
                    "activity": "Claimed: %s%s" % (
                        c["reward_name"],
                        " (TNG %s)" % format_my_phone(c["phone"]) if c["phone"] else ""),
                    "points": -c["points_spent"],
                })
        history.sort(key=lambda h: h["when"], reverse=True)
        for h in history:
            h["date"] = h["when"][:10]
    finally:
        conn.close()

    # pre-fill the TNG box with the phone number from the donor's profile
    prefill = ""
    if donor_id:
        pconn = get_db_connection()
        try:
            row = pconn.execute(
                "SELECT phone_number FROM users WHERE email = ?",
                ((session.get('user_email') or '').lower(),)).fetchone()
        finally:
            pconn.close()
        raw = row["phone_number"] if row else ""
        prefill = format_my_phone(normalize_my_phone(raw)) or (raw or "")

    cards = []
    for r in reward_rows:
        cost = r["points_cost"]
        out_of_stock = r["stock"] is not None and r["stock"] <= 0
        cards.append({
            "id": r["reward_id"],
            "name": r["name"],
            "description": r["description"] or "",
            "cost": cost,
            "stock": r["stock"],
            "needs_phone": bool(r["needs_phone"]),
            "out_of_stock": out_of_stock,
            "can_claim": balance >= cost and not out_of_stock,
            "needed": max(cost - balance, 0),
            "percent": min(100, int(max(balance, 0) * 100 / cost)),
        })

    return render_template(
        "donor/rewards.html",
        points=balance,
        total_donations=donations,
        points_claimed=points_claimed,
        phone_prefill=prefill,
        points_per_donation=POINTS_PER_DONATION,
        rewards=cards,
        history=history[:100],
    )
# ---------------------------------------------------------------
# DONOR BOOK APPOINTMENT
#

def _logged_in_donor():
    """
    Returns (donor, redirect_response).
    donor is None when the user is not a logged-in, registered donor,
    and redirect_response then says where to send them.
    """
    if session.get('role') != 'donor':
        return None, redirect(url_for('login', next='make_appointment'))

    donor = get_donor_by_email(session.get('user_email'))
    if not donor:
        flash("Please complete your donor registration before booking an appointment.", "error")
        return None, redirect(url_for('registration'))

    return donor, None


@app.route('/make_appointment', methods=['GET'])
def make_appointment():
    donor, response = _logged_in_donor()
    if response:
        return response

    return render_template(
        "donor/make_appointment.html",
        events=get_bookable_events(donor['donor_id']),
        my_appointments=get_donor_upcoming_appointments(donor['donor_id'])
    )




@app.route('/book_appointment', methods=['POST'])
def book_appointment():
    donor, response = _logged_in_donor()
    if response:
        return response

    event_id = request.form.get('event_id', type=int)
    appt_time = (request.form.get('appointment_time') or '').strip()
    notes = (request.form.get('notes') or '').strip()[:300]

    if not event_id or not appt_time:
        flash("Please select an event and an appointment time.", "error")
    else:
        ok, message = create_appointment(donor['donor_id'], event_id, appt_time, notes)
        flash(message, "success" if ok else "error")

    return redirect(url_for('make_appointment'))

@app.route('/cancel_appointment', methods=['POST'])
def cancel_appointment():
    donor, response = _logged_in_donor()
    if response:
        return response

    appointment_id = request.form.get('appointment_id', type=int)

    if appointment_id and cancel_donor_appointment(appointment_id, donor['donor_id']):
        flash("Appointment cancelled.", "success")
    else:
        flash("Appointment not found.", "error")

    return redirect(url_for('make_appointment'))

# ---------- helpers ----------
def _rep_clause(column, from_date, to_date):
    """(' AND date(col) >= date(?) ...', [params]) for an optional date range."""
    sql, params = "", []
    if from_date:
        sql += f" AND date({column}) >= date(?)"
        params.append(from_date)
    if to_date:
        sql += f" AND date({column}) <= date(?)"
        params.append(to_date)
    return sql, params


def _rep_filters():
    from_date = (request.args.get('from_date') or '').strip()
    to_date = (request.args.get('to_date') or '').strip()
    return from_date, to_date


def _rep_columns(conn, table):
    return {r['name'] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------- the one place every number is calculated ----------
def collect_report_data(conn, from_date, to_date):
    d_clause, d_params = _rep_clause('collection_date', from_date, to_date)
    r_clause, r_params = _rep_clause('request_date', from_date, to_date)

    # 1. Stock (always current, not date-filtered)
    stock_rows = conn.execute("""
        SELECT blood_group, COUNT(*) AS units FROM donations
        WHERE status = 'Available' AND date(expiry_date) >= date('now')
        GROUP BY blood_group
    """).fetchall()
    stock = {r['blood_group']: r['units'] for r in stock_rows}
    stock_units = [stock.get(t, 0) for t in BLOOD_TYPES]

    critical = [t for t in BLOOD_TYPES if stock.get(t, 0) <= MIN_THRESHOLD * 0.5]
    low = [t for t in BLOOD_TYPES
           if MIN_THRESHOLD * 0.5 < stock.get(t, 0) < MIN_THRESHOLD]
    below = critical + low

    def level(t):
        return "Critical" if t in critical else ("Low" if t in low else "Sufficient")

    # 2. Low stock alerts (current stock vs MIN_THRESHOLD)
    alert_counts = [stock.get(t, 0) for t in below]
    most_low_type = min(BLOOD_TYPES, key=lambda t: stock.get(t, 0)) if below else '-'

    # 3. Requests
    req = {r['status']: r['n'] for r in conn.execute(
        f"SELECT status, COUNT(*) AS n FROM blood_requests WHERE 1=1 {r_clause} GROUP BY status",
        r_params).fetchall()}
    req_by_type = conn.execute(f"""
        SELECT blood_group, COUNT(*) AS n, COALESCE(SUM(units_requested), 0) AS units
        FROM blood_requests WHERE 1=1 {r_clause}
        GROUP BY blood_group ORDER BY blood_group
    """, r_params).fetchall()

    # 5. Donations
    total_donations = conn.execute(
        f"SELECT COUNT(*) FROM donations WHERE 1=1 {d_clause}", d_params).fetchone()[0]
    donations_this_month = conn.execute("""
        SELECT COUNT(*) FROM donations
        WHERE strftime('%Y-%m', collection_date) = strftime('%Y-%m', 'now')
    """).fetchone()[0]
    month_rows = conn.execute(f"""
        SELECT strftime('%Y-%m', collection_date) AS m, COUNT(*) AS n
        FROM donations WHERE 1=1 {d_clause}
        GROUP BY m ORDER BY m DESC LIMIT 6
    """, d_params).fetchall()[::-1]
    type_rows = conn.execute(f"""
        SELECT blood_group, COUNT(*) AS n FROM donations
        WHERE 1=1 {d_clause} GROUP BY blood_group
    """, d_params).fetchall()
    by_type = {r['blood_group']: r['n'] for r in type_rows}
    donation_type_counts = [by_type.get(t, 0) for t in BLOOD_TYPES]
    top_donated_type = max(by_type, key=by_type.get) if by_type else '-'

    # 4. Users - Inactive = an admin deactivated the donor's account
    ucols = _rep_columns(conn, 'users')
    status_expr = "LOWER(TRIM(COALESCE(u.status, '')))" if 'status' in ucols else "''"
    total_donors = conn.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    inactive_users = conn.execute(f"""
        SELECT COUNT(*) FROM donors d JOIN users u ON u.id = d.user_id
        WHERE {status_expr} = 'inactive'
    """).fetchone()[0]
    active_users = total_donors - inactive_users

    # New registrations needs users.created_at to be filled in at sign-up
    new_registrations = "N/A"
    if 'created_at' in ucols:
        has_dates = conn.execute("""
            SELECT COUNT(*) FROM donors d JOIN users u ON u.id = d.user_id
            WHERE u.created_at IS NOT NULL""").fetchone()[0]
        if has_dates:
            u_clause, u_params = _rep_clause('u.created_at', from_date, to_date)
            new_registrations = conn.execute(f"""
                SELECT COUNT(*) FROM donors d JOIN users u ON u.id = d.user_id
                WHERE u.created_at IS NOT NULL {u_clause}""", u_params).fetchone()[0]

    created_expr = "COALESCE(u.created_at, '-')" if 'created_at' in ucols else "'-'"
    status_show = "COALESCE(NULLIF(TRIM(u.status), ''), 'Active')" if 'status' in ucols else "'Active'"
    donor_list = conn.execute(f"""
        SELECT COALESCE(d.donor_name, u.full_name, '-') AS name, u.email,
               d.blood_type, {status_show} AS status, {created_expr} AS created
        FROM donors d JOIN users u ON u.id = d.user_id
        ORDER BY d.donor_id DESC
    """).fetchall()

    return dict(
        from_date=from_date, to_date=to_date,
        # stock
        total_units=sum(stock_units),
        sufficient_count=len(BLOOD_TYPES) - len(below),
        low_count=len(low), critical_count=len(critical),
        stock_labels=BLOOD_TYPES, stock_units=stock_units,
        # alerts
        alerts_triggered=len(below), alerts_notified="N/A",
        most_low_type=most_low_type,
        alert_labels=below, alert_counts=alert_counts,
        # requests
        total_requests=sum(req.values()),
        approved_requests=req.get('Approved', 0),
        rejected_requests=req.get('Rejected', 0),
        pending_requests=req.get('Pending', 0),
        auto_closed_requests=req.get('Auto-Closed', 0),
        # donations
        total_donations=total_donations,
        donations_this_month=donations_this_month,
        top_donated_type=top_donated_type,
        donation_months=[r['m'] for r in month_rows],
        donation_counts=[r['n'] for r in month_rows],
        donation_type_labels=BLOOD_TYPES,
        donation_type_counts=donation_type_counts,
        # users
        total_donors=total_donors, new_registrations=new_registrations,
        active_users=active_users, inactive_users=inactive_users,
        # extra detail rows used only by the PDFs
        _stock_detail=[(t, stock.get(t, 0), level(t)) for t in BLOOD_TYPES],
        _alert_detail=[(t, stock.get(t, 0), level(t)) for t in below],
        _request_detail=[(r['blood_group'], r['n'], r['units']) for r in req_by_type],
        _donation_detail=[(t, by_type.get(t, 0)) for t in BLOOD_TYPES],
        _donor_detail=[(r['name'], r['email'], r['blood_type'], r['status'], r['created'])
                       for r in donor_list],
    )


def _load_report():
    from_date, to_date = _rep_filters()
    conn = get_db_connection()
    try:
        return collect_report_data(conn, from_date, to_date)
    finally:
        conn.close()


# ---------- the page ----------
@app.route('/admin_report', methods=['GET', 'POST'])
def admin_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template("admin/admin_report.html", **_load_report())


# ---------- PDF builder ----------
def _build_pdf(title, summary, headers, rows, filename, from_date='', to_date=''):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    centre = lambda name: ParagraphStyle(name, parent=styles['Normal'], alignment=TA_CENTER)
    elements = [
        Paragraph(title, ParagraphStyle(
            'ReportTitle', parent=styles['Title'], fontSize=20, leading=22,
            alignment=TA_CENTER, spaceAfter=2, textColor=colors.black)),
        Paragraph(("Period: %s to %s" % (from_date or 'start', to_date or 'today'))
                  if (from_date or to_date) else "Period: All time", centre('Period')),
        Paragraph("Generated: " + datetime.now().strftime('%Y-%m-%d %H:%M'), centre('Gen')),
        Spacer(1, 30),
    ]

    summary_table = Table([[s[0] for s in summary], [s[1] for s in summary]])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.darkblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements += [summary_table, Spacer(1, 30),
                 Paragraph("Details", styles['Heading2']), Spacer(1, 10)]

    if rows:
        detail = Table([headers] + [list(r) for r in rows], repeatRows=1)
        detail.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(detail)
    else:
        elements.append(Paragraph("No records found for this period.", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=filename, mimetype='application/pdf')


# ---------- the five PDF exports ----------
@app.route('/download_stock_report')
def download_stock_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    d = _load_report()
    return _build_pdf(
        "Blood Stock Report",
        [("Total Units", d["total_units"]), ("Sufficient Types", d["sufficient_count"]),
         ("Low Types", d["low_count"]), ("Critical Types", d["critical_count"])],
        ["Blood Type", "Units", "Status"], d["_stock_detail"],
        "Blood_Stock_Report.pdf")


@app.route('/download_alert_report')
def download_alert_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    d = _load_report()
    return _build_pdf(
        "Low Stock Alert Report",
        [("Alerts Triggered", d["alerts_triggered"]),
         ("Staff Notified", d["alerts_notified"]),
         ("Lowest Stock Type", d["most_low_type"])],
        ["Blood Type", "Units in Stock", "Level"], d["_alert_detail"],
        "Low_Stock_Alert_Report.pdf")


@app.route('/download_request_report')
def download_request_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    d = _load_report()
    return _build_pdf(
        "Blood Request Report",
        [("Total", d["total_requests"]), ("Approved", d["approved_requests"]),
         ("Rejected", d["rejected_requests"]), ("Pending", d["pending_requests"]),
         ("Auto-Closed", d["auto_closed_requests"])],
        ["Blood Type", "Requests", "Units Requested"], d["_request_detail"],
        "Blood_Request_Report.pdf", d["from_date"], d["to_date"])


@app.route('/download_donation_report')
def download_donation_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    d = _load_report()
    return _build_pdf(
        "Donation Report",
        [("Total Donations", d["total_donations"]),
         ("This Month", d["donations_this_month"]),
         ("Top Donated Type", d["top_donated_type"])],
        ["Blood Type", "Donations"], d["_donation_detail"],
        "Donation_Report.pdf", d["from_date"], d["to_date"])


@app.route('/download_user_report')
def download_user_report():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    d = _load_report()
    return _build_pdf(
        "User Report",
        [("Registered Donors", d["total_donors"]),
         ("New Registrations", d["new_registrations"]),
         ("Active Users", d["active_users"]),
         ("Inactive Users", d["inactive_users"])],
        ["Name", "Email", "Blood Type", "Status", "Registered"], d["_donor_detail"],
        "User_Report.pdf", d["from_date"], d["to_date"])


STAFF_ROLES = ("Hospital Staff", "Blood Bank Staff")
# Value stored in users.role (matches your existing 'donor' / 'blood_bank_staff')
ROLE_DB = {"Hospital Staff": "hospital_staff", "Blood Bank Staff": "blood_bank_staff"}
STATUSES = ("Active", "Inactive")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


# ============================================================
# Schema additions (safe to run every time)
#   users.status               'Active' / 'Inactive'  (default Active)
#   users.organisation         hospital / blood bank name (staff)
#   users.created_at           date the account was created
#   users.must_change_password 1 = must change password at next login
# ============================================================
def ensure_user_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'")
    if "organisation" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN organisation TEXT")
    if "created_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    if "must_change_password" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    repair_user_foreign_keys(conn)


def repair_user_foreign_keys(conn):
    """
    Your Admin and Announcements tables were created with
    REFERENCES Users(user_id), but the users table's key is `id`.
    With foreign keys ON, SQLite then refuses to delete any user
    ("foreign key mismatch"). This rebuilds those two tables, once,
    pointing at users(id). Existing rows are kept.
    """

    def is_broken(table):
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            if fk["table"].lower() == "users" and fk["to"] and fk["to"].lower() == "user_id":
                return True
        return False

    existing = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    jobs = {
        "Admin": """
            CREATE TABLE Admin_new (
                admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )""",
        "Announcements": """
            CREATE TABLE Announcements_new (
                announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )""",
    }

    todo = [t for t in jobs if t in existing and is_broken(t)]
    if not todo:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for table in todo:
            conn.execute(jobs[table])
            conn.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def get_users_conn():
    conn = get_db_connection()
    ensure_user_columns(conn)
    return conn


# ============================================================
# Helpers
# ============================================================
def _norm_role(role):
    return (role or "").strip().lower().replace("_", " ")


def _display_role(role):
    n = _norm_role(role)
    return {
        "donor": "Donor",
        "hospital staff": "Hospital Staff",
        "blood bank staff": "Blood Bank Staff",
    }.get(n, (role or "").strip().title())


def _is_donor(role):
    return _norm_role(role) == "donor"


def _is_admin(role):
    return _norm_role(role) == "admin"


def _json_error(message, code=400):
    return jsonify(ok=False, error=message), code


def _admin_only_json():
    """Returns an error response if the caller is not an admin, else None."""
    if session.get('role') != 'admin':
        return _json_error("Your session has expired. Please log in again.", 403)
    return None


def get_all_users(conn):
    """Every non-admin user, shaped for the Manage Users template."""
    rows = conn.execute("""
        SELECT u.id, u.full_name, u.email, u.phone_number, u.role,
               COALESCE(u.status, 'Active') AS status,
               u.organisation, u.created_at,
               d.donor_name, d.blood_type
        FROM users u
        LEFT JOIN donors d ON d.user_id = u.id
        ORDER BY u.id DESC
    """).fetchall()

    users = []
    for r in rows:
        if _is_admin(r["role"]):
            continue
        donor = _is_donor(r["role"])
        name = (r["full_name"] or r["donor_name"] or r["email"] or "?").strip() or "?"
        users.append({
            "id": r["id"],
            "name": name,
            "email": r["email"],
            "phone": r["phone_number"] or "",
            "role": _display_role(r["role"]),
            "org": (r["blood_type"] or "-") if donor else (r["organisation"] or "-"),
            "status": r["status"] if r["status"] in STATUSES else "Active",
            "date": (r["created_at"] or "")[:10] or "-",
        })
    return users


def _get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _read_staff_form(conn, user_id=None, password_required=True):
    """Validate the add/edit form. Returns (data, error_message)."""
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "email": f.get("email", "").strip().lower(),
        "phone": f.get("phone", "").strip(),
        "role": f.get("role", "").strip(),
        "org": f.get("organisation", "").strip(),
        "status": f.get("status", "Active").strip() or "Active",
        "password": f.get("password", ""),
    }

    if not data["name"]:
        return None, "Full name is required."
    if not EMAIL_RE.match(data["email"]):
        return None, "Please enter a valid email address."
    if not data["phone"]:
        return None, "Phone number is required."
    if data["role"] not in STAFF_ROLES:
        return None, "Please choose a valid role."
    if not data["org"]:
        return None, "Hospital / blood bank name is required."
    if data["status"] not in STATUSES:
        return None, "Invalid status."

    if password_required or data["password"]:
        if len(data["password"]) < 8:
            return None, "Password must be at least 8 characters."

    dup_email = conn.execute(
        "SELECT 1 FROM users WHERE email = ? AND id != ?",
        (data["email"], user_id or 0)).fetchone()
    if dup_email:
        return None, "That email is already used by another account."

    dup_phone = conn.execute(
        "SELECT 1 FROM users WHERE phone_number = ? AND id != ?",
        (data["phone"], user_id or 0)).fetchone()
    if dup_phone:
        return None, "That phone number is already used by another account."

    return data, None


# ============================================================
# Page
# ============================================================
@app.route('/manage_users')
def manage_users():


    conn = get_users_conn()
    users = get_all_users(conn)
    conn.close()

    return render_template('admin/manage_users.html', users=users)


# ============================================================
# Add staff
# ============================================================
@app.route('/manage_users/add', methods=['POST'])
def add_staff():
    if session.get('role') != 'admin':
        return redirect(url_for('login', next="manage_users"))

    name = request.form.get('name','').strip()
    email = request.form.get('email', '').strip()
    role = request.form.get('role', '').strip()
    org = request.form.get('organisation', '').strip()
    phone = request.form.get('phone_number', '').strip()

    if not name or not email or not role:
        flash("Please fill in all required fields!", "error")
        return redirect(url_for("manage_users"))

    temporary_password = secrets.token_urlsafe(9)

    success = register_staff_user(name, email, phone,role, temporary_password)

    if not success:
        flash("Email is already registered!", "error")
        return redirect(url_for("manage_users"))

    email_sent = send_credentials_email(email, name, temporary_password)

    if email_sent:
        flash("Staff account created successfully!", "success")
    else:
        flash("Accounted created, failed to send credentials. Please contact IT department!", "error")

    return redirect(url_for("manage_users"))


# ============================================================
# Edit staff
# ============================================================
@app.route('/manage_users/<int:user_id>/edit', methods=['POST'])
def admin_edit_user(user_id):
    denied = _admin_only_json()
    if denied:
        return denied

    conn = get_users_conn()
    try:
        user = _get_user(conn, user_id)
        if not user:
            return _json_error("User not found.", 404)
        if _is_donor(user["role"]) or _is_admin(user["role"]):
            return _json_error("Only staff accounts can be edited here.", 403)

        data, error = _read_staff_form(conn, user_id=user_id, password_required=False)
        if error:
            return _json_error(error)

        # Don't let the admin lock themselves out
        if data["status"] == "Inactive" and str(user_id) == str(session.get('user_id')):
            return _json_error("You cannot deactivate your own account.")

        conn.execute("""
            UPDATE users
               SET full_name = ?, email = ?, phone_number = ?, role = ?,
                   organisation = ?, status = ?
             WHERE id = ?
        """, (data["name"], data["email"], data["phone"], ROLE_DB[data["role"]],
              data["org"], data["status"], user_id))

        if data["password"]:
            conn.execute(
                "UPDATE users SET hashed_password = ?, must_change_password = 1 WHERE id = ?",
                (_hash_password(data["password"]), user_id))

        conn.commit()
        return jsonify(ok=True)

    except sqlite3.IntegrityError:
        return _json_error("That email or phone number is already in use.")
    finally:
        conn.close()


# ============================================================
# Activate / deactivate (staff and donors)
# ============================================================
@app.route('/manage_users/<int:user_id>/toggle', methods=['POST'])
def toggle_user_status(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='manage_users'))

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if user:
        current_status = user['status'] if user['status'] else 'Active'
        new_status = 'Inactive' if current_status == 'Active' else 'Active'

        conn.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
        conn.commit()

        name = user['full_name'] or user['email']
        session['success_toast'] = f"User {name} has been {new_status.lower()}."

    conn.close()
    return redirect(url_for('manage_users'))


# ============================================================
# Reset password (staff)
# ============================================================
@app.route('/manage_users/<int:user_id>/reset-password', methods=['POST'])
def admin_reset_password(user_id):
    denied = _admin_only_json()
    if denied:
        return denied

    conn = get_users_conn()
    try:
        user = _get_user(conn, user_id)
        if not user:
            return _json_error("User not found.", 404)
        if _is_donor(user["role"]) or _is_admin(user["role"]):
            return _json_error("Only staff passwords can be reset here.", 403)

        temp = "".join(secrets.choice(PASSWORD_CHARS) for _ in range(10))
        conn.execute(
            "UPDATE users SET hashed_password = ?, must_change_password = 1 WHERE id = ?",
            (_hash_password(temp), user_id))
        conn.commit()
        return jsonify(ok=True, temp_password=temp)
    finally:
        conn.close()


# ============================================================
# Delete staff
# ============================================================
@app.route('/manage_users/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    denied = _admin_only_json()
    if denied:
        return denied

    conn = get_users_conn()
    try:
        user = _get_user(conn, user_id)
        if not user:
            return _json_error("User not found.", 404)
        if _is_donor(user["role"]) or _is_admin(user["role"]):
            return _json_error("Only staff accounts can be deleted here.", 403)
        if str(user_id) == str(session.get('user_id')):
            return _json_error("You cannot delete your own account.")

        # blood_requests.staff_id has ON DELETE CASCADE, so deleting a staff
        # member would silently wipe their requests and distort the reports.
        used = conn.execute(
            "SELECT COUNT(*) FROM blood_requests WHERE staff_id = ?", (user_id,)
        ).fetchone()[0]
        if used:
            return _json_error(
                "This staff member has %d blood request(s) on record. "
                "Deactivate the account instead to keep the history." % used)

        ann_cols = {r["name"] for r in conn.execute("PRAGMA table_info(announcements)").fetchall()}
        posted = 0
        if "user_id" in ann_cols:
            posted = conn.execute(
                "SELECT COUNT(*) FROM announcements WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        if posted:
            return _json_error(
                "This account has posted %d announcement(s). "
                "Deactivate the account instead to keep them." % posted)

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return jsonify(ok=True)

    except sqlite3.Error as e:
        conn.rollback()
        return _json_error("Could not delete this account: %s" % e, 500)
    finally:
        conn.close()

@app.route("/blood_bank_staff_dashboard", methods=["GET", "POST"])
def blood_bank_staff_dashboard():
    return render_template("blood_bank_staff/blood_bank_staff_dashboard.html")

@app.route('/hospital_staff/blood_request', methods=['GET', 'POST'])
def hospital_staff_blood_request():
    if request.method == 'POST':
        hospital_name = request.form.get('hospital_name', '').strip()
        blood_group = request.form.get('blood_type', '').strip()
        quantity = request.form.get('quantity', '').strip()
        reason = request.form.get('reason', '').strip()

        # Validate the submitted information
        if not hospital_name or not blood_group or not quantity or not reason:
            return render_template(
                'hospital_staff/hospital_staff_blood_request.html',
                error="Please fill in all fields."
            )

        try:
            quantity = int(quantity)
            if quantity < 1:
                raise ValueError
        except ValueError:
            return render_template(
                'hospital_staff/hospital_staff_blood_request.html',
                error="Quantity must be at least 1 unit."
            )

        conn = get_db_connection()

        try:
            conn.execute("""
                INSERT INTO blood_requests (
                    hospital_name,
                    blood_group,
                    units_requested,
                    reason,
                    status
                )
                VALUES (?, ?, ?, ?, 'Pending')
            """, (hospital_name, blood_group, quantity, reason))

            conn.commit()

        finally:
            conn.close()

        return redirect(url_for('view_blood_request'))

    return render_template(
        'hospital_staff/hospital_staff_blood_request.html'
    )


@app.route("/manage_blood_stock", methods=["GET", "POST"])
def manage_blood_stock():
    conn = get_db_connection()

    try:
        rows = conn.execute("""
            SELECT
                blood_group,
                COUNT(*) AS quantity,
                MAX(collection_date) AS last_updated
            FROM donations
            WHERE status = 'Available'
              AND date(expiry_date) >= date('now')
            GROUP BY blood_group
        """).fetchall()

    finally:
        conn.close()

    stock = {row["blood_group"]: row for row in rows}

    blood_stocks = []

    for blood_type in BLOOD_TYPES:
        row = stock.get(blood_type)
        quantity = row["quantity"] if row else 0

        if quantity <= MIN_THRESHOLD * 0.5:
            status = "Critical"
        elif quantity < MIN_THRESHOLD:
            status = "Low"
        else:
            status = "Sufficient"

        blood_stocks.append({
            "blood_type": blood_type,
            "quantity": quantity,
            "last_updated": (
                row["last_updated"][:10]
                if row and row["last_updated"]
                else "No donations yet"
            ),
            "status": status
        })

    return render_template(
        "blood_bank_staff/manage_blood_stock.html",
        blood_stocks=blood_stocks
    )



@app.route("/get_donor_by_ic", methods=["GET"])
def get_donor_by_ic():
    ic = request.args.get("ic", "").strip()

    if not ic:
        return jsonify({"success": False})

    conn = get_db_connection()

    try:
        donor = conn.execute("""
            SELECT d.donor_id, d.blood_type, u.full_name
            FROM donors d
            JOIN users u ON d.user_id = u.id
            WHERE d.ic = ?
        """, (ic,)).fetchone()

        if donor:
            return jsonify({
                "success": True,
                "donor_id": donor["donor_id"],
                "full_name": donor["full_name"],
                "blood_type": donor["blood_type"]
            })

        return jsonify({"success": False})

    finally:
        conn.close()


@app.route("/record_donation", methods=["GET", "POST"])
def record_donation():
    donor = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "search":
            ic = request.form.get("ic").strip()
            conn = get_db_connection()
            donor = conn.execute('''
                SELECT d.*, u.full_name, u.phone_number
                FROM donors d
                JOIN users u ON d.user_id = u.id
                WHERE d.ic = ?
            ''', (ic,)).fetchone()
            conn.close()

            if not donor:
                return render_template("blood_bank_staff/record_donation.html", error_popup="No registered account with this IC number!")

        elif action == "record":
            donor_id = request.form.get("donor_id")
            blood_group = request.form.get("blood_group")
            volume_blood = request.form.get("volume_blood")
            expiry_date = request.form.get("expiry_date")
            status = "Available"

            conn = get_db_connection()
            conn.execute('''
                INSERT INTO donations (donor_id, blood_group, volume_blood, expiry_date, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (donor_id, blood_group, volume_blood, expiry_date, status))
            conn.commit()
            conn.close()

            return render_template("blood_bank_staff/record_donation.html", error_popup="Donation successfully recorded!")

    return render_template("blood_bank_staff/record_donation.html")


@app.route("/view_appointment")
def view_appointment():
    conn = get_db_connection()

    try:
        appointments = conn.execute("""
            SELECT
                a.appointment_id,
                u.full_name AS donor_name,
                a.appointment_date,
                a.appointment_time,
                a.status
            FROM appointments a
            JOIN donors d ON a.donor_id = d.donor_id
            JOIN users u ON d.user_id = u.id
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """).fetchall()

    finally:
        conn.close()

    return render_template(
        "blood_bank_staff/view_appointment.html",
        appointments=appointments
    )


if __name__ == "__main__":
    from database import init_db, DB_PATH

    init_db()
    print("Using database:", DB_PATH)

    app.run(debug=True, port=5000)