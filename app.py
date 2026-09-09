import os
from flask import Flask, render_template, url_for, redirect, session
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

oauth = OAuth(app)

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


@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/resetpassword")
def resetpassword():
    return render_template("resetpassword.html")

@app.route("/signup")
def signup():
    return render_template("signup.html")

if __name__ == "__main__":
    app.run(debug=True, ssl_context='adhoc', port=5000)
