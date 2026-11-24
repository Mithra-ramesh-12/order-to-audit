
import os
import sqlite3
from datetime import date
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get(
    "DATABASE_PATH",
    os.environ.get("DATABASE", os.path.join(BASE_DIR, "order_to_audit.db"))
)
SCHEMA = os.path.join(BASE_DIR, "schema.sql")


def seed_database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    with open(SCHEMA, "r", encoding="utf-8") as file:
        connection.executescript(file.read())

    users = [
        ("Owner", "owner", "owner123", "owner"),
        ("Administrator", "admin", "admin123", "admin"),
        ("Production Supervisor", "production", "prod123", "production"),
        ("Accountant", "accountant", "account123", "accountant"),
        ("Salesman A", "salesa", "sales123", "salesman"),
        ("Salesman B", "salesb", "sales123", "salesman"),
    ]

    for name, username, password, role in users:
        connection.execute(
            """
            INSERT OR IGNORE INTO users (name, username, password_hash, role, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (name, username, generate_password_hash(password), role),
        )

    owner_row = connection.execute(
        "SELECT id FROM users WHERE username='owner'"
    ).fetchone()
    owner_id = owner_row["id"]

    materials = [
        ("Flour", "kg", "1101"),
        ("Oil", "litre", "1507"),
        ("Spice Mix", "kg", "0910"),
        ("Pouch", "piece", "3923"),
        ("Carton", "carton", "4819"),
    ]

    for name, unit, hsn in materials:
        connection.execute(
            """
            INSERT OR IGNORE INTO materials (name, unit, hsn, gst_rate_bps)
            VALUES (?, ?, ?, 500)
            """,
            (name, unit, hsn),
        )

    connection.execute(
        """
        INSERT OR IGNORE INTO products
        (name, description, unit, packets_per_carton,
         selling_price_paise, hsn, gst_rate_bps)
        VALUES (?, ?, 'packet', 20, 5000, '1905', 500)
        """,
        ("Murukku 200g", "Traditional South Indian murukku snack, 200g packet"),
    )

    connection.execute(
        """
        INSERT INTO customers
        (name, phone, address, state, gstin, customer_type)
        SELECT 'Retailer A', '9000000001', 'Tirunelveli, Tamil Nadu',
               'Tamil Nadu', '', 'retailer'
        WHERE NOT EXISTS (SELECT 1 FROM customers WHERE name='Retailer A')
        """
    )
    connection.execute(
        """
        INSERT INTO customers
        (name, phone, address, state, gstin, customer_type)
        SELECT 'Distributor B', '9000000002', 'Bengaluru, Karnataka',
               'Karnataka', '', 'distributor'
        WHERE NOT EXISTS (SELECT 1 FROM customers WHERE name='Distributor B')
        """
    )

    product_id = connection.execute(
        "SELECT id FROM products WHERE name='Murukku 200g'"
    ).fetchone()["id"]

    material_ids = {
        row["name"]: row["id"]
        for row in connection.execute("SELECT id, name FROM materials").fetchall()
    }

    existing_bom = connection.execute(
        "SELECT id FROM bom WHERE product_id=? AND batch_name='Standard 200 packet batch'",
        (product_id,),
    ).fetchone()

    if not existing_bom:
        cursor = connection.execute(
            """
            INSERT INTO bom
            (product_id, batch_name, batch_size_packets, expected_yield_packets)
            VALUES (?, ?, 200, 200)
            """,
            (product_id, "Standard 200 packet batch"),
        )
        bom_id = cursor.lastrowid

        bom_items = [
            ("Flour", "40"),
            ("Oil", "10"),
            ("Spice Mix", "1.2"),
            ("Pouch", "200"),
            ("Carton", "10"),
        ]
        for material_name, quantity in bom_items:
            connection.execute(
                """
                INSERT INTO bom_lines (bom_id, material_id, quantity)
                VALUES (?, ?, ?)
                """,
                (bom_id, material_ids[material_name], quantity),
            )

    # Opening stock is recorded as ledger movements, never as a balance field.
    opening_exists = connection.execute(
        "SELECT id FROM stock_ledger WHERE source_type='opening' LIMIT 1"
    ).fetchone()

    if not opening_exists:
        opening_materials = [
            ("Flour", "100"),
            ("Oil", "30"),
            ("Spice Mix", "5"),
            ("Pouch", "500"),
            ("Carton", "30"),
        ]

        for material_name, quantity in opening_materials:
            connection.execute(
                """
                INSERT INTO stock_ledger
                (item_type, item_id, quantity_in, quantity_out,
                 source_type, source_id, movement_date, user_id, notes)
                VALUES ('material', ?, ?, '0', 'opening', 0, ?, ?, 'Opening stock')
                """,
                (
                    material_ids[material_name],
                    quantity,
                    date.today().isoformat(),
                    owner_id,
                ),
            )

        connection.execute(
            """
            INSERT INTO stock_ledger
            (item_type, item_id, quantity_in, quantity_out,
             source_type, source_id, movement_date, user_id, notes)
            VALUES ('product', ?, '50', '0', 'opening', 0, ?, ?,
                    'Opening finished goods stock')
            """,
            (product_id, date.today().isoformat(), owner_id),
        )

    # Benchmark purchase: 60 kg flour at ₹45/kg.
    purchase_exists = connection.execute(
        "SELECT id FROM purchases WHERE purchase_number='PUR-SEED-001'"
    ).fetchone()

    if not purchase_exists:
        cursor = connection.execute(
            """
            INSERT INTO purchases
            (purchase_number, supplier_name, purchase_date,
             reference_number, created_by)
            VALUES ('PUR-SEED-001', 'Benchmark Flour Supplier', ?, 'SEED-001', ?)
            """,
            (date.today().isoformat(), owner_id),
        )
        purchase_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO purchase_lines
            (purchase_id, material_id, quantity, rate_paise,
             taxable_value_paise, gst_paise)
            VALUES (?, ?, '60', 4500, 270000, 0)
            """,
            (purchase_id, material_ids["Flour"]),
        )
        connection.execute(
            """
            INSERT INTO stock_ledger
            (item_type, item_id, quantity_in, quantity_out,
             source_type, source_id, movement_date, user_id, notes)
            VALUES ('material', ?, '60', '0', 'purchase', ?, ?, ?,
                    'Benchmark purchase of 60 kg flour at ₹45/kg')
            """,
            (material_ids["Flour"], purchase_id, date.today().isoformat(), owner_id),
        )

    connection.commit()
    connection.close()

    print("\nDatabase seed completed!")
    print("----------------------------------")
    print("Login credentials:")
    print("Owner       : owner / owner123")
    print("Admin       : admin / admin123")
    print("Production  : production / prod123")
    print("Accountant  : accountant / account123")
    print("Salesman A  : salesa / sales123")
    print("Salesman B  : salesb / sales123")
    print("----------------------------------")
    print("Product: Murukku 200g")
    print("Selling price: ₹50 per packet")
    print("GST: 5%")
    print("Opening finished stock: 50 packets")
    print("Opening flour stock: 100 kg")
    print("Benchmark flour purchase: 60 kg at ₹45/kg")
    print("Run the application after the remaining project files are ready.")


if __name__ == "__main__":
    seed_database()
