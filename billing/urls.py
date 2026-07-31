from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'customers', views.CustomerViewSet, basename='customer')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')
router.register(r'estimates', views.EstimateViewSet, basename='estimate')

urlpatterns = [
    # REST API
    path('api/', include(router.urls)),

    # Invoice print — kept server-rendered (CSS/layout precision for PDF)
    path('invoices/<int:pk>/print/', views.invoice_print, name='invoice_print'),

    # Estimate print — kept server-rendered (CSS/layout precision for PDF)
    path('estimates/<int:pk>/print/', views.estimate_print, name='estimate_print'),

    # Backward-compatible named URLs so workers templates (base.html) don't break
    path('invoices/', views.app_shell, name='invoice_list'),
    path('invoices/new/', views.app_shell, name='invoice_create'),
    path('invoices/<int:pk>/', views.app_shell, name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.app_shell, name='invoice_edit'),
    path('customers/', views.app_shell, name='customer_list'),
    path('customers/new/', views.app_shell, name='customer_create'),
    path('customers/<int:pk>/edit/', views.app_shell, name='customer_edit'),

    # Estimate SPA routes
    path('estimates/', views.app_shell, name='estimate_list'),
    path('estimates/new/', views.app_shell, name='estimate_create'),
    path('estimates/<int:pk>/', views.app_shell, name='estimate_detail'),
    path('estimates/<int:pk>/edit/', views.app_shell, name='estimate_edit'),

    # SPA shell — catch-all for billing routes
    path('', views.app_shell, name='dashboard'),
]
