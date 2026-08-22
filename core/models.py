from django.db import models
from django.contrib.auth.models import User

class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def pending_balance(self):
        """Total recorded customer sales awaiting settlement."""
        return self.sale_set.aggregate(total=models.Sum("total_amount"))["total"] or 0

class Product(models.Model):
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=50, blank=True)
    barcode = models.CharField(max_length=64, blank=True, unique=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_quantity = models.IntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def stock_value(self):
        return self.stock_quantity * self.cost_price

    def __str__(self):
        return f"{self.name} - ₹{self.price}"

class Sale(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    sale_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Sale #{self.id} - {self.product.name} (x{self.quantity})"


class InventoryMovement(models.Model):
    RECEIPT = "RECEIPT"
    SALE = "SALE"
    ADJUSTMENT = "ADJUSTMENT"
    MOVEMENT_TYPES = (
        (RECEIPT, "Receipt"),
        (SALE, "Sale"),
        (ADJUSTMENT, "Adjustment"),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField()
    stock_before = models.IntegerField()
    stock_after = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.name}: {self.quantity:+d} ({self.movement_type})"


class PaymentOrder(models.Model):
    INITIATED = "INITIATED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STATUSES = ((INITIATED, "Initiated"), (SUCCESS, "Success"), (FAILED, "Failed"))

    order_id = models.CharField(max_length=64, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUSES, default=INITIATED)
    transaction_id = models.CharField(max_length=128, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.order_id} ({self.status})"