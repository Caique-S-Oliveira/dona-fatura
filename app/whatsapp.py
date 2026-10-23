import hashlib
import hmac
import logging
import os

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

from app import alertas, limites
from app.comandos import acesso, lembretes
from app.comandos import processar_comprovante, processar_mensagem
from app.comandos.resposta import Resposta
from app.comandos.sair_casal import pegar_avisos
from app.db import get_engine

load_dotenv()

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0"
MAX_MIDIA = 5 * 1024 * 1024  # 5 MB: limite de imagem da API do Claude
MAX_TEXTO = 1000  # caracteres aceitos por mensagem (o resto é descartado antes da IA)
MAX_MENSAGENS_POR_MINUTO = 20  # por número; passou disso, ignora (custo de IA e abuso)


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


def _post_message(payload: dict) -> str | None:
    """Envia pela Cloud API. Devolve o id da mensagem enviada (para o registro dos alertas)."""
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
    mensagens = response.json().get("messages") or [{}]
    return mensagens[0].get("id")


def send_text(to: str, body: str) -> str | None:
    return _post_message({"to": to, "type": "text", "text": {"body": body}})


def send_template(to: str, nome: str, parametros: list[str], idioma: str = "pt_BR",
                  botoes: tuple[str, ...] = ()) -> str | None:
    """Mensagem por modelo (template) aprovado; vale também fora da janela de 24h.

    botoes: o payload de cada botão de resposta rápida do modelo, na ordem (volta no toque)."""
    componentes = [{
        "type": "body",
        "parameters": [{"type": "text", "text": valor} for valor in parametros],
    }]
    for indice, payload in enumerate(botoes):
        componentes.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(indice),
            "parameters": [{"type": "payload", "payload": payload}],
        })
    return _post_message({
        "to": to,
        "type": "template",
        "template": {"name": nome, "language": {"code": idioma}, "components": componentes},
    })


def send_image(to: str, png: bytes, legenda: str) -> None:
    """Sobe o PNG na rota /media da API e envia pelo id da mídia."""
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não definidos.")
    upload = httpx.post(
        f"{GRAPH_API_URL}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={"messaging_product": "whatsapp", "type": "image/png"},
        files={"file": ("grafico.png", png, "image/png")},
        timeout=30,
    )
    upload.raise_for_status()
    _post_message({
        "to": to,
        "type": "image",
        "image": {"id": upload.json()["id"], "caption": legenda[:1024]},
    })


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def send_document(to: str, nome: str, conteudo: bytes, legenda: str) -> None:
    """Sobe o arquivo (.xlsx) na rota /media da API e envia pelo id da mídia."""
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não definidos.")
    upload = httpx.post(
        f"{GRAPH_API_URL}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={"messaging_product": "whatsapp", "type": XLSX_MIME},
        files={"file": (nome, conteudo, XLSX_MIME)},
        timeout=30,
    )
    upload.raise_for_status()
    _post_message({
        "to": to,
        "type": "document",
        "document": {"id": upload.json()["id"], "filename": nome, "caption": legenda[:1024]},
    })


def send_buttons_ids(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Botões de resposta rápida com id próprio: (id, título). A Meta aceita no máximo 3."""
    _post_message({
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": id_botao, "title": titulo[:20]}}
                    for id_botao, titulo in buttons[:3]
                ]
            },
        },
    })


def send_buttons(to: str, body: str, buttons: tuple[str, ...]) -> None:
    """Mensagem com botões de resposta rápida (a Meta aceita no máximo 3)."""
    send_buttons_ids(to, body, [(titulo.lower(), titulo) for titulo in buttons])


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
                "sections": [{"title": resposta.titulo_lista[:24], "rows": linhas}],
            },
        },
    })


def send_reply(to: str, resposta: str | Resposta | None) -> None:
    if resposta is None:
        return  # número não liberado: silêncio
    if isinstance(resposta, Resposta) and resposta.documento:
        send_document(to, resposta.documento[0], resposta.documento[1], resposta.texto)
    elif isinstance(resposta, Resposta) and resposta.imagem:
        send_image(to, resposta.imagem, resposta.texto)
    elif isinstance(resposta, Resposta) and resposta.lista:
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
    if message.get("type") == "button":  # toque num botão de modelo (template)
        return message.get("button", {}).get("text")
    return None


def message_button_id(message: dict) -> str | None:
    """Id do botão de resposta rápida tocado (None para o resto)."""
    if message.get("type") == "button":  # botão de modelo: o payload que enviamos junto
        return message.get("button", {}).get("payload")
    if message.get("type") != "interactive":
        return None
    return message.get("interactive", {}).get("button_reply", {}).get("id")


def extract_profile_names(payload: dict) -> dict[str, str]:
    """Nome do perfil do WhatsApp por número (vem em contacts, no webhook)."""
    nomes = {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for contato in change.get("value", {}).get("contacts", []):
                nome = contato.get("profile", {}).get("name")
                if contato.get("wa_id") and nome:
                    nomes[contato["wa_id"]] = nome
    return nomes


def message_media(message: dict) -> tuple[str, str] | None:
    """(id da mídia, tipo MIME) se for foto ou documento; None para o resto."""
    if message.get("type") not in ("image", "document"):
        return None
    midia = message.get(message["type"], {})
    if not midia.get("id"):
        return None
    return midia["id"], midia.get("mime_type", "")


def download_media(media_id: str) -> bytes | None:
    """Baixa o arquivo da Meta (só na memória). None se for grande demais ou der erro."""
    token = os.getenv("WHATSAPP_TOKEN")
    if not token:
        raise RuntimeError("WHATSAPP_TOKEN não definido.")
    headers = {"Authorization": f"Bearer {token}"}
    info = httpx.get(f"{GRAPH_API_URL}/{media_id}", headers=headers, timeout=15)
    info.raise_for_status()
    dados = info.json()
    if int(dados.get("file_size", 0)) > MAX_MIDIA:
        return None
    arquivo = httpx.get(dados["url"], headers=headers, timeout=30)
    arquivo.raise_for_status()
    return arquivo.content if len(arquivo.content) <= MAX_MIDIA else None


def entregar_avisos(destino: str) -> None:
    """Avisos que ficaram esperando (ex.: o parceiro saiu do casal). A mensagem que acabou de
    chegar reabre a janela de 24h, então agora dá para enviar texto livre."""
    try:
        for aviso in pegar_avisos(destino):
            send_text(destino, aviso)
    except Exception:
        logger.exception("Erro ao entregar avisos pendentes")


def handle_incoming(payload: dict) -> None:
    """Processa o webhook depois de a resposta 200 já ter sido enviada."""
    nomes = extract_profile_names(payload)
    for message in extract_messages(payload):
        try:
            message_id = message.get("id")
            sender = message.get("from")
            if not message_id or not sender:
                continue
            if not register_message(message_id, sender):
                continue  # mensagem repetida
            if limites.excedeu(f"msg:{sender}", MAX_MENSAGENS_POR_MINUTO, 60):
                logger.warning("Limite de mensagens por minuto excedido (***%s)", sender[-4:])
                continue
            texto = message_text(message)
            if texto is not None:
                texto = texto[:MAX_TEXTO]
            botao = message_button_id(message)
            if botao and botao.startswith(acesso.PREFIXO_BOTAO):
                confirmacao = acesso.tratar_botao(sender, botao)  # [Liberar] [Negar] do admin
                if confirmacao:
                    send_text(sender, confirmacao)
                continue
            # Porta de entrada: antes de avisos, comandos, IA ou download de mídia.
            porta = acesso.avaliar(sender, nomes.get(sender), texto)
            if not porta.liberado:
                if porta.resposta:
                    send_text(sender, porta.resposta)
                if porta.novo_pedido:
                    acesso.enviar_pedidos()
                continue
            entregar_avisos(sender)
            resposta_lembrete = lembretes.tratar_botao(sender, botao, texto)
            if resposta_lembrete is not None:  # "Registrar agora" / "Parar lembretes"
                corpo, botoes = resposta_lembrete
                if botoes:
                    send_buttons_ids(sender, corpo, botoes)
                else:
                    send_text(sender, corpo)
                continue
            texto = lembretes.COMANDO_DO_BOTAO.get(botao, texto)
            alertas.abrir_fila()
            midia = message_media(message)
            if texto is not None:
                send_reply(sender, processar_mensagem(sender, texto))
            elif midia is not None:
                id_midia, tipo = midia
                send_reply(
                    sender,
                    processar_comprovante(sender, tipo, lambda: download_media(id_midia)),
                )
            alertas.enviar_alertas_de_gasto()  # só depois da confirmação já ter sido enviada
        except Exception:
            logger.exception("Erro ao processar mensagem do WhatsApp")
