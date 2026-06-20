from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Q, Sum
from django.utils import timezone
from django.conf import settings
from .models import Customer, Invoice, LineItem
from .forms import CustomerForm, InvoiceForm, LineItemFormSet
import datetime


# ─── Dashboard ──────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    today = timezone.now().date()
    # Financial year boundaries
    if today.month >= 4:
        fy_start = datetime.date(today.year, 4, 1)
        fy_end = datetime.date(today.year + 1, 3, 31)
    else:
        fy_start = datetime.date(today.year - 1, 4, 1)
        fy_end = datetime.date(today.year, 3, 31)

    fy_invoices = Invoice.objects.filter(invoice_date__range=(fy_start, fy_end))
    fy_revenue = sum(inv.total for inv in fy_invoices)

    recent_invoices = Invoice.objects.select_related('customer').order_by('-invoice_date', '-created_at')[:10]

    # Monthly revenue for current FY (12 months)
    monthly_data = []
    for i in range(12):
        month_date = fy_start + datetime.timedelta(days=i * 30)
        month_start = datetime.date(month_date.year, month_date.month, 1)
        if month_date.month == 12:
            month_end = datetime.date(month_date.year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            month_end = datetime.date(month_date.year, month_date.month + 1, 1) - datetime.timedelta(days=1)
        inv_in_month = Invoice.objects.filter(invoice_date__range=(month_start, month_end))
        rev = sum(inv.total for inv in inv_in_month)
        monthly_data.append({
            'month': month_start.strftime('%b %y'),
            'revenue': float(rev),
        })

    context = {
        'recent_invoices': recent_invoices,
        'total_invoices': Invoice.objects.count(),
        'total_customers': Customer.objects.count(),
        'fy_revenue': fy_revenue,
        'fy_label': f"{fy_start.year}-{str(fy_end.year)[-2:]}",
        'monthly_data': monthly_data,
    }
    return render(request, 'billing/dashboard.html', context)


# ─── Invoice List ────────────────────────────────────────────────────────────

@login_required
def invoice_list(request):
    q = request.GET.get('q', '').strip()
    invoices = Invoice.objects.select_related('customer').order_by('-invoice_date', '-created_at')
    if q:
        invoices = invoices.filter(
            Q(invoice_number__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(car_number__icontains=q) |
            Q(car_model__icontains=q)
        )
    return render(request, 'billing/invoice_list.html', {'invoices': invoices, 'query': q})


# ─── Invoice Create ──────────────────────────────────────────────────────────

@login_required
def invoice_create(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = LineItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            invoice = form.save()
            items = formset.save(commit=False)
            for i, item in enumerate(items, start=1):
                item.invoice = invoice
                item.sr_no = i
                item.save()
            for obj in formset.deleted_objects:
                obj.delete()
            messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        initial_number = Invoice.get_next_invoice_number()
        form = InvoiceForm(initial={'invoice_number': initial_number, 'invoice_date': timezone.now().date()})
        formset = LineItemFormSet()
    return render(request, 'billing/invoice_form.html', {
        'form': form,
        'formset': formset,
        'title': 'New Invoice',
        'action': 'Create',
    })


# ─── Invoice Detail ──────────────────────────────────────────────────────────

@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('customer').prefetch_related('line_items'), pk=pk)
    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice,
        'settings': settings,
    })


# ─── Invoice Edit ────────────────────────────────────────────────────────────

@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        formset = LineItemFormSet(request.POST, instance=invoice)
        if form.is_valid() and formset.is_valid():
            invoice = form.save()
            items = formset.save(commit=False)
            for i, item in enumerate(items, start=1):
                item.invoice = invoice
                item.sr_no = i
                item.save()
            for obj in formset.deleted_objects:
                obj.delete()
            # Re-number remaining items
            for i, item in enumerate(invoice.line_items.all(), start=1):
                if item.sr_no != i:
                    item.sr_no = i
                    item.save()
            messages.success(request, f'Invoice {invoice.invoice_number} updated!')
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)
        formset = LineItemFormSet(instance=invoice)
    return render(request, 'billing/invoice_form.html', {
        'form': form,
        'formset': formset,
        'invoice': invoice,
        'title': f'Edit Invoice {invoice.invoice_number}',
        'action': 'Update',
    })


# ─── Invoice Delete ──────────────────────────────────────────────────────────

@login_required
def invoice_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        num = invoice.invoice_number
        invoice.delete()
        messages.success(request, f'Invoice {num} deleted.')
        return redirect('invoice_list')
    return render(request, 'billing/invoice_confirm_delete.html', {'invoice': invoice})


# ─── Invoice Print ──────────────────────────────────────────────────────────

@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('customer').prefetch_related('line_items'), pk=pk)
    return render(request, 'billing/invoice_print.html', {
        'invoice': invoice,
        'settings': settings,
    })


# ─── Customer List ───────────────────────────────────────────────────────────

@login_required
def customer_list(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all().order_by('name')
    if q:
        customers = customers.filter(
            Q(name__icontains=q) | Q(mobile__icontains=q) | Q(email__icontains=q)
        )
    return render(request, 'billing/customer_list.html', {'customers': customers, 'query': q})


# ─── Customer Create ─────────────────────────────────────────────────────────

@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f'Customer "{c.name}" added.')
            return redirect('customer_list')
    else:
        form = CustomerForm()
    return render(request, 'billing/customer_form.html', {'form': form, 'title': 'New Customer', 'action': 'Add'})


# ─── Customer Edit ───────────────────────────────────────────────────────────

@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Customer "{customer.name}" updated.')
            return redirect('customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'billing/customer_form.html', {
        'form': form,
        'customer': customer,
        'title': f'Edit {customer.name}',
        'action': 'Update',
    })


# ─── Customer Delete ──────────────────────────────────────────────────────────

@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        name = customer.name
        customer.delete()
        messages.success(request, f'Customer "{name}" deleted.')
        return redirect('customer_list')
    return render(request, 'billing/customer_confirm_delete.html', {'customer': customer})
