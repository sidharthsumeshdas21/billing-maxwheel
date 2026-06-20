from django.db import models
from django.utils import timezone
import datetime


class Customer(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True, default='')
    mobile = models.CharField(max_length=20, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Invoice(models.Model):
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField(default=timezone.now)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices')
    car_model = models.CharField(max_length=100, blank=True, default='')
    car_number = models.CharField(max_length=50, blank=True, default='')
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date', '-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} — {self.customer.name}"

    @property
    def subtotal(self):
        return sum(item.amount for item in self.line_items.all())

    @property
    def total(self):
        return self.subtotal - self.discount

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.line_items.all())

    @classmethod
    def get_next_invoice_number(cls):
        """Auto-generate invoice number like 36/26-27 based on Indian financial year."""
        today = timezone.now().date()
        if today.month >= 4:
            fy_start = today.year
        else:
            fy_start = today.year - 1
        fy_end = fy_start + 1
        fy_suffix = f"{str(fy_start)[-2:]}-{str(fy_end)[-2:]}"

        # Find the last invoice for this financial year
        prefix = f"/{fy_suffix}"
        last = cls.objects.filter(invoice_number__endswith=prefix).order_by('-invoice_number').first()

        if last:
            try:
                last_num = int(last.invoice_number.split('/')[0])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"{next_num}/{fy_suffix}"


class LineItem(models.Model):
    UNIT_CHOICES = [
        ('PCS', 'PCS'),
        ('NOS', 'NOS'),
        ('LTR', 'LTR'),
        ('KG', 'KG'),
        ('MTR', 'MTR'),
        ('SET', 'SET'),
        ('-', '-'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    sr_no = models.PositiveIntegerField()
    product_name = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='PCS')
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['sr_no']

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sr_no}. {self.product_name}"
