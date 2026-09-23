import os
import smtplib
import sqlite3
import bcrypt
from email.message import EmailMessage
from flask import Flask, render_template, url_for, redirect, session, request, flash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from database import get_user_by_email
import random

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a-very-secure-permanent-fallback-key')

oauth = OAuth(app)

def register_user(username, plain_password):
    password_bytes = plain_password.encode('utf-8')
    salt=bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password_bytes, salt)

    conn = sqlite3.connect('bloodbank.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, hashed_password, role) VALUES (?,?,?)",
            (username, hashed_password.decode('utf-8'), 'donor')
        )
        conn.commit()
        print("User registered successful!")
    except sqlite3.IntegrityError:
        print("Username already exists.")
        return False
    except Exception as e:
        return False
    finally:
        conn.close()

def get_db_connection():
    conn = sqlite3.connect('bloodbank.db')
    conn.row_factory = sqlite3.Row
    return conn

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
        email = request.form.get('email')
        password = request.form.get('password')

        admin_email = os.getenv('ADMIN_EMAIL')
        admin_password = os.getenv('ADMIN_PASSWORD')

        if email == admin_email and password == admin_password:
            otp = str(random.randint(100000, 999999))

            session['user_email'] = email
            session['pending_otp'] = str(otp)
            session['user_name'] = "Admin"
            session['pending_role'] = 'admin'
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
    password_bytes = new_password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_new_password = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

    conn = sqlite3.connect('bloodbank.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET hashed_password =? WHERE email = ?", (hashed_new_password, email)
    )
    conn.commit()
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
    message = EmailMessage()
    message.set_content(f"Your verification code is: {otp} \nThis code will expire shortly. Do not share it with anyone. ")
    message['Subject'] = "Blood Bank Management System Verification Code"
    message['From'] = os.getenv('MAIL_USERNAME')
    message['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(os.getenv('MAIL_USERNAME'), os.getenv('MAIL_PASSWORD'))
            server.send_message(message)
        print(f"This is the test otp: {otp}")
        return True
    except Exception as e:
        return False


@app.route("/signup", methods=['GET', 'POST'])
def signup():
    session.pop('is_reset_flow', None)
    next_page = request.args.get('next') or request.form.get('next')

    if request.method == "POST":
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if confirm_password != password:
            return render_template("general/signup.html", error_popup="Passwords do not match!")

        otp = str(random.randint(100000, 999999))

        session['pending_email'] = email
        session['pending_password'] = password
        session['pending_otp'] = otp
        if next_page:
            session['next_page'] = next_page

        send_otp_email(email, otp)
        return render_template("general/verification.html")

    return render_template("general/signup.html", next=next_page)


@app.route('/verification', methods=['POST'])
def verification():
    entered_otp = request.form.get('otp')
    generated_otp = session.get('pending_otp')

    if entered_otp == generated_otp:
        session.pop('pending_otp', None)

        if session.get('is_reset_flow'):
            session['otp_verified'] = True
            return redirect(url_for('reset_password'))

        pending_password = session.pop('pending_password', None)
        email = session.pop('pending_email', None)
        name = session.pop('pending_name', 'User')

        # Normalize incoming role string
        raw_role = session.pop('pending_role', 'donor')
        role = str(raw_role).strip().lower().replace(' ', '_')

        if pending_password and email:
            register_user(email, pending_password)

        session['user_email'] = email
        session['user_name'] = name
        session['role'] = role

        target_page = session.pop('next_page', None)
        if not target_page or target_page == 'None':
            if role == 'admin':
                target_page = 'admin_dashboard'
            elif role == 'hospital_staff':
                target_page = 'hospital_staff_dashboard'
            elif role == 'blood_bank_staff':
                target_page = 'blood_bank_staff_dashboard'
            else:
                target_page = 'donor_dashboard'

        try:
            redirect_url = url_for(target_page)
        except Exception:
            redirect_url = url_for('donor_dashboard')

        return f"""
            <script>
                alert('Verification successful! Welcome!');
                window.location.href="{redirect_url}";
            </script>
        """
    else:
        return render_template("general/verification.html", error_popup="Invalid OTP. Try again!")

@app.route('/quiz', methods=['GET','POST'])
def quiz():
    return render_template("general/quiz.html")

@app.route('/donor_quiz', methods=['GET','POST'])
def donor_quiz():
    return render_template("donor/donor_quiz.html")

@app.route('/make_appointment', methods=['GET','POST'])
def make_appointment():
    return render_template("donor/make_appointment.html")

@app.route('/rewards', methods=['GET','POST'])
def rewards():
    return render_template("donor/rewards.html")

@app.route('/donor_faq', methods=['GET','POST'])
def donor_faq():
    return render_template("donor/donor_faq.html")

@app.route('/blood_request', methods=['GET','POST'])
def blood_request():
    return render_template("blood_bank_staff/blood_request.html")

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
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

    normalized_role = str(role).strip().lower().replace(' ', '_')

    conn = sqlite3.connect('bloodbank.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (full_name, email, phone_number, hashed_password, role) VALUES (?,?,?,?,?)", (full_name, email, phone_number, hashed_password, normalized_role)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
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

@app.route("/donor_dashboard", methods=['GET','POST'])
def donor_dashboard():
    return render_template("donor/donor_dashboard.html")

@app.route("/manage_profile", methods=["GET", "POST"])
def manage_profile():
    return render_template("donor/manage_profile.html")

@app.route("/blood_bank_staff_dashboard", methods=["GET", "POST"])
def blood_bank_staff_dashboard():
    return render_template("blood_bank_staff/blood_bank_staff_dashboard.html")

@app.route("/manage_blood_stock", methods=["GET", "POST"])
def manage_blood_stock():
    return render_template("blood_bank_staff/manage_blood_stock.html")

@app.route("/record_donation", methods=["GET", "POST"])
def record_donation():
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
    # app.run(debug=True, ssl_context='adhoc', port=5000)
