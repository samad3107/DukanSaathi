from django.contrib import admin
from .models import Customer, InventoryMovement, PaymentOrder, Product, Sale

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'created_at')
    search_fields = ('name', 'phone')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'price', 'stock_quantity', 'reorder_level', 'updated_at')
    search_fields = ('name', 'category')
    list_filter = ('category',)

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'customer', 'quantity', 'total_amount', 'sale_date')
    list_filter = ('sale_date',)


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'movement_type', 'quantity', 'stock_before', 'stock_after', 'note')
    list_filter = ('movement_type', 'created_at')
    search_fields = ('product__name', 'note')


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'product', 'quantity', 'amount', 'status', 'transaction_id', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_id', 'transaction_id', 'product__name')