import os
import smtplib
import sqlite3
from datetime import datetime, date

import bcrypt
from email.message import EmailMessage
from flask import Flask, render_template, url_for, redirect, session, request, flash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from database import (get_user_by_email, get_all_events,
                      add_event, update_event, delete_event, get_donor_by_email, create_appointment,
                      get_donor_upcoming_appointments, get_bookable_events, cancel_donor_appointment, get_db_connection)
import random

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a-very-secure-permanent-fallback-key')

oauth = OAuth(app)




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
                role
            )
            VALUES (?, ?, ?, ?)
            """,
            (email, email, hashed_password, "donor")
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

        print("Admin email configured:", bool(admin_email))
        print("Admin password configured:", bool(admin_password))
        print("Submitted email matches:", email == admin_email)

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
            return render_template("general/check_email.html", error_popup="Admin password can't be reset here! Contact IT department!")

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
    #verification otp bypass for testing
    print(f"This is the test otp: {otp}")
    message = EmailMessage()
    message.set_content(f"Your verification code is: {otp} \nThis code will expire shortly. Do not share it with anyone. ")
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


@app.route('/quiz', methods=['GET','POST'])
def quiz():
    return render_template("general/quiz.html")


@app.route('/donor_quiz', methods=['GET','POST'])
def donor_quiz():
    return render_template("donor/donor_quiz.html")


@app.route('/rewards', methods=['GET','POST'])
def rewards():
    return render_template("donor/rewards.html")

@app.route('/donor_faq', methods=['GET','POST'])
def donor_faq():
    return render_template("donor/donor_faq.html")

@app.route('/donation_history', methods=['GET','POST'])
def donation_history():
    return render_template("donor/donation_history.html")

@app.route('/donor_announcements', methods=['GET','POST'])
def donor_announcements():
    return render_template("donor/donor_announcements.html")

@app.route('/blood_request', methods=['GET','POST'])
def blood_request():
    return render_template("blood_bank_staff/blood_request.html")

@app.route('/view_blood_request', methods=['GET','POST'])
def view_blood_request():
    return render_template("hospital_staff/view_blood_request.html")

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
                (full_name, email, phone_number, hashed_password, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                full_name,
                email,
                phone_number,
                hashed_password,
                normalized_role
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


@app.route('/create_account', methods=['GET','POST'])
def create_account():
    if request.method == 'POST':
        full_name = request.form.get('name')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        role = request.form.get('role')
        password = request.form.get('temp-password')

        if not full_name or not email or not role or not password:
            return render_template('admin/create_account.html', error_popup="Please enter all the details!")

        db_success = register_staff_user(full_name, email, phone_number, role, password)

        if not db_success:
            return render_template('admin/create_account.html', error_popup="Email already registered!")

        email_sent = send_credentials_email(email, full_name, password)

        if email_sent:
            return render_template('admin/create_account.html', success_popup="Account creation successful!")
        else:
            return render_template('admin/create_account.html', error_popup="Account creation unsuccessful!")
    return render_template("admin/create_account.html")


@app.route('/faq', methods=['GET','POST'])
def faq():
    return render_template("general/faq.html")

@app.route('/hospital_staff_dashboard', methods=['GET', 'POST'])
def hospital_staff_dashboard():
    return render_template("hospital_staff/hospital_staff_dashboard.html")

@app.route('/manage_user', methods=['GET','POST'])
def manage_user():
    return render_template("admin/manage_user.html")

@app.route('/view_blood_info', methods=['GET','POST'])
def view_blood_info():
    return render_template("admin/view_blood_info.html")

@app.route('/admin_report', methods=['GET','POST'])
def admin_report():
    return render_template("admin/admin_report.html")

@app.route('/staff_report', methods=['GET','POST'])
def staff_report():
    return render_template("blood_bank_staff/staff_report.html")

@app.route('/make_announcement', methods=['GET', 'POST'])
def make_announcement():
    return render_template('blood_bank_staff/make_announcement.html')

@app.route("/donor_dashboard", methods=['GET','POST'])
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

@app.route("/blood_bank_staff_dashboard", methods=["GET", "POST"])
def blood_bank_staff_dashboard():
    return render_template("blood_bank_staff/blood_bank_staff_dashboard.html")

@app.route('/hospital_staff/blood_request', methods=['GET', 'POST'])
def hospital_staff_blood_request():
    if request.method == 'POST':

        #The existing code to save the blood request to the database goes here.

        return redirect(url_for('view_blood_request'))

    return render_template('hospital_staff/hospital_staff_blood_request.html')

@app.route("/manage_blood_stock", methods=["GET", "POST"])
def manage_blood_stock():
    return render_template("blood_bank_staff/manage_blood_stock.html")

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

@app.route("/view_appointment", methods=["GET", "POST"])
def view_appointment():
    return render_template("blood_bank_staff/view_appointment.html")

@app.route("/admin_dashboard")
def admin_dashboard():
    return render_template("admin/admin_dashboard.html")

@app.route("/index")
def logout():
    session.clear()
    return render_template("general/index.html")


def _clean_event_form(form, is_new):
    """Read and validate the event form. Returns (data_tuple, error_message)."""
    title   = (form.get('title') or '').strip()
    ev_date = (form.get('date') or '').strip()
    start   = (form.get('start') or '').strip()
    end     = (form.get('end') or '').strip()
    place   = (form.get('place') or '').strip()
    address = (form.get('address') or '').strip()
    notes   = (form.get('notes') or '').strip()

    if not (title and ev_date and start and end and place and address):
        return None, "Please fill in all the required fields."

    if len(title) > 120 or len(place) > 120 or len(address) > 200 or len(notes) > 500:
        return None, "One of the fields is too long."

    try:
        parsed_date = datetime.strptime(ev_date, "%Y-%m-%d").date()
        t_start = datetime.strptime(start, "%H:%M")
        t_end   = datetime.strptime(end, "%H:%M")
    except ValueError:
        return None, "Invalid date or time."

    if t_end <= t_start:
        return None, "End time must be after the start time."

    if is_new and parsed_date < date.today():
        return None, "New events cannot be set in the past."

    return (title, ev_date, start, end, place, address, notes), None


@app.route('/manage_events', methods=['GET', 'POST'])
def manage_events():
    # Only the admin can see or change events
    if session.get('role') != 'admin':
        return redirect(url_for('login', next='manage_events'))

    if request.method == 'POST':
        action   = request.form.get('action')
        event_id = request.form.get('event_id', type=int)

        if action == 'delete':
            if event_id and delete_event(event_id):
                flash("Event deleted.", "success")
            else:
                flash("Event not found.", "error")

        elif action in ('add', 'edit'):
            data, error = _clean_event_form(request.form, is_new=(action == 'add'))

            if error:
                flash(error, "error")
            elif action == 'add':
                add_event(*data)
                flash("Event added.", "success")
            elif event_id and update_event(event_id, *data):
                flash("Event updated.", "success")
            else:
                flash("Event not found.", "error")

        # Post/Redirect/Get: refreshing the page will not re-submit the form
        return redirect(url_for('manage_events'))

    return render_template("admin/manage_events.html", events=get_all_events())

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

    event_id  = request.form.get('event_id', type=int)
    appt_time = (request.form.get('appointment_time') or '').strip()
    notes     = (request.form.get('notes') or '').strip()[:300]

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

if __name__ == "__main__":
    from database import init_db, DB_PATH

    init_db()
    print("Using database:", DB_PATH)

    app.run(debug=True, port=5000)
