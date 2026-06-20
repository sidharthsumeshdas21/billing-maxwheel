from django import forms
from django.forms import inlineformset_factory
from .models import Customer, Invoice, LineItem


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'address', 'mobile', 'email']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Customer / Company Name'}),
            'address': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'City / Address'}),
            'mobile': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Mobile Number'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email (optional)'}),
        }


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['invoice_number', 'invoice_date', 'customer', 'car_model', 'car_number', 'discount', 'notes']
        widgets = {
            'invoice_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 36/26-27'}),
            'invoice_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'customer': forms.Select(attrs={'class': 'form-input'}),
            'car_model': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. XUV500'}),
            'car_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. GJ01 RS 1098'}),
            'discount': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': '0.00', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional notes'}),
        }


class LineItemForm(forms.ModelForm):
    class Meta:
        model = LineItem
        fields = ['product_name', 'quantity', 'unit', 'rate']
        widgets = {
            'product_name': forms.TextInput(attrs={'class': 'form-input li-product', 'placeholder': 'Product / Service'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-input li-qty', 'placeholder': '1', 'step': '0.01', 'min': '0'}),
            'unit': forms.Select(attrs={'class': 'form-input li-unit'}),
            'rate': forms.NumberInput(attrs={'class': 'form-input li-rate', 'placeholder': '0.00', 'step': '0.01', 'min': '0'}),
        }


LineItemFormSet = inlineformset_factory(
    Invoice,
    LineItem,
    form=LineItemForm,
    extra=10,
    min_num=1,
    validate_min=True,
    can_delete=True,
    fields=['product_name', 'quantity', 'unit', 'rate'],
)
