from rest_framework import serializers
from .models import Worker, DailyWorkLog
from django.db.models import Sum


class WorkerSerializer(serializers.ModelSerializer):
    work_logs_count = serializers.SerializerMethodField()
    total_wages = serializers.SerializerMethodField()

    class Meta:
        model = Worker
        fields = [
            'id', 'name', 'mobile', 'role', 'is_active',
            'created_at', 'work_logs_count', 'total_wages'
        ]

    def get_work_logs_count(self, obj):
        return obj.work_logs.count()

    def get_total_wages(self, obj):
        return obj.work_logs.aggregate(total=Sum('wages'))['total'] or 0


class DailyWorkLogSerializer(serializers.ModelSerializer):
    worker_name = serializers.ReadOnlyField(source='worker.name')
    worker_role = serializers.ReadOnlyField(source='worker.role')
    invoice_number = serializers.ReadOnlyField(source='invoice.invoice_number')

    class Meta:
        model = DailyWorkLog
        fields = [
            'id', 'worker', 'worker_name', 'worker_role', 'date',
            'invoice', 'invoice_number', 'car_number', 'car_model',
            'work_description', 'wages', 'remarks', 'created_at'
        ]
