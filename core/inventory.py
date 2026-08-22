from django.db import transaction

from .models import InventoryMovement, Product, Sale


class InventoryError(ValueError):
    """Raised when an inventory operation cannot be completed safely."""


@transaction.atomic
def record_sale(product_id, customer=None, quantity=1):
    if quantity < 1:
        raise InventoryError("Sale quantity must be at least 1")
    product = Product.objects.select_for_update().get(pk=product_id)
    stock_before = product.stock_quantity
    if stock_before < quantity:
        raise InventoryError(
            f"Insufficient stock for {product.name}. Available: {stock_before}"
        )
    product.stock_quantity = stock_before - quantity
    product.save(update_fields=["stock_quantity", "updated_at"])
    InventoryMovement.objects.create(
        product=product,
        movement_type=InventoryMovement.SALE,
        quantity=-quantity,
        stock_before=stock_before,
        stock_after=product.stock_quantity,
        note="Sale checkout",
    )
    return Sale.objects.create(
        product=product,
        customer=customer,
        quantity=quantity,
        total_amount=product.price * quantity,
    )


@transaction.atomic
def change_stock(product_id, delta, movement_type, note=""):
    """Apply one stock change while locking the product row and recording it."""
    product = Product.objects.select_for_update().get(pk=product_id)
    stock_before = product.stock_quantity
    stock_after = stock_before + delta

    if stock_after < 0:
        raise InventoryError(
            f"Insufficient stock for {product.name}. Available: {stock_before}"
        )

    product.stock_quantity = stock_after
    product.save(update_fields=["stock_quantity", "updated_at"])
    InventoryMovement.objects.create(
        product=product,
        movement_type=movement_type,
        quantity=delta,
        stock_before=stock_before,
        stock_after=stock_after,
        note=note,
    )
    return product


@transaction.atomic
def set_stock(product_id, stock_quantity, note="Manual stock count"):
    product = Product.objects.select_for_update().get(pk=product_id)
    delta = stock_quantity - product.stock_quantity
    if delta == 0:
        return product
    return change_stock(product_id, delta, InventoryMovement.ADJUSTMENT, note)


def product_snapshot(products=None):
    products = products if products is not None else Product.objects.all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "category": product.category or "General",
            "price": str(product.price),
            "stock_quantity": product.stock_quantity,
            "reorder_level": product.reorder_level,
            "status": (
                "out_of_stock" if product.stock_quantity == 0
                else "low_stock" if product.stock_quantity <= product.reorder_level
                else "in_stock"
            ),
            "updated_at": product.updated_at.isoformat(),
        }
        for product in products
    ]