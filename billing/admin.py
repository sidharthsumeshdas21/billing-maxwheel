from django.contrib import admin
from .models import Customer, Invoice, LineItem, Estimate, EstimateLineItem


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


class EstimateLineItemInline(admin.TabularInline):
    model = EstimateLineItem
    extra = 0
    readonly_fields = ('amount',)


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display = ('estimate_number', 'customer', 'estimate_date', 'subtotal', 'discount', 'total')
    list_filter = ('estimate_date',)
    search_fields = ('estimate_number', 'customer__name', 'car_number')
    inlines = [EstimateLineItemInline]
    date_hierarchy = 'estimate_date'


@admin.register(EstimateLineItem)
class EstimateLineItemAdmin(admin.ModelAdmin):
    list_display = ('estimate', 'sr_no', 'product_name', 'quantity', 'unit', 'rate', 'amount')
