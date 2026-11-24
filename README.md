# 🏭 Order-to-Audit Manufacturing Management System

### An Integrated Order, Inventory, Production & Accounting Management System

A web-based manufacturing management application developed using **Python Flask and SQLite** to manage the complete business workflow of a small-scale snack manufacturing company.

The system connects sales, order processing, production, inventory, GST billing, payments and audit tracking in one platform.

---

## 📸 Application Screenshots

### Login
![Login](screenshots/login.png)

### Dashboard
![Dashboard](screenshots/dashboard.png)

### Order Management
![Orders](screenshots/orders.png)

### Production Management
![Production](screenshots/production.png)

### Inventory Management
![Inventory](screenshots/inventory.png)

### GST Invoice
![Invoice](screenshots/invoice.png)

### Reports
![Reports](screenshots/reports.png)

---

## ✨ Key Features

- **Role-Based Access:** Separate access for Owner, Admin, Production, Accountant and Salesman.
- **Order Management:** Create, review, approve and track customer orders.
- **Product & Customer Masters:** Manage products, customers, raw materials and Bills of Materials.
- **GST Billing:** Generate invoices with applicable CGST, SGST or IGST.
- **Production Management:** Record production output, material consumption and production expenses.
- **Inventory Management:** Track raw materials and finished goods through stock movements.
- **Purchase Management:** Record raw material purchases and purchase receipts.
- **Payment Tracking:** Record customer payments and outstanding balances.
- **Audit Trail:** Maintain records of important system changes.
- **Reports:** View sales, purchases, GST, stock, production variance and outstanding reports.
- **Export Options:** Export supported reports as PDF and CSV.

---

## 👥 User Roles

| Role | Main Responsibilities |
|---|---|
| Owner | Overall business monitoring |
| Admin | Masters, order approvals, invoices, purchases and payments |
| Production | Production entries and inventory viewing |
| Accountant | Payments, inventory and reports |
| Salesman | Customer orders and order tracking |

---

## 🔄 Business Workflow

1. Admin maintains products, customers and raw materials.
2. Salesman creates customer orders.
3. Admin reviews and approves orders based on available stock.
4. Approved orders are converted into GST invoices.
5. Production records manufacturing output and material usage.
6. Dispatch updates finished-goods stock.
7. Accountant records customer payments.
8. Reports and audit logs help monitor business activities.

---

## 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web application framework |
| SQLite | Database |
| HTML5 | Page structure |
| CSS3 | Styling |
| JavaScript | Frontend interactions |
| Bootstrap 5 | Responsive interface |
| Jinja2 | Template rendering |
| ReportLab | PDF generation |
| Werkzeug | Password hashing |

---

## 📂 Project Structure

```text
order-to-audit/
│
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
│
├── static/
│   └── style.css
│
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── orders.html
│   ├── order_new.html
│   ├── invoice.html
│   ├── production.html
│   ├── inventory.html
│   ├── masters.html
│   ├── payments.html
│   └── reports.html
│
└── screenshots/
```

---

## 🚀 Installation & Setup

### Prerequisites

- Python 3.10 or above
- Git
- Visual Studio Code (recommended)

### 1. Clone the repository

```bash
git clone https://github.com/Mithra-ramesh-12/order-to-audit.git
```

### 2. Open the project folder

```bash
cd order-to-audit
```

### 3. Create a virtual environment

```bash
python -m venv venv
```

### 4. Activate the virtual environment

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

### 6. Initialize sample data

```bash
python seed.py
```

Run this once for the initial demo database.

### 7. Start the application

```bash
python app.py
```

### 8. Open in your browser

```text
http://127.0.0.1:5000
```

---

## 🔐 Demo Login Credentials

| Role | Username | Password |
|---|---|---|
| Owner | owner | owner123 |
| Admin | admin | admin123 |
| Production | production | prod123 |
| Accountant | accountant | account123 |
| Salesman A | salesa | sales123 |
| Salesman B | salesb | sales123 |

**Note:** These are demonstration credentials only. Change them before any real deployment.

---

## 📊 Sample Business Scenario

The application includes a sample Murukku 200g manufacturing scenario.

| Parameter | Sample Value |
|---|---:|
| Product | Murukku 200g |
| Selling Price | ₹50 per packet |
| GST Rate | 5% |
| Planned Production | 200 packets |
| Actual Good Production | 188 packets |
| Retailer A Order | 150 packets |
| Retailer A Payment | ₹4,000 |

The sample scenario demonstrates order processing, stock movements, production variance, GST billing and customer outstanding tracking.

---

## 🔒 Security & Data Management

- Passwords are stored using password hashing.
- Application routes use authentication and role checks.
- SQLite foreign-key constraints are enabled.
- Important business changes are recorded in the audit log.
- Database files and environment secrets should not be committed to GitHub.
- A production deployment requires a secure secret key and appropriate access controls.

---

## 🎯 Project Objective

The main objective of this project is to demonstrate how a manufacturing business can manage its day-to-day operations through an integrated digital system instead of maintaining disconnected manual records.

It aims to improve operational visibility, inventory tracking, production monitoring, billing accuracy and accountability.

---

## ⚠️ Project Disclaimer

This is an internship prototype intended for demonstration and educational purposes. Before using it for actual business accounting or statutory GST filing, calculations, tax treatment, reports and audit controls must be validated by qualified professionals.

---

## 👩‍💻 Repository

**GitHub:** https://github.com/Mithra-ramesh-12/order-to-audit

**Project:** Order-to-Audit Manufacturing Management System

**Status:** Internship Prototype
