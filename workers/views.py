from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Avg, Count
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Worker, DailyWorkLog
from .forms import WorkerForm, DailyWorkLogForm
from .serializers import WorkerSerializer, DailyWorkLogSerializer


# ─── REST API ViewSets ───────────────────────────────────────────────────────

class WorkerViewSet(viewsets.ModelViewSet):
    serializer_class = WorkerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Worker.objects.all().order_by('name')
        q = self.request.query_params.get('q', '').strip()
        role = self.request.query_params.get('role', '').strip()
        is_active = self.request.query_params.get('is_active', '').strip()

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(mobile__icontains=q) | Q(role__icontains=q))
        if role and role != 'all':
            qs = qs.filter(role__iexact=role)
        if is_active.lower() == 'true':
            qs = qs.filter(is_active=True)
        elif is_active.lower() == 'false':
            qs = qs.filter(is_active=False)

        return qs

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        worker = self.get_object()
        logs = worker.work_logs.select_related('invoice').all().order_by('-date', '-created_at')
        log_serializer = DailyWorkLogSerializer(logs, many=True)

        agg = logs.aggregate(
            total_wages=Sum('wages'),
            avg_wage=Avg('wages'),
            job_count=Count('id')
        )

        last_log = logs.first()
        last_date = last_log.date if last_log else None

        return Response({
            'worker': WorkerSerializer(worker).data,
            'stats': {
                'total_wages': agg['total_wages'] or 0,
                'avg_wage': agg['avg_wage'] or 0,
                'job_count': agg['job_count'] or 0,
                'last_date': last_date,
            },
            'logs': log_serializer.data,
        })


class DailyWorkLogViewSet(viewsets.ModelViewSet):
    serializer_class = DailyWorkLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = DailyWorkLog.objects.select_related('worker', 'invoice').all().order_by('-date', '-created_at')
        worker_id = self.request.query_params.get('worker', '').strip()
        date_from = self.request.query_params.get('date_from', '').strip()
        date_to = self.request.query_params.get('date_to', '').strip()
        car_number = self.request.query_params.get('car_number', '').strip()
        q = self.request.query_params.get('q', '').strip()

        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if car_number:
            qs = qs.filter(car_number__icontains=car_number)
        if q:
            qs = qs.filter(
                Q(worker__name__icontains=q) |
                Q(car_number__icontains=q) |
                Q(car_model__icontains=q) |
                Q(work_description__icontains=q)
            )

        return qs


# ─── Traditional Django HTML Template Views ─────────────────────────────────

@login_required
def worker_list(request):
    q = request.GET.get('q', '').strip()
    workers = Worker.objects.all().order_by('name')
    if q:
        workers = workers.filter(
            Q(name__icontains=q) | Q(mobile__icontains=q) | Q(role__icontains=q)
        )
    return render(request, 'workers/worker_list.html', {'workers': workers, 'query': q})


@login_required
def worker_create(request):
    if request.method == 'POST':
        form = WorkerForm(request.POST)
        if form.is_valid():
            w = form.save()
            messages.success(request, f'Worker "{w.name}" added.')
            return redirect('worker_list')
    else:
        form = WorkerForm()
    return render(request, 'workers/worker_form.html', {'form': form, 'title': 'New Worker', 'action': 'Add'})


@login_required
def worker_detail(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    logs = worker.work_logs.select_related('invoice').all()
    total_wages = logs.aggregate(total=Sum('wages'))['total'] or 0
    return render(request, 'workers/worker_detail.html', {
        'worker': worker,
        'logs': logs,
        'total_wages': total_wages,
    })


@login_required
def worker_edit(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    if request.method == 'POST':
        form = WorkerForm(request.POST, instance=worker)
        if form.is_valid():
            form.save()
            messages.success(request, f'Worker "{worker.name}" updated.')
            return redirect('worker_detail', pk=worker.pk)
    else:
        form = WorkerForm(instance=worker)
    return render(request, 'workers/worker_form.html', {
        'form': form,
        'worker': worker,
        'title': f'Edit {worker.name}',
        'action': 'Update',
    })


@login_required
def worker_delete(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    if request.method == 'POST':
        name = worker.name
        worker.delete()
        messages.success(request, f'Worker "{name}" deleted.')
        return redirect('worker_list')
    return render(request, 'workers/worker_confirm_delete.html', {'worker': worker})


@login_required
def worklog_list(request):
    logs = DailyWorkLog.objects.select_related('worker', 'invoice').all()

    worker_id = request.GET.get('worker', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    car_number = request.GET.get('car_number', '').strip()

    if worker_id:
        logs = logs.filter(worker_id=worker_id)
    if date_from:
        logs = logs.filter(date__gte=date_from)
    if date_to:
        logs = logs.filter(date__lte=date_to)
    if car_number:
        logs = logs.filter(car_number__icontains=car_number)

    workers = Worker.objects.filter(is_active=True).order_by('name')
    total_wages = logs.aggregate(total=Sum('wages'))['total'] or 0

    return render(request, 'workers/worklog_list.html', {
        'logs': logs,
        'workers': workers,
        'filter_worker': worker_id,
        'filter_date_from': date_from,
        'filter_date_to': date_to,
        'filter_car_number': car_number,
        'total_wages': total_wages,
    })


@login_required
def worklog_create(request):
    if request.method == 'POST':
        form = DailyWorkLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            messages.success(request, f'Work log added for {log.worker.name}.')
            return redirect('worklog_list')
    else:
        form = DailyWorkLogForm(initial={'date': timezone.now().date()})
    return render(request, 'workers/worklog_form.html', {
        'form': form,
        'title': 'New Work Log',
        'action': 'Add',
    })


@login_required
def worklog_edit(request, pk):
    log = get_object_or_404(DailyWorkLog, pk=pk)
    if request.method == 'POST':
        form = DailyWorkLogForm(request.POST, instance=log)
        if form.is_valid():
            form.save()
            messages.success(request, f'Work log updated.')
            return redirect('worklog_list')
    else:
        form = DailyWorkLogForm(instance=log)
    return render(request, 'workers/worklog_form.html', {
        'form': form,
        'log': log,
        'title': f'Edit Work Log',
        'action': 'Update',
    })


@login_required
def worklog_delete(request, pk):
    log = get_object_or_404(DailyWorkLog, pk=pk)
    if request.method == 'POST':
        log.delete()
        messages.success(request, 'Work log deleted.')
        return redirect('worklog_list')
    return render(request, 'workers/worklog_confirm_delete.html', {'log': log})
