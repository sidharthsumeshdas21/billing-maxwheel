from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'customers', views.CustomerViewSet, basename='customer')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')

urlpatterns = [
    # REST API
    path('api/', include(router.urls)),

    # Invoice print — kept server-rendered (CSS/layout precision for PDF)
    path('invoices/<int:pk>/print/', views.invoice_print, name='invoice_print'),

    # Backward-compatible named URLs so workers templates (base.html) don't break
    path('invoices/', views.app_shell, name='invoice_list'),
    path('invoices/new/', views.app_shell, name='invoice_create'),
    path('customers/', views.app_shell, name='customer_list'),
    path('customers/new/', views.app_shell, name='customer_create'),

    # SPA shell — catch-all for billing routes
    path('', views.app_shell, name='dashboard'),
]
