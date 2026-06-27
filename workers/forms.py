from django import forms
from .models import Worker, DailyWorkLog


class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'mobile', 'role', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Full Name'}),
            'mobile': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Mobile Number'}),
            'role': forms.Select(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }


class DailyWorkLogForm(forms.ModelForm):
    class Meta:
        model = DailyWorkLog
        fields = ['worker', 'date', 'invoice', 'car_number', 'car_model', 'work_description', 'wages', 'remarks']
        widgets = {
            'worker': forms.Select(attrs={'class': 'form-input'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'invoice': forms.Select(attrs={'class': 'form-input'}),
            'car_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. GJ01 RS 1098'}),
            'car_model': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. XUV500'}),
            'work_description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Describe the work done'}),
            'wages': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': '0.00', 'step': '0.01'}),
            'remarks': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional remarks'}),
        }
