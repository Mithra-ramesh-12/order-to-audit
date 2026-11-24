
PRAGMA foreign_keys = ON;

-- =========================================
-- 1. USERS AND ROLES
-- =========================================

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (
        role IN (
            'salesman',
            'admin',
            'production',
            'accountant',
            'owner'
        )
    ),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================================
-- 2. CUSTOMERS
-- =========================================

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    state TEXT NOT NULL,
    gstin TEXT,
    customer_type TEXT DEFAULT 'retailer',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================================
-- 3. RAW MATERIALS
-- =========================================

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    unit TEXT NOT NULL CHECK (
        unit IN ('kg', 'g', 'litre', 'piece', 'packet', 'carton')
    ),
    hsn TEXT,
    gst_rate_bps INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

-- =========================================
-- 4. PRODUCTS
-- =========================================

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    unit TEXT NOT NULL DEFAULT 'packet',
    packets_per_carton INTEGER NOT NULL DEFAULT 20,
    selling_price_paise INTEGER NOT NULL,
    hsn TEXT,
    gst_rate_bps INTEGER NOT NULL DEFAULT 500,
    active INTEGER NOT NULL DEFAULT 1,
    CHECK (selling_price_paise >= 0),
    CHECK (packets_per_carton > 0)
);

-- =========================================
-- 5. BILL OF MATERIALS (BOM)
-- =========================================

CREATE TABLE IF NOT EXISTS bom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch_name TEXT NOT NULL,
    batch_size_packets INTEGER NOT NULL,
    expected_yield_packets INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (product_id) REFERENCES products(id),

    CHECK (batch_size_packets > 0),
    CHECK (expected_yield_packets > 0)
);

CREATE TABLE IF NOT EXISTS bom_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    quantity TEXT NOT NULL,

    FOREIGN KEY (bom_id) REFERENCES bom(id),
    FOREIGN KEY (material_id) REFERENCES materials(id),

    UNIQUE (bom_id, material_id)
);

-- =========================================
-- 6. SALES ORDERS
-- =========================================

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    salesman_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'approved',
                'rejected',
                'invoiced',
                'dispatched',
                'cancelled'
            )
        ),
    order_date TEXT NOT NULL,
    notes TEXT,
    approved_by INTEGER,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (salesman_id) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity_packets INTEGER NOT NULL,
    unit_price_paise INTEGER NOT NULL,

    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id),

    CHECK (quantity_packets > 0),
    CHECK (unit_price_paise >= 0)
);

-- =========================================
-- 7. PURCHASES
-- =========================================

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_number TEXT NOT NULL UNIQUE,
    supplier_name TEXT NOT NULL,
    purchase_date TEXT NOT NULL,
    reference_number TEXT,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS purchase_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    quantity TEXT NOT NULL,
    rate_paise INTEGER NOT NULL,
    taxable_value_paise INTEGER NOT NULL,
    gst_paise INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (purchase_id) REFERENCES purchases(id),
    FOREIGN KEY (material_id) REFERENCES materials(id),

    CHECK (rate_paise >= 0),
    CHECK (taxable_value_paise >= 0)
);

-- =========================================
-- 8. PRODUCTION RUNS
-- =========================================

CREATE TABLE IF NOT EXISTS production_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_number TEXT NOT NULL UNIQUE,
    bom_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    planned_packets INTEGER NOT NULL,
    actual_good_packets INTEGER NOT NULL DEFAULT 0,
    damaged_pouches INTEGER NOT NULL DEFAULT 0,
    cartons_used INTEGER NOT NULL DEFAULT 0,
    labour_cost_paise INTEGER NOT NULL DEFAULT 0,
    power_gas_cost_paise INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'posted', 'cancelled')),
    production_date TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (bom_id) REFERENCES bom(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (created_by) REFERENCES users(id),

    CHECK (planned_packets > 0),
    CHECK (actual_good_packets >= 0),
    CHECK (damaged_pouches >= 0),
    CHECK (cartons_used >= 0),
    CHECK (labour_cost_paise >= 0),
    CHECK (power_gas_cost_paise >= 0)
);

CREATE TABLE IF NOT EXISTS production_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_run_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    planned_quantity TEXT NOT NULL,
    actual_quantity TEXT NOT NULL,

    FOREIGN KEY (production_run_id)
        REFERENCES production_runs(id),

    FOREIGN KEY (material_id)
        REFERENCES materials(id),

    UNIQUE (production_run_id, material_id)
);

-- =========================================
-- 9. STOCK LEDGER
-- =========================================

CREATE TABLE IF NOT EXISTS stock_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    item_type TEXT NOT NULL CHECK (
        item_type IN ('material', 'product')
    ),

    item_id INTEGER NOT NULL,

    quantity_in TEXT NOT NULL DEFAULT '0',
    quantity_out TEXT NOT NULL DEFAULT '0',

    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'opening',
            'purchase',
            'production_issue',
            'production_output',
            'dispatch',
            'adjustment',
            'credit_note'
        )
    ),

    source_id INTEGER NOT NULL,
    movement_date TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id),

    CHECK (
        (CAST(quantity_in AS REAL) >= 0)
        AND (CAST(quantity_out AS REAL) >= 0)
    ),

    CHECK (
        NOT (
            CAST(quantity_in AS REAL) > 0
            AND CAST(quantity_out AS REAL) > 0
        )
    ),

    CHECK (
        CAST(quantity_in AS REAL) > 0
        OR CAST(quantity_out AS REAL) > 0
    )
);

CREATE INDEX IF NOT EXISTS idx_ledger_item
ON stock_ledger(item_type, item_id);

CREATE INDEX IF NOT EXISTS idx_ledger_date
ON stock_ledger(movement_date);

CREATE INDEX IF NOT EXISTS idx_ledger_source
ON stock_ledger(source_type, source_id);

-- =========================================
-- 10. INVOICES
-- =========================================

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    financial_year TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    invoice_date TEXT NOT NULL,
    customer_gstin TEXT,
    customer_state TEXT NOT NULL,
    taxable_value_paise INTEGER NOT NULL,
    cgst_paise INTEGER NOT NULL DEFAULT 0,
    sgst_paise INTEGER NOT NULL DEFAULT 0,
    igst_paise INTEGER NOT NULL DEFAULT 0,
    total_paise INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'posted'
        CHECK (status IN ('posted', 'cancelled')),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (created_by) REFERENCES users(id),

    UNIQUE (financial_year, sequence_number)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    hsn TEXT,
    quantity_packets INTEGER NOT NULL,
    unit_price_paise INTEGER NOT NULL,
    taxable_value_paise INTEGER NOT NULL,
    gst_rate_bps INTEGER NOT NULL,
    cgst_paise INTEGER NOT NULL DEFAULT 0,
    sgst_paise INTEGER NOT NULL DEFAULT 0,
    igst_paise INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- =========================================
-- 11. CREDIT NOTES
-- =========================================

CREATE TABLE IF NOT EXISTS credit_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credit_note_number TEXT NOT NULL UNIQUE,
    invoice_id INTEGER NOT NULL,
    credit_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    taxable_value_paise INTEGER NOT NULL,
    tax_paise INTEGER NOT NULL,
    total_paise INTEGER NOT NULL,
    created_by INTEGER NOT NULL,

    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- =========================================
-- 12. DISPATCHES
-- =========================================

CREATE TABLE IF NOT EXISTS dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL UNIQUE,
    dispatch_date TEXT NOT NULL,
    vehicle_number TEXT,
    dispatched_by INTEGER NOT NULL,
    notes TEXT,

    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (dispatched_by) REFERENCES users(id)
);

-- =========================================
-- 13. PAYMENTS
-- =========================================

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    payment_mode TEXT NOT NULL,
    reference_number TEXT,
    received_by INTEGER NOT NULL,
    notes TEXT,

    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (received_by) REFERENCES users(id),

    CHECK (amount_paise > 0)
);

-- =========================================
-- 14. PRODUCTION EXPENSES
-- =========================================

CREATE TABLE IF NOT EXISTS production_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_run_id INTEGER NOT NULL,
    expense_type TEXT NOT NULL CHECK (
        expense_type IN ('labour', 'power_gas', 'other')
    ),
    amount_paise INTEGER NOT NULL,
    description TEXT,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (production_run_id)
        REFERENCES production_runs(id),

    FOREIGN KEY (created_by) REFERENCES users(id),

    CHECK (amount_paise >= 0)
);

-- =========================================
-- 15. AUDIT LOG
-- =========================================

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (
        action IN ('create', 'update', 'post', 'cancel')
    ),
    old_values TEXT,
    new_values TEXT,
    user_id INTEGER NOT NULL,
    action_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_record
ON audit_log(table_name, record_id);

CREATE INDEX IF NOT EXISTS idx_audit_time
ON audit_log(action_time);
