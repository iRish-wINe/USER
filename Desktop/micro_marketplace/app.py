import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Secret key signs session cookies securely
app.secret_key = "commercial_marketplace_super_secret_token"

# Configure the upload directory path for product pictures
UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- SECURE DATABASE SYSTEM ---
def init_db():
    # Added timeout=20 flag to break database busy/locked crashes
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
    
    # Force table validation schemas on boot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT NOT NULL,
            image_file TEXT NOT NULL,
            seller TEXT NOT NULL,
            seller_email TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# Run initialization loop immediately
init_db()

# Universal helper function to manage query operations safely
def query_db(query, args=(), one=False):
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.commit()
    conn.close()
    return (rv if rv else None) if one else rv

# --- ROUTES MATRIX ---

# 1. Main Marketplace Storefront Homepage
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # Block unauthorized uploads trying to spoof requests
        if "username" not in session:
            return redirect(url_for("login"))
            
        title = request.form.get("title")
        price = request.form.get("price")
        description = request.form.get("description")
        file = request.files.get("product_image")
        
        if title and price and description and file:
            filename = secure_filename(file.filename)
            # Save the raw photograph file into static/uploads/
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            
            # Map product entry row and bind it to the logged-in seller session metadata
            query_db(
                "INSERT INTO products (title, price, description, image_file, seller, seller_email) VALUES (?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, session["username"], session["email"])
            )
            return redirect(url_for("home"))
            
    all_products = query_db("SELECT * FROM products ORDER BY id DESC")
    # CRUCIAL: Renders index.html for the store catalog home screen
    return render_template("index.html", products=all_products)

# 2. Member Authorization Sign In Portal
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login_user")
        password = request.form.get("login_pass")
        
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        
        # Crosscheck hash cryptography keys
        if user and check_password_hash(user["password_hash"], password):
            session["username"] = user["username"]
            session["email"] = user["email"]
            return redirect(url_for("home"))
            
        return render_template("login.html", login_error="Invalid username or password.")
    return render_template("login.html")

# 3. New Account Registration Portal
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("reg_user")
        email = request.form.get("reg_email")
        password = request.form.get("reg_pass")
        
        try:
            # Scramble the user password securely
            hashed_pwd = generate_password_hash(password)
            query_db("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)", (username, email, hashed_pwd))
            
            # Autologin after a clean registration setup row
            session["username"] = username
            session["email"] = email
            return redirect(url_for("home"))
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
    return redirect(url_for("login"))

# 4. Global Account Sign Out Terminal
@app.route("/logout")
def logout():
    session.clear() # Clear encrypted authorization cookie state tracking tokens
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
