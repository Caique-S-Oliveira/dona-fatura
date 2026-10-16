import hashlib
import hmac
import logging
import os

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

from app.comandos import processar_mensagem
from app.comandos.resposta import Resposta
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


def _post_message(payload: dict) -> None:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não definidos.")
    response = httpx.post(
        f"{GRAPH_API_URL}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"messaging_product": "whatsapp", **payload},
        timeout=15,
    )
    response.raise_for_status()


def send_text(to: str, body: str) -> None:
    _post_message({"to": to, "type": "text", "text": {"body": body}})


def send_buttons(to: str, body: str, buttons: tuple[str, ...]) -> None:
    """Mensagem com botões de resposta rápida (a Meta aceita no máximo 3)."""
    _post_message({
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": titulo.lower(), "title": titulo[:20]}}
                    for titulo in buttons[:3]
                ]
            },
        },
    })


def send_list(to: str, resposta: Resposta) -> None:
    """Mensagem de lista (a Meta aceita no máximo 10 linhas)."""
    linhas = []
    for id_linha, titulo, descricao in resposta.lista[:10]:
        linha = {"id": id_linha, "title": titulo[:24]}
        if descricao:
            linha["description"] = descricao[:72]
        linhas.append(linha)
    _post_message({
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": resposta.texto[:1024]},
            "action": {
                "button": resposta.botao_lista[:20],
                "sections": [{"title": "Categorias", "rows": linhas}],
            },
        },
    })


def send_reply(to: str, resposta: str | Resposta) -> None:
    if isinstance(resposta, Resposta) and resposta.lista:
        send_list(to, resposta)
    elif isinstance(resposta, Resposta) and resposta.botoes:
        send_buttons(to, resposta.texto, resposta.botoes)
    else:
        send_text(to, resposta.texto if isinstance(resposta, Resposta) else resposta)


def message_text(message: dict) -> str | None:
    """Texto digitado, título do botão tocado ou id da linha da lista tocada.

    None para outros tipos (foto etc.).
    """
    if message.get("type") == "text":
        return message.get("text", {}).get("body", "")
    if message.get("type") == "interactive":
        interativo = message.get("interactive", {})
        if interativo.get("type") == "list_reply":
            return interativo.get("list_reply", {}).get("id")
        return interativo.get("button_reply", {}).get("title")
    return None


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
            texto = message_text(message)
            if texto is not None:
                send_reply(sender, processar_mensagem(sender, texto))
        except Exception:
            logger.exception("Erro ao processar mensagem do WhatsApp")
