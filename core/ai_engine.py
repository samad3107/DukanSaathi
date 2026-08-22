from datetime import timedelta
import math

from django.db.models import Sum
from django.utils import timezone
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error

from .models import Customer, Product, Sale

def get_restock_predictions():
    """
    Trains one lightweight regression model per product on daily sales.
    Sparse products use a clearly marked historical baseline instead.
    """
    today = timezone.localdate()
    window_start = today - timedelta(days=29)
    products = Product.objects.all()
    predictions = []
    chart_products = []

    for product in products:
        daily_sales = []
        for day_offset in range(30):
            day = window_start + timedelta(days=day_offset)
            quantity = Sale.objects.filter(
                product=product, sale_date__date=day
            ).aggregate(total_qty=Sum("quantity"))["total_qty"] or 0
            daily_sales.append(float(quantity))

        sale_days = sum(quantity > 0 for quantity in daily_sales)
        model_used = "historical baseline"
        total_units = sum(daily_sales)
        average_demand = total_units / 30 if total_units else 0
        recent_demand = sum(daily_sales[-7:]) / 7
        deviation = (sum((value - average_demand) ** 2 for value in daily_sales) / 30) ** 0.5
        forecast = total_units / max(7, sale_days) if total_units else 0
        confidence = min(95, round(25 + sale_days * 7 + min(total_units, 20)))
        trend = "stable"
        if sale_days >= 3:
            model = LinearRegression().fit(
                [[index] for index in range(30)], daily_sales
            )
            future_values = model.predict([[index] for index in range(30, 37)])
            forecast = max(0, sum(max(0, value) for value in future_values) / 7)
            model_used = "trained linear regression"
            trend = "rising" if forecast > average_demand * 1.1 else "falling" if forecast < average_demand * .9 else "stable"
            backtest_prediction = model.predict([[index] for index in range(23)])
            confidence = max(35, min(95, round(100 - mean_absolute_error(daily_sales[:23], backtest_prediction) * 12)))
        elif recent_demand > average_demand * 1.1:
            trend = "rising"
        elif recent_demand < average_demand * .9:
            trend = "falling"

        daily_velocity = round(forecast, 2)
        days_left = round(product.stock_quantity / forecast, 1) if forecast > 0 else None

        lead_time_days = 3
        safety_stock = math.ceil(deviation * 1.65 * math.sqrt(lead_time_days))
        reorder_point = math.ceil(forecast * lead_time_days + safety_stock)
        target_stock = max(reorder_point + math.ceil(forecast * 12), 15)
        suggested_reorder = max(0, target_stock - product.stock_quantity)

        if product.stock_quantity == 0:
            risk = "CRITICAL"
        elif days_left is not None and days_left <= 3:
            risk = "HIGH"
        elif days_left is not None and days_left <= 7:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        labels = [(window_start + timedelta(days=index)).isoformat() for index in range(30)]
        labels += [(today + timedelta(days=index)).isoformat() for index in range(1, 8)]
        chart_products.append({
            "name": product.name,
            "actual": daily_sales + [None] * 7,
            "forecast": [None] * 29 + [daily_sales[-1] if daily_sales else 0] + [round(max(0, forecast), 2)] * 7,
        })

        predictions.append({
            'product_id': product.id,
            'name': product.name,
            'category': product.category or 'General',
            'current_stock': product.stock_quantity,
            'daily_velocity': round(daily_velocity, 2),
            'days_left': days_left if days_left is not None else 'No recent sales',
            'suggested_reorder': suggested_reorder,
            'reorder_point': reorder_point,
            'safety_stock': safety_stock,
            'risk': risk,
            'model_used': model_used,
            'training_days': sale_days,
            'confidence': confidence,
            'trend': trend,
            'average_demand': round(average_demand, 2),
        })

    # Sort by highest risk first
    risk_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    predictions.sort(key=lambda x: risk_order[x['risk']])
    summary = {
        "products": len(predictions),
        "reorder_count": sum(item["suggested_reorder"] > 0 for item in predictions),
        "critical_count": sum(item["risk"] == "CRITICAL" for item in predictions),
        "average_confidence": round(sum(item["confidence"] for item in predictions) / len(predictions)) if predictions else 0,
    }
    return {
        "predictions": predictions,
        "chart": {
            "labels": labels if products.exists() else [],
            "products": chart_products[:6],
        },
        "model_name": "Per-product linear regression",
        "training_window": "30 days",
        "summary": summary,
    }


def process_ai_query(user_query):
    """
    Interprets natural language queries from shopkeepers in English or Hinglish/Hindi
    and queries the Django ORM dynamically.
    """
    query = user_query.lower().strip()

    # Product revenue questions need to be resolved before general revenue questions.
    if ('product' in query or 'products' in query) and any(
        k in query for k in ['revenue', 'earning', 'sales', 'kamai']
    ):
        top_products = list(
            Sale.objects.values('product__name')
            .annotate(total_revenue=Sum('total_amount'))
            .order_by('-total_revenue')[:5]
        )
        if not top_products:
            return {
                'answer': "No sales transactions recorded yet to calculate product revenue.",
                'intent': 'PRODUCT_REVENUE',
            }
        items = "; ".join(
            f"{item['product__name']}: ₹{item['total_revenue']:,.2f}"
            for item in top_products
        )
        return {
            'answer': f"Top products by revenue: {items}.",
            'intent': 'PRODUCT_REVENUE',
        }

    # Query 1: Sales / Revenue performance
    if any(k in query for k in ['revenue', 'earnings', 'kamai', 'total sales', 'paisa']):
        total_rev = Sale.objects.aggregate(total=Sum('total_amount'))['total'] or 0.0
        total_count = Sale.objects.count()
        return {
            'answer': f"Your total lifetime revenue is ₹{total_rev:,.2f} across {total_count} recorded sales transactions.",
            'intent': 'REVENUE_STATS'
        }

    # Query 2: Low stock or restock questions
    elif any(k in query for k in ['low stock', 'restock', 'khatam', 'stock', 'reorder', 'alert']):
        low_stock = Product.objects.filter(stock_quantity__lte=F('reorder_level'))
        if not low_stock.exists():
            return {
                'answer': "All product inventory levels are currently healthy! No critical low stock items found.",
                'intent': 'LOW_STOCK'
            }
        items_str = ", ".join([f"{p.name} ({p.stock_quantity} left)" for p in low_stock])
        return {
            'answer': f"Alert: You have {low_stock.count()} item(s) running low on stock: {items_str}.",
            'intent': 'LOW_STOCK'
        }

    # Query 3: Top selling products
    elif any(k in query for k in ['top', 'best', 'popular', 'highest', 'sabse zyada']):
        top_product = Sale.objects.values('product__name').annotate(
            total_sold=Sum('quantity')
        ).order_by('-total_sold').first()

        if top_product:
            return {
                'answer': f"Your top-selling product is '{top_product['product__name']}' with {top_product['total_sold']} units sold.",
                'intent': 'TOP_PRODUCT'
            }
        return {'answer': "No sales transactions recorded yet to calculate top products.", 'intent': 'TOP_PRODUCT'}

    # Query 4: Customer count
    elif any(k in query for k in ['customer', 'grahak', 'client']):
        cust_count = Customer.objects.count()
        return {
            'answer': f"You currently have {cust_count} registered customers in DukaanSaathi.",
            'intent': 'CUSTOMER_STATS'
        }

    # Default fallback
    return {
        'answer': f"I analyzed your shop data for '{user_query}'. For best results, ask me about 'low stock items', 'total revenue', or 'top selling products'.",
        'intent': 'GENERAL'
    }