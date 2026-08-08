"""
billing/ocr_views.py

Gemini-powered API views for Maxwheel billing intelligence features:

  POST /api/ocr/scan-invoice/
      Accepts a handwritten invoice photo → returns structured draft JSON.
      Zero-storage: image is processed in memory and never written to disk or DB.

  GET  /api/invoices/ai-summary/
      Returns a Gemini-narrated plain-English business summary for the dashboard.
      Response is cached for 24 hours to conserve API quota.

  GET  /api/customers/{id}/whatsapp-draft/
      Returns a personalised WhatsApp follow-up message for a dormant customer.

  GET  /api/invoices/suggest-rate/?product=<name>
      Returns a suggested rate for a product based on your own invoice history.
"""

import base64
import json
import logging
import re
import time
from datetime import date

from google import genai
from google.genai import types as genai_types
from django.conf import settings
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Customer, Invoice, LineItem

logger = logging.getLogger(__name__)


# ─── Gemini client initialisation ────────────────────────────────────────────
# Called once at module load. If GEMINI_API_KEY is blank the views return a
# clear error instead of crashing the whole Django process.

def _get_gemini_client():
    """Return a configured Gemini Client, or raise if key is missing."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Add it to your .env file. "
            "Get a free key at https://aistudio.google.com/app/apikey"
        )
    return genai.Client(api_key=api_key)


# ─── Helpers ──────────────────────────────────────────────────────────────────

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
MAX_SIZE_BYTES = settings.OCR_MAX_IMAGE_SIZE_MB * 1024 * 1024


def _validate_image(image_file):
    """
    Validate uploaded image file.
    Returns (ok: bool, error_message: str | None)
    """
    if image_file.size > MAX_SIZE_BYTES:
        return False, f"Image too large. Maximum size is {settings.OCR_MAX_IMAGE_SIZE_MB} MB."
    content_type = image_file.content_type or ''
    if content_type not in ALLOWED_MIME_TYPES:
        return False, f"Unsupported file type '{content_type}'. Use JPEG, PNG, WebP, or HEIC."
    return True, None


def _fuzzy_match_customer(name: str):
    """
    Try to find an existing customer whose name loosely matches the OCR result.
    Returns the best-matching Customer instance, or None.

    Strategy:
      1. Exact match (case-insensitive)
      2. Name contains the OCR name
      3. OCR name contains the stored name
    Each word in the OCR name is tried independently as a fallback.
    """
    if not name or not name.strip():
        return None

    name = name.strip()

    # 1. Exact / case-insensitive match
    exact = Customer.objects.filter(name__iexact=name).first()
    if exact:
        return exact

    # 2. DB name contains OCR name OR OCR name contains DB name
    partial = Customer.objects.filter(
        Q(name__icontains=name) | Q(name__icontains=name.split()[0])
    ).first()
    if partial:
        return partial

    # 3. Word-by-word fallback (useful for "Rajesh Kumar" ↔ "Rajesh K.")
    for word in name.split():
        if len(word) >= 3:  # skip short words like "Mr", "A"
            match = Customer.objects.filter(name__icontains=word).first()
            if match:
                return match

    return None


# ─── OCR: Handwritten Invoice Scanner ────────────────────────────────────────

# The prompt is the most critical part of the OCR pipeline.
# It is tuned specifically for Maxwheel's Indian automotive workshop context.
OCR_PROMPT = """
You are an expert OCR system for an Indian automotive spare-parts workshop called Maxwheel Auto Services.
Analyse the provided handwritten invoice image carefully.

The invoice is written by the workshop for services/parts provided to vehicle owners.
Common items include: engine oil, oil filter, air filter, brake pads, spark plugs, coolant, etc.
Car numbers follow Indian format e.g. GJ01AB1234.
Prices are in Indian Rupees (₹).

Extract all visible information and return ONLY valid JSON — no markdown, no explanation, no extra text.
If a field is not visible or unreadable, use an empty string "" for text fields and 0 for number fields.
Never invent or guess data — leave fields empty if uncertain.

Return this exact JSON structure:
{
  "customer_name": "full name as written or empty string",
  "customer_mobile": "10-digit mobile number or empty string",
  "invoice_date": "YYYY-MM-DD format — use today if not visible",
  "car_number": "vehicle registration like GJ01AB1234 or empty string",
  "car_model": "make and model like Maruti Swift or empty string",
  "notes": "any service notes, next service due, remarks — or empty string",
  "discount": 0,
  "line_items": [
    {
      "product_name": "exact product name as written",
      "quantity": 1.0,
      "unit": "PCS",
      "rate": 0.0
    }
  ],
  "confidence": "high",
  "warnings": []
}

Rules for line_items:
- Include every row you can see, even if partially legible
- quantity and rate must be numbers (use 0 if unreadable)
- unit must be one of exactly: PCS, NOS, LTR, KG, MTR, SET, -
- If unit is unclear, use PCS as default

Rules for confidence:
- "high"   → most text is clearly legible
- "medium" → some areas are unclear but core data is readable
- "low"    → significant portions are unreadable

Add a warning string for each area you could not read clearly.
""".strip()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def scan_invoice(request):
    """
    POST /api/ocr/scan-invoice/

    Accepts multipart/form-data with field 'image'.
    Sends image to Gemini Vision → returns a structured draft invoice.

    The image is processed entirely in memory and NEVER saved to disk or DB.
    Safe for Supabase free tier — zero storage used.

    Response (200):
    {
      "customer_name": "...",
      "customer_mobile": "...",
      "customer_match": { "id": 3, "name": "Rajesh Shah", "mobile": "..." } | null,
      "invoice_date": "2026-08-06",
      "car_number": "...",
      "car_model": "...",
      "notes": "...",
      "discount": 0,
      "line_items": [...],
      "confidence": "high",
      "warnings": []
    }
    """
    # ── 1. Get image from request ──────────────────────────────────────────
    image_file = request.FILES.get('image')
    if not image_file:
        return Response(
            {'error': 'No image provided. Send the image as multipart field "image".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── 2. Validate image ──────────────────────────────────────────────────
    ok, err = _validate_image(image_file)
    if not ok:
        return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

    # ── 3. Read image bytes into memory (no disk write) ───────────────────
    image_bytes = image_file.read()   # InMemoryUploadedFile → bytes
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    mime_type = image_file.content_type

    # ── 4. Call Gemini Vision API ──────────────────────────────────────────
    try:
        client = _get_gemini_client()
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        response = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=[
                genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                OCR_PROMPT,
            ],
        )
        raw_text = response.text.strip()
    except Exception as e:
        logger.exception("Gemini API call failed during invoice scan")
        return Response(
            {'error': f'Gemini API error: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # ── 5. Parse Gemini's JSON response ───────────────────────────────────
    # Gemini sometimes wraps JSON in ```json ... ``` — strip that defensively
    clean_text = re.sub(r'^```(?:json)?\s*', '', raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r'\s*```$', '', clean_text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError:
        logger.error("Gemini returned non-JSON response: %s", raw_text[:500])
        return Response(
            {
                'error': 'Could not parse the invoice. The image may be too blurry or dark.',
                'raw_response': raw_text[:500],  # helpful for debugging
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # ── 6. Validate and sanitise extracted data ────────────────────────────
    valid_units = {'PCS', 'NOS', 'LTR', 'KG', 'MTR', 'SET', '-'}

    line_items = []
    for item in data.get('line_items', []):
        product_name = str(item.get('product_name', '')).strip()
        if not product_name:
            continue
        unit = str(item.get('unit', 'PCS')).upper()
        if unit not in valid_units:
            unit = 'PCS'
        try:
            quantity = float(item.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1.0
        try:
            rate = float(item.get('rate', 0))
        except (TypeError, ValueError):
            rate = 0.0

        line_items.append({
            'product_name': product_name,
            'quantity': quantity,
            'unit': unit,
            'rate': rate,
        })

    # ── 7. Fuzzy-match customer against DB (auto-create if not found) ─────
    customer_name = str(data.get('customer_name', '')).strip()
    matched_customer = _fuzzy_match_customer(customer_name)
    customer_was_created = False

    # Auto-create customer when Gemini extracted a name but no DB match exists
    if not matched_customer and customer_name:
        try:
            matched_customer = Customer.objects.create(
                name=customer_name,
                mobile=str(data.get('customer_mobile', '')).strip(),
            )
            customer_was_created = True
            logger.info("Auto-created customer '%s' (id=%s) from OCR scan", customer_name, matched_customer.id)
        except Exception:
            logger.exception("Failed to auto-create customer from OCR result")

    customer_match = None
    if matched_customer:
        customer_match = {
            'id':      matched_customer.id,
            'name':    matched_customer.name,
            'mobile':  matched_customer.mobile,
            'address': matched_customer.address,
            'email':   getattr(matched_customer, 'email', ''),
            'created': customer_was_created,   # True = brand-new record, show editable form
        }

    # ── 8. Build and return draft invoice ─────────────────────────────────
    today_str = date.today().isoformat()
    result = {
        'customer_name': customer_name,
        'customer_mobile': str(data.get('customer_mobile', '')).strip(),
        'customer_match': customer_match,           # pre-matched DB customer or null
        'invoice_date': data.get('invoice_date') or today_str,
        'car_number': str(data.get('car_number', '')).strip().upper(),
        'car_model': str(data.get('car_model', '')).strip(),
        'notes': str(data.get('notes', '')).strip(),
        'discount': float(data.get('discount', 0) or 0),
        'line_items': line_items,
        'confidence': data.get('confidence', 'medium'),
        'warnings': data.get('warnings', []),
    }

    return Response(result, status=status.HTTP_200_OK)


# ─── AI Dashboard Summary ─────────────────────────────────────────────────────

# Simple in-process cache (module-level dict) — avoids a Redis dependency.
# Resets on every server restart (acceptable for a 24h cache).
_summary_cache: dict = {}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ai_dashboard_summary(request):
    """
    GET /api/ocr/ai-summary/

    Returns a Gemini-narrated plain-English business summary.
    Cached for AI_SUMMARY_CACHE_SECONDS (default 24h) to conserve API quota.

    Response:
    {
      "summary": "July was your best month...",
      "cached": false,
      "generated_at": "2026-08-06T10:00:00"
    }
    """
    cache_ttl = getattr(settings, 'AI_SUMMARY_CACHE_SECONDS', 86400)
    now = time.time()

    # ── Return cached summary if still fresh ──────────────────────────────
    cached = _summary_cache.get('dashboard')
    if cached and (now - cached['ts']) < cache_ttl:
        return Response({
            'summary': cached['text'],
            'cached': True,
            'generated_at': cached['generated_at'],
        })

    # ── Gather stats from DB ───────────────────────────────────────────────
    today = timezone.now().date()
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    fy_end = date(fy_start.year + 1, 3, 31)

    fy_invoices = Invoice.objects.filter(
        invoice_date__range=(fy_start, fy_end)
    ).prefetch_related('line_items')

    fy_revenue = float(sum(inv.total for inv in fy_invoices))
    fy_invoice_count = fy_invoices.count()
    total_customers = Customer.objects.count()

    # Monthly breakdown (last 6 months)
    from datetime import timedelta
    monthly = []
    for i in range(5, -1, -1):
        check = today.replace(day=1)
        # Go back i months
        month = check.month - i
        year = check.year
        while month <= 0:
            month += 12
            year -= 1
        m_start = date(year, month, 1)
        next_m = month + 1 if month < 12 else 1
        next_y = year if month < 12 else year + 1
        m_end = date(next_y, next_m, 1) - timedelta(days=1)
        m_inv = Invoice.objects.filter(
            invoice_date__range=(m_start, m_end)
        ).prefetch_related('line_items')
        monthly.append({
            'month': m_start.strftime('%b %Y'),
            'revenue': float(sum(inv.total for inv in m_inv)),
            'count': m_inv.count(),
        })

    # Top products this FY
    top_products = (
        LineItem.objects
        .filter(invoice__invoice_date__range=(fy_start, fy_end))
        .values('product_name')
        .annotate(total_qty=Sum('quantity'), total_revenue=Sum('amount'))
        .order_by('-total_revenue')[:5]
    )

    # Dormant customers (no invoice in 90 days)
    ninety_days_ago = today - timezone.timedelta(days=90)
    active_customer_ids = Invoice.objects.filter(
        invoice_date__gte=ninety_days_ago
    ).values_list('customer_id', flat=True).distinct()
    dormant_count = Customer.objects.exclude(id__in=active_customer_ids).count()

    # ── Build Gemini prompt ────────────────────────────────────────────────
    summary_prompt = f"""
You are a friendly business analyst for Maxwheel Auto Services, an automotive workshop in Ahmedabad.
Write a concise, plain-English business summary (3-4 sentences max) based on this data.
Be specific, positive, and actionable. Do not use bullet points.

Financial Year: {fy_start.year}-{str(fy_end.year)[-2:]}
Total FY Revenue: ₹{fy_revenue:,.0f}
Total FY Invoices: {fy_invoice_count}
Total Customers: {total_customers}
Customers inactive >90 days: {dormant_count}

Monthly revenue (last 6 months):
{json.dumps(monthly, indent=2)}

Top 5 products by revenue:
{json.dumps(list(top_products), indent=2, default=str)}

Write a natural, encouraging summary highlighting trends and one actionable recommendation.
""".strip()

    try:
        client = _get_gemini_client()
        resp = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=summary_prompt,
        )
        summary_text = resp.text.strip()
    except Exception as e:
        logger.exception("Gemini AI summary generation failed")
        return Response(
            {'error': f'Could not generate AI summary: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Cache the result
    generated_at = timezone.now().isoformat()
    _summary_cache['dashboard'] = {
        'text': summary_text,
        'ts': now,
        'generated_at': generated_at,
    }

    return Response({
        'summary': summary_text,
        'cached': False,
        'generated_at': generated_at,
    })


# ─── WhatsApp Follow-up Draft ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def whatsapp_draft(request, customer_id):
    """
    GET /api/ocr/customers/<id>/whatsapp-draft/

    Generates a personalised WhatsApp follow-up message for a dormant customer.
    Uses the customer's invoice history to make it specific and relevant.

    Response:
    {
      "message": "Hi Rajesh ji, this is Maxwheel Auto Services...",
      "whatsapp_url": "https://wa.me/919876543210?text=...",
      "days_since_last_visit": 73
    }
    """
    try:
        customer = Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Get last invoice and visit info
    last_invoice = customer.invoices.order_by('-invoice_date').first()
    days_since = None
    if last_invoice:
        days_since = (date.today() - last_invoice.invoice_date).days

    # Top products for this customer
    top_items = (
        LineItem.objects
        .filter(invoice__customer=customer)
        .values('product_name')
        .annotate(times=Count('id'))
        .order_by('-times')[:3]
    )
    top_item_names = ', '.join(i['product_name'] for i in top_items) if top_items else 'service'

    last_car = last_invoice.car_number if last_invoice else ''
    last_model = last_invoice.car_model if last_invoice else ''

    draft_prompt = f"""
Write a short, friendly WhatsApp message in Hinglish (mix of Hindi and English, as spoken in Gujarat/Ahmedabad)
from Maxwheel Auto Services to a customer who hasn't visited in a while.

Customer name: {customer.name}
Days since last visit: {days_since or 'unknown'}
Last car: {last_model} ({last_car})
Most purchased items: {top_item_names}
Workshop mobile: {settings.COMPANY_MOBILE}

Rules:
- Keep it under 3 sentences
- Be warm and personal, not salesy
- Mention their car if known
- End with a soft call to action (call or visit)
- Do NOT use emojis or formal English
- Sound like a real person, not a bot
""".strip()

    try:
        client = _get_gemini_client()
        resp = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=draft_prompt,
        )
        message = resp.text.strip()
    except Exception as e:
        logger.exception("WhatsApp draft generation failed")
        return Response(
            {'error': f'Could not generate message: {str(e)}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Build wa.me URL (works without WhatsApp Business API — completely free)
    import urllib.parse
    mobile = (customer.mobile or '').strip().lstrip('+').lstrip('0')
    if mobile and not mobile.startswith('91'):
        mobile = '91' + mobile
    whatsapp_url = f"https://wa.me/{mobile}?text={urllib.parse.quote(message)}" if mobile else None

    return Response({
        'message': message,
        'whatsapp_url': whatsapp_url,
        'days_since_last_visit': days_since,
    })


# ─── Rate Suggestion ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def suggest_rate(request):
    """
    GET /api/ocr/suggest-rate/?product=Engine+Oil+5W30

    Suggests a rate for a product.
    First checks your own invoice history (most accurate).
    Falls back to Gemini's general knowledge if no history found.

    Response:
    {
      "suggested_rate": 450.0,
      "based_on": "your last 5 invoices",
      "product": "Engine Oil 5W30"
    }
    """
    product = request.query_params.get('product', '').strip()
    if not product:
        return Response({'error': 'Provide ?product= query param.'}, status=status.HTTP_400_BAD_REQUEST)

    # ── Check own invoice history first ───────────────────────────────────
    history = (
        LineItem.objects
        .filter(product_name__icontains=product)
        .order_by('-invoice__invoice_date')[:10]
    )

    if history.exists():
        rates = [float(item.rate) for item in history if item.rate > 0]
        if rates:
            avg_rate = sum(rates) / len(rates)
            return Response({
                'suggested_rate': round(avg_rate, 2),
                'based_on': f'your last {len(rates)} invoice(s)',
                'product': product,
            })

    # ── Fallback to Gemini ────────────────────────────────────────────────
    rate_prompt = f"""
What is the typical retail price in Indian Rupees (₹) for "{product}" 
at an automotive workshop in Ahmedabad, India in 2026?

Return ONLY a JSON object like: {{"rate": 450, "note": "typical market rate"}}
No explanation, no markdown.
""".strip()

    try:
        client = _get_gemini_client()
        resp = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=rate_prompt,
        )
        raw = re.sub(r'^```(?:json)?\s*', '', resp.text.strip(), flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE).strip()
        rate_data = json.loads(raw)
        return Response({
            'suggested_rate': float(rate_data.get('rate', 0)),
            'based_on': 'Gemini market estimate (no history found)',
            'product': product,
        })
    except Exception as e:
        logger.exception("Rate suggestion via Gemini failed")
        return Response({
            'suggested_rate': 0,
            'based_on': 'unavailable',
            'product': product,
        })


# ─── AI Chatbot (Text-to-SQL + Gemini narration) ─────────────────────────────

_DB_SCHEMA = """
Database tables (Django ORM / SQLite in dev, PostgreSQL in prod):
  billing_customer(id, name, address, mobile, email, created_at)
  billing_invoice(id, invoice_number, invoice_date, customer_id,
                  car_model, car_number, discount, notes, created_at, updated_at)
  billing_lineitem(id, invoice_id, sr_no, product_name, quantity, unit, rate, amount)

Relationships:
  billing_invoice.customer_id -> billing_customer.id
  billing_lineitem.invoice_id -> billing_invoice.id

Note: invoice total = SUM(billing_lineitem.amount) - billing_invoice.discount
All money values are in Indian Rupees. Dates stored as YYYY-MM-DD text.
For SQLite: use strftime('%Y-%m', invoice_date) for month grouping.
""".strip()

_ALLOWED_TABLES = {'billing_customer', 'billing_invoice', 'billing_lineitem'}
_FORBIDDEN_KEYWORDS = {
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
    'TRUNCATE', 'EXEC', 'EXECUTE', 'GRANT', 'REVOKE',
}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chatbot_query(request):
    """
    POST /api/ocr/chatbot/
    Body: { "message": "What is the total revenue this month?" }

    Pipeline:
      1. Gemini generates a safe SELECT SQL from the user question.
      2. Server validates: SELECT only, whitelisted tables, no dangerous keywords.
      3. Query executes against the DB.
      4. Gemini narrates the raw results into a conversational answer.

    Response: { "answer": "...", "sql_used": "...", "row_count": 0 }
    """
    message = (request.data.get('message') or '').strip()
    if not message:
        return Response({'error': 'message is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Fast-path for greetings & general app introduction
    msg_lower = message.lower().strip()
    greetings = {'hi', 'hello', 'hey', 'hi there', 'hey there', 'greetings', 'hola', 'good morning', 'good evening', 'good afternoon'}
    app_info_keywords = ['what is this app', 'what can you do', 'who are you', 'what does this app do', 'help', 'how to use', 'about app']

    if msg_lower in greetings or any(k in msg_lower for k in app_info_keywords):
        conv_answer = (
            "Hello! 👋 I am your MaxWheel AI Business Assistant.\n\n"
            "I can help you track your workshop's sales, analyze customer billing history, view daily work logs, or auto-fill invoices from uploaded handwritten photos.\n\n"
            "Try asking me questions like:\n"
            "• 'What is our revenue this month?'\n"
            "• 'Who are our top 5 customers?'\n"
            "• 'Show total invoices generated this week'"
        )
        return Response({
            'answer': conv_answer,
            'sql_used': '',
            'row_count': 0,
        })
    sql_prompt = f"""
You are a SQL expert for an Indian automotive workshop billing system.
Given the schema and a user question, write one safe READ-ONLY SQL SELECT query.

Schema:
{_DB_SCHEMA}

User question: "{message}"

Rules:
- Return ONLY a JSON object: {{"sql": "SELECT ...", "explanation": "brief note"}}
- Only SELECT statements. Never INSERT/UPDATE/DELETE/DROP/CREATE/ALTER.
- Use only the tables listed in the schema.
- Always end with LIMIT 50.
- Use strftime for date grouping in SQLite.
- If the question cannot be answered, return {{"sql": "", "explanation": "Cannot answer."}}
""".strip()

    try:
        client = _get_gemini_client()
        resp = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=sql_prompt,
        )
        raw = re.sub(r'^```(?:json)?\s*', '', resp.text.strip(), flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE).strip()
        sql_data = json.loads(raw)
    except Exception:
        logger.exception("Chatbot SQL generation failed")
        return Response({
            'answer': "Sorry, I couldn't understand that question. Try rephrasing it.",
            'sql_used': '', 'row_count': 0,
        })

    sql = (sql_data.get('sql') or '').strip()
    if not sql:
        # For general questions, greetings ("hi"), or app explanation queries ("what is this app for")
        general_prompt = f"""
You are the AI Assistant for MaxWheel Auto Services Billing SPA — an automotive workshop billing & customer management system.
The user asked: "{message}"

If this is a greeting (like 'hi', 'hello', 'hey'), greet the user warmly as MaxWheel's AI assistant.
If the user asks what the app is for or what you can do, explain briefly in 2-3 friendly sentences:
- MaxWheel Billing is an invoice and customer management platform for auto service shops.
- It allows staff to create/edit invoices, manage customer 360 history, scan handwritten invoice photos using AI OCR, send WhatsApp notifications, and query real-time revenue analytics.
- Invite the user to ask any business questions (e.g., "What is our revenue this month?", "Who are our top customers?").

Keep the response warm, natural, concise (2-3 sentences), and professional.
""".strip()
        try:
            client = _get_gemini_client()
            resp = client.models.generate_content(
                model=settings.OCR_GEMINI_MODEL,
                contents=general_prompt,
            )
            conv_answer = resp.text.strip()
        except Exception:
            conv_answer = "Hello! I am your AI Business Assistant for MaxWheel Auto Services. I can answer questions about your sales, revenue, top customers, or auto-fill invoices from scanned handwritten photos."

        return Response({
            'answer': conv_answer,
            'sql_used': '',
            'row_count': 0,
        })

    # Step 2: Validate SQL (strict allowlist)
    sql_upper = sql.upper().strip()

    if not sql_upper.startswith('SELECT'):
        return Response({'answer': 'I can only answer read-only questions.', 'sql_used': '', 'row_count': 0})

    for kw in _FORBIDDEN_KEYWORDS:
        if kw in sql_upper:
            return Response({'answer': 'That query is not allowed for safety reasons.', 'sql_used': '', 'row_count': 0})

    found_tables = set(re.findall(r'billing_\w+', sql.lower()))
    if not found_tables.issubset(_ALLOWED_TABLES):
        return Response({'answer': 'I can only query invoice and customer data.', 'sql_used': '', 'row_count': 0})

    # Step 3: Execute query
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
    except Exception:
        logger.exception("Chatbot SQL execution failed: %s", sql)
        return Response({
            'answer': "I found a query but had trouble running it. The question may be too complex.",
            'sql_used': sql, 'row_count': 0,
        })

    # Step 4: Narrate results with Gemini
    results_text = f"Columns: {columns}\nRows ({len(rows)} total):\n"
    for row in rows[:15]:
        results_text += str(row) + "\n"

    narrate_prompt = f"""
You are a friendly business analyst for Maxwheel Auto Services, an automotive workshop in Ahmedabad.
The user asked: "{message}"

Query results:
{results_text}

Write 1-3 natural sentences that directly answer the question using the data.
Be specific with numbers. Use Rs. for currency. Sound conversational, not formal.
If no rows were returned, say so naturally.
""".strip()

    try:
        client = _get_gemini_client()
        narr = client.models.generate_content(
            model=settings.OCR_GEMINI_MODEL,
            contents=narrate_prompt,
        )
        answer = narr.text.strip()
    except Exception:
        answer = (
            f"Found {len(rows)} result(s). "
            + (', '.join(str(r) for r in rows[:5]) if rows else 'No data.')
        )

    return Response({'answer': answer, 'sql_used': sql, 'row_count': len(rows)})
