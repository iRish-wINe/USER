import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "commercial_marketplace_super_secret_token"

UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- SECURE DATABASE SYSTEM ---
def init_db():
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
    # UPGRADED: Users table now explicitly tracks individual account roles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Customer',
            seller_type TEXT NOT NULL DEFAULT 'Individual',
            company_name TEXT
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
            location TEXT NOT NULL DEFAULT 'Accra',
            business_label TEXT NOT NULL DEFAULT 'Individual Vendor'
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

# --- ROUTES ---

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # Block malicious requests if a customer somehow tries to post a product form payload
        if "username" not in session or session.get("role") != "Vendor":
            return redirect(url_for("home"))
            
        title = request.form.get("title")
        price = request.form.get("price")
        description = request.form.get("description")
        location = request.form.get("location")
        file = request.files.get("product_image")
        
        if title and price and description and location and file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            b_label = session.get("company_name") if session.get("company_name") else "Individual Vendor"
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, seller, seller_email, location, business_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, session["username"], session["email"], location, b_label)
            )
            return redirect(url_for("home"))
            
    selected_filter = request.args.get("filter_location")
    if selected_filter and selected_filter != "All":
        all_products = query_db("SELECT * FROM products WHERE location = ? ORDER BY id DESC", (selected_filter,))
    else:
        all_products = query_db("SELECT * FROM products ORDER BY id DESC")
        selected_filter = "All"
        
    cart_items = []
    cart_total = 0.0
    whatsapp_text = "Hello, I want to buy these products on SikaExpress:%0A"
    
    if 'cart' in session and session['cart']:
        placeholders = ",".join("?" for _ in session['cart'])
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", session['cart'])
        if items_in_db:
            for item in items_in_db:
                cart_items.append(item)
                cart_total += float(item['price'])
                whatsapp_text += f"- {item['title']} (GH₵{item['price']}) in {item['location']}%0A"
            whatsapp_text += f"%0ATotal Cost: GH₵{cart_total:.2f}. Let's arrange MoMo payment!"

    return render_template("index.html", products=all_products, active_filter=selected_filter, cart_items=cart_items, cart_total=cart_total, whatsapp_text=whatsapp_text)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login_user")
        password = request.form.get("login_pass")
        user_list = query_db("SELECT * FROM users WHERE username = ?", (username,))
        
        if user_list:
            user = user_list
            if check_password_hash(user["password_hash"], password):
                session["username"] = user["username"]
                session["email"] = user["email"]
                session["role"] = user["role"]  # Track role inside session memory
                session["company_name"] = user["company_name"]
                return redirect(url_for("home"))
        return render_template("login.html", login_error="Invalid username or password.")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("reg_user")
        email = request.form.get("reg_email")
        password = request.form.get("reg_pass")
        role = request.form.get("role")  # Capture 'Customer' or 'Vendor'
        seller_type = request.form.get("seller_type")
        company_name = request.form.get("company_name")
        
        # Force default settings if they selected Customer
        if role == "Customer":
            seller_type = "Individual"
            company_name = None
        elif role == "Vendor" and seller_type == "Individual":
            company_name = None
            
        try:
            hashed_pwd = generate_password_hash(password)
            query_db(
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name) VALUES (?, ?, ?, ?, ?, ?)", 
                (username, email, hashed_pwd, role, seller_type, company_name)
            )
            session["username"] = username
            session["email"] = email
            session["role"] = role
            session["company_name"] = company_name
            return redirect(url_for("home"))
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
