from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Q, Sum, Count, Avg, Max
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Customer, Invoice, LineItem, CustomerNote, SMSLog
from .serializers import (
    CustomerSerializer,
    CustomerNoteSerializer,
    InvoiceListSerializer,
    InvoiceDetailSerializer,
    InvoiceWriteSerializer,
)
from .sms_service import send_invoice_whatsapp
import datetime


# ─── Customer ViewSet ────────────────────────────────────────────────────────

class CustomerViewSet(viewsets.ModelViewSet):
    """CRUD for customers. Supports ?q= search."""
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerSerializer

    def get_queryset(self):
        qs = Customer.objects.all().order_by('name')
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(mobile__icontains=q) |
                Q(email__icontains=q)
            )
        return qs

    # ── Customer 360: Full history + stats ────────────────────────────────

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """
        GET /api/customers/{id}/history/

        Returns aggregated stats + invoice list for Customer 360 panel.
        All data comes from existing Invoice + LineItem tables — no extra DB needed.
        """
        customer = self.get_object()
        invoices = customer.invoices.prefetch_related('line_items').order_by('-invoice_date')

        # Core stats
        total_revenue = float(sum(inv.total for inv in invoices))
        invoice_count = invoices.count()
        avg_invoice_value = round(total_revenue / invoice_count, 2) if invoice_count else 0

        # Last visit
        last_invoice = invoices.first()
        last_visit = last_invoice.invoice_date.isoformat() if last_invoice else None
        days_since_visit = (
            (datetime.date.today() - last_invoice.invoice_date).days
            if last_invoice else None
        )

        # Visit frequency (average days between visits)
        dates = [inv.invoice_date for inv in invoices]
        if len(dates) >= 2:
            gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
            avg_gap_days = round(sum(gaps) / len(gaps))
        else:
            avg_gap_days = None

        # Top 5 products this customer buys most
        top_products = list(
            LineItem.objects
            .filter(invoice__customer=customer)
            .values('product_name')
            .annotate(
                times_ordered=Count('id'),
                total_quantity=Sum('quantity'),
                total_spent=Sum('amount'),
            )
            .order_by('-times_ordered')[:5]
        )

        # Customer notes
        notes = CustomerNoteSerializer(customer.customer_notes.all(), many=True).data

        # Recent invoices (last 10)
        recent = InvoiceListSerializer(invoices[:10], many=True).data

        return Response({
            'customer': CustomerSerializer(customer).data,
            'stats': {
                'total_revenue': total_revenue,
                'invoice_count': invoice_count,
                'avg_invoice_value': avg_invoice_value,
                'last_visit': last_visit,
                'days_since_last_visit': days_since_visit,
                'avg_days_between_visits': avg_gap_days,
            },
            'top_products': top_products,
            'recent_invoices': recent,
            'notes': notes,
        })

    # ── Customer Notes CRUD ────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='notes')
    def notes(self, request, pk=None):
        """
        GET  /api/customers/{id}/notes/  → list notes
        POST /api/customers/{id}/notes/  → create a note (body: {"text": "..."})
        """
        customer = self.get_object()
        if request.method == 'GET':
            notes = customer.customer_notes.all()
            return Response(CustomerNoteSerializer(notes, many=True).data)

        serializer = CustomerNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(customer=customer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'], url_path=r'notes/(?P<note_id>\d+)')
    def note_detail(self, request, pk=None, note_id=None):
        """
        PATCH  /api/customers/{id}/notes/{note_id}/  → edit a note
        DELETE /api/customers/{id}/notes/{note_id}/  → delete a note
        """
        customer = self.get_object()
        note = get_object_or_404(CustomerNote, pk=note_id, customer=customer)

        if request.method == 'DELETE':
            note.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = CustomerNoteSerializer(note, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # ── Autocomplete: fast lightweight search for invoice form ─────────────

    @action(detail=False, methods=['get'])
    def autocomplete(self, request):
        """
        GET /api/customers/autocomplete/?q=raj

        Returns id + name + mobile only — used in the invoice form's
        customer search dropdown. Much lighter than the full list endpoint.
        """
        q = request.query_params.get('q', '').strip()
        if not q or len(q) < 2:
            return Response([])
        customers = Customer.objects.filter(
            Q(name__icontains=q) | Q(mobile__icontains=q)
        ).values('id', 'name', 'mobile')[:10]
        return Response(list(customers))


# ─── Invoice ViewSet ──────────────────────────────────────────────────────────

class InvoiceViewSet(viewsets.ModelViewSet):
    """
    CRUD for invoices with nested line items.
    - list    → InvoiceListSerializer   (lightweight)
    - retrieve → InvoiceDetailSerializer (full with line_items)
    - create / update → InvoiceWriteSerializer (writable nested items)
    Supports ?q= search on list.
    Extra actions:
      GET /api/invoices/next-number/ → {'next_number': '42/26-27'}
      GET /api/invoices/dashboard/   → dashboard stats
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Invoice.objects.select_related('customer').prefetch_related('line_items').order_by(
            '-invoice_date', '-created_at'
        )
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(invoice_number__icontains=q) |
                Q(customer__name__icontains=q) |
                Q(car_number__icontains=q) |
                Q(car_model__icontains=q)
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return InvoiceListSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return InvoiceWriteSerializer
        return InvoiceDetailSerializer

    # ── SMS helper ─────────────────────────────────────────────────────────────────────

    def _notify_whatsapp(self, invoice) -> dict:
        """
        Fire-and-forget WhatsApp notification after invoice save.
        Writes result to SMSLog and returns the result dict.
        """
        result = send_invoice_whatsapp(invoice)
        SMSLog.objects.create(
            invoice=invoice,
            phone=result['phone'] or '',
            status=result['status'],
            twilio_sid=result['sid'] or '',
            error_message=result['error'],
        )
        return result

    def create(self, request, *args, **kwargs):
        """
        Override create to inject sms_status into the response.
        The DRF default create() returns the serialised invoice; we add
        'sms_status' and 'sms_phone' keys so the SPA can show the right toast.
        """
        response = super().create(request, *args, **kwargs)
        # Fetch the newly created invoice (id is in the response data)
        invoice_id = response.data.get('id')
        if invoice_id:
            try:
                invoice = Invoice.objects.select_related('customer').get(pk=invoice_id)
                sms_result = self._notify_whatsapp(invoice)
                response.data['sms_status'] = sms_result['status']
                response.data['sms_phone']  = sms_result['phone'] or ''
            except Exception:
                response.data['sms_status'] = 'skipped'
                response.data['sms_phone']  = ''
        return response

    def update(self, request, *args, **kwargs):
        """
        Override update to send WhatsApp on every edit as well.
        """
        response = super().update(request, *args, **kwargs)
        invoice_id = response.data.get('id')
        if invoice_id:
            try:
                invoice = Invoice.objects.select_related('customer').get(pk=invoice_id)
                sms_result = self._notify_whatsapp(invoice)
                response.data['sms_status'] = sms_result['status']
                response.data['sms_phone']  = sms_result['phone'] or ''
            except Exception:
                response.data['sms_status'] = 'skipped'
                response.data['sms_phone']  = ''
        return response

    # ── Extra: next invoice number ────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='next-number')
    def next_number(self, request):
        return Response({'next_number': Invoice.get_next_invoice_number()})

    # ── Extra: dashboard data ─────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        today = timezone.now().date()
        if today.month >= 4:
            fy_start = datetime.date(today.year, 4, 1)
            fy_end = datetime.date(today.year + 1, 3, 31)
        else:
            fy_start = datetime.date(today.year - 1, 4, 1)
            fy_end = datetime.date(today.year, 3, 31)

        fy_invoices = Invoice.objects.filter(
            invoice_date__range=(fy_start, fy_end)
        ).prefetch_related('line_items')
        fy_revenue = float(sum(inv.total for inv in fy_invoices))

        # Monthly revenue for this FY (12 months)
        monthly_data = []
        for i in range(12):
            month_date = fy_start + datetime.timedelta(days=i * 30)
            month_start = datetime.date(month_date.year, month_date.month, 1)
            if month_date.month == 12:
                month_end = datetime.date(month_date.year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                month_end = datetime.date(month_date.year, month_date.month + 1, 1) - datetime.timedelta(days=1)
            inv_in_month = Invoice.objects.filter(
                invoice_date__range=(month_start, month_end)
            ).prefetch_related('line_items')
            monthly_data.append({
                'month': month_start.strftime('%b %y'),
                'revenue': float(sum(inv.total for inv in inv_in_month)),
            })

        recent = Invoice.objects.select_related('customer').prefetch_related('line_items').order_by(
            '-invoice_date', '-created_at'
        )[:10]

        return Response({
            'fy_revenue': fy_revenue,
            'fy_label': f"{fy_start.year}-{str(fy_end.year)[-2:]}",
            'total_invoices': Invoice.objects.count(),
            'total_customers': Customer.objects.count(),
            'monthly_data': monthly_data,
            'recent_invoices': InvoiceListSerializer(recent, many=True).data,
        })


from django.views.decorators.cache import never_cache

# ─── SPA shell ───────────────────────────────────────────────────────────────

@never_cache
@login_required
def app_shell(request, *args, **kwargs):
    """Serves the single-page app. All billing UI routing is done client-side."""
    return render(request, 'billing/app.html', {
        'settings': settings,
        'user': request.user,
    })


# ─── Invoice print (server-rendered for print/PDF quality) ───────────────────

@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer').prefetch_related('line_items'),
        pk=pk,
    )
    return render(request, 'billing/invoice_print.html', {
        'invoice': invoice,
        'settings': settings,
    })
