
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
import sqlite3


ZERO = Decimal("0")
MONEY_FACTOR = Decimal("100")
GST_FACTOR = Decimal("10000")


# ---------------------------------------------------------
# DECIMAL AND MONEY HELPERS
# ---------------------------------------------------------

def to_decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid numeric value: {value}")

    if not result.is_finite():
        raise ValueError("Numeric value must be finite.")

    return result


def decimal_text(value):
    return format(to_decimal(value).normalize(), "f")


def money_to_paise(rupees):
    amount = to_decimal(rupees)

    if amount < ZERO:
        raise ValueError("Money cannot be negative.")

    return int(
        (amount * MONEY_FACTOR).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def paise_to_rupees(paise):
    return (
        to_decimal(paise) / MONEY_FACTOR
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_percentage(amount, percentage):
    return (
        to_decimal(amount) * to_decimal(percentage) / Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_connection(database="order_to_audit.db"):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ---------------------------------------------------------
# UNIT CONVERSION
# ---------------------------------------------------------

def convert_quantity(quantity, from_unit, to_unit):
    quantity = to_decimal(quantity)

    if quantity < ZERO:
        raise ValueError("Quantity cannot be negative.")

    if from_unit == to_unit:
        return quantity

    conversions = {
        ("kg", "g"): Decimal("1000"),
        ("g", "kg"): Decimal("0.001"),
        ("carton", "packet"): Decimal("20"),
        ("packet", "carton"): Decimal("0.05"),
    }

    key = (from_unit, to_unit)

    if key not in conversions:
        raise ValueError(
            f"Conversion from {from_unit} to {to_unit} is not supported."
        )

    return quantity * conversions[key]


# ---------------------------------------------------------
# STOCK LEDGER
# ---------------------------------------------------------

def record_stock_movement(
    connection,
    item_type,
    item_id,
    quantity,
    movement_type,
    source_type,
    source_id,
    user_id,
    movement_date=None,
    notes=None
):
    quantity = to_decimal(quantity)

    if quantity <= ZERO:
        raise ValueError("Stock movement quantity must be positive.")

    if item_type not in ("material", "product"):
        raise ValueError("Invalid stock item type.")

    if movement_type not in ("IN", "OUT"):
        raise ValueError("Movement type must be IN or OUT.")

    allowed_sources = {
        "opening",
        "purchase",
        "production_issue",
        "production_output",
        "dispatch",
        "adjustment",
        "credit_note",
    }

    if source_type not in allowed_sources:
        raise ValueError("Invalid stock movement source.")

    quantity_in = decimal_text(quantity) if movement_type == "IN" else "0"
    quantity_out = decimal_text(quantity) if movement_type == "OUT" else "0"

    cursor = connection.execute(
        """
        INSERT INTO stock_ledger
        (
            item_type, item_id, quantity_in, quantity_out,
            source_type, source_id, movement_date, user_id, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_type,
            item_id,
            quantity_in,
            quantity_out,
            source_type,
            source_id,
            movement_date or date.today().isoformat(),
            user_id,
            notes
        )
    )

    return cursor.lastrowid


def get_stock_balance(connection, item_type, item_id):
    rows = connection.execute(
        """
        SELECT quantity_in, quantity_out
        FROM stock_ledger
        WHERE item_type = ? AND item_id = ?
        """,
        (item_type, item_id)
    ).fetchall()

    total_in = ZERO
    total_out = ZERO

    for row in rows:
        total_in += to_decimal(row["quantity_in"])
        total_out += to_decimal(row["quantity_out"])

    return total_in - total_out


def check_stock_availability(
    connection,
    item_type,
    item_id,
    required_quantity
):
    available = get_stock_balance(connection, item_type, item_id)
    required = to_decimal(required_quantity)

    shortage = max(ZERO, required - available)

    return {
        "available": available,
        "required": required,
        "sufficient": available >= required,
        "shortage": shortage,
    }


# ---------------------------------------------------------
# VARIANCE
# ---------------------------------------------------------

def calculate_variance(
    planned_quantity,
    actual_quantity,
    tolerance=Decimal("3")
):
    planned = to_decimal(planned_quantity)
    actual = to_decimal(actual_quantity)
    tolerance = to_decimal(tolerance)

    difference = actual - planned

    if planned == ZERO:
        variance_percent = ZERO if actual == ZERO else Decimal("100")
    else:
        variance_percent = (
            difference / planned * Decimal("100")
        )

    variance_percent = variance_percent.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    return {
        "planned": planned,
        "actual": actual,
        "difference": difference,
        "variance_percent": variance_percent,
        "flagged": abs(variance_percent) > tolerance,
    }


# ---------------------------------------------------------
# GST
# ---------------------------------------------------------

def calculate_gst(
    taxable_value_paise,
    gst_rate_bps,
    customer_state,
    factory_state="Tamil Nadu"
):
    taxable = int(taxable_value_paise)
    rate = int(gst_rate_bps)

    if taxable < 0 or rate < 0:
        raise ValueError("Taxable value and GST rate cannot be negative.")

    total_tax = int(
        (
            Decimal(taxable) * Decimal(rate) / GST_FACTOR
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    if customer_state.strip().casefold() == factory_state.strip().casefold():
        cgst = total_tax // 2
        sgst = total_tax - cgst
        igst = 0
    else:
        cgst = 0
        sgst = 0
        igst = total_tax

    return {
        "taxable_value_paise": taxable,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "total_tax_paise": total_tax,
        "total_paise": taxable + total_tax,
    }


# ---------------------------------------------------------
# WEIGHTED AVERAGE COST
# ---------------------------------------------------------

def weighted_average_cost(
    opening_quantity,
    opening_rate_paise,
    purchases
):
    total_quantity = to_decimal(opening_quantity)
    total_value = (
        total_quantity * to_decimal(opening_rate_paise)
    )

    for purchase in purchases:
        quantity = to_decimal(purchase["quantity"])
        rate = to_decimal(purchase["rate_paise"])

        if quantity < ZERO or rate < ZERO:
            raise ValueError("Purchase quantity and rate cannot be negative.")

        total_quantity += quantity
        total_value += quantity * rate

    if total_quantity == ZERO:
        return 0

    average = total_value / total_quantity

    return int(
        average.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


# ---------------------------------------------------------
# PRODUCTION COST
# ---------------------------------------------------------

def calculate_run_cost(
    material_costs,
    labour_cost_paise,
    power_gas_cost_paise,
    good_packets
):
    material_total = sum(
        (to_decimal(value) for value in material_costs),
        ZERO
    )

    labour = to_decimal(labour_cost_paise)
    power_gas = to_decimal(power_gas_cost_paise)
    output = to_decimal(good_packets)

    total = material_total + labour + power_gas

    if output <= ZERO:
        cost_per_packet = ZERO
    else:
        cost_per_packet = total / output

    return {
        "material_cost_paise": int(material_total),
        "labour_cost_paise": int(labour),
        "power_gas_cost_paise": int(power_gas),
        "total_cost_paise": int(total),
        "cost_per_packet_paise": int(
            cost_per_packet.quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP
            )
        ),
    }


# ---------------------------------------------------------
# PRODUCTION POSTING
# ---------------------------------------------------------

def post_production_run(
    connection,
    bom_id,
    product_id,
    planned_packets,
    actual_good_packets,
    material_actuals,
    damaged_pouches,
    cartons_used,
    labour_cost_paise,
    power_gas_cost_paise,
    user_id,
    production_date=None,
    run_number=None
):
    planned_packets = int(planned_packets)
    actual_good_packets = int(actual_good_packets)
    damaged_pouches = int(damaged_pouches)
    cartons_used = int(cartons_used)

    if planned_packets <= 0:
        raise ValueError("Planned production must be positive.")

    if actual_good_packets <= 0:
        raise ValueError("Good output must be positive.")

    if min(damaged_pouches, cartons_used) < 0:
        raise ValueError("Damaged pouches and cartons cannot be negative.")

    bom = connection.execute(
        """
        SELECT * FROM bom
        WHERE id = ? AND product_id = ? AND active = 1
        """,
        (bom_id, product_id)
    ).fetchone()

    if not bom:
        raise ValueError("Selected BOM was not found.")

    bom_lines = connection.execute(
        """
        SELECT bl.material_id, bl.quantity, m.name, m.unit
        FROM bom_lines bl
        JOIN materials m ON m.id = bl.material_id
        WHERE bl.bom_id = ?
        """,
        (bom_id,)
    ).fetchall()

    if not bom_lines:
        raise ValueError("The selected BOM has no material lines.")

    scale = Decimal(planned_packets) / Decimal(
        bom["batch_size_packets"]
    )

    actuals = {
        int(key): to_decimal(value)
        for key, value in material_actuals.items()
    }

    for line in bom_lines:
        material_id = int(line["material_id"])

        if material_id not in actuals:
            raise ValueError(
                f"Enter actual usage for {line['name']}."
            )

        quantity = actuals[material_id]

        if quantity <= ZERO:
            raise ValueError(
                f"Actual usage for {line['name']} must be positive."
            )

        stock = check_stock_availability(
            connection,
            "material",
            material_id,
            quantity
        )

        if not stock["sufficient"]:
            raise ValueError(
                f"Insufficient {line['name']} stock. "
                f"Available: {stock['available']}, "
                f"required: {quantity}."
            )

    for material_id in actuals:
        if material_id not in {
            int(line["material_id"]) for line in bom_lines
        }:
            raise ValueError(
                "Actual material list contains a material not in this BOM."
            )

    run_number = run_number or (
        "RUN-" + date.today().strftime("%Y%m%d") + f"-{user_id}"
    )

    cursor = connection.execute(
        """
        INSERT INTO production_runs
        (
            run_number, bom_id, product_id, planned_packets,
            actual_good_packets, damaged_pouches, cartons_used,
            labour_cost_paise, power_gas_cost_paise,
            status, production_date, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted', ?, ?)
        """,
        (
            run_number,
            bom_id,
            product_id,
            planned_packets,
            actual_good_packets,
            damaged_pouches,
            cartons_used,
            int(labour_cost_paise),
            int(power_gas_cost_paise),
            production_date or date.today().isoformat(),
            user_id
        )
    )

    run_id = cursor.lastrowid
    material_costs = []

    for line in bom_lines:
        material_id = int(line["material_id"])
        actual_quantity = actuals[material_id]
        planned_quantity = to_decimal(line["quantity"]) * scale

        connection.execute(
            """
            INSERT INTO production_materials
            (
                production_run_id, material_id,
                planned_quantity, actual_quantity
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                material_id,
                decimal_text(planned_quantity),
                decimal_text(actual_quantity)
            )
        )

        record_stock_movement(
            connection,
            "material",
            material_id,
            actual_quantity,
            "OUT",
            "production_issue",
            run_id,
            user_id,
            production_date,
            f"Material issued for {run_number}"
        )

        # Cost estimate uses the latest purchase rate when available.
        latest_purchase = connection.execute(
            """
            SELECT pl.rate_paise
            FROM purchase_lines pl
            JOIN purchases pu ON pu.id = pl.purchase_id
            WHERE pl.material_id = ?
            ORDER BY pu.purchase_date DESC, pl.id DESC
            LIMIT 1
            """,
            (material_id,)
        ).fetchone()

        rate = (
            to_decimal(latest_purchase["rate_paise"])
            if latest_purchase else ZERO
        )

        material_costs.append(actual_quantity * rate)

    record_stock_movement(
        connection,
        "product",
        product_id,
        actual_good_packets,
        "IN",
        "production_output",
        run_id,
        user_id,
        production_date,
        f"Good finished output from {run_number}"
    )

    connection.execute(
        """
        INSERT INTO production_expenses
        (production_run_id, expense_type, amount_paise, description, created_by)
        VALUES (?, 'labour', ?, 'Production labour', ?)
        """,
        (run_id, int(labour_cost_paise), user_id)
    )

    connection.execute(
        """
        INSERT INTO production_expenses
        (production_run_id, expense_type, amount_paise, description, created_by)
        VALUES (?, 'power_gas', ?, 'Production power and gas', ?)
        """,
        (run_id, int(power_gas_cost_paise), user_id)
    )

    cost = calculate_run_cost(
        material_costs,
        labour_cost_paise,
        power_gas_cost_paise,
        actual_good_packets
    )

    yield_variance = calculate_variance(
        bom["expected_yield_packets"],
        actual_good_packets
    )

    material_variances = []

    for line in bom_lines:
        material_id = int(line["material_id"])
        planned_quantity = to_decimal(line["quantity"]) * scale

        material_variances.append({
            "material_id": material_id,
            "material_name": line["name"],
            **calculate_variance(
                planned_quantity,
                actuals[material_id]
            )
        })

    connection.commit()

    return {
        "run_id": run_id,
        "run_number": run_number,
        "yield_variance": yield_variance,
        "material_variances": material_variances,
        "cost": cost,
    }
