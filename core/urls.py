from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('sales/', views.sales_list, name='sales_list'),
    path('sales/export/', views.export_sales_csv, name='export_sales_csv'),
    path('api/generate-qr/', views.generate_checkout_qr, name='generate_checkout_qr'),
    path('api/paytm/initiate/', views.initiate_paytm_payment, name='initiate_paytm_payment'),
    path('paytm/callback/', views.paytm_callback, name='paytm_callback'),
    path('api/inventory-snapshot/', views.inventory_snapshot, name='inventory_snapshot'),
    path('api/udhaar-qr/<int:customer_id>/', views.udhaar_payment_qr, name='udhaar_payment_qr'),
    path('ai-advisor/', views.ai_advisor_view, name='ai_advisor'),
    path('api/ai-chat/', views.ai_chat_api, name='ai_chat_api'),
    path('api/parse-invoice/', views.parse_invoice_image, name='parse_invoice'),
    path('api/bulk-add-inventory/', views.bulk_add_inventory, name='bulk_add_inventory'),
    path('api/lookup-barcode/', views.lookup_barcode, name='lookup_barcode'),
    path('api/ai-agent/', views.ai_analytics_agent, name='ai_analytics_agent'),
    path('api/send-udhaar-reminder/', views.send_udhaar_reminder_view, name='send_udhaar_reminder'),
    path('api/send-sms-udhaar-reminder/', views.send_sms_udhaar_reminder_view, name='send_sms_udhaar_reminder'),
]