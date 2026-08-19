import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Secret key signs session cookies securely to keep you logged in on page reloads
app.secret_key = "commercial_marketplace_super_secret_token"

UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- SECURE DATABASE SYSTEM ---
def init_db():
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
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
            seller_email TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT 'Accra'
        )
    """)
    conn.commit()
    conn.close()

init_db()

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

# 1. Main Marketplace Storefront Catalog
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if "username" not in session:
            return redirect(url_for("login"))
            
        title = request.form.get("title")
        price = request.form.get("price")
        description = request.form.get("description")
        location = request.form.get("location")
        file = request.files.get("product_image")
        
        if title and price and description and location and file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, seller, seller_email, location) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, session["username"], session["email"], location)
            )
            return redirect(url_for("home"))
            
    all_products = query_db("SELECT * FROM products ORDER BY id DESC")
    return render_template("index.html", products=all_products)

# 2. Member Authorization Sign In Portal (FIXED ROW SELECTION)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login_user")
        password = request.form.get("login_pass")
        
        # Query the database
        user_list = query_db("SELECT * FROM users WHERE username = ?", (username,))
        
        # Verify the list isn't empty, then safely extract the first row dictionary
        if user_list:
            user = user_list[0]
            # Crosscheck secure encryption password hashes
            if check_password_hash(user["password_hash"], password):
                session["username"] = user["username"]
                session["email"] = user["email"]
                return redirect(url_for("home"))
            
        return render_template("login.html", login_error="Invalid username or password.")
    return render_template("login.html")


# 3. New Account Registration Portal
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Captures fields from the GREEN registration portal form boxes
        username = request.form.get("reg_user")
        email = request.form.get("reg_email")
        password = request.form.get("reg_pass")
        
        try:
            hashed_pwd = generate_password_hash(password)
            query_db("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)", (username, email, hashed_pwd))
            
            # Auto log you in right after hitting the green register button
            session["username"] = username
            session["email"] = email
            return redirect(url_for("home"))
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
    return redirect(url_for("login"))

# 4. Global Account Sign Out Terminal
@app.route("/logout")
def logout():
    session.clear() # Clears encrypted session cookies completely
    return redirect(url_for("home"))

if __name__ == "__main__":
    # Keeps your universal network host connection open for phone access
    app.run(debug=True, host="0.0.0.0")
