from rest_framework import serializers
from django.db.models import Q
from .models import Customer, Invoice, LineItem


# ─── Customer ────────────────────────────────────────────────────────────────

class CustomerSerializer(serializers.ModelSerializer):
    invoice_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ['id', 'name', 'address', 'mobile', 'email', 'created_at', 'invoice_count']
        read_only_fields = ['created_at']

    def get_invoice_count(self, obj):
        return obj.invoices.count()


# ─── Line Items ───────────────────────────────────────────────────────────────

class LineItemSerializer(serializers.ModelSerializer):
    """Read-only serializer — used in invoice detail responses."""
    class Meta:
        model = LineItem
        fields = ['id', 'sr_no', 'product_name', 'quantity', 'unit', 'rate', 'amount']
        read_only_fields = ['sr_no', 'amount']


class LineItemWriteSerializer(serializers.Serializer):
    """Write-only serializer — used in invoice create/update payloads."""
    id = serializers.IntegerField(required=False, allow_null=True)
    product_name = serializers.CharField(max_length=200)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit = serializers.ChoiceField(choices=[c[0] for c in LineItem.UNIT_CHOICES])
    rate = serializers.DecimalField(max_digits=10, decimal_places=2)


# ─── Invoice (read) ───────────────────────────────────────────────────────────

class InvoiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    subtotal = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'invoice_date',
            'customer', 'customer_name',
            'car_number', 'car_model',
            'discount', 'subtotal', 'total', 'created_at',
        ]

    def get_subtotal(self, obj):
        return float(obj.subtotal)

    def get_total(self, obj):
        return float(obj.total)


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail / retrieve views — includes nested line items."""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_mobile = serializers.CharField(source='customer.mobile', read_only=True)
    customer_address = serializers.CharField(source='customer.address', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    line_items = LineItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'invoice_date',
            'customer', 'customer_name', 'customer_mobile',
            'customer_address', 'customer_email',
            'car_model', 'car_number', 'discount', 'notes',
            'line_items', 'subtotal', 'total',
            'created_at', 'updated_at',
        ]

    def get_subtotal(self, obj):
        return float(obj.subtotal)

    def get_total(self, obj):
        return float(obj.total)


# ─── Invoice (write) ──────────────────────────────────────────────────────────

class InvoiceWriteSerializer(serializers.ModelSerializer):
    """
    Handles create and update with nested line_items.
    Items with id=null  → created
    Items with id=N     → updated
    Items in DB but absent from payload → deleted
    """
    line_items = LineItemWriteSerializer(many=True)

    class Meta:
        model = Invoice
        fields = [
            'invoice_number', 'invoice_date', 'customer',
            'car_model', 'car_number', 'discount', 'notes',
            'line_items',
        ]

    def validate_line_items(self, value):
        valid = [i for i in value if i.get('product_name', '').strip()]
        if not valid:
            raise serializers.ValidationError("At least one line item with a product name is required.")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('line_items')
        invoice = Invoice.objects.create(**validated_data)
        for sr, item in enumerate(items_data, start=1):
            if not item.get('product_name', '').strip():
                continue
            LineItem.objects.create(
                invoice=invoice,
                sr_no=sr,
                product_name=item['product_name'],
                quantity=item['quantity'],
                unit=item['unit'],
                rate=item['rate'],
            )
        return invoice

    def update(self, instance, validated_data):
        items_data = validated_data.pop('line_items')

        # Update invoice header fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        existing_ids = set(instance.line_items.values_list('id', flat=True))
        submitted_ids = {item['id'] for item in items_data if item.get('id')}

        # Delete items removed from payload
        LineItem.objects.filter(
            invoice=instance,
            id__in=(existing_ids - submitted_ids)
        ).delete()

        # Upsert remaining items
        for sr, item in enumerate(items_data, start=1):
            if not item.get('product_name', '').strip():
                continue
            item_id = item.get('id')
            payload = dict(
                sr_no=sr,
                product_name=item['product_name'],
                quantity=item['quantity'],
                unit=item['unit'],
                rate=item['rate'],
            )
            if item_id and item_id in existing_ids:
                li = LineItem.objects.get(id=item_id, invoice=instance)
                for k, v in payload.items():
                    setattr(li, k, v)
                li.save()
            else:
                LineItem.objects.create(invoice=instance, **payload)

        instance.refresh_from_db()
        return instance
