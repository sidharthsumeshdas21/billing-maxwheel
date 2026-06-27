from django.db import models


class Worker(models.Model):
    ROLE_CHOICES = [
        ('Mechanic', 'Mechanic'),
        ('Helper', 'Helper'),
        ('Painter', 'Painter'),
        ('Electrician', 'Electrician'),
        ('Detailer', 'Detailer'),
        ('Other', 'Other'),
    ]

    name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=20, blank=True, default='')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Mechanic')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.role})"


class DailyWorkLog(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='work_logs')
    date = models.DateField()
    invoice = models.ForeignKey(
        'billing.Invoice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='work_logs'
    )
    car_number = models.CharField(max_length=50, blank=True, default='')
    car_model = models.CharField(max_length=100, blank=True, default='')
    work_description = models.TextField()
    wages = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    remarks = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.worker.name} — {self.date}"
