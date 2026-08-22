from unittest.mock import patch

from django.test import TestCase

from .whatsapp_utils import send_whatsapp_udhaar_reminder

from .ai_engine import process_ai_query
from .ai_tools import get_low_stock_inventory, get_top_selling_products
from .inventory import InventoryError, change_stock, record_sale
from .models import Customer, InventoryMovement, PaymentOrder, Product, Sale
from .utils import generate_paytm_payment_link


class MerchantAnalyticsTests(TestCase):
	def setUp(self):
		self.product = Product.objects.create(
			name="Tea", category="Beverages", price="20.00", stock_quantity=3
		)
		self.customer = Customer.objects.create(name="Asha", phone="9876543210")
		Sale.objects.create(
			product=self.product,
			customer=self.customer,
			quantity=2,
			total_amount="40.00",
		)

	def test_product_revenue_query_uses_recorded_sales(self):
		result = process_ai_query("Which products generated the most revenue?")
		self.assertEqual(result["intent"], "PRODUCT_REVENUE")
		self.assertIn("Tea: ₹40.00", result["answer"])

	def test_ai_tools_use_actual_model_fields(self):
		self.assertIn('"revenue": 40.0', get_top_selling_products())
		self.assertIn('"current_stock": 3', get_low_stock_inventory())

	def test_customer_pending_balance_is_recorded_sales_total(self):
		self.assertEqual(float(self.customer.pending_balance), 40.0)

	def test_stock_changes_create_audit_movement(self):
		change_stock(self.product.id, 4, InventoryMovement.RECEIPT, "Supplier delivery")
		self.product.refresh_from_db()
		self.assertEqual(self.product.stock_quantity, 7)
		movement = InventoryMovement.objects.latest("created_at")
		self.assertEqual(movement.stock_after, 7)
		self.assertEqual(movement.quantity, 4)

	def test_inventory_snapshot_returns_live_stock_state(self):
		response = self.client.get("/api/inventory-snapshot/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["products"][0]["stock_quantity"], 3)

	def test_record_sale_updates_stock_and_creates_sale(self):
		record_sale(self.product.id, customer=self.customer, quantity=2)
		self.product.refresh_from_db()
		self.assertEqual(self.product.stock_quantity, 1)
		self.assertEqual(Sale.objects.filter(product=self.product).count(), 2)

	def test_record_sale_rejects_insufficient_stock_without_new_sale(self):
		with self.assertRaises(InventoryError):
			record_sale(self.product.id, customer=self.customer, quantity=4)
		self.assertEqual(Sale.objects.filter(product=self.product).count(), 1)

	def test_restock_model_includes_sales_recorded_today(self):
		from .ai_engine import get_restock_predictions

		result = get_restock_predictions()
		prediction = next(item for item in result["predictions"] if item["product_id"] == self.product.id)
		self.assertGreater(prediction["daily_velocity"], 0)
		chart_product = next(item for item in result["chart"]["products"] if item["name"] == self.product.name)
		self.assertIn(2.0, chart_product["actual"])

	def test_paytm_initiation_creates_order_and_qr_fallback_without_credentials(self):
		response = self.client.post("/api/paytm/initiate/", {
			"product_id": self.product.id,
			"quantity": 1,
		})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["mode"], "qr_fallback")
		self.assertTrue(response.json()["qr_code"].startswith("data:image/png;base64,"))
		self.assertEqual(PaymentOrder.objects.count(), 1)

	def test_paytm_udhaar_link_contains_exact_customer_balance(self):
		link = generate_paytm_payment_link(40, self.customer.name)
		self.assertIn("upi://pay?", link)
		self.assertIn("am=40.00", link)
		self.assertIn("pa=", link)

	@patch.dict("os.environ", {"WHATSAPP_TEST_NUMBER": "+919999999999"})
	@patch("core.views.send_whatsapp_udhaar_reminder")
	def test_udhaar_reminder_uses_test_number_and_paytm_link(self, send_reminder):
		send_reminder.return_value = {"success": True, "sid": "test-message"}
		response = self.client.post("/api/send-udhaar-reminder/", data={"customer_id": self.customer.id}, content_type="application/json")
		self.assertEqual(response.status_code, 200)
		call = send_reminder.call_args.kwargs
		self.assertEqual(call["customer_phone"], "+919999999999")
		self.assertIn("upi://pay?", call["payment_link"])

	@patch.dict("os.environ", {
		"WHATSAPP_TEST_NUMBER": "+919999999999",
		"PUBLIC_BASE_URL": "https://demo.example.com",
	})
	@patch("core.views.send_whatsapp_udhaar_reminder")
	def test_udhaar_reminder_includes_public_qr_media_url(self, send_reminder):
		send_reminder.return_value = {"success": True, "sid": "test-message"}
		response = self.client.post("/api/send-udhaar-reminder/", data={"customer_id": self.customer.id}, content_type="application/json")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			send_reminder.call_args.kwargs["media_url"],
			f"https://demo.example.com/api/udhaar-qr/{self.customer.id}/",
		)

	def test_udhaar_qr_endpoint_returns_png_for_balance(self):
		response = self.client.get(f"/api/udhaar-qr/{self.customer.id}/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response["Content-Type"], "image/png")

	@patch.dict("os.environ", {
		"TWILIO_ACCOUNT_SID": "your_twilio_account_sid",
		"TWILIO_AUTH_TOKEN": "your_twilio_auth_token",
		"TWILIO_WHATSAPP_NUMBER": "whatsapp:+14155238886",
	})
	@patch("twilio.rest.Client")
	def test_whatsapp_reminder_rejects_placeholder_twilio_credentials(self, mock_client):
		result = send_whatsapp_udhaar_reminder(
			customer_phone="9876543210",
			customer_name="Asha",
			pending_amount=40.00,
			payment_link="https://example.com/pay",
		)
		self.assertFalse(result["success"])
		self.assertIn("configured", result["error"])
		mock_client.assert_not_called()

	@patch.dict("os.environ", {
		"TWILIO_ACCOUNT_SID": "AC123",
		"TWILIO_AUTH_TOKEN": "token123",
		"TWILIO_WHATSAPP_NUMBER": "whatsapp:+14155238886",
	})
	@patch("twilio.rest.Client")
	def test_whatsapp_reminder_handles_missing_twilio_channel_error(self, mock_client):
		mock_client.return_value.messages.create.side_effect = Exception(
			"Twilio could not find a channel with the specified From address"
		)
		result = send_whatsapp_udhaar_reminder(
			customer_phone="9876543210",
			customer_name="Asha",
			pending_amount=40.00,
			payment_link="https://example.com/pay",
		)
		self.assertFalse(result["success"])
		self.assertIn("sender number", result["error"])
		self.assertIn("same Twilio account", result["error"])

	@patch.dict("os.environ", {"SMS_TEST_NUMBER": "+919999999999"})
	@patch("core.views.send_sms_udhaar_reminder")
	@patch("core.views.send_voice_udhaar_reminder")
	def test_sms_reminder_uses_test_number_and_customer_balance(self, send_call, send_sms):
		send_sms.return_value = {"success": True, "sid": "test-sms"}
		send_call.return_value = {"success": True, "sid": "test-call"}
		response = self.client.post(
			"/api/send-sms-udhaar-reminder/",
			data={"customer_id": self.customer.id},
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 200)
		call = send_sms.call_args.kwargs
		self.assertEqual(call["customer_phone"], "+919999999999")
		self.assertEqual(call["pending_amount"], 40.0)

	def test_sms_reminder_requires_customer_id(self):
		response = self.client.post(
			"/api/send-sms-udhaar-reminder/",
			data="{}",
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 400)

	def test_chatbot_returns_answer_without_gemini_credentials(self):
		response = self.client.post(
			"/api/ai-chat/",
			data='{"query":"what is my total revenue?"}',
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 200)
		self.assertIn("answer", response.json())
