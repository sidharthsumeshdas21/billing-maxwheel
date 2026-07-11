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

    # SPA shell — all other billing routes served by the JS app
    path('', views.app_shell, name='app_shell'),
]
