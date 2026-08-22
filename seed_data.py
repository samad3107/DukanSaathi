import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dukaan_saathi.settings')
django.setup()

from core.models import Product, Customer, Sale

def run_seed():
    print("Seeding initial inventory and customer data...")
    
    # Create Customers
    c1, _ = Customer.objects.get_or_create(name="Rahul Sharma", phone="9876543210")
    c2, _ = Customer.objects.get_or_create(name="Priya Patel", phone="9812345678")
    c3, _ = Customer.objects.get_or_create(name="Anil Kumar", phone="9765432109")

    # Create Products
    p1, _ = Product.objects.get_or_create(name="Basmati Rice 5kg", category="Groceries", price=450.00, stock_quantity=15)
    p2, _ = Product.objects.get_or_create(name="Sunflower Oil 1L", category="Groceries", price=165.00, stock_quantity=4) # Low stock
    p3, _ = Product.objects.get_or_create(name="Whole Wheat Atta 10kg", category="Groceries", price=380.00, stock_quantity=20)
    p4, _ = Product.objects.get_or_create(name="Toor Dal 1kg", category="Pulses", price=140.00, stock_quantity=2) # Low stock

    # Record Sales
    Sale.objects.get_or_create(product=p1, customer=c1, quantity=2, total_amount=900.00)
    Sale.objects.get_or_create(product=p2, customer=c2, quantity=1, total_amount=165.00)
    Sale.objects.get_or_create(product=p3, customer=c3, quantity=1, total_amount=380.00)

    print("Seeding completed successfully! Check your dashboard.")

if __name__ == '__main__':
    run_seed()