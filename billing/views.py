from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Customer, Invoice, LineItem
from .serializers import (
    CustomerSerializer,
    InvoiceListSerializer,
    InvoiceDetailSerializer,
    InvoiceWriteSerializer,
)
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

    # ── Extra: next invoice number ────────────────────────────────────────

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


# ─── SPA shell ───────────────────────────────────────────────────────────────

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
