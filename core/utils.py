import io
import base64
import json
import os
import requests
import qrcode
from urllib.parse import quote


def paytm_settings():
    production = os.getenv("PAYTM_ENV", "staging").lower() == "production"
    mid = os.getenv("PAYTM_MID", "")
    merchant_key = os.getenv("PAYTM_MERCHANT_KEY", "")
    if mid.startswith("your_") or merchant_key.startswith("your_"):
        mid = ""
        merchant_key = ""
    return {
        "mid": mid,
        "merchant_key": merchant_key,
        "website": os.getenv("PAYTM_WEBSITE", "DEFAULT" if production else "WEBSTAGING"),
        "callback_url": os.getenv("PAYTM_CALLBACK_URL", ""),
        "base_url": "https://securegw.paytm.in" if production else "https://securegw-stage.paytm.in",
    }


def generate_paytm_payment_link(amount, customer_name="Customer", note="Udhaar settlement"):
    """Create a Paytm-compatible UPI deep link for an exact outstanding amount."""
    payee_vpa = os.getenv("PAYTM_UPI_VPA", "paytm.dukaansaathi@paytm")
    params = (
        f"pa={quote(payee_vpa)}&pn={quote('DukaanSaathi Store')}&"
        f"am={amount:.2f}&cu=INR&tn={quote(f'{note} - {customer_name}') }"
    )
    return f"upi://pay?{params}"


def initiate_paytm_transaction(order_id, amount, customer_id, callback_url):
    config = paytm_settings()
    if not config["mid"] or not config["merchant_key"]:
        return {"configured": False}
    from paytmchecksum import PaytmChecksum

    body = {
        "requestType": "Payment",
        "mid": config["mid"],
        "websiteName": config["website"],
        "orderId": order_id,
        "txnAmount": {"value": f"{amount:.2f}", "currency": "INR"},
        "userInfo": {"custId": str(customer_id or f"WALKIN_{order_id}")},
        "callbackUrl": callback_url or config["callback_url"],
    }
    signature = PaytmChecksum.generateSignature(json.dumps(body), config["merchant_key"])
    response = requests.post(
        f"{config['base_url']}/theia/api/v1/initiateTransaction?mid={config['mid']}&orderId={order_id}",
        json={"body": body, "head": {"signature": signature}},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    result_info = payload.get("body", {}).get("resultInfo", {})
    if result_info.get("resultStatus") != "S":
        raise RuntimeError(result_info.get("resultMsg", "Paytm could not initiate this payment."))
    return {
        "configured": True,
        "mid": config["mid"],
        "order_id": order_id,
        "txn_token": payload["body"]["txnToken"],
        "gateway_url": f"{config['base_url']}/theia/api/v1/showPaymentPage",
    }


def verify_paytm_callback(payload):
    config = paytm_settings()
    if not config["merchant_key"]:
        return False
    from paytmchecksum import PaytmChecksum
    checksum = payload.get("CHECKSUMHASH", "")
    values = {key: value for key, value in payload.items() if key != "CHECKSUMHASH"}
    return bool(checksum and PaytmChecksum.verifySignature(values, config["merchant_key"], checksum))

def generate_paytm_upi_qr(amount, note="DukaanSaathi Sale", payee_vpa=None):
    """
    Generates a dynamic Base64-encoded PNG image for a Paytm UPI payment QR.
    """
    payee_vpa = payee_vpa or os.getenv("PAYTM_UPI_VPA", "paytm.dukaansaathi@paytm")
    upi_url = f"upi://pay?pa={payee_vpa}&pn=DukaanSaathi%20Store&am={amount:.2f}&cu=INR&tn={note}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=2,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#002E6E", back_color="white") # Paytm Dark Blue theme
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return f"data:image/png;base64,{qr_b64}"


def generate_paytm_upi_qr_bytes(amount, note="DukaanSaathi Sale", payee_vpa=None):
    data_uri = generate_paytm_upi_qr(amount, note=note, payee_vpa=payee_vpa)
    return base64.b64decode(data_uri.split(",", 1)[1])

import os
from twilio.rest import Client

def send_whatsapp_udhaar_reminder(customer_phone: str, customer_name: str, pending_amount: float, payment_link: str = None):
    """
    Sends a WhatsApp message via Twilio Sandbox/Production API for pending Udhaar balances.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

    if not account_sid or not auth_token:
        return {"success": False, "error": "Twilio credentials not configured."}

    client = Client(account_sid, auth_token)

    # Ensure phone number format includes country code (default +91 for India)
    formatted_phone = customer_phone.strip()
    if not formatted_phone.startswith('+'):
        formatted_phone = f"+91{formatted_phone}"

    message_body = (
        f"Namaste {customer_name}! 🙏\n\n"
        f"This is a gentle reminder from your local shop regarding your pending balance of *₹{pending_amount:.2f}*.\n\n"
    )
    if payment_link:
        message_body += f"You can clear your bill online using this UPI link: {payment_link}\n\n"
    
    message_body += "Thank you for your business! 🛍️"

    try:
        message = client.messages.create(
            body=message_body,
            from_=from_whatsapp_number,
            to=f"whatsapp:{formatted_phone}"
        )
        return {"success": True, "sid": message.sid}
    except Exception as e:
        return {"success": False, "error": str(e)}