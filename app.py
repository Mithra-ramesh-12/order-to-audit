
import os
import io
import csv
import json
import re
import sqlite3
import html
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_file, Response, abort
)
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from logic import (
    get_stock_balance,
    post_production_run,
    decimal_text,
    money_to_paise,
    paise_to_rupees,
    calculate_gst,
    record_stock_movement,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-development-secret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get(
    "DATABASE_PATH",
    os.environ.get("DATABASE", os.path.join(BASE_DIR, "order_to_audit.db"))
)
FACTORY_STATE = "Tamil Nadu"


def db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """Create the schema when the database is missing OR is an empty file."""
    database_dir = os.path.dirname(os.path.abspath(DATABASE))
    os.makedirs(database_dir, exist_ok=True)
    connection = db()
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if not exists:
            schema_path = os.path.join(BASE_DIR, "schema.sql")
            with open(schema_path, "r", encoding="utf-8") as file:
                connection.executescript(file.read())
            connection.commit()
    finally:
        connection.close()


def fetch_all(sql, params=()):
    with db() as connection:
        return connection.execute(sql, params).fetchall()


def fetch_one(sql, params=()):
    with db() as connection:
        return connection.execute(sql, params).fetchone()


def money_text(value):
    amount = Decimal(str(value or 0)) / Decimal("100")
    return f"₹{amount:,.2f}"


def write_audit(connection, table_name, record_id, action,
                old_values=None, new_values=None, user_id=None):
    connection.execute(
        """
        INSERT INTO audit_log
        (table_name, record_id, action, old_values, new_values, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            table_name,
            record_id,
            action,
            json.dumps(old_values, default=str) if old_values is not None else None,
            json.dumps(new_values, default=str) if new_values is not None else None,
            user_id,
        ),
    )


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                abort(403)
            return function(*args, **kwargs)
        return wrapper
    return decorator


def current_user_id():
    return session.get("user_id")


def financial_year(day=None):
    day = day or date.today()
    if day.month >= 4:
        return f"{day.year}-{str(day.year + 1)[-2:]}"
    return f"{day.year - 1}-{str(day.year)[-2:]}"


def next_invoice_number(connection, day=None):
    fy = financial_year(day)
    row = connection.execute(
        "SELECT MAX(sequence_number) AS last_number FROM invoices WHERE financial_year=?",
        (fy,),
    ).fetchone()
    sequence = (row["last_number"] or 0) + 1
    return f"{fy}/{sequence:04d}", fy, sequence


def next_number(connection, table, column, prefix):
    row = connection.execute(
        f"SELECT COUNT(*) AS total FROM {table}"
    ).fetchone()
    return f"{prefix}-{date.today():%Y%m%d}-{(row['total'] or 0) + 1:04d}"


def stock_balance(connection, item_type, item_id):
    return get_stock_balance(connection, item_type, item_id)


def get_order_lines(connection, order_id):
    return connection.execute(
        """
        SELECT ol.*, p.name AS product_name, p.hsn, p.gst_rate_bps
        FROM order_lines ol
        JOIN products p ON p.id=ol.product_id
        WHERE ol.order_id=?
        """,
        (order_id,),
    ).fetchall()


@app.context_processor
def inject_globals():
    return {
        "current_user": session.get("name"),
        "current_role": session.get("role"),
        "money_text": money_text,
    }


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        user = fetch_one(
            "SELECT * FROM users WHERE username=? AND active=1",
            (username,),
        )

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html", register_mode=False)




@app.route("/register", methods=["GET", "POST"])
def register():

    available_roles = [
        "salesman",
        "admin",
        "owner",
        "production",
        "accountant"
    ]

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "").strip().lower()

        if len(name) < 2:
            flash("Enter your full name.", "warning")

        elif not re.fullmatch(r"[a-zA-Z0-9_.-]{3,30}", username):
            flash("Username must contain 3–30 valid characters.", "warning")

        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "warning")

        elif password != confirm_password:
            flash("Passwords do not match.", "warning")

        elif role not in available_roles:
            flash("Please select a valid role.", "warning")

        else:
            connection = db()

            try:
                existing = connection.execute(
                    "SELECT id FROM users WHERE username=?",
                    (username,)
                ).fetchone()

                if existing:
                    flash("Username already exists. Choose another.", "danger")

                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO users
                        (name, username, password_hash, role, active)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (
                            name,
                            username,
                            generate_password_hash(password),
                            role
                        )
                    )

                    user_id = cursor.lastrowid

                    write_audit(
                        connection,
                        "users",
                        user_id,
                        "create",
                        new_values={
                            "name": name,
                            "username": username,
                            "role": role
                        },
                        user_id=user_id
                    )

                    connection.commit()

                    # Automatically sign in the newly registered user.
                    session.clear()
                    session["user_id"] = user_id
                    session["name"] = name
                    session["role"] = role

                    flash(
                        f"Welcome {name}! Your {role.title()} account is ready.",
                        "success"
                    )

                    return redirect(url_for("dashboard"))

            except sqlite3.Error as error:
                connection.rollback()
                flash(f"Registration failed: {error}", "danger")

            finally:
                connection.close()

    return render_template(
        "login.html",
        register_mode=True,
        available_roles=available_roles
    )


@app.route("/users", methods=["GET", "POST"])
@login_required
@roles_required("admin", "owner")
def manage_users():

    allowed_roles = ["salesman", "production", "accountant"]

    if session.get("role") == "owner":
        allowed_roles = [
            "salesman", "admin", "production",
            "accountant", "owner"
        ]

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "").strip()

        if len(name) < 2:
            flash("Enter a valid full name.", "warning")

        elif not re.fullmatch(r"[a-zA-Z0-9_.-]{3,30}", username):
            flash("Username must be 3–30 valid characters.", "warning")

        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "warning")

        elif password != confirm_password:
            flash("Passwords do not match.", "warning")

        elif role not in allowed_roles:
            flash("You are not authorized to create this role.", "danger")

        else:
            connection = db()

            try:
                existing = connection.execute(
                    "SELECT id FROM users WHERE username=?",
                    (username,)
                ).fetchone()

                if existing:
                    flash("This username already exists.", "danger")

                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO users
                        (name, username, password_hash, role, active)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (
                            name,
                            username,
                            generate_password_hash(password),
                            role
                        )
                    )

                    write_audit(
                        connection,
                        "users",
                        cursor.lastrowid,
                        "create",
                        new_values={
                            "name": name,
                            "username": username,
                            "role": role
                        },
                        user_id=current_user_id()
                    )

                    connection.commit()
                    flash(
                        f"{role.title()} account created successfully!",
                        "success"
                    )

                    return redirect(url_for("manage_users"))

            except sqlite3.Error as error:
                connection.rollback()
                flash(f"Account creation failed: {error}", "danger")

            finally:
                connection.close()

    users = fetch_all("""
        SELECT id, name, username, role, active, created_at
        FROM users
        ORDER BY id DESC
    """)

    role_options = "".join(
        f'<option value="{html.escape(role)}">{html.escape(role.title())}</option>'
        for role in allowed_roles
    )

    user_rows = ""

    for user in users:
        status = "Active" if user["active"] else "Inactive"

        user_rows += f"""
        <tr>
            <td>{html.escape(str(user["name"]))}</td>
            <td>{html.escape(str(user["username"]))}</td>
            <td>{html.escape(str(user["role"]).title())}</td>
            <td>{status}</td>
        </tr>
        """

    if not user_rows:
        user_rows = "<tr><td colspan='4'>No accounts found.</td></tr>"

    messages = ""

    for category, message in session.pop("_flashes", []):
        messages += (
            f'<div class="alert alert-{html.escape(str(category))}">'
            f'{html.escape(str(message))}</div>'
        )

    page = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Account Management | Order-to-Audit</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
              rel="stylesheet">
        <style>
            body {{
                background: #faf7f3;
                color: #263746;
                font-family: Arial, sans-serif;
            }}
            .top {{
                background: #1e303e;
                color: white;
                padding: 22px 6%;
            }}
            .container {{
                max-width: 1100px;
                margin-top: 35px;
            }}
            .panel {{
                background: white;
                border: 1px solid #eee5dc;
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 5px 20px rgba(0,0,0,.035);
            }}
            .btn-main {{
                background: #ed783e;
                color: white;
                border: none;
                padding: 11px 22px;
                border-radius: 8px;
            }}
            .btn-main:hover {{
                background: #d9632d;
                color: white;
            }}
            .form-control, .form-select {{
                padding: 11px;
                border-radius: 8px;
            }}
            th {{
                color: #718093 !important;
                font-size: 12px;
                text-transform: uppercase;
            }}
        </style>
    </head>
    <body>
        <header class="top">
            <h3>Order<span style="color:#ed783e">Audit</span></h3>
            <p class="mb-0">Account Management</p>
        </header>

        <main class="container">
            <div class="mb-4">
                <a href="/dashboard" class="text-decoration-none">
                    ← Back to dashboard
                </a>
            </div>

            {messages}

            <section class="panel">
                <h4>Create a new account</h4>
                <p class="text-secondary">
                    Create employee accounts and assign their access roles.
                </p>

                <form method="POST">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label">Full name</label>
                            <input name="name" class="form-control"
                                   placeholder="Enter full name" required>
                        </div>

                        <div class="col-md-6">
                            <label class="form-label">Username</label>
                            <input name="username" class="form-control"
                                   placeholder="Choose username"
                                   minlength="3" maxlength="30" required>
                        </div>

                        <div class="col-md-6">
                            <label class="form-label">Password</label>
                            <input type="password" name="password"
                                   class="form-control"
                                   minlength="8" required>
                        </div>

                        <div class="col-md-6">
                            <label class="form-label">Confirm password</label>
                            <input type="password" name="confirm_password"
                                   class="form-control"
                                   minlength="8" required>
                        </div>

                        <div class="col-md-6">
                            <label class="form-label">Assign role</label>
                            <select name="role" class="form-select" required>
                                <option value="">Choose a role</option>
                                {role_options}
                            </select>
                        </div>
                    </div>

                    <button type="submit" class="btn btn-main mt-4">
                        + Create account
                    </button>
                </form>
            </section>

            <section class="panel">
                <h4>Registered accounts</h4>
                <p class="text-secondary">
                    Accounts currently registered in your system.
                </p>

                <div class="table-responsive">
                    <table class="table align-middle">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Username</th>
                                <th>Role</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {user_rows}
                        </tbody>
                    </table>
                </div>
            </section>
        </main>
    </body>
    </html>
    """

    return Response(page, mimetype="text/html")



@app.route("/dashboard")
@login_required
def dashboard():
    role = session.get("role")
    user_id = current_user_id()
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()

    dashboard_data = {}

    def scalar(sql, params=()):
        row = fetch_one(sql, params)
        return row[0] if row else 0

    def outstanding_total():
        return scalar("""
            SELECT COALESCE(
                SUM(i.total_paise - COALESCE(p.paid, 0)), 0
            )
            FROM invoices i
            LEFT JOIN (
                SELECT invoice_id, SUM(amount_paise) AS paid
                FROM payments
                GROUP BY invoice_id
            ) p ON p.invoice_id = i.id
            WHERE i.status = 'posted'
        """)

    if role == "salesman":
        dashboard_data["total_orders"] = scalar(
            "SELECT COUNT(*) FROM orders WHERE salesman_id=?",
            (user_id,)
        )
        dashboard_data["pending_orders"] = scalar(
            "SELECT COUNT(*) FROM orders WHERE salesman_id=? AND status='pending'",
            (user_id,)
        )
        dashboard_data["approved_orders"] = scalar(
            "SELECT COUNT(*) FROM orders WHERE salesman_id=? AND status IN ('approved','invoiced','dispatched')",
            (user_id,)
        )
        dashboard_data["recent_orders"] = fetch_all("""
            SELECT o.*, c.name AS customer_name
            FROM orders o
            JOIN customers c ON c.id=o.customer_id
            WHERE o.salesman_id=?
            ORDER BY o.created_at DESC
            LIMIT 10
        """, (user_id,))

    elif role == "admin":
        dashboard_data["pending_orders"] = scalar(
            "SELECT COUNT(*) FROM orders WHERE status='pending'"
        )
        dashboard_data["today_sales"] = scalar(
            "SELECT COALESCE(SUM(total_paise),0) FROM invoices WHERE invoice_date=? AND status='posted'",
            (today,)
        )
        dashboard_data["outstanding"] = outstanding_total()
        dashboard_data["products"] = scalar(
            "SELECT COUNT(*) FROM products WHERE active=1"
        )
        dashboard_data["customers"] = scalar(
            "SELECT COUNT(*) FROM customers WHERE active=1"
        )
        dashboard_data["recent_orders"] = fetch_all("""
            SELECT o.*, c.name AS customer_name, u.name AS salesman_name
            FROM orders o
            JOIN customers c ON c.id=o.customer_id
            JOIN users u ON u.id=o.salesman_id
            ORDER BY o.created_at DESC LIMIT 8
        """)
        dashboard_data["recent_invoices"] = fetch_all("""
            SELECT i.invoice_number, i.invoice_date, i.total_paise,
                   c.name AS customer_name
            FROM invoices i
            JOIN customers c ON c.id=i.customer_id
            WHERE i.status='posted'
            ORDER BY i.id DESC LIMIT 5
        """)
        dashboard_data["stock"] = fetch_all("""
            SELECT p.id, p.name,
                   COALESCE(SUM(
                       CAST(sl.quantity_in AS REAL) -
                       CAST(sl.quantity_out AS REAL)
                   ), 0) AS balance
            FROM products p
            LEFT JOIN stock_ledger sl
                ON sl.item_type='product' AND sl.item_id=p.id
            WHERE p.active=1
            GROUP BY p.id, p.name
            ORDER BY p.name
        """)

    elif role == "production":
        dashboard_data["today_runs"] = scalar(
            "SELECT COUNT(*) FROM production_runs WHERE production_date=? AND status='posted'",
            (today,)
        )
        dashboard_data["today_output"] = scalar(
            "SELECT COALESCE(SUM(actual_good_packets),0) FROM production_runs WHERE production_date=? AND status='posted'",
            (today,)
        )
        dashboard_data["total_runs"] = scalar(
            "SELECT COUNT(*) FROM production_runs WHERE status='posted'"
        )
        dashboard_data["boms"] = fetch_all("""
            SELECT b.id, b.batch_name, b.batch_size_packets,
                   b.expected_yield_packets, p.name AS product_name
            FROM bom b
            JOIN products p ON p.id=b.product_id
            WHERE b.active=1
            ORDER BY p.name, b.batch_name
        """)
        dashboard_data["materials"] = fetch_all("""
            SELECT m.id, m.name, m.unit,
                   COALESCE(SUM(
                       CAST(sl.quantity_in AS REAL) -
                       CAST(sl.quantity_out AS REAL)
                   ), 0) AS balance
            FROM materials m
            LEFT JOIN stock_ledger sl
                ON sl.item_type='material' AND sl.item_id=m.id
            WHERE m.active=1
            GROUP BY m.id, m.name, m.unit
            ORDER BY m.name
        """)
        dashboard_data["recent_runs"] = fetch_all("""
            SELECT r.run_number, r.production_date,
                   r.planned_packets, r.actual_good_packets,
                   r.status, p.name AS product_name
            FROM production_runs r
            JOIN products p ON p.id=r.product_id
            ORDER BY r.id DESC LIMIT 8
        """)

    elif role == "accountant":
        dashboard_data["invoice_count"] = scalar(
            "SELECT COUNT(*) FROM invoices WHERE status='posted'"
        )
        dashboard_data["sales_total"] = scalar(
            "SELECT COALESCE(SUM(total_paise),0) FROM invoices WHERE status='posted' AND invoice_date BETWEEN ? AND ?",
            (month_start, today)
        )
        dashboard_data["paid_total"] = scalar(
            "SELECT COALESCE(SUM(amount_paise),0) FROM payments WHERE payment_date BETWEEN ? AND ?",
            (month_start, today)
        )
        dashboard_data["outstanding"] = outstanding_total()
        dashboard_data["recent_invoices"] = fetch_all("""
            SELECT i.id, i.invoice_number, i.invoice_date,
                   i.taxable_value_paise, i.total_paise,
                   i.cgst_paise, i.sgst_paise, i.igst_paise,
                   c.name AS customer_name
            FROM invoices i
            JOIN customers c ON c.id=i.customer_id
            WHERE i.status='posted'
            ORDER BY i.id DESC LIMIT 8
        """)
        dashboard_data["recent_payments"] = fetch_all("""
            SELECT p.payment_date, p.amount_paise, p.payment_mode,
                   i.invoice_number, c.name AS customer_name
            FROM payments p
            JOIN invoices i ON i.id=p.invoice_id
            JOIN customers c ON c.id=i.customer_id
            ORDER BY p.id DESC LIMIT 8
        """)

    elif role == "owner":
        dashboard_data["products"] = scalar(
            "SELECT COUNT(*) FROM products WHERE active=1"
        )
        dashboard_data["customers"] = scalar(
            "SELECT COUNT(*) FROM customers WHERE active=1"
        )
        dashboard_data["employees"] = scalar(
            "SELECT COUNT(*) FROM users WHERE active=1"
        )
        dashboard_data["pending_orders"] = scalar(
            "SELECT COUNT(*) FROM orders WHERE status='pending'"
        )
        dashboard_data["today_sales"] = scalar(
            "SELECT COALESCE(SUM(total_paise),0) FROM invoices WHERE invoice_date=? AND status='posted'",
            (today,)
        )
        dashboard_data["month_sales"] = scalar(
            "SELECT COALESCE(SUM(total_paise),0) FROM invoices WHERE invoice_date BETWEEN ? AND ? AND status='posted'",
            (month_start, today)
        )
        dashboard_data["outstanding"] = outstanding_total()
        dashboard_data["production_runs"] = scalar(
            "SELECT COUNT(*) FROM production_runs WHERE status='posted'"
        )
        dashboard_data["recent_orders"] = fetch_all("""
            SELECT o.*, c.name AS customer_name, u.name AS salesman_name
            FROM orders o
            JOIN customers c ON c.id=o.customer_id
            JOIN users u ON u.id=o.salesman_id
            ORDER BY o.created_at DESC LIMIT 8
        """)
        dashboard_data["recent_runs"] = fetch_all("""
            SELECT r.run_number, r.production_date,
                   r.actual_good_packets, p.name AS product_name
            FROM production_runs r
            JOIN products p ON p.id=r.product_id
            WHERE r.status='posted'
            ORDER BY r.id DESC LIMIT 5
        """)

    else:
        abort(403)

    return render_template(
        "dashboard.html",
        dashboard_data=dashboard_data,
        today=today,
        month_start=month_start
    )



@app.route("/masters", methods=["GET", "POST"])
@login_required
@roles_required("admin", "owner")
def masters():
    if request.method == "POST":
        action = request.form.get("action")

        try:
            with db() as connection:
                if action == "product":
                    name = request.form["name"].strip()
                    price = money_to_paise(request.form.get("price_paise", "0"))
                    hsn = request.form.get("hsn", "").strip()
                    gst = int(request.form.get("gst_rate_bps", "500"))
                    cursor = connection.execute(
                        """
                        INSERT INTO products
                        (name, selling_price_paise, hsn, gst_rate_bps)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, price, hsn, gst),
                    )
                    write_audit(connection, "products", cursor.lastrowid,
                                "create", new_values={"name": name},
                                user_id=current_user_id())
                    flash("Product added successfully.", "success")

                elif action == "customer":
                    cursor = connection.execute(
                        """
                        INSERT INTO customers
                        (name, phone, state, gstin, address)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            request.form["name"].strip(),
                            request.form.get("phone", "").strip(),
                            request.form.get("state", "Tamil Nadu").strip(),
                            request.form.get("gstin", "").strip(),
                            request.form.get("address", "").strip(),
                        ),
                    )
                    write_audit(connection, "customers", cursor.lastrowid,
                                "create", user_id=current_user_id())
                    flash("Customer added successfully.", "success")

                elif action == "material":
                    cursor = connection.execute(
                        """
                        INSERT INTO materials (name, unit, hsn)
                        VALUES (?, ?, ?)
                        """,
                        (
                            request.form["name"].strip(),
                            request.form["unit"],
                            request.form.get("hsn", "").strip(),
                        ),
                    )
                    write_audit(connection, "materials", cursor.lastrowid,
                                "create", user_id=current_user_id())
                    flash("Raw material added successfully.", "success")

                elif action == "bom":
                    product_id = int(request.form["product_id"])
                    batch_size = int(
                        request.form.get("batch_size_packets")
                        or request.form.get("batch_size")
                    )
                    expected_yield = int(
                        request.form.get("expected_yield_packets")
                        or request.form.get("expected_yield")
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO bom
                        (product_id, batch_name, batch_size_packets,
                         expected_yield_packets)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            product_id,
                            request.form.get("batch_name", "Standard batch"),
                            batch_size,
                            expected_yield,
                        ),
                    )
                    bom_id = cursor.lastrowid

                    lines_text = request.form.get("bom_lines", "").strip()
                    if lines_text:
                        for line in lines_text.splitlines():
                            if "=" not in line:
                                continue
                            material_id, quantity = line.split("=", 1)
                            connection.execute(
                                """
                                INSERT INTO bom_lines (bom_id, material_id, quantity)
                                VALUES (?, ?, ?)
                                """,
                                (bom_id, int(material_id.strip()),
                                 decimal_text(quantity.strip())),
                            )
                    else:
                        ids = request.form.getlist("material_id[]")
                        quantities = request.form.getlist("quantity[]")
                        for material_id, quantity in zip(ids, quantities):
                            connection.execute(
                                """
                                INSERT INTO bom_lines (bom_id, material_id, quantity)
                                VALUES (?, ?, ?)
                                """,
                                (bom_id, int(material_id), decimal_text(quantity)),
                            )

                    write_audit(connection, "bom", bom_id, "create",
                                user_id=current_user_id())
                    flash("Bill of Materials created.", "success")

                else:
                    flash("Unknown master action.", "warning")

        except (ValueError, KeyError, InvalidOperation, sqlite3.Error) as error:
            flash(f"Could not save record: {error}", "danger")

        return redirect(url_for("masters"))

    products = fetch_all("SELECT * FROM products ORDER BY name")
    customers = fetch_all("SELECT * FROM customers ORDER BY name")
    materials = fetch_all("SELECT * FROM materials ORDER BY name")
    boms = fetch_all(
        """
        SELECT b.*, p.name AS product_name
        FROM bom b JOIN products p ON p.id=b.product_id
        ORDER BY b.id DESC
        """
    )
    return render_template(
        "masters.html",
        products=products,
        customers=customers,
        materials=materials,
        boms=boms,
    )


@app.route("/orders")
@login_required
def orders():
    sql = """
        SELECT o.*, c.name AS customer_name, u.name AS salesman_name,
               i.id AS invoice_id
        FROM orders o
        JOIN customers c ON c.id=o.customer_id
        JOIN users u ON u.id=o.salesman_id
        LEFT JOIN invoices i ON i.order_id=o.id
    """
    params = ()
    if session.get("role") == "salesman":
        sql += " WHERE o.salesman_id=?"
        params = (current_user_id(),)
    sql += " ORDER BY o.created_at DESC"

    return render_template("orders.html", orders=fetch_all(sql, params))


@app.route("/orders/new", methods=["GET", "POST"])
@login_required
@roles_required("salesman", "admin", "owner")
def order_new():
    if request.method == "POST":
        customer_id = int(request.form["customer_id"])
        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")

        valid_lines = []
        for product_id, quantity in zip(product_ids, quantities):
            if not product_id or not quantity:
                continue
            qty = int(quantity)
            if qty <= 0:
                continue
            product = fetch_one(
                "SELECT id, selling_price_paise FROM products WHERE id=? AND active=1",
                (int(product_id),),
            )
            if product:
                valid_lines.append((product["id"], qty, product["selling_price_paise"]))

        if not valid_lines:
            flash("Add at least one valid product and quantity.", "warning")
            return redirect(url_for("order_new"))

        try:
            with db() as connection:
                order_number = next_number(connection, "orders", "order_number", "ORD")
                cursor = connection.execute(
                    """
                    INSERT INTO orders
                    (order_number, customer_id, salesman_id, status, order_date, notes)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        order_number, customer_id, current_user_id(),
                        date.today().isoformat(),
                        request.form.get("notes", "").strip(),
                    ),
                )
                order_id = cursor.lastrowid

                for product_id, quantity, price in valid_lines:
                    connection.execute(
                        """
                        INSERT INTO order_lines
                        (order_id, product_id, quantity_packets, unit_price_paise)
                        VALUES (?, ?, ?, ?)
                        """,
                        (order_id, product_id, quantity, price),
                    )

                write_audit(connection, "orders", order_id, "create",
                            user_id=current_user_id())
            flash("Order submitted for approval.", "success")
            return redirect(url_for("orders"))
        except (ValueError, sqlite3.Error) as error:
            flash(f"Could not create order: {error}", "danger")

    return render_template(
        "order_new.html",
        customers=fetch_all("SELECT * FROM customers WHERE active=1 ORDER BY name"),
        products=fetch_all("SELECT * FROM products WHERE active=1 ORDER BY name"),
        today=date.today().isoformat(),
    )


@app.route("/orders/<int:order_id>/approve", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def approve_order(order_id):
    with db() as connection:
        order = connection.execute(
            "SELECT * FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        if not order or order["status"] != "pending":
            flash("This order cannot be approved.", "warning")
            return redirect(url_for("orders"))

        shortages = []
        for line in get_order_lines(connection, order_id):
            available = stock_balance(connection, "product", line["product_id"])
            required = Decimal(str(line["quantity_packets"]))
            if available < required:
                shortages.append(
                    f"{line['product_name']}: need {required}, available {available}"
                )

        if shortages:
            flash("Insufficient finished stock — " + "; ".join(shortages), "danger")
            return redirect(url_for("orders"))

        connection.execute(
            """
            UPDATE orders SET status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (current_user_id(), order_id),
        )
        write_audit(connection, "orders", order_id, "update",
                    old_values={"status": "pending"},
                    new_values={"status": "approved"},
                    user_id=current_user_id())

    flash("Order approved.", "success")
    return redirect(url_for("orders"))


@app.route("/orders/<int:order_id>/reject", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def reject_order(order_id):
    with db() as connection:
        order = connection.execute(
            "SELECT status FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        if not order or order["status"] != "pending":
            flash("Only pending orders can be rejected.", "warning")
        else:
            connection.execute(
                "UPDATE orders SET status='rejected' WHERE id=?", (order_id,)
            )
            write_audit(connection, "orders", order_id, "update",
                        old_values={"status": "pending"},
                        new_values={"status": "rejected"},
                        user_id=current_user_id())
            flash("Order rejected.", "success")
    return redirect(url_for("orders"))


@app.route("/orders/<int:order_id>/invoice", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def create_invoice(order_id):
    with db() as connection:
        order = connection.execute(
            """
            SELECT o.*, c.state, c.gstin, c.name AS customer_name
            FROM orders o JOIN customers c ON c.id=o.customer_id
            WHERE o.id=?
            """,
            (order_id,),
        ).fetchone()

        if not order or order["status"] != "approved":
            flash("Only approved orders can be invoiced.", "warning")
            return redirect(url_for("orders"))

        lines = get_order_lines(connection, order_id)
        invoice_number, fy, sequence = next_invoice_number(connection)
        taxable_total = cgst_total = sgst_total = igst_total = total = 0
        line_data = []

        for line in lines:
            taxable = int(line["unit_price_paise"]) * int(line["quantity_packets"])
            gst = calculate_gst(
                taxable, int(line["gst_rate_bps"] or 0),
                order["state"], FACTORY_STATE
            )
            cgst = int(gst.get("cgst_paise", 0))
            sgst = int(gst.get("sgst_paise", 0))
            igst = int(gst.get("igst_paise", 0))
            line_total = taxable + cgst + sgst + igst

            taxable_total += taxable
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst
            total += line_total

            line_data.append((line, taxable, cgst, sgst, igst))

        cursor = connection.execute(
            """
            INSERT INTO invoices
            (invoice_number, financial_year, sequence_number, order_id,
             customer_id, invoice_date, customer_gstin, customer_state,
             taxable_value_paise, cgst_paise, sgst_paise, igst_paise,
             total_paise, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?)
            """,
            (
                invoice_number, fy, sequence, order_id, order["customer_id"],
                date.today().isoformat(), order["gstin"], order["state"],
                taxable_total, cgst_total, sgst_total, igst_total, total,
                current_user_id(),
            ),
        )
        invoice_id = cursor.lastrowid

        for line, taxable, cgst, sgst, igst in line_data:
            connection.execute(
                """
                INSERT INTO invoice_lines
                (invoice_id, product_id, description, hsn, quantity_packets,
                 unit_price_paise, taxable_value_paise, gst_rate_bps,
                 cgst_paise, sgst_paise, igst_paise)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id, line["product_id"], line["product_name"],
                    line["hsn"], line["quantity_packets"],
                    line["unit_price_paise"], taxable, line["gst_rate_bps"],
                    cgst, sgst, igst,
                ),
            )

        connection.execute(
            "UPDATE orders SET status='invoiced' WHERE id=?", (order_id,)
        )
        write_audit(connection, "invoices", invoice_id, "post",
                    new_values={"invoice_number": invoice_number},
                    user_id=current_user_id())

    flash(f"Invoice {invoice_number} created.", "success")
    return redirect(url_for("invoice", invoice_id=invoice_id))


@app.route("/invoice/<int:invoice_id>")
@login_required
def invoice(invoice_id):
    invoice_row = fetch_one(
        """
        SELECT i.*, o.order_number
        FROM invoices i JOIN orders o ON o.id=i.order_id
        WHERE i.id=?
        """,
        (invoice_id,),
    )
    if not invoice_row:
        abort(404)

    customer = fetch_one("SELECT * FROM customers WHERE id=?",
                         (invoice_row["customer_id"],))
    items = fetch_all(
        "SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice_id,)
    )
    is_dispatched = fetch_one(
        "SELECT id FROM dispatches WHERE invoice_id=?", (invoice_id,)
    ) is not None
    has_payments = fetch_one(
        "SELECT id FROM payments WHERE invoice_id=? LIMIT 1", (invoice_id,)
    ) is not None
    return render_template(
        "invoice.html",
        invoice=invoice_row,
        customer=customer,
        items=items,
        company_gstin=os.environ.get("COMPANY_GSTIN", ""),
        today=date.today().isoformat(),
        is_dispatched=is_dispatched,
        has_payments=has_payments,
    )


@app.route("/invoice/<int:invoice_id>/pdf")
@login_required
def invoice_pdf(invoice_id):
    invoice_row = fetch_one(
        """
        SELECT i.*, o.order_number, c.name AS customer_name,
               c.address, c.state, c.gstin
        FROM invoices i
        JOIN orders o ON o.id=i.order_id
        JOIN customers c ON c.id=i.customer_id
        WHERE i.id=?
        """,
        (invoice_id,),
    )
    if not invoice_row:
        abort(404)

    items = fetch_all(
        "SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice_id,)
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    content = [
        Paragraph("<b>ORDER-TO-AUDIT</b>", styles["Title"]),
        Paragraph("GST TAX INVOICE", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph(f"Invoice: {invoice_row['invoice_number']}", styles["Normal"]),
        Paragraph(f"Date: {invoice_row['invoice_date']}", styles["Normal"]),
        Paragraph(f"Customer: {invoice_row['customer_name']}", styles["Normal"]),
        Paragraph(f"State: {invoice_row['state']}", styles["Normal"]),
        Paragraph(f"GSTIN: {invoice_row['gstin'] or '-'}", styles["Normal"]),
        Spacer(1, 14),
    ]

    data = [["Product", "HSN", "Qty", "Rate", "Taxable"]]
    for item in items:
        data.append([
            item["description"], item["hsn"] or "-",
            str(item["quantity_packets"]),
            money_text(item["unit_price_paise"]),
            money_text(item["taxable_value_paise"]),
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263746")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    content.extend([
        table, Spacer(1, 14),
        Paragraph(f"Taxable value: {money_text(invoice_row['taxable_value_paise'])}", styles["Normal"]),
        Paragraph(f"CGST: {money_text(invoice_row['cgst_paise'])}", styles["Normal"]),
        Paragraph(f"SGST: {money_text(invoice_row['sgst_paise'])}", styles["Normal"]),
        Paragraph(f"IGST: {money_text(invoice_row['igst_paise'])}", styles["Normal"]),
        Paragraph(f"<b>Total: {money_text(invoice_row['total_paise'])}</b>", styles["Heading2"]),
    ])
    document.build(content)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{invoice_row['invoice_number'].replace('/', '-')}.pdf",
        mimetype="application/pdf",
    )


@app.route("/invoice/<int:invoice_id>/dispatch", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def dispatch_invoice(invoice_id):
    dispatch_date = request.form.get("dispatch_date") or date.today().isoformat()
    try:
        date.fromisoformat(dispatch_date)
    except ValueError:
        flash("Please enter a valid dispatch date.", "danger")
        return redirect(url_for("invoice", invoice_id=invoice_id))

    with db() as connection:
        invoice_row = connection.execute(
            "SELECT * FROM invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        if not invoice_row or invoice_row["status"] != "posted":
            flash("This invoice cannot be dispatched.", "warning")
            return redirect(url_for("orders"))

        existing = connection.execute(
            "SELECT id FROM dispatches WHERE invoice_id=?", (invoice_id,)
        ).fetchone()
        if existing:
            flash("This invoice has already been dispatched.", "warning")
            return redirect(url_for("invoice", invoice_id=invoice_id))

        lines = connection.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id=?", (invoice_id,)
        ).fetchall()
        if not lines:
            flash("This invoice has no line items and cannot be dispatched.", "danger")
            return redirect(url_for("invoice", invoice_id=invoice_id))

        for line in lines:
            available = stock_balance(connection, "product", line["product_id"])
            required = Decimal(str(line["quantity_packets"]))
            if available < required:
                flash(
                    f"Insufficient stock for {line['description']}. "
                    f"Available: {available}, required: {required}.",
                    "danger",
                )
                return redirect(url_for("invoice", invoice_id=invoice_id))

        cursor = connection.execute(
            """
            INSERT INTO dispatches
            (invoice_id, dispatch_date, vehicle_number, dispatched_by, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                invoice_id, dispatch_date,
                request.form.get("vehicle_number", "").strip(),
                current_user_id(), request.form.get("notes", "").strip(),
            ),
        )
        dispatch_id = cursor.lastrowid

        for line in lines:
            record_stock_movement(
                connection, "product", line["product_id"],
                Decimal(str(line["quantity_packets"])), "OUT",
                "dispatch", dispatch_id, current_user_id(),
                dispatch_date, f"Invoice {invoice_row['invoice_number']}",
            )

        connection.execute(
            "UPDATE orders SET status='dispatched' WHERE id=?",
            (invoice_row["order_id"],),
        )
        write_audit(
            connection, "dispatches", dispatch_id, "post",
            new_values={"invoice_id": invoice_id, "dispatch_date": dispatch_date},
            user_id=current_user_id(),
        )

    flash("Dispatch recorded and finished stock reduced.", "success")
    return redirect(url_for("invoice", invoice_id=invoice_id))


@app.route("/production", methods=["GET", "POST"])
@login_required
@roles_required("production", "admin", "owner")
def production():
    if request.method == "POST":
        connection = db()
        try:
            bom_id = int(request.form["bom_id"])
            bom = connection.execute("SELECT * FROM bom WHERE id=?", (bom_id,)).fetchone()
            if not bom:
                raise ValueError("Selected BOM was not found.")

            planned_packets = int(request.form.get("planned_packets") or bom["batch_size_packets"])
            actual_good_packets = int(request.form["actual_good_packets"])
            damaged_pouches = int(request.form.get("damaged_pouches", 0) or 0)
            cartons_used = int(request.form.get("cartons_used", 0) or 0)
            labour_cost = money_to_paise(request.form.get("labour_cost", "0") or "0")
            power_cost = money_to_paise(request.form.get("power_gas_cost", "0") or "0")

            material_actuals = {}
            material_ids = request.form.getlist("material_id[]")
            actual_quantities = request.form.getlist("actual_quantity[]")
            for material_id, quantity in zip(material_ids, actual_quantities):
                if material_id and quantity and quantity.strip():
                    material_actuals[int(material_id)] = Decimal(quantity)

            raw_json = request.form.get("material_actuals")
            if raw_json:
                material_actuals.update({
                    int(key): Decimal(str(value))
                    for key, value in json.loads(raw_json).items()
                })

            run_number = f"RUN-{datetime.now():%Y%m%d%H%M%S%f}"
            result = post_production_run(
                connection=connection,
                bom_id=bom_id,
                product_id=bom["product_id"],
                planned_packets=planned_packets,
                actual_good_packets=actual_good_packets,
                material_actuals=material_actuals,
                damaged_pouches=damaged_pouches,
                cartons_used=cartons_used,
                labour_cost_paise=labour_cost,
                power_gas_cost_paise=power_cost,
                user_id=current_user_id(),
                production_date=date.today().isoformat(),
                run_number=run_number,
            )
            write_audit(
                connection, "production_runs", result["run_id"], "post",
                new_values={
                    "run_number": run_number,
                    "planned_packets": planned_packets,
                    "actual_good_packets": actual_good_packets,
                    "material_actuals": {str(k): str(v) for k, v in material_actuals.items()},
                    "yield_variance": result["yield_variance"],
                },
                user_id=current_user_id(),
            )
            connection.commit()
            flash("Production run posted successfully.", "success")
        except (ValueError, KeyError, InvalidOperation, sqlite3.Error, TypeError) as error:
            connection.rollback()
            flash(f"Production could not be posted: {error}", "danger")
        finally:
            connection.close()
        return redirect(url_for("production"))

    return render_template(
        "production.html",
        boms=fetch_all(
            """
            SELECT b.*, p.name AS product_name
            FROM bom b JOIN products p ON p.id=b.product_id
            WHERE b.active=1 ORDER BY p.name
            """
        ),
        materials=fetch_all("SELECT * FROM materials WHERE active=1 ORDER BY name"),
        runs=fetch_all(
            """
            SELECT r.*, p.name AS product_name
            FROM production_runs r JOIN products p ON p.id=r.product_id
            ORDER BY r.created_at DESC LIMIT 30
            """
        ),
        today=date.today().isoformat(),
    )


@app.route("/inventory")
@login_required
@roles_required("admin", "production", "accountant", "owner")
def inventory():
    connection = db()
    try:
        material_stock = []
        for item in connection.execute(
            "SELECT * FROM materials WHERE active=1 ORDER BY name"
        ).fetchall():
            material_stock.append({
                "id": item["id"],
                "name": item["name"],
                "unit": item["unit"],
                "balance": stock_balance(connection, "material", item["id"]),
            })

        product_stock = []
        for item in connection.execute(
            "SELECT * FROM products WHERE active=1 ORDER BY name"
        ).fetchall():
            product_stock.append({
                "id": item["id"],
                "name": item["name"],
                "unit": "packet",
                "balance": stock_balance(connection, "product", item["id"]),
            })

        ledger = connection.execute(
            """
            SELECT sl.*, 
                CASE WHEN sl.item_type='material' THEN m.name ELSE p.name END AS item_name,
                u.name AS user_name
            FROM stock_ledger sl
            LEFT JOIN materials m ON sl.item_type='material' AND sl.item_id=m.id
            LEFT JOIN products p ON sl.item_type='product' AND sl.item_id=p.id
            LEFT JOIN users u ON u.id=sl.user_id
            ORDER BY sl.movement_date DESC, sl.id DESC LIMIT 100
            """
        ).fetchall()
    finally:
        connection.close()

    return render_template(
        "inventory.html",
        material_stock=material_stock,
        product_stock=product_stock,
        ledger=ledger,
    )


@app.route("/payments")
@login_required
@roles_required("admin", "accountant", "owner")
def payments():
    invoices = fetch_all(
        """
        SELECT i.id, i.invoice_number, c.name AS customer_name,
               i.total_paise,
               COALESCE(SUM(p.amount_paise),0) AS received_paise,
               i.total_paise-COALESCE(SUM(p.amount_paise),0) AS balance_paise
        FROM invoices i
        JOIN customers c ON c.id=i.customer_id
        LEFT JOIN payments p ON p.invoice_id=i.id
        WHERE i.status='posted'
        GROUP BY i.id
        HAVING balance_paise > 0
        ORDER BY i.invoice_date
        """
    )
    payments_list = fetch_all(
        """
        SELECT p.*, i.invoice_number, c.name AS customer_name,
               p.reference_number AS reference
        FROM payments p
        JOIN invoices i ON i.id=p.invoice_id
        JOIN customers c ON c.id=i.customer_id
        ORDER BY p.payment_date DESC, p.id DESC
        """
    )

    total_invoiced = fetch_one(
        "SELECT COALESCE(SUM(total_paise),0) AS n FROM invoices WHERE status='posted'"
    )["n"]
    total_received = fetch_one(
        """SELECT COALESCE(SUM(p.amount_paise),0) AS n
           FROM payments p JOIN invoices i ON i.id=p.invoice_id
           WHERE i.status='posted'"""
    )["n"]

    outstanding_customers = fetch_all(
        """
        SELECT c.name AS customer_name,
               SUM(i.total_paise) AS total_paise,
               COALESCE(SUM(p.paid),0) AS received_paise,
               SUM(i.total_paise)-COALESCE(SUM(p.paid),0) AS balance_paise
        FROM invoices i
        JOIN customers c ON c.id=i.customer_id
        LEFT JOIN (
            SELECT invoice_id, SUM(amount_paise) AS paid
            FROM payments GROUP BY invoice_id
        ) p ON p.invoice_id=i.id
        WHERE i.status='posted'
        GROUP BY c.id
        HAVING balance_paise > 0
        ORDER BY balance_paise DESC
        """
    )

    return render_template(
        "payments.html",
        total_invoiced=total_invoiced,
        total_received=total_received,
        outstanding=total_invoiced - total_received,
        invoices=invoices,
        today=date.today().isoformat(),
        outstanding_customers=outstanding_customers,
        payments=payments_list,
    )


@app.route("/payments/add", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def add_payment():
    try:
        invoice_id = int(request.form["invoice_id"])
        amount = money_to_paise(request.form["amount_rupees"])
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        with db() as connection:
            invoice_row = connection.execute(
                "SELECT total_paise FROM invoices WHERE id=? AND status='posted'",
                (invoice_id,),
            ).fetchone()
            if not invoice_row:
                raise ValueError("Invoice not found.")

            paid = connection.execute(
                "SELECT COALESCE(SUM(amount_paise),0) AS n FROM payments WHERE invoice_id=?",
                (invoice_id,),
            ).fetchone()["n"]
            balance = invoice_row["total_paise"] - paid

            if amount > balance:
                raise ValueError(f"Payment exceeds outstanding balance of {money_text(balance)}.")

            cursor = connection.execute(
                """
                INSERT INTO payments
                (invoice_id, payment_date, amount_paise, payment_mode,
                 reference_number, received_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    request.form.get("payment_date") or date.today().isoformat(),
                    amount,
                    request.form.get("payment_mode", "Cash"),
                    request.form.get("reference", "").strip(),
                    current_user_id(),
                ),
            )
            write_audit(connection, "payments", cursor.lastrowid, "create",
                        user_id=current_user_id())
        flash("Payment recorded successfully.", "success")
    except (ValueError, KeyError, InvalidOperation, sqlite3.Error) as error:
        flash(str(error), "danger")

    return redirect(url_for("payments"))


@app.route("/purchases")
@login_required
@roles_required("admin", "accountant", "owner")
def purchases():
    start_date = request.args.get("from_date", "").strip()
    end_date = request.args.get("to_date", "").strip()
    sql = """
        SELECT pu.*, COALESCE(SUM(pl.taxable_value_paise + pl.gst_paise), 0)
            AS total_amount_paise
        FROM purchases pu
        LEFT JOIN purchase_lines pl ON pl.purchase_id=pu.id
    """
    conditions, params = [], []
    if start_date:
        conditions.append("pu.purchase_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("pu.purchase_date <= ?")
        params.append(end_date)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " GROUP BY pu.id ORDER BY pu.purchase_date DESC, pu.id DESC"
    return render_template("purchases.html", purchases=fetch_all(sql, params))


@app.route("/purchases/new", methods=["GET", "POST"])
@login_required
@roles_required("admin", "owner")
def purchase_new():
    if request.method == "GET":
        return render_template(
            "purchase_new.html",
            materials=fetch_all("SELECT * FROM materials WHERE active=1 ORDER BY name"),
            today=date.today().isoformat(),
        )

    connection = db()
    try:
        supplier = request.form.get("supplier_name", "").strip()
        if not supplier:
            raise ValueError("Supplier name is required.")
        material_ids = request.form.getlist("material_id[]")
        quantities = request.form.getlist("quantity[]")
        units = request.form.getlist("unit[]")
        rates = request.form.getlist("rate[]")
        gst_rates = request.form.getlist("gst[]")
        if not material_ids:
            raise ValueError("Add at least one purchase line.")

        purchase_date = request.form.get("purchase_date") or date.today().isoformat()
        purchase_number = next_number(connection, "purchases", "purchase_number", "PUR")
        cursor = connection.execute(
            """INSERT INTO purchases
            (purchase_number, supplier_name, purchase_date, reference_number, created_by)
            VALUES (?, ?, ?, ?, ?)""",
            (purchase_number, supplier, purchase_date,
             request.form.get("reference_number", "").strip(), current_user_id()),
        )
        purchase_id = cursor.lastrowid
        from logic import convert_quantity
        for material_id_text, qty_text, unit_text, rate_text, gst_text in zip(
            material_ids, quantities, units, rates, gst_rates
        ):
            if not material_id_text:
                continue
            material_id = int(material_id_text)
            material = connection.execute(
                "SELECT * FROM materials WHERE id=? AND active=1", (material_id,)
            ).fetchone()
            if not material:
                raise ValueError("One selected material is unavailable.")
            quantity = Decimal(qty_text)
            if quantity <= 0:
                raise ValueError(f"Enter a positive quantity for {material['name']}.")
            entered_unit = unit_text or material["unit"]
            unit_factor = convert_quantity(Decimal("1"), entered_unit, material["unit"])
            quantity = quantity * unit_factor
            entered_rate_paise = money_to_paise(rate_text)
            rate_paise = int((Decimal(entered_rate_paise) / unit_factor).quantize(Decimal("1")))
            gst_percent = Decimal(gst_text or "0")
            if rate_paise < 0 or gst_percent < 0 or gst_percent > 100:
                raise ValueError("Enter a valid rate and GST percentage.")
            taxable = int((quantity * Decimal(rate_paise)).quantize(Decimal("1")))
            gst_amount = int((Decimal(taxable) * gst_percent / Decimal("100")).quantize(Decimal("1")))
            connection.execute(
                """INSERT INTO purchase_lines
                (purchase_id, material_id, quantity, rate_paise, taxable_value_paise, gst_paise)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (purchase_id, material_id, decimal_text(quantity), rate_paise, taxable, gst_amount),
            )
            record_stock_movement(
                connection, "material", material_id, quantity, "IN", "purchase",
                purchase_id, current_user_id(), purchase_date,
                f"Purchase {purchase_number}",
            )
        if not connection.execute(
            "SELECT 1 FROM purchase_lines WHERE purchase_id=?", (purchase_id,)
        ).fetchone():
            raise ValueError("At least one valid material line is required.")
        write_audit(connection, "purchases", purchase_id, "create",
                    new_values={"purchase_number": purchase_number},
                    user_id=current_user_id())
        connection.commit()
        flash(f"Purchase {purchase_number} saved and stock updated.", "success")
        return redirect(url_for("purchase_detail", purchase_id=purchase_id))
    except (ValueError, KeyError, InvalidOperation, sqlite3.Error) as error:
        connection.rollback()
        flash(f"Purchase could not be saved: {error}", "danger")
        return redirect(url_for("purchase_new"))
    finally:
        connection.close()


@app.route("/purchases/<int:purchase_id>")
@login_required
@roles_required("admin", "accountant", "owner")
def purchase_detail(purchase_id):
    purchase = fetch_one(
        """SELECT pu.*, COALESCE(SUM(pl.taxable_value_paise + pl.gst_paise), 0)
        AS total_amount_paise FROM purchases pu
        LEFT JOIN purchase_lines pl ON pl.purchase_id=pu.id
        WHERE pu.id=? GROUP BY pu.id""", (purchase_id,)
    )
    if not purchase:
        abort(404)
    lines = fetch_all(
        """SELECT pl.*, m.name AS material_name
        FROM purchase_lines pl JOIN materials m ON m.id=pl.material_id
        WHERE pl.purchase_id=? ORDER BY pl.id""", (purchase_id,)
    )
    return render_template("purchase_detail.html", purchase=purchase, purchase_lines=lines)


@app.route("/purchases/add", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def add_purchase():
    try:
        material_id = int(request.form["material_id"])
        quantity = Decimal(request.form["quantity"])
        rate_paise = money_to_paise(request.form["rate_rupees"])
        if quantity <= 0 or rate_paise < 0:
            raise ValueError("Enter a valid quantity and rate.")

        with db() as connection:
            purchase_number = next_number(connection, "purchases", "purchase_number", "PUR")
            cursor = connection.execute(
                """
                INSERT INTO purchases
                (purchase_number, supplier_name, purchase_date, reference_number, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    purchase_number,
                    request.form.get("supplier_name", "").strip(),
                    request.form.get("purchase_date") or date.today().isoformat(),
                    request.form.get("reference_number", "").strip(),
                    current_user_id(),
                ),
            )
            purchase_id = cursor.lastrowid
            taxable = int((quantity * Decimal(rate_paise)).quantize(Decimal("1")))
            connection.execute(
                """
                INSERT INTO purchase_lines
                (purchase_id, material_id, quantity, rate_paise, taxable_value_paise, gst_paise)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (purchase_id, material_id, decimal_text(quantity),
                 rate_paise, taxable),
            )
            record_stock_movement(
                connection, "material", material_id, quantity, "IN",
                "purchase", purchase_id, current_user_id(),
                request.form.get("purchase_date") or date.today().isoformat(),
                f"Purchase {purchase_number}",
            )
            write_audit(connection, "purchases", purchase_id, "create",
                        user_id=current_user_id())
        flash("Purchase saved and raw-material stock updated.", "success")
    except (ValueError, KeyError, InvalidOperation, sqlite3.Error) as error:
        flash(f"Purchase could not be saved: {error}", "danger")

    return redirect(url_for("inventory"))


@app.route("/reports")
@login_required
@roles_required("admin", "accountant", "owner")
def reports():
    start = request.args.get("from_date") or date.today().replace(day=1).isoformat()
    end = request.args.get("to_date") or date.today().isoformat()
    try:
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        if start_day > end_day:
            raise ValueError
    except ValueError:
        flash("Please choose a valid date range.", "warning")
        start = date.today().replace(day=1).isoformat()
        end = date.today().isoformat()

    sales_rows = fetch_all(
        """
        SELECT i.*, c.name AS customer_name
        FROM invoices i JOIN customers c ON c.id=i.customer_id
        WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
        ORDER BY i.invoice_date DESC, i.id DESC
        """, (start, end),
    )
    purchase_rows = fetch_all(
        """
        SELECT pu.purchase_date, pu.purchase_number, m.name AS material_name,
               m.unit, pl.quantity, pl.rate_paise,
               pl.taxable_value_paise AS total_amount_paise
        FROM purchase_lines pl
        JOIN purchases pu ON pu.id=pl.purchase_id
        JOIN materials m ON m.id=pl.material_id
        WHERE pu.purchase_date BETWEEN ? AND ?
        ORDER BY pu.purchase_date DESC, pu.id DESC
        """, (start, end),
    )
    production_rows = fetch_all(
        """
        SELECT r.*, p.name AS product_name,
               CASE WHEN r.planned_packets > 0
                    THEN ROUND((r.actual_good_packets-r.planned_packets)*100.0/r.planned_packets,2)
                    ELSE 0 END AS variance_percent,
               CASE WHEN r.planned_packets > 0
                    AND ABS((r.actual_good_packets-r.planned_packets)*100.0/r.planned_packets)>3
                    THEN 1 ELSE 0 END AS flagged
        FROM production_runs r JOIN products p ON p.id=r.product_id
        WHERE r.production_date BETWEEN ? AND ? AND r.status='posted'
        ORDER BY r.production_date DESC, r.id DESC
        """, (start, end),
    )
    outstanding_rows = fetch_all(
        """
        SELECT c.id AS customer_id, c.name AS customer_name,
               SUM(i.total_paise) AS total_paise,
               COALESCE(SUM(pay.received),0) AS received_paise,
               SUM(i.total_paise)-COALESCE(SUM(pay.received),0) AS balance_paise
        FROM invoices i
        JOIN customers c ON c.id=i.customer_id
        LEFT JOIN (
            SELECT invoice_id, SUM(amount_paise) AS received
            FROM payments GROUP BY invoice_id
        ) pay ON pay.invoice_id=i.id
        WHERE i.status='posted'
        GROUP BY c.id, c.name
        HAVING balance_paise > 0
        ORDER BY balance_paise DESC
        """
    )
    customer_sales_rows = fetch_all(
        """
        SELECT c.name AS customer_name, COUNT(i.id) AS invoice_count,
               SUM(i.taxable_value_paise) AS taxable_paise,
               SUM(i.total_paise) AS total_paise
        FROM invoices i JOIN customers c ON c.id=i.customer_id
        WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
        GROUP BY c.id, c.name ORDER BY total_paise DESC
        """, (start, end),
    )
    product_sales_rows = fetch_all(
        """
        SELECT p.name AS product_name, SUM(il.quantity_packets) AS quantity_packets,
               SUM(il.taxable_value_paise) AS taxable_paise
        FROM invoice_lines il
        JOIN invoices i ON i.id=il.invoice_id
        JOIN products p ON p.id=il.product_id
        WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
        GROUP BY p.id, p.name ORDER BY taxable_paise DESC
        """, (start, end),
    )
    gst_rate_rows = fetch_all(
        """
        SELECT il.gst_rate_bps, i.customer_state,
               SUM(il.taxable_value_paise) AS taxable_paise,
               SUM(il.cgst_paise) AS cgst_paise,
               SUM(il.sgst_paise) AS sgst_paise,
               SUM(il.igst_paise) AS igst_paise
        FROM invoice_lines il JOIN invoices i ON i.id=il.invoice_id
        WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
        GROUP BY il.gst_rate_bps, i.customer_state
        ORDER BY il.gst_rate_bps, i.customer_state
        """, (start, end),
    )
    material_variance_rows = fetch_all(
        """
        SELECT r.run_number, r.production_date, p.name AS product_name,
               m.name AS material_name, m.unit,
               pm.planned_quantity, pm.actual_quantity
        FROM production_materials pm
        JOIN production_runs r ON r.id=pm.production_run_id
        JOIN products p ON p.id=r.product_id
        JOIN materials m ON m.id=pm.material_id
        WHERE r.production_date BETWEEN ? AND ? AND r.status='posted'
        ORDER BY r.production_date DESC, r.id DESC, m.name
        """, (start, end),
    )

    material_stock = []
    product_stock = []
    stock_connection = db()
    try:
        for item in stock_connection.execute(
            "SELECT id, name, unit FROM materials WHERE active=1 ORDER BY name"
        ).fetchall():
            material_stock.append({
                "name": item["name"], "unit": item["unit"],
                "balance": str(get_stock_balance(stock_connection, "material", item["id"]))
            })
        for item in stock_connection.execute(
            "SELECT id, name, unit FROM products WHERE active=1 ORDER BY name"
        ).fetchall():
            product_stock.append({
                "name": item["name"], "unit": item["unit"],
                "balance": str(get_stock_balance(stock_connection, "product", item["id"]))
            })
    finally:
        stock_connection.close()

    payment_total = fetch_one(
        """SELECT COALESCE(SUM(p.amount_paise),0) AS n
           FROM payments p JOIN invoices i ON i.id=p.invoice_id
           WHERE p.payment_date BETWEEN ? AND ? AND i.status='posted'""",
        (start, end),
    )["n"]
    sales_total = sum(row["total_paise"] for row in sales_rows)
    purchase_total = sum(row["total_amount_paise"] for row in purchase_rows)
    outstanding_total = sum(row["balance_paise"] for row in outstanding_rows)
    gst_summary = {
        "taxable": sum(row["taxable_value_paise"] for row in sales_rows),
        "cgst": sum(row["cgst_paise"] for row in sales_rows),
        "sgst": sum(row["sgst_paise"] for row in sales_rows),
        "igst": sum(row["igst_paise"] for row in sales_rows),
    }

    ageing_rows = []
    today = date.today()
    for row in fetch_all(
        """
        SELECT i.id, i.invoice_number, i.invoice_date, c.name AS customer_name,
               i.total_paise-COALESCE(p.received,0) AS balance_paise
        FROM invoices i JOIN customers c ON c.id=i.customer_id
        LEFT JOIN (SELECT invoice_id, SUM(amount_paise) AS received
                   FROM payments GROUP BY invoice_id) p ON p.invoice_id=i.id
        WHERE i.status='posted'
        ORDER BY i.invoice_date
        """
    ):
        if row["balance_paise"] <= 0:
            continue
        try:
            age = max(0, (today - date.fromisoformat(row["invoice_date"])).days)
        except ValueError:
            age = 0
        bucket = "0-30 days" if age <= 30 else "31-60 days" if age <= 60 else "61-90 days" if age <= 90 else "Over 90 days"
        ageing_rows.append({**dict(row), "age_days": age, "age_bucket": bucket})

    return render_template(
        "reports.html", from_date=start, to_date=end,
        sales_total=sales_total, purchase_total=purchase_total,
        payment_total=payment_total, outstanding_total=outstanding_total,
        sales_rows=sales_rows, gst_summary=gst_summary,
        purchase_rows=purchase_rows, production_rows=production_rows,
        outstanding_rows=outstanding_rows,
        customer_sales_rows=customer_sales_rows,
        product_sales_rows=product_sales_rows,
        gst_rate_rows=gst_rate_rows,
        material_variance_rows=material_variance_rows,
        material_stock=material_stock, product_stock=product_stock,
        ageing_rows=ageing_rows,
    )


@app.route("/reports/export")
@login_required
@roles_required("admin", "accountant", "owner")
def export_report():
    report_type = request.args.get("report_type", "sales")
    export_format = request.args.get("format", "csv").lower()
    start = request.args.get("from_date", "2000-01-01")
    end = request.args.get("to_date", date.today().isoformat())
    try:
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        if start_day > end_day:
            raise ValueError
    except ValueError:
        flash("Invalid export date range.", "warning")
        return redirect(url_for("reports"))

    report_queries = {
        "sales": ("""
            SELECT i.invoice_number, i.invoice_date, c.name AS customer,
                   i.taxable_value_paise, i.cgst_paise, i.sgst_paise,
                   i.igst_paise, i.total_paise
            FROM invoices i JOIN customers c ON c.id=i.customer_id
            WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
            ORDER BY i.invoice_date, i.invoice_number
        """, ("Invoice", "Date", "Customer", "Taxable Paise", "CGST Paise", "SGST Paise", "IGST Paise", "Total Paise")),
        "purchases": ("""
            SELECT pu.purchase_number, pu.purchase_date, m.name,
                   pl.quantity, pl.rate_paise, pl.taxable_value_paise
            FROM purchase_lines pl JOIN purchases pu ON pu.id=pl.purchase_id
            JOIN materials m ON m.id=pl.material_id
            WHERE pu.purchase_date BETWEEN ? AND ?
            ORDER BY pu.purchase_date, pu.purchase_number
        """, ("Purchase", "Date", "Material", "Quantity", "Rate Paise", "Value Paise")),
        "production": ("""
            SELECT r.run_number, r.production_date, p.name,
                   r.planned_packets, r.actual_good_packets,
                   r.damaged_pouches, r.cartons_used
            FROM production_runs r JOIN products p ON p.id=r.product_id
            WHERE r.production_date BETWEEN ? AND ? AND r.status='posted'
            ORDER BY r.production_date, r.run_number
        """, ("Run", "Date", "Product", "Planned", "Actual Good", "Damaged Pouches", "Cartons")),
        "payments": ("""
            SELECT p.payment_date, i.invoice_number, c.name, p.payment_mode,
                   p.reference_number, p.amount_paise
            FROM payments p JOIN invoices i ON i.id=p.invoice_id
            JOIN customers c ON c.id=i.customer_id
            WHERE p.payment_date BETWEEN ? AND ?
            ORDER BY p.payment_date, p.id
        """, ("Date", "Invoice", "Customer", "Mode", "Reference", "Amount Paise")),
        "gst": ("""
            SELECT il.gst_rate_bps, i.customer_state,
                   SUM(il.taxable_value_paise), SUM(il.cgst_paise),
                   SUM(il.sgst_paise), SUM(il.igst_paise)
            FROM invoice_lines il JOIN invoices i ON i.id=il.invoice_id
            WHERE i.invoice_date BETWEEN ? AND ? AND i.status='posted'
            GROUP BY il.gst_rate_bps, i.customer_state
            ORDER BY il.gst_rate_bps, i.customer_state
        """, ("GST Rate BPS", "Place of Supply", "Taxable Paise", "CGST Paise", "SGST Paise", "IGST Paise")),
    }
    if report_type == "stock":
        rows = fetch_all(
            """SELECT sl.movement_date, sl.item_type, sl.item_id,
                      sl.quantity_in, sl.quantity_out, sl.source_type, sl.notes
               FROM stock_ledger sl WHERE sl.movement_date BETWEEN ? AND ?
               ORDER BY sl.movement_date, sl.id""", (start, end),
        )
        headers = ("Date", "Item Type", "Item ID", "Quantity In", "Quantity Out", "Source", "Notes")
    elif report_type in report_queries:
        sql, headers = report_queries[report_type]
        rows = fetch_all(sql, (start, end))
    else:
        flash("Unknown report type.", "warning")
        return redirect(url_for("reports", from_date=start, to_date=end))

    if export_format == "pdf":
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=f"{report_type.title()} Report")
        styles = getSampleStyleSheet()
        content = [
            Paragraph(f"<b>Order-to-Audit - {report_type.title()} Report</b>", styles["Title"]),
            Paragraph(f"Period: {start} to {end}", styles["Normal"]),
            Spacer(1, 12),
        ]
        data = [list(headers)] + [[str(value) if value is not None else "" for value in row] for row in rows]
        if len(data) == 1:
            data.append(["No records"] + [""] * (len(headers) - 1))
        table = Table(data, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263746")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        content.append(table)
        document.build(content)
        buffer.seek(0)
        return send_file(
            buffer, as_attachment=True,
            download_name=f"{report_type}_{start}_to_{end}.pdf",
            mimetype="application/pdf",
        )

    if export_format != "csv":
        flash("Choose CSV or PDF export.", "warning")
        return redirect(url_for("reports", from_date=start, to_date=end))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([tuple(row) for row in rows])
    return Response(
        output.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={report_type}_{start}_to_{end}.csv"},
    )


@app.route("/credit-notes")
@login_required
@roles_required("admin", "accountant", "owner")
def credit_notes():
    notes = fetch_all(
        """
        SELECT cn.*, i.invoice_number, c.name AS customer_name,
               u.name AS created_by_name
        FROM credit_notes cn
        JOIN invoices i ON i.id=cn.invoice_id
        JOIN customers c ON c.id=i.customer_id
        JOIN users u ON u.id=cn.created_by
        ORDER BY cn.credit_date DESC, cn.id DESC
        """
    )
    return render_template("credit_notes.html", credit_notes=notes)


@app.route("/invoice/<int:invoice_id>/credit-note", methods=["POST"])
@login_required
@roles_required("admin", "owner")
def create_credit_note(invoice_id):
    reason = request.form.get("reason", "Invoice cancellation").strip()
    with db() as connection:
        invoice_row = connection.execute(
            "SELECT * FROM invoices WHERE id=?", (invoice_id,)
        ).fetchone()

        if not invoice_row or invoice_row["status"] != "posted":
            flash("Only posted invoices can be credited.", "warning")
            return redirect(url_for("orders"))

        already_dispatched = connection.execute(
            "SELECT id FROM dispatches WHERE invoice_id=?", (invoice_id,)
        ).fetchone()
        if already_dispatched:
            flash("This invoice was dispatched. Handle the return through a separate stock-return process.", "danger")
            return redirect(url_for("invoice", invoice_id=invoice_id))

        payment_exists = connection.execute(
            "SELECT id FROM payments WHERE invoice_id=? LIMIT 1", (invoice_id,)
        ).fetchone()
        if payment_exists:
            flash("A payment has already been received for this invoice. Record the refund/adjustment before cancellation.", "danger")
            return redirect(url_for("invoice", invoice_id=invoice_id))

        if not reason:
            flash("Please enter a credit note reason.", "warning")
            return redirect(url_for("invoice", invoice_id=invoice_id))

        credit_number = next_number(connection, "credit_notes", "credit_note_number", "CN")
        tax_total = (
            invoice_row["cgst_paise"] + invoice_row["sgst_paise"]
            + invoice_row["igst_paise"]
        )
        total = invoice_row["total_paise"]

        cursor = connection.execute(
            """
            INSERT INTO credit_notes
            (credit_note_number, invoice_id, credit_date, reason,
             taxable_value_paise, tax_paise, total_paise, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                credit_number, invoice_id, date.today().isoformat(), reason,
                invoice_row["taxable_value_paise"], tax_total, total,
                current_user_id(),
            ),
        )
        write_audit(
            connection, "credit_notes", cursor.lastrowid, "create",
            new_values={"credit_note_number": credit_number, "invoice_id": invoice_id, "reason": reason},
            user_id=current_user_id(),
        )
        connection.execute(
            "UPDATE invoices SET status='cancelled' WHERE id=?", (invoice_id,)
        )
        connection.execute(
            "UPDATE orders SET status='cancelled' WHERE id=?",
            (invoice_row["order_id"],),
        )
        write_audit(connection, "invoices", invoice_id, "cancel",
                    old_values={"status": "posted"},
                    new_values={"status": "cancelled", "credit_note": credit_number},
                    user_id=current_user_id())

    flash(f"Credit note {credit_number} created. Invoice cancelled.", "success")
    return redirect(url_for("credit_notes"))


@app.errorhandler(403)
def forbidden(error):
    return render_template("base.html"), 403


@app.errorhandler(404)
def not_found(error):
    return "The requested page or record was not found.", 404


init_db()

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
