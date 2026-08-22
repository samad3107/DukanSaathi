import logging
import os
from pathlib import Path
from xml.sax.saxutils import escape

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)


def _is_placeholder_value(value):
    if value is None:
        return True
    cleaned = str(value).strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if lowered.startswith("your_") or lowered.startswith("example"):
        return True
    return lowered in {"changeme", "placeholder", "demo", "test", "sample"}


def _twilio_settings():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path, override=False)
    file_values = dotenv_values(env_path)

    def setting(name, default=""):
        value = os.getenv(name)
        return (value if value and value.strip() else file_values.get(name, default) or default).strip()

    return {
        "account_sid": setting("TWILIO_ACCOUNT_SID"),
        "auth_token": setting("TWILIO_AUTH_TOKEN"),
        "from_number": setting("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886"),
        "voice_number": setting("TWILIO_VOICE_NUMBER"),
        "sms_number": setting("TWILIO_SMS_NUMBER"),
    }


def send_whatsapp_udhaar_reminder(customer_phone, customer_name, pending_amount, payment_link=None, media_url=None):
    """
    Sends a WhatsApp payment reminder for outstanding Udhaar balances.
    Sends through Twilio WhatsApp when credentials are configured.
    """
    try:
        message_body = (
            f"Namaste {customer_name}, your outstanding balance at DukaanSaathi "
            f"is ₹{pending_amount:.2f}. Please clear your dues at your earliest convenience.\n\n"
        )
        if payment_link:
            message_body += f"Pay securely using Paytm UPI:\n{payment_link}\n\n"
        message_body += "Thank you for shopping with us."
        
        twilio = _twilio_settings()
        account_sid = twilio["account_sid"]
        auth_token = twilio["auth_token"]
        from_number = twilio["from_number"]
        if (
            not account_sid
            or not auth_token
            or _is_placeholder_value(account_sid)
            or _is_placeholder_value(auth_token)
        ):
            return {
                "success": False,
                "error": "Twilio WhatsApp credentials are not configured.",
            }

        if _is_placeholder_value(from_number):
            return {
                "success": False,
                "error": "Twilio WhatsApp sender number is not configured.",
            }

        from twilio.rest import Client

        phone = str(customer_phone).strip()
        if not phone.startswith("+"):
            phone = f"+91{phone}"

        message_options = {
            "body": message_body,
            "from_": from_number,
            "to": f"whatsapp:{phone}",
        }
        if media_url:
            message_options["media_url"] = [media_url]
        message = Client(account_sid, auth_token).messages.create(**message_options)
        return {"success": True, "sid": message.sid}
    except Exception as e:
        message = str(e)
        logger.error(f"Failed to send WhatsApp message: {message}")
        lowered = message.lower()
        if "channel with the specified from address" in lowered or "from address" in lowered:
            return {
                "success": False,
                "error": "Twilio WhatsApp sender number is invalid for this account. Set TWILIO_WHATSAPP_NUMBER to the same Twilio WhatsApp Sandbox or number configured in the same Twilio account.",
            }
        return {
            "success": False,
            "error": message,
        }


def send_voice_udhaar_reminder(customer_phone, customer_name, pending_amount):
    """Place a Twilio voice call with an automated outstanding-balance reminder."""
    try:
        twilio = _twilio_settings()
        account_sid = twilio["account_sid"]
        auth_token = twilio["auth_token"]
        from_number = twilio["voice_number"]
        if (
            not account_sid
            or not auth_token
            or _is_placeholder_value(account_sid)
            or _is_placeholder_value(auth_token)
        ):
            return {"success": False, "error": "Twilio credentials are not configured."}
        if _is_placeholder_value(from_number):
            return {"success": False, "error": "TWILIO_VOICE_NUMBER is not configured."}

        phone = str(customer_phone).strip()
        if not phone.startswith("+"):
            phone = f"+91{phone}"
        safe_name = escape(str(customer_name))
        twiml = (
            '<Response><Say language="en-IN" voice="Polly.Aditi">'
            f"Namaste {safe_name}. Your outstanding balance at Dukaan Saathi is "
            f"rupees {float(pending_amount):.2f}. Please clear your dues. Thank you."
            "</Say></Response>"
        )
        from twilio.rest import Client

        call = Client(account_sid, auth_token).calls.create(
            to=f"+{phone.lstrip('+')}",
            from_=from_number,
            twiml=twiml,
        )
        return {"success": True, "sid": call.sid}
    except Exception as e:
        message = str(e)
        logger.error(f"Failed to place voice call: {message}")
        return {"success": False, "error": message}


def send_sms_udhaar_reminder(customer_phone, customer_name, pending_amount, payment_link=None):
    """Send a plain SMS reminder through a Twilio SMS-capable number."""
    try:
        twilio = _twilio_settings()
        account_sid = twilio["account_sid"]
        auth_token = twilio["auth_token"]
        from_number = twilio["sms_number"]
        if (
            not account_sid
            or not auth_token
            or _is_placeholder_value(account_sid)
            or _is_placeholder_value(auth_token)
        ):
            return {"success": False, "error": "Twilio credentials are not configured."}
        if _is_placeholder_value(from_number):
            return {"success": False, "error": "TWILIO_SMS_NUMBER is not configured."}

        phone = str(customer_phone).strip()
        if not phone.startswith("+"):
            phone = f"+91{phone}"
        body = (
            f"Dukaan Saathi: {customer_name}, please pay using Paytm."
        )
        body += " For help, call 9959364017."
        from twilio.rest import Client

        message = Client(account_sid, auth_token).messages.create(
            body=body,
            from_=from_number,
            to=f"+{phone.lstrip('+').replace(' ', '')}",
        )
        return {"success": True, "sid": message.sid}
    except Exception as e:
        message = str(e)
        logger.error(f"Failed to send SMS reminder: {message}")
        return {"success": False, "error": message}