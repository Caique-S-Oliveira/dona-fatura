import hashlib
import hmac
import logging
import os

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

from app.db import get_engine

load_dotenv()

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0"


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Confere o X-Hub-Signature-256 enviado pela Meta."""
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    if not app_secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def extract_messages(payload: dict) -> list[dict]:
    """Devolve a lista de mensagens recebidas (ignora status de entrega etc.)."""
    messages = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            messages.extend(change.get("value", {}).get("messages", []))
    return messages


def register_message(message_id: str, sender_phone: str) -> bool:
    """Guarda o id da mensagem. Devolve False se ela já tinha sido recebida."""
    with get_engine().begin() as connection:
        result = connection.execute(
            text(
                "INSERT INTO processed_messages (whatsapp_message_id, sender_phone_number)"
                " VALUES (:message_id, :sender) ON CONFLICT (whatsapp_message_id) DO NOTHING"
            ),
            {"message_id": message_id, "sender": sender_phone},
        )
        return result.rowcount == 1


def send_text(to: str, body: str) -> None:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não definidos.")
    response = httpx.post(
        f"{GRAPH_API_URL}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        timeout=15,
    )
    response.raise_for_status()


def handle_incoming(payload: dict) -> None:
    """Processa o webhook depois de a resposta 200 já ter sido enviada."""
    for message in extract_messages(payload):
        try:
            message_id = message.get("id")
            sender = message.get("from")
            if not message_id or not sender:
                continue
            if not register_message(message_id, sender):
                continue  # mensagem repetida
            if message.get("type") == "text":
                send_text(sender, "Oi, eu sou a Dona Fatura!")
        except Exception:
            logger.exception("Erro ao processar mensagem do WhatsApp")
