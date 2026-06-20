from django.contrib import admin
from .models import Customer, Invoice, LineItem


class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 0
    readonly_fields = ('amount',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'customer', 'invoice_date', 'subtotal', 'discount', 'total')
    list_filter = ('invoice_date',)
    search_fields = ('invoice_number', 'customer__name', 'car_number')
    inlines = [LineItemInline]
    date_hierarchy = 'invoice_date'


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'mobile', 'email', 'created_at')
    search_fields = ('name', 'mobile', 'email')


@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'sr_no', 'product_name', 'quantity', 'unit', 'rate', 'amount')
