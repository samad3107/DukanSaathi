import json
from django.db.models import Sum

from .models import Product, Sale, Customer

# -------------------------------------------------------------------
# 1. Defined Tool Functions
# -------------------------------------------------------------------

def get_top_selling_products(limit: int = 5) -> str:
    """Returns the top selling products by total revenue generated."""
    try:
        results = (
            Sale.objects.values('product__name')
            .annotate(total_revenue=Sum('total_amount'))
            .order_by('-total_revenue')[:limit]
        )
        if not results:
            return "No sales data found."
        
        data = [
            {"product": item['product__name'], "revenue": float(item['total_revenue'] or 0)}
            for item in results
        ]
        return json.dumps(data)
    except Exception as e:
        return f"Error calculating top selling products: {str(e)}"


def get_pending_udhaar_balances(limit: int = 5) -> str:
    """Returns customers with the highest pending udhaar (credit) balances."""
    try:
        customers = [customer for customer in Customer.objects.all() if customer.pending_balance > 0]
        customers.sort(key=lambda customer: customer.pending_balance, reverse=True)
        customers = customers[:limit]
        if not customers:
            return "No customers with pending udhaar balance found."
            
        data = [
            {"customer": c.name, "pending_balance": float(c.pending_balance), "phone": c.phone}
            for c in customers
        ]
        return json.dumps(data)
    except Exception as e:
        return f"Error retrieving udhaar balances: {str(e)}"


def get_low_stock_inventory(threshold: int = 10) -> str:
    """Returns products that have stock levels equal to or below the given threshold."""
    try:
        products = Product.objects.filter(stock_quantity__lte=threshold).order_by('stock_quantity')
        if not products:
            return f"All items have sufficient stock (greater than {threshold})."
            
        data = [
            {"product": p.name, "current_stock": p.stock_quantity}
            for p in products
        ]
        return json.dumps(data)
    except Exception as e:
        return f"Error checking inventory levels: {str(e)}"


# -------------------------------------------------------------------
# 2. Tool Mapping Dictionary
# -------------------------------------------------------------------

AI_TOOL_MAP = {
    "get_top_selling_products": get_top_selling_products,
    "get_pending_udhaar_balances": get_pending_udhaar_balances,
    "get_low_stock_inventory": get_low_stock_inventory,
}

# -------------------------------------------------------------------
# 3. Gemini Schema Declarations (Import Target for views.py)
# -------------------------------------------------------------------

# Option A: Passing Python functions directly (supported in latest google-genai SDK)
gemini_tools_schema = [
    get_top_selling_products,
    get_pending_udhaar_balances,
    get_low_stock_inventory,
]

# Option B: Explicit Function Declaration Schema
# (If using raw FunctionDeclaration types in your Gemini setup, uncomment this instead):
"""
gemini_tools_schema = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_top_selling_products",
                description="Retrieves top selling products based on total sales revenue.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "limit": types.Schema(type=types.Type.INTEGER, description="Number of products to return. Default 5.")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_pending_udhaar_balances",
                description="Retrieves customers owing the highest pending credit/udhaar balance.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "limit": types.Schema(type=types.Type.INTEGER, description="Number of customers to return. Default 5.")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_low_stock_inventory",
                description="Retrieves products with stock count below or equal to a threshold.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "threshold": types.Schema(type=types.Type.INTEGER, description="Stock count threshold limit. Default 10.")
                    }
                )
            )
        ]
    )
]
"""