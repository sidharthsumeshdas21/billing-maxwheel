from django.urls import path
from . import views

urlpatterns = [
    # Workers
    path('', views.worker_list, name='worker_list'),
    path('new/', views.worker_create, name='worker_create'),
    path('<int:pk>/', views.worker_detail, name='worker_detail'),
    path('<int:pk>/edit/', views.worker_edit, name='worker_edit'),
    path('<int:pk>/delete/', views.worker_delete, name='worker_delete'),

    # Work Logs
    path('logs/', views.worklog_list, name='worklog_list'),
    path('logs/new/', views.worklog_create, name='worklog_create'),
    path('logs/<int:pk>/edit/', views.worklog_edit, name='worklog_edit'),
    path('logs/<int:pk>/delete/', views.worklog_delete, name='worklog_delete'),
]
