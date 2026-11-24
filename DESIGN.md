
# Order-to-Audit System — Design

## 1. Project Overview

Order-to-Audit is a Flask-based manufacturing management prototype for a small snack manufacturing business.

It connects sales orders, production, inventory, invoicing, dispatch, payments and reporting.

## 2. Technology Stack

- Python
- Flask
- SQLite
- HTML, CSS and Bootstrap 5
- Jinja2 templates
- ReportLab for PDF invoices
- CSV and Excel export support

## 3. User Roles

| Role | Main responsibility |
|---|---|
| Salesman | Create customer orders |
| Admin | Masters, approvals, billing, dispatch and payments |
| Production Supervisor | Record production runs |
| Accountant | Read-only reports and financial information |
| Owner | Monitor business performance |

## 4. Main Workflow

1. Create products, customers, materials and BOM.
2. Salesman creates an order.
3. Admin reviews and approves the order.
4. Admin creates a GST invoice.
5. Finished stock is reduced when dispatch is recorded.
6. Customer payments are recorded.
7. Reports display sales, GST, production and outstanding balances.

## 5. Inventory Design

Stock is derived from the stock ledger.

Every stock movement records:
- Item type and item ID
- Quantity in
- Quantity out
- Source type and source ID
- Movement date
- User
- Notes

The application does not directly overwrite a stock balance.

## 6. Production Design

A production run records planned output, actual good output, damaged pouches, cartons used, actual material consumption and production expenses.

Material and yield variance is calculated against a 3% tolerance.

## 7. GST Design

The factory state is Tamil Nadu.

- Tamil Nadu customer: CGST + SGST
- Other-state customer: IGST

GST values are calculated in integer paise.

## 8. Audit Design

Important records use an audit log to preserve:
- Table name
- Record ID
- Action
- Old values
- New values
- User ID
- Action time

Posted invoices must not be deleted. Corrections should be represented through credit notes.

## 9. Security

- Password hashes are stored rather than plain-text passwords.
- Routes are protected by login and role checks.
- SQLite foreign-key enforcement is enabled.
- Financial amounts are stored in integer paise.
