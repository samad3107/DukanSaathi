import csv
import json
import os
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from google import genai
from google.genai import types
from PIL import Image

from .ai_engine import get_restock_predictions, process_ai_query
from .ai_tools import AI_TOOL_MAP, gemini_tools_schema
from .inventory import InventoryError, change_stock, product_snapshot, record_sale, set_stock
from .models import Customer, InventoryMovement, PaymentOrder, Product, Sale
from .utils import generate_paytm_payment_link, generate_paytm_upi_qr, generate_paytm_upi_qr_bytes, initiate_paytm_transaction, verify_paytm_callback
from .whatsapp_utils import send_sms_udhaar_reminder, send_voice_udhaar_reminder, send_whatsapp_udhaar_reminder

API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None


def dashboard(request):
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_product":
            name = request.POST.get("name")
            category = request.POST.get("category")
            price = request.POST.get("price")
            stock = request.POST.get("stock_quantity")
            product = Product.objects.create(
                name=name, category=category, price=price, stock_quantity=stock,
                cost_price=request.POST.get("cost_price") or 0,
                reorder_level=request.POST.get("reorder_level") or 5,
            )
            opening_stock = int(stock or 0)
            if opening_stock:
                product.stock_quantity = 0
                product.save(update_fields=["stock_quantity", "updated_at"])
                change_stock(product.id, opening_stock, InventoryMovement.RECEIPT, "Opening stock")
            messages.success(request, f"Product '{name}' added successfully!")

        elif action == "add_customer":
            name = request.POST.get("name")
            phone = request.POST.get("phone")
            Customer.objects.create(name=name, phone=phone)
            messages.success(
                request, f"Customer '{name}' registered successfully!"
            )

        elif action == "add_sale":
            product_id = request.POST.get("product_id")
            customer_id = request.POST.get("customer_id")
            quantity = int(request.POST.get("quantity", 1))

            customer = (
                Customer.objects.filter(id=customer_id).first()
                if customer_id
                else None
            )
            try:
                record_sale(product_id, customer=customer, quantity=quantity)
                messages.success(request, "Sale recorded successfully!")
            except (Product.DoesNotExist, InventoryError) as error:
                messages.error(
                    request,
                    str(error),
                )

        return redirect("dashboard")

    # GET Request context
    total_products = Product.objects.count()
    total_customers = Customer.objects.count()
    total_sales_count = Sale.objects.count()
    total_revenue = (
        Sale.objects.aggregate(revenue=Sum("total_amount"))["revenue"] or 0.00
    )

    products = Product.objects.all()
    customers = Customer.objects.all()
    low_stock_products = Product.objects.filter(stock_quantity__lte=F("reorder_level"))
    recent_sales = Sale.objects.select_related("product", "customer").order_by(
        "-sale_date"
    )[:5]

    context = {
        "total_products": total_products,
        "total_customers": total_customers,
        "total_sales_count": total_sales_count,
        "total_revenue": total_revenue,
        "products": products,
        "customers": customers,
        "low_stock_products": low_stock_products,
        "recent_sales": recent_sales,
    }
    return render(request, "core/dashboard.html", context)


def inventory_list(request):
    search_query = request.GET.get("search", "")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_stock":
            product_id = request.POST.get("product_id")
            new_stock = request.POST.get("stock_quantity")
            try:
                product = set_stock(product_id, int(new_stock))
                messages.success(request, f"Updated stock for {product.name} to {new_stock} units.")
            except (Product.DoesNotExist, ValueError) as error:
                messages.error(request, str(error))
            return redirect("inventory_list")

    products = Product.objects.all()
    if search_query:
        products = products.filter(
            name__icontains=search_query
        ) | products.filter(category__icontains=search_query)

    context = {
        "products": products,
        "search_query": search_query,
    }
    return render(request, "core/inventory.html", context)


def sales_list(request):
    customer_filter = request.GET.get("customer", "")

    sales = Sale.objects.select_related("product", "customer").order_by(
        "-sale_date"
    )

    if customer_filter:
        sales = sales.filter(customer_id=customer_filter)

    customers = Customer.objects.all()

    context = {
        "sales": sales,
        "customers": customers,
        "selected_customer": customer_filter,
    }
    return render(request, "core/sales.html", context)


def export_sales_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="sales_report.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "Sale ID",
            "Product",
            "Customer",
            "Quantity",
            "Total Amount (INR)",
            "Sale Date",
        ]
    )

    sales = Sale.objects.select_related("product", "customer").order_by(
        "-sale_date"
    )
    for sale in sales:
        customer_name = (
            sale.customer.name if sale.customer else "Walk-in Customer"
        )
        writer.writerow(
            [
                sale.id,
                sale.product.name,
                customer_name,
                sale.quantity,
                sale.total_amount,
                sale.sale_date.strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    return response


def generate_checkout_qr(request):
    """AJAX endpoint to return payment QR code for a given product and quantity."""
    if request.method != "GET":
        return JsonResponse({"error": "Invalid request"}, status=400)

    product_id = request.GET.get("product_id")
    try:
        quantity = int(request.GET.get("quantity", 1))
        if quantity < 1:
            raise ValueError("Quantity must be at least 1")
        product = Product.objects.get(id=product_id)
        total_amount = float(product.price * quantity)

        if product.stock_quantity < quantity:
            return JsonResponse(
                {
                    "error": f"Insufficient stock! Available: {product.stock_quantity}"
                },
                status=400,
            )

        qr_code_data = generate_paytm_upi_qr(
            total_amount, note=f"Order for {product.name}"
        )

        return JsonResponse(
            {
                "success": True,
                "product_name": product.name,
                "total_amount": f"{total_amount:.2f}",
                "qr_code": qr_code_data,
            }
        )
    except Product.DoesNotExist:
        return JsonResponse({"error": "Product not found"}, status=404)
    except (TypeError, ValueError):
        return JsonResponse({"error": "A valid product and quantity are required"}, status=400)
    except Exception as error:
        return JsonResponse({"error": f"QR generation failed: {error}"}, status=500)


@require_POST
def initiate_paytm_payment(request):
    try:
        product_id = request.POST.get("product_id")
        quantity = int(request.POST.get("quantity", 1))
        customer_id = request.POST.get("customer_id") or None
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            if quantity < 1 or product.stock_quantity < quantity:
                return JsonResponse({"error": f"Insufficient stock for {product.name}. Available: {product.stock_quantity}"}, status=400)
            customer = Customer.objects.filter(pk=customer_id).first() if customer_id else None
            order = PaymentOrder.objects.create(
                order_id=f"DS_{timezone.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10].upper()}",
                product=product,
                customer=customer,
                quantity=quantity,
                amount=product.price * quantity,
            )
        gateway = initiate_paytm_transaction(
            order.order_id, order.amount, customer_id, request.build_absolute_uri("/paytm/callback/")
        )
        if not gateway["configured"]:
            return JsonResponse({
                "mode": "qr_fallback",
                "order_id": order.order_id,
                "message": "Paytm gateway credentials are not configured; using UPI QR fallback.",
                "qr_code": generate_paytm_upi_qr(float(order.amount), note=f"Order {order.order_id}"),
                "total_amount": f"{order.amount:.2f}",
            })
        return JsonResponse({"mode": "paytm_gateway", "amount": f"{order.amount:.2f}", **gateway})
    except (Product.DoesNotExist, ValueError) as error:
        return JsonResponse({"error": str(error)}, status=400)
    except Exception as error:
        return JsonResponse({"error": f"Paytm initiation failed: {error}"}, status=502)


@csrf_exempt
@require_POST
def paytm_callback(request):
    payload = request.POST.dict()
    order_id = payload.get("ORDERID", "")
    try:
        with transaction.atomic():
            order = PaymentOrder.objects.select_for_update().select_related("product").get(order_id=order_id)
            if not verify_paytm_callback(payload):
                return HttpResponse("Invalid Paytm signature", status=400)
            if order.status == PaymentOrder.SUCCESS:
                return redirect("dashboard")
            order.gateway_response = payload
            order.transaction_id = payload.get("TXNID", "")
            try:
                callback_amount = Decimal(payload.get("TXNAMOUNT", "0")).quantize(Decimal("0.01"))
            except InvalidOperation:
                callback_amount = Decimal("0")
            if payload.get("STATUS") == "TXN_SUCCESS" and callback_amount == order.amount:
                record_sale(order.product_id, customer=order.customer, quantity=order.quantity)
                order.status = PaymentOrder.SUCCESS
            else:
                order.status = PaymentOrder.FAILED
            order.save(update_fields=["status", "transaction_id", "gateway_response", "updated_at"])
        return redirect("dashboard")
    except PaymentOrder.DoesNotExist:
        return HttpResponse("Payment order not found", status=404)


def inventory_snapshot(request):
    """Return current stock state for dashboards and lightweight live polling."""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)
    return JsonResponse({"products": product_snapshot(), "server_time": timezone.now().isoformat()})


def udhaar_payment_qr(request, customer_id):
    try:
        customer = Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        return HttpResponse("Customer not found", status=404)
    amount = float(customer.pending_balance)
    if amount <= 0:
        return HttpResponse("No outstanding balance", status=404)
    return HttpResponse(
        generate_paytm_upi_qr_bytes(amount, note=f"Udhaar payment - {customer.name}"),
        content_type="image/png",
    )


def ai_advisor_view(request):
    """Renders the AI Restock Prediction Dashboard page."""
    model_output = get_restock_predictions()
    context = {
        "predictions": model_output["predictions"],
        "chart_data": json.dumps(model_output["chart"]),
        "model_name": model_output["model_name"],
        "training_window": model_output["training_window"],
        "forecast_summary": model_output["summary"],
    }
    return render(request, "core/ai_advisor.html", context)


def ai_chat_api(request):
    """AJAX endpoint for the Ask DukaanSaathi AI Natural Language Assistant."""
    if request.method == "POST":
        data = json.loads(request.body)
        user_query = data.get("query", "")

        if not user_query:
            return JsonResponse({"error": "Query empty"}, status=400)

        try:
            if client is not None:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=(
                        "You are DukaanSaathi, a concise retail business assistant. "
                        "Answer in simple English or Hinglish using INR when relevant. "
                        f"Shopkeeper question: {user_query}"
                    ),
                )
                return JsonResponse({"answer": response.text, "source": "gemini"})
            return JsonResponse({**process_ai_query(user_query), "source": "local"})
        except Exception as error:
            return JsonResponse({"error": f"Gemini chat failed: {error}"}, status=502)

    return JsonResponse({"error": "Invalid method"}, status=405)


@csrf_exempt
def parse_invoice_image(request):
    """Accepts an uploaded invoice/receipt image, passes it to Gemini 2.5 Flash,

    and returns extracted structured inventory items.
    """
    if request.method != "POST" or not request.FILES.get("invoice_image"):
        return JsonResponse(
            {"error": "Please provide an invoice image file."}, status=400
        )

    try:
        if client is None:
            return JsonResponse(
                {"error": "Gemini is not configured. Set GEMINI_API_KEY to enable invoice scanning."},
                status=503,
            )
        uploaded_file = request.FILES["invoice_image"]
        img = Image.open(uploaded_file)

        prompt = """
        Analyze this supplier invoice / purchase receipt / paper khata note.
        Extract all individual product items listed on the document.
        For each product item, extract:
        1. product_name (String): Name of the item/product
        2. category (String): Choose best fit from [Grains & Pulses, Oils & Spices, Beverages, Snacks & Packaged, Personal Care, Household]
        3. quantity (Integer): Number of units or packs purchased
        4. cost_price (Float): Cost price per single unit in INR (₹)
        5. selling_price (Float): Estimated selling price per unit in INR (₹) (if not specified, set to cost_price * 1.15)
        6. low_stock_threshold (Integer): Default to 10 if unknown

        Return a strictly valid JSON object matching this schema:
        {
          "invoice_number": "String or Unknown",
          "supplier_name": "String or Unknown",
          "items": [
             {
               "product_name": "Product Name",
               "category": "Category",
               "quantity": 50,
               "cost_price": 45.0,
               "selling_price": 52.0,
               "low_stock_threshold": 10
             }
          ]
        }
        """

        # Request structured JSON output from Gemini 2.5 Flash using hardcoded API key client
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[img, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )

        parsed_data = json.loads(response.text)
        return JsonResponse({"status": "success", "data": parsed_data})

    except Exception as e:
        return JsonResponse(
            {"error": f"Failed to parse invoice: {str(e)}"}, status=500
        )


@csrf_exempt
@require_POST
def bulk_add_inventory(request):
    """Saves parsed invoice items directly to the database.

    If an item with the same name exists, it increments stock. Otherwise,
    creates it.
    """
    try:
        payload = json.loads(request.body)
        items = payload.get("items", [])

        added_count = 0
        updated_count = 0

        for item in items:
            product_name = item.get("product_name").strip()
            qty = int(item.get("quantity", 0))
            cost_price = float(item.get("cost_price", 0))
            selling_price = float(item.get("selling_price", 0))
            category = item.get("category", "General")

            product, created = Product.objects.get_or_create(
                name__iexact=product_name,
                defaults={
                    "name": product_name,
                    "category": category,
                    "stock_quantity": 0,
                    "cost_price": cost_price,
                    "price": selling_price or cost_price,
                },
            )

            if selling_price > 0 or cost_price > 0:
                product.price = selling_price or product.price
                product.cost_price = cost_price or product.cost_price
                product.save(update_fields=["price", "cost_price", "updated_at"])
            if qty > 0:
                change_stock(product.id, qty, InventoryMovement.RECEIPT, "Invoice receipt")
            if not created:
                updated_count += 1
            else:
                added_count += 1

        return JsonResponse({
            "status": "success",
            "message": (
                f"Successfully processed items: {added_count} created,"
                f" {updated_count} stock updated."
            ),
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def send_sms_udhaar_reminder_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        customer_id = data.get("customer_id")
        if not customer_id:
            return JsonResponse({"error": "Customer ID is required"}, status=400)

        customer = Customer.objects.get(id=customer_id)
        pending_amount = getattr(customer, "pending_balance", 0.0)
        if pending_amount <= 0:
            return JsonResponse({"error": "Customer has no outstanding balance"}, status=400)

        recipient = os.getenv("SMS_TEST_NUMBER") or os.getenv("VOICE_TEST_NUMBER") or customer.phone
        sms_result = send_sms_udhaar_reminder(
            customer_phone=recipient,
            customer_name=customer.name,
            pending_amount=float(pending_amount),
            payment_link=generate_paytm_payment_link(
                float(pending_amount), customer.name, note="Udhaar payment"
            ),
        )
        call_result = send_voice_udhaar_reminder(
            customer_phone=recipient,
            customer_name=customer.name,
            pending_amount=float(pending_amount),
        )
        sms_status = "sent" if sms_result["success"] else f"failed: {sms_result['error']}"
        call_status = "started" if call_result["success"] else f"failed: {call_result['error']}"
        message = f"SMS {sms_status}; voice call {call_status}."
        response = {
            "message": message,
            "sms_sent": sms_result["success"],
            "call_started": call_result["success"],
        }
        if sms_result["success"]:
            response["sms_sid"] = sms_result["sid"]
        if call_result["success"]:
            response["call_sid"] = call_result["sid"]
        return JsonResponse(response, status=200 if sms_result["success"] or call_result["success"] else 502)
    except Customer.DoesNotExist:
        return JsonResponse({"error": "Customer not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def lookup_barcode(request):
    """Looks up a product by its barcode string or exact SKU name."""
    code = request.GET.get("code", "").strip()
    if not code:
        return JsonResponse(
            {"status": "error", "message": "No code provided"}, status=400
        )

    product = Product.objects.filter(barcode=code).first() or Product.objects.filter(
        name__icontains=code
    ).first()

    if product:
        return JsonResponse({
            "status": "success",
            "product": {
                "id": product.id,
                "name": product.name,
                "selling_price": float(product.price),
                "quantity_in_stock": product.stock_quantity,
            },
        })

    return JsonResponse(
        {"status": "not_found", "message": "Product not found in inventory."},
        status=404,
    )


@csrf_exempt
def ai_analytics_agent(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    data = json.loads(request.body)
    user_prompt = data.get("prompt", "")

    if not user_prompt:
        return JsonResponse({"error": "Prompt is required"}, status=400)

    system_instruction = (
        "You are DukaanSaathi AI, a data analytics copilot for retail shop owners. "
        "Use provided function tools to fetch accurate real-time inventory and revenue metrics. "
        "Format currency values in Indian Rupees (₹)."
    )

    try:
        if client is None:
            return JsonResponse(
                {"error": "Gemini is not configured. Set GEMINI_API_KEY to enable the AI copilot."},
                status=503,
            )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[{"function_declarations": gemini_tools_schema}],
                temperature=0.2,
            ),
        )

        if response.function_calls:
            tool_responses = []

            for call in response.function_calls:
                fn_name = call.name
                fn_args = call.args or {}

                if fn_name in AI_TOOL_MAP:
                    tool_output = AI_TOOL_MAP[fn_name](**fn_args)

                    tool_responses.append(
                        types.Part.from_function_response(
                            name=fn_name, response={"result": tool_output}
                        )
                    )

            final_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    user_prompt,
                    response.candidates[0].content,
                    *tool_responses,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                ),
            )

            return JsonResponse({"response": final_response.text})

        return JsonResponse({"response": response.text})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def send_udhaar_reminder_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        customer_id = data.get("customer_id")

        if not customer_id:
            return JsonResponse(
                {"error": "Customer ID is required"}, status=400
            )

        customer = Customer.objects.get(id=customer_id)
        pending_amount = getattr(customer, "pending_balance", 0.0)

        if pending_amount <= 0:
            return JsonResponse(
                {"error": "Customer has no outstanding balance"}, status=400
            )

        payment_link = generate_paytm_payment_link(
            float(pending_amount), customer.name, note="Udhaar payment"
        )
        test_recipient = os.getenv("WHATSAPP_TEST_NUMBER")
        public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        media_url = (
            f"{public_base_url}/api/udhaar-qr/{customer.id}/"
            if public_base_url else None
        )
        result = send_whatsapp_udhaar_reminder(
            customer_phone=test_recipient or customer.phone,
            customer_name=customer.name,
            pending_amount=float(pending_amount),
            payment_link=payment_link,
            media_url=media_url,
        )

        if result["success"]:
            return JsonResponse({
                "message": f"WhatsApp reminder sent to {customer.name}!",
                "sid": result["sid"],
            })
        else:
            return JsonResponse({"error": result["error"]}, status=500)

    except Customer.DoesNotExist:
        return JsonResponse({"error": "Customer not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)