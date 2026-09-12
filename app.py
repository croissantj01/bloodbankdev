import os
import smtplib
import sqlite3
import bcrypt
from email.message import EmailMessage
from flask import Flask, render_template, url_for, redirect, session, request
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
            "INSERT INTO users (email, password) VALUES (?,?)",
            (username, hashed_password.decode('utf-8'))
        )
        conn.commit()
        print("User registered successful!")
    except sqlite3.IntegrityError:
        print("Username already exists.")
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
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.pop('is_reset_flow', None)
    next_page = request.args.get('next') or request.form.get('next')

    if request.method == "POST":
        email = request.form.get('email')
        password = request.form.get('password')

        user = get_user_by_email(email)

        if not user:
            return render_template("login.html", error_popup="Invalid credentials.")

        stored_hash = user['password'] if 'password' in user.keys() else None

        if stored_hash:
            password_bytes = password.encode('utf-8')
            hashed_bytes = stored_hash.encode('utf-8')

            if bcrypt.checkpw(password_bytes, hashed_bytes):
                otp = str(random.randint(100000, 999999))

                session['pending_email'] = email
                session['pending_otp'] = otp
                session['next_page'] = next_page

                send_otp_email(email, otp)

                return render_template("verification.html")

        return render_template("login.html", error="Invalid credentials.")

    return render_template("login.html", next=next_page)

@app.route("/check_email", methods=["GET", "POST"])
def check_email():
    if request.method == "POST":
        entered_email = request.form.get('email')
        user = get_user_by_email(entered_email)

        if not user:
            return render_template("check_email.html", error_popup="No email found! Please try again.")
        else:
            otp = str(random.randint(100000, 999999))

            session['pending_email'] = entered_email
            session['pending_otp'] = otp
            session['is_reset_flow'] = True

            send_otp_email(entered_email, otp)

            return render_template("verification.html")
    return render_template("check_email.html")

def update_password(email, new_password):
    password_bytes = new_password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_new_password = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

    conn = sqlite3.connect('bloodbank.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password =? WHERE email = ?", (hashed_new_password, email)
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
            return render_template("reset_password.html", error_popup="The password does not match!")

        email = session.get('pending_email')
        update_password(email, new_password)

        session.pop('pending_email', None)
        session.pop('is_reset_flow', None)
        session.pop('otp_verified', None)

        return redirect(url_for('login'))

    return render_template("reset_password.html")

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
        print(f"Successfully sent OTP email to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
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
            return render_template("signup.html", error_popup="Password do not match!")

        otp = str(random.randint(100000, 999999))

        session['pending_email'] = email
        session['pending_password'] = password
        session['pending_otp'] = otp

        session['next_page'] = next_page

        send_otp_email(email, otp)

        return render_template("verification.html")

    return render_template("signup.html", next=next_page)



@app.route('/verification', methods=['POST'])
def verification():
    entered_otp = request.form.get('otp')
    generated_otp = session.get('pending_otp')

    if entered_otp == generated_otp:
        session.pop('pending_otp', None)

        if session.get('is_reset_flow'):
            session['otp_verified'] = True
            return redirect(url_for('reset_password'))
        else:
            email = session.get('pending_email')
            password = session.get('pending_password')

            if password:
                register_user(email,password)

            session.pop('pending_email', None)
            session.pop('pending_password', None)

            session['user_email'] = email

            target_page = session.pop('next_page', 'index')

            try:
                redirect_url = url_for(target_page)
            except:
                redirect_url = target_page

            return f"""
                <script>
                    alert('Email verified successfully! Welcome!');
                    window.location.href='{redirect_url}'
                </script>
            """

    else:
        return "Invalid OTP code. Please go back and try again.", 400

@app.route('/quiz', methods=['GET','POST'])
def quiz():
    return render_template("quiz.html")

@app.route('/make_appointment', methods=['GET','POST'])
def make_appointment():
    return render_template("make_appointment.html")

@app.route('/rewards', methods=['GET','POST'])
def rewards():
    return render_template("rewards.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
    # app.run(debug=True, ssl_context='adhoc', port=5000)
