from django.contrib import admin
from .models import Worker, DailyWorkLog


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'mobile', 'is_active', 'created_at')
    list_filter = ('role', 'is_active')
    search_fields = ('name', 'mobile')


@admin.register(DailyWorkLog)
class DailyWorkLogAdmin(admin.ModelAdmin):
    list_display = ('worker', 'date', 'car_number', 'car_model', 'work_description', 'wages', 'invoice')
    list_filter = ('date', 'worker', 'worker__role')
    search_fields = ('worker__name', 'car_number', 'car_model', 'work_description')
    date_hierarchy = 'date'
