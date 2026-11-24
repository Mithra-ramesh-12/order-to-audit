Order-to-Audit System

A Flask and SQLite-based order, production, inventory, GST billing, payment, and audit management system for a small snack manufacturing business.

1. Project Overview

The system connects the complete business workflow:





Create products, customers, raw materials, and Bills of Materials.



Salesmen submit customer orders.



Admin approves or rejects orders after checking finished stock.



Approved orders are converted into GST invoices.



Dispatch reduces finished-goods stock through the stock ledger.



Production consumes raw materials and records finished packets.



Payments update customer outstanding balances.



Reports provide sales, GST, purchase, stock, production, and outstanding information.



2. Technology Stack





Python



Flask



SQLite



HTML, CSS, JavaScript



Bootstrap 5



Jinja2



ReportLab for PDF invoices and PDF reports



CSV for report exports



Werkzeug password hashing



3. Project Structure

order-to-audit/
├── app.py
├── logic.py
├── schema.sql
├── seed.py
├── test_logic.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
├── DESIGN.md
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── order_new.html
    ├── orders.html
    ├── invoice.html
    ├── credit_notes.html
    ├── production.html
    ├── inventory.html
    ├── purchases.html
    ├── purchase_new.html
    ├── purchase_detail.html
    ├── masters.html
    ├── payments.html
    └── reports.html



4. User Roles







Role



Main permissions





Salesman



Create and view own orders





Admin



Masters, approvals, invoices, dispatch, purchases, payments





Production



Record production runs and view inventory





Accountant



View inventory, payments, and reports





Owner



Overall dashboard and business access



5. Business Rules



Inventory

Stock is calculated from the stock_ledger table. The system records every stock movement instead of directly overwriting a stock balance.

Stock movement types include:





Opening stock



Purchase receipt



Production material issue



Production output



Dispatch



Adjustment



Credit note



Units

Supported units:





Kilogram (kg)



Gram (g)



Litre



Piece



Packet



Carton

One carton contains 20 packets.

GST

The factory is based in Tamil Nadu.





Tamil Nadu customer: CGST + SGST



Other-state customer: IGST

Invoice values are stored in integer paise to avoid floating-point money errors.

Invoices

Invoice numbers follow the financial-year format:

2026-27/0001

Posted invoices must not be deleted. Corrections and cancellations must be handled through credit notes.

Production

Each production run records:





Planned output



Actual good packets



Material consumption



Damaged pouches



Cartons used



Labour cost



Power and gas cost

A variance above 3% should be investigated.

6. Benchmark Scenario

The project uses the following sample business data.

Product







Field



Value





Product



Murukku 200g





Selling price



₹50 per packet





GST



5%





Batch size



200 packets





Expected yield



200 packets



Bill of Materials







Material



Planned quantity





Flour



40 kg





Oil



10 litres





Spice mix



1.2 kg





Pouch



200 pieces





Carton



10 cartons



Opening stock







Material



Quantity





Flour



100 kg





Oil



30 litres





Spice mix



5 kg





Pouches



500 pieces





Cartons



30 cartons





Finished goods



50 packets



Benchmark purchase





Flour purchased: 60 kg



Purchase rate: ₹45 per kg



Benchmark production





Flour consumed: 40 kg



Oil consumed: 10.5 litres



Spice mix consumed: 1.2 kg



Good output: 188 packets



Damaged pouches: 6



Cartons used: 9



Labour cost: ₹1,200



Power and gas cost: ₹600



Benchmark sales





Retailer A: 150 packets



Distributor B: 120 packets



Retailer A payment: ₹4,000

The system should identify stock shortage when the second order is checked after the first dispatch.

7. Database

The SQLite database uses the tables defined in schema.sql.

Important tables include:





users



customers



materials



products



bom



bom_lines



orders



order_lines



purchases



purchase_lines



production_runs



production_materials



stock_ledger



invoices



invoice_lines



credit_notes



dispatches



payments



production_expenses



audit_log



8. Audit Trail

Important changes are recorded in audit_log.

Audit records capture:





Table name



Record ID



Action



Previous values



Updated values



User ID



Action timestamp



9. Reports

The reports section is designed to cover:





Sales register



Customer and product sales



GST summary



Purchase register



Stock summary



Stock movement ledger



Production variance



Outstanding balances and invoice ageing buckets



Material-wise production usage variance



Current raw-material and finished-goods stock summaries



GST rate and place-of-supply summary in a GSTR-style layout

Supported report categories can be exported as CSV or PDF.

10. Initial Setup and Demo Accounts

The application and seed script use the same database file: order_to_audit.db.
The Flask application creates the schema automatically if the database is missing or empty.
Run the seed script once to add demo users and benchmark master/opening/purchase data:

python seed.py

Then start the application:

python app.py

Open http://127.0.0.1:5000 in your browser.

Demo accounts:







Role



Username



Password





Owner



owner



owner123





Admin



admin



admin123





Production



production



prod123





Accountant



accountant



account123





Salesman A



salesa



sales123





Salesman B



salesb



sales123

The seed script is designed to avoid duplicating the benchmark opening stock and purchase when run again.

11. Security Notes





Passwords are stored as hashes.



Routes are protected by login and role checks.



Database foreign-key constraints are enabled.



A production deployment must use a strong secret key.



Debug mode should be disabled in production.



Demo passwords must be changed before real use.



12. Project Status

This is an internship prototype intended to demonstrate an integrated order-to-audit workflow. Before using it for real business accounting or statutory GST filing, validate all calculations, reports, invoice formats, tax treatment, and audit controls with a qualified accountant.