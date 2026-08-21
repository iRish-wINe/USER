import sqlite3
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "commercial_marketplace_super_secret_token"
PRODUCT_CATEGORIES = ["Phones & Accessories", "Groceries", "Clothing", "Books", "Health & Beauty", "Beauty & Personal Care", "Home & Kitchen", "Electronics", "Fast Food", "Other"]
VENDOR_CATEGORIES = PRODUCT_CATEGORIES + ["Health & Beauty", "Fast Food"]

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
            whatsapp_number TEXT,
            plan TEXT NOT NULL DEFAULT 'basic',
            trial_started_at TEXT,
            subscription_expires_at TEXT,
            upgrade_requested_at TEXT,
            catalog_mode TEXT
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
            ,category TEXT NOT NULL DEFAULT 'Other'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "whatsapp_number" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN whatsapp_number TEXT")
    if "plan" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'basic'")
    if "trial_started_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN trial_started_at TEXT")
    if "subscription_expires_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_expires_at TEXT")
    if "upgrade_requested_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN upgrade_requested_at TEXT")
    if "catalog_mode" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN catalog_mode TEXT")
    product_columns = {row[1] for row in cursor.execute("PRAGMA table_info(products)")}
    if "seller_whatsapp" not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN seller_whatsapp TEXT")
    if "category" not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
    trial_start = datetime.now(timezone.utc)
    trial_expiry = trial_start + timedelta(days=61)
    cursor.execute(
        "UPDATE users SET trial_started_at = ?, subscription_expires_at = ? WHERE role = 'Vendor' AND trial_started_at IS NULL",
        (trial_start.isoformat(), trial_expiry.isoformat())
    )
    conn.commit()
    conn.close()

init_db()

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def subscription_status(user):
    now = datetime.now(timezone.utc)
    trial_expiry = datetime.fromisoformat(user["subscription_expires_at"]) if user["subscription_expires_at"] else None
    trial_active = user["role"] == "Vendor" and trial_expiry and trial_expiry > now and user["plan"] == "basic"
    premium_active = user["role"] == "Vendor" and ((user["plan"] == "premium" and trial_expiry and trial_expiry > now) or trial_active)
    if trial_active:
        return {"name": "Free trial", "is_premium": True, "trial": True, "expires": trial_expiry.strftime("%d %b %Y")}
    if premium_active:
        return {"name": "Premium Store", "is_premium": True, "trial": False, "expires": trial_expiry.strftime("%d %b %Y")}
    return {"name": "Basic", "is_premium": False, "trial": False, "expires": None}

def admin_configured():
    return bool(os.environ.get("BIZ_HUB_ADMIN_USERNAME") and os.environ.get("BIZ_HUB_ADMIN_PASSWORD"))

def is_admin():
    return session.get("is_admin") is True

def query_db(query, args=(), one=False):
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.commit()
    conn.close()
    return (rv if rv else None) if one else rv

def get_vendor_categories(user_id):
    return [row["category"] for row in query_db("SELECT category FROM vendor_categories WHERE user_id = ? ORDER BY category", (user_id,))]

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if "username" not in session or session.get("role") != "Vendor":
            return redirect(url_for("home"))
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))[0]
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],))[0]["count"]
        if not vendor_subscription["is_premium"] and listing_count >= 3:
            return redirect(url_for("home", listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))
            
        price = request.form.get("price")
        is_fast_food = vendor["seller_type"] == "Fast Food"
        title = request.form.get("meal_name" if is_fast_food else "title")
        description = request.form.get("meal_description" if is_fast_food else "description")
        category = "Fast Food" if is_fast_food else request.form.get("category", "Other")
        location = request.form.get("location")
        file = request.files.get("product_image")
        filename = "fast-food-placeholder.svg" if is_fast_food else secure_filename(file.filename) if file and file.filename else ""
        
        if title and price and description and location and (is_fast_food or file and file.filename):
            if not is_fast_food:
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            b_label = session.get("company_name") if vendor_subscription["is_premium"] and session.get("company_name") else "Individual Vendor"
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, seller, seller_email, seller_whatsapp, location, business_label, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, session["username"], session["email"], session.get("whatsapp_number"), location, b_label, category)
            )
            return redirect(url_for("home"))
            
    selected_filter = request.args.get("filter_location", "All")
    company_search = request.args.get("company_search", "").strip()
    selected_category = request.args.get("category", "All")
    listing_error = request.args.get("listing_error")
    product_conditions = []
    product_args = []
    if selected_filter != "All":
        product_conditions.append("location = ?")
        product_args.append(selected_filter)
    if company_search:
        product_conditions.append("(business_label LIKE ? OR seller LIKE ?)")
        search_pattern = f"%{company_search}%"
        product_args.extend([search_pattern, search_pattern])
    if selected_category != "All":
        product_conditions.append("category = ?")
        product_args.append(selected_category)
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

    premium_sellers = {row["username"] for row in query_db("SELECT username FROM users WHERE role = 'Vendor' AND plan = 'premium' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))}
    trial_sellers = {row["username"] for row in query_db("SELECT username FROM users WHERE role = 'Vendor' AND plan = 'basic' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))}
    premium_sellers.update(trial_sellers)
    for seller_order in seller_orders.values():
        seller_order["priority"] = seller_order["seller"] in premium_sellers
    vendor_subscription = None
    listing_count = 0
    if session.get("role") == "Vendor":
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))[0]
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],))[0]["count"]
    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, cart_items=cart_items, cart_total=cart_total, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, listing_error=listing_error, premium_sellers=premium_sellers)

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

@app.route("/subscription")
def subscription():
    if "username" not in session:
        return redirect(url_for("login"))
    user_list = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))
    if not user_list:
        session.clear()
        return redirect(url_for("login"))
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    payment_text = quote(f"Hello Biz Hub, I want to upgrade my {session['username']} account to Premium Store.")
    return render_template("subscription.html", user=user_list[0], subscription=subscription_status(user_list[0]), payment_number=payment_number, payment_text=payment_text, requested=request.args.get("requested") == "1")

@app.route("/request-premium", methods=["POST"])
def request_premium():
    if "username" not in session or session.get("role") != "Vendor":
        return redirect(url_for("login"))
    query_db("UPDATE users SET upgrade_requested_at = ? WHERE username = ?", (datetime.now(timezone.utc).isoformat(), session["username"]))
    return redirect(url_for("subscription", requested="1"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if not admin_configured():
            return render_template("admin_login.html", admin_error="Admin credentials are not configured.")
        if request.form.get("username") == os.environ.get("BIZ_HUB_ADMIN_USERNAME") and request.form.get("password") == os.environ.get("BIZ_HUB_ADMIN_PASSWORD"):
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", admin_error="Invalid admin credentials.")
    return render_template("admin_login.html", admin_configured=admin_configured())

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("admin_login"))
    vendors = query_db("SELECT * FROM users WHERE role = 'Vendor' ORDER BY COALESCE(upgrade_requested_at, '') DESC, username")
    listing_counts = {row["seller"]: row["count"] for row in query_db("SELECT seller, COUNT(*) AS count FROM products GROUP BY seller")}
    return render_template("admin.html", vendors=vendors, subscription_status=subscription_status, listing_counts=listing_counts)

@app.route("/admin/approve-premium/<int:user_id>", methods=["POST"])
def approve_premium(user_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    query_db("UPDATE users SET plan = 'premium', subscription_expires_at = ?, upgrade_requested_at = NULL WHERE id = ? AND role = 'Vendor'", (expiry.isoformat(), user_id))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "username" not in session:
        return redirect(url_for("login"))

    user_list = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))
    if not user_list:
        session.clear()
        return redirect(url_for("login"))
    user = user_list[0]
    vendor_categories = get_vendor_categories(user["id"]) if user["role"] == "Vendor" else []

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        company_name = request.form.get("company_name", "").strip() or None
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        catalog_mode = request.form.get("catalog_mode", "Focused")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]

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
            catalog_mode = None
            selected_categories = []
        elif catalog_mode not in ("Variety", "Focused") or not selected_categories:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Choose whether you sell a variety or focus on a category, then select at least one product range.")
        query_db(
            "UPDATE users SET email = ?, password_hash = ?, company_name = ?, whatsapp_number = ?, catalog_mode = ? WHERE username = ?",
            (email, password_hash, company_name, whatsapp_number, catalog_mode, session["username"])
        )
        query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
        for category in selected_categories:
            query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (user["id"], category))
        session["email"] = email
        session["company_name"] = company_name
        session["whatsapp_number"] = whatsapp_number
        return redirect(url_for("settings", updated="1"))

    return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, updated=request.args.get("updated") == "1")

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
                session["seller_type"] = user["seller_type"]
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
        catalog_mode = request.form.get("catalog_mode")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]
        company_name = request.form.get("company_name")
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        if role == "Customer":
            seller_type = "Individual"
            company_name = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
        elif role == "Vendor" and seller_type == "Individual":
            company_name = None
        if role == "Vendor" and not whatsapp_number:
            return render_template("login.html", reg_error="Vendor accounts need a WhatsApp number to receive payments.")
        if role == "Vendor" and (catalog_mode not in ("Variety", "Focused") or not selected_categories):
            return render_template("login.html", reg_error="Choose a product range and select at least one category.")
        try:
            hashed_pwd = generate_password_hash(password)
            trial_started_at = datetime.now(timezone.utc)
            trial_expires_at = trial_started_at + timedelta(days=61)
            query_db("INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, "basic", trial_started_at.isoformat() if role == "Vendor" else None, trial_expires_at.isoformat() if role == "Vendor" else None, catalog_mode))
            new_user = query_db("SELECT id FROM users WHERE username = ?", (username,))[0]
            for category in selected_categories:
                query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (new_user["id"], category))
            session["username"] = username
            session["email"] = email
            session["role"] = role
            session["seller_type"] = seller_type
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
