import sqlite3
import os
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "commercial_marketplace_super_secret_token"

UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def init_db():
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Customer',
            seller_type TEXT NOT NULL DEFAULT 'Individual',
            company_name TEXT,
            whatsapp_number TEXT
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
            seller_whatsapp TEXT,
            location TEXT NOT NULL DEFAULT 'Accra',
            business_label TEXT NOT NULL DEFAULT 'Individual Vendor'
        )
    """)
    user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "whatsapp_number" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN whatsapp_number TEXT")
    product_columns = {row[1] for row in cursor.execute("PRAGMA table_info(products)")}
    if "seller_whatsapp" not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN seller_whatsapp TEXT")
    conn.commit()
    conn.close()

init_db()

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def query_db(query, args=(), one=False):
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.commit()
    conn.close()
    return (rv if rv else None) if one else rv

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
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
                "INSERT INTO products (title, price, description, image_file, seller, seller_email, seller_whatsapp, location, business_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, session["username"], session["email"], session.get("whatsapp_number"), location, b_label)
            )
            return redirect(url_for("home"))
            
    selected_filter = request.args.get("filter_location", "All")
    company_search = request.args.get("company_search", "").strip()
    product_conditions = []
    product_args = []
    if selected_filter != "All":
        product_conditions.append("location = ?")
        product_args.append(selected_filter)
    if company_search:
        product_conditions.append("(business_label LIKE ? OR seller LIKE ?)")
        search_pattern = f"%{company_search}%"
        product_args.extend([search_pattern, search_pattern])
    product_query = "SELECT * FROM products"
    if product_conditions:
        product_query += " WHERE " + " AND ".join(product_conditions)
    product_query += " ORDER BY id DESC"
    all_products = query_db(product_query, product_args)
        
    cart_items = []
    cart_total = 0.0
    seller_orders = {}
    
    if 'cart' in session and session['cart']:
        placeholders = ",".join("?" for _ in session['cart'])
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", session['cart'])
        if items_in_db:
            for item in items_in_db:
                cart_items.append(item)
                cart_total += float(item['price'])
                seller_number = normalize_whatsapp_number(item['seller_whatsapp'])
                seller_key = (item['seller'], seller_number)
                seller_order = seller_orders.setdefault(seller_key, {
                    "seller": item["seller"],
                    "number": seller_number,
                    "items": [],
                    "total": 0.0,
                })
                seller_order["items"].append(item)
                seller_order["total"] += float(item["price"])

    for seller_order in seller_orders.values():
        message = f"Hello {seller_order['seller']}, I want to buy these products on Biz Hub:\n"
        for item in seller_order["items"]:
            message += f"- {item['title']} (GH₵{item['price']}) in {item['location']}\n"
        message += f"\nTotal Cost: GH₵{seller_order['total']:.2f}. Let's arrange MoMo payment!"
        seller_order["whatsapp_text"] = quote(message)

    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, cart_items=cart_items, cart_total=cart_total, seller_orders=seller_orders.values())

@app.route("/delete-item/<int:product_id>")
def delete_item(product_id):
    if "username" not in session:
        return redirect(url_for("login"))
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product and product["seller"] == session["username"]:
        query_db("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("home"))

@app.route("/add-to-cart/<int:product_id>")
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = []
    current_cart = session['cart']
    if product_id not in current_cart:
        current_cart.append(product_id)
        session['cart'] = current_cart
    return redirect(url_for("home"))

@app.route("/clear-cart")
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for("home"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "username" not in session:
        return redirect(url_for("login"))

    user_list = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))
    if not user_list:
        session.clear()
        return redirect(url_for("login"))
    user = user_list[0]

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        company_name = request.form.get("company_name", "").strip() or None
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email:
            return render_template("settings.html", user=user, settings_error="Email is required.")
        if user["role"] == "Vendor" and not whatsapp_number:
            return render_template("settings.html", user=user, settings_error="Vendor accounts need a WhatsApp number for payments.")
        if new_password and new_password != confirm_password:
            return render_template("settings.html", user=user, settings_error="The new passwords do not match.")

        password_hash = generate_password_hash(new_password) if new_password else user["password_hash"]
        if user["role"] != "Vendor":
            company_name = None
            whatsapp_number = None
        query_db(
            "UPDATE users SET email = ?, password_hash = ?, company_name = ?, whatsapp_number = ? WHERE username = ?",
            (email, password_hash, company_name, whatsapp_number, session["username"])
        )
        session["email"] = email
        session["company_name"] = company_name
        session["whatsapp_number"] = whatsapp_number
        return redirect(url_for("settings", updated="1"))

    return render_template("settings.html", user=user, updated=request.args.get("updated") == "1")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login_user")
        password = request.form.get("login_pass")
        user_list = query_db("SELECT * FROM users WHERE username = ?", (username,))
        if user_list:
            user = user_list[0]
            if check_password_hash(user["password_hash"], password):
                session["username"] = user["username"]
                session["email"] = user["email"]
                session["role"] = user["role"]
                session["company_name"] = user["company_name"]
                session["whatsapp_number"] = user["whatsapp_number"]
                return redirect(url_for("home"))
        return render_template("login.html", login_error="Invalid username or password.")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("reg_user")
        email = request.form.get("reg_email")
        password = request.form.get("reg_pass")
        role = request.form.get("role")
        seller_type = request.form.get("seller_type")
        company_name = request.form.get("company_name")
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        if role == "Customer":
            seller_type = "Individual"
            company_name = None
            whatsapp_number = None
        elif role == "Vendor" and seller_type == "Individual":
            company_name = None
        if role == "Vendor" and not whatsapp_number:
            return render_template("login.html", reg_error="Vendor accounts need a WhatsApp number to receive payments.")
        try:
            hashed_pwd = generate_password_hash(password)
            query_db("INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number) VALUES (?, ?, ?, ?, ?, ?, ?)", (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number))
            session["username"] = username
            session["email"] = email
            session["role"] = role
            session["company_name"] = company_name
            session["whatsapp_number"] = whatsapp_number
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
