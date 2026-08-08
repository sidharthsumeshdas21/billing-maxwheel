# MaxWheel Auto Services — Billing SPA Redesign & Enhancements

A single-page application (SPA) built with **Django REST Framework** and **Tailwind CSS v4** for invoice management, customer records, and AI features.

---

## 🚀 Key Features

1. **Tailwind CSS v4 Redesign**:
   - Sleek dark UI matching Stripe/Linear style.
   - Dynamic right-side drawer panels for AI Invoice Scanning and the Chatbot.
   - Micro-interactions, hover card effects, customized thin scrollbars, and full responsive support.

2. **AI Invoice Scanner (Gemini 1.5 Flash)**:
   - Drag-and-drop handwritten invoice photos directly into the browser.
   - Automatically extracts customer names, car numbers, items, rates, and quantities.
   - **Intelligent Customer Link**: Automatically checks if the customer exists. If not, creates a new database customer record and displays an editable profile form prior to saving.

3. **Gemini AI Chatbot (Text-to-SQL)**:
   - Ask natural language business queries (e.g., *"What is the total revenue this month?"*, *"Top 5 customers?"*).
   - Safe execution pipeline: Gemini parses user intent to a read-only SQL query, runs strict checks (whitelisted tables, SELECT only, blocklist keywords), and narrates database results conversationally.

4. **Twilio WhatsApp Notifications**:
   - Sends an automated WhatsApp alert containing invoice numbers, dates, and amounts upon creation or update.
   - Saves delivery parameters (Twilio SID, mobile number, success status, and errors) into the `SMSLog` model for tracking.

---

## 🛠️ Environment Variables Setup

Create a `.env` file in the project root directory (use `.env.example` as a template):

```env
# Django settings
SECRET_KEY=your-django-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database string (Supabase PostgreSQL / default sqlite)
# DATABASE_URL=postgresql://user:pass@host:5432/db

# Google Gemini API key
GEMINI_API_KEY=your-gemini-api-key

# Twilio Credentials (WhatsApp notifications)
TWILIO_ACCOUNT_SID=your-twilio-account-sid
TWILIO_AUTH_TOKEN=your-twilio-auth-token
TWILIO_FROM_NUMBER=whatsapp:+17372508034
TWILIO_CONTENT_SID=HXfe5ab5f00277942d4d4200328b4d403c
```

---

## 💻 Local Setup & Execution

### 1. Set Up Virtual Environment & Packages
```bash
# Initialize and activate venv
python -m venv venv
.\venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Apply Migrations
```bash
python manage.py makemigrations billing
python manage.py migrate
```

### 3. Initialize Admin Superuser (Optional)
```bash
python manage.py createsuperuser
```

### 4. Start Server
```bash
python manage.py runserver 8000
```
Open http://127.0.0.1:8000/ to view the application.

---

## 📈 Database Schema Overview

The system operates on four key models:

1. **Customer**: Holds name, address, mobile, email, and created dates.
2. **Invoice**: Unique invoice number, date, customer link, car details, notes, and discount amount.
3. **LineItem**: List of items associated with an invoice, storing quantity, units, rates, and auto-computed amounts.
4. **SMSLog**: Records WhatsApp notification parameters (SID, receiver, status, error reasons) for debugging.
