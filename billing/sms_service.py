"""
billing/sms_service.py

WhatsApp invoice notification via Twilio.
Called automatically after every InvoiceViewSet.create() and .update().

Behaviour:
  - If TWILIO_ACCOUNT_SID is blank -> skip silently, status='skipped'
  - If customer has no mobile      -> skip silently, status='skipped'
  - On success                     -> status='sent', twilio_sid logged
  - On Twilio API error            -> status='failed', error logged
  - All outcomes written to SMSLog -> visible in Django admin
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _normalise_to_whatsapp(mobile: str):
    """
    Normalise a raw Indian mobile number to Twilio WhatsApp format.
    Returns e.g. 'whatsapp:+919898989898' or None if invalid.
    """
    mobile = mobile.strip().lstrip('+').replace(' ', '').replace('-', '')
    if not mobile:
        return None
    mobile = mobile.lstrip('0')
    if not mobile.startswith('91'):
        mobile = '91' + mobile
    if len(mobile) < 10:
        return None
    return f"whatsapp:+{mobile}"


def send_invoice_whatsapp(invoice) -> dict:
    """
    Send a WhatsApp notification for the given Invoice instance.

    Returns a dict:
    {
        'status': 'sent' | 'failed' | 'skipped',
        'phone':  'whatsapp:+91...' | None,
        'sid':    'SMxxxx' | None,
        'error':  '' | '<error message>',
    }
    The caller is responsible for writing an SMSLog entry.
    """
    # 1. Guard: credentials configured?
    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '').strip()
    auth_token  = getattr(settings, 'TWILIO_AUTH_TOKEN',  '').strip()
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '').strip()
    content_sid = getattr(settings, 'TWILIO_CONTENT_SID', '').strip()

    if not all([account_sid, auth_token, from_number]):
        logger.debug("Twilio not configured - skipping WhatsApp for invoice %s", invoice.invoice_number)
        return {'status': 'skipped', 'phone': None, 'sid': None, 'error': 'Twilio not configured'}

    # 2. Guard: customer has a mobile number?
    raw_mobile = (invoice.customer.mobile or '').strip()
    to_number  = _normalise_to_whatsapp(raw_mobile)
    if not to_number:
        logger.info("No valid mobile for customer '%s' - skipping WhatsApp", invoice.customer.name)
        return {'status': 'skipped', 'phone': None, 'sid': None, 'error': 'No mobile number'}

    # 3. Build Twilio message params
    msg_params = {
        'to':    to_number,
        'from_': from_number,
    }

    if content_sid:
        # Pre-approved template (ContentSid)
        msg_params['content_sid'] = content_sid
        msg_params['content_variables'] = json.dumps({
            '1': invoice.invoice_number,
            '2': f"\u20b9{float(invoice.total):,.0f}",
            '3': invoice.invoice_date.strftime('%d %b %Y'),
            '4': invoice.customer.name,
        })
    else:
        # Fallback: plain-text WhatsApp body (works on sandbox / session messages)
        msg_params['body'] = (
            f"*Maxwheel Auto Services*\n"
            f"\u2705 Invoice Ready\n\n"
            f"Invoice No: {invoice.invoice_number}\n"
            f"Amount:     \u20b9{float(invoice.total):,.0f}\n"
            f"Date:       {invoice.invoice_date.strftime('%d %b %Y')}\n\n"
            f"Thank you for visiting Maxwheel!\n"
            f"\u260e {settings.COMPANY_MOBILE}"
        )

    # 4. Send via Twilio
    try:
        from twilio.rest import Client
        client  = Client(account_sid, auth_token)
        message = client.messages.create(**msg_params)
        logger.info(
            "WhatsApp sent | SID=%s | to=%s | invoice=%s",
            message.sid, to_number, invoice.invoice_number
        )
        return {'status': 'sent', 'phone': to_number, 'sid': message.sid, 'error': ''}

    except Exception as exc:
        logger.exception(
            "WhatsApp FAILED | to=%s | invoice=%s | error=%s",
            to_number, invoice.invoice_number, exc
        )
        return {'status': 'failed', 'phone': to_number, 'sid': None, 'error': str(exc)}
