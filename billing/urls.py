from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import ocr_views

from workers.views import WorkerViewSet, DailyWorkLogViewSet

router = DefaultRouter()
router.register(r'customers', views.CustomerViewSet, basename='customer')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')
router.register(r'workers', WorkerViewSet, basename='worker')
router.register(r'work-logs', DailyWorkLogViewSet, basename='worklog')

urlpatterns = [
    # REST API
    path('api/', include(router.urls)),

    # ── Gemini AI endpoints ───────────────────────────────────────────────
    # POST  /api/ocr/scan-invoice/         → OCR a handwritten invoice photo
    # GET   /api/ocr/ai-summary/           → Gemini-narrated dashboard summary
    # GET   /api/ocr/customers/<id>/whatsapp-draft/ → WhatsApp follow-up message
    # GET   /api/ocr/suggest-rate/?product=Engine+Oil → rate suggestion
    path('api/ocr/scan-invoice/', ocr_views.scan_invoice, name='ocr_scan_invoice'),
    path('api/ocr/ai-summary/', ocr_views.ai_dashboard_summary, name='ocr_ai_summary'),
    path('api/ocr/customers/<int:customer_id>/whatsapp-draft/', ocr_views.whatsapp_draft, name='ocr_whatsapp_draft'),
    path('api/ocr/suggest-rate/', ocr_views.suggest_rate, name='ocr_suggest_rate'),
    path('api/ocr/chatbot/', ocr_views.chatbot_query, name='ocr_chatbot'),

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
