"""Limpeza de dados técnicos que não precisam ficar para sempre (LGPD art. 15 e 16).

Só mexe em dados de funcionamento do bot. Registros financeiros, usuários inativos e a lista de
espera dependem de decisão sobre prazo e ficam de fora (veja audit/RELATORIO_SEGURANCA_LGPD.md)."""
import logging

from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)

DIAS_MENSAGENS = 30  # processed_messages só serve para ignorar mensagem repetida
DIAS_LOGS = 90  # reminder_log e sent_alerts
DIAS_AVISOS = 30  # pending_notices que o parceiro nunca chegou a receber

# Cada item: (descrição, SQL). Os prazos acima são inteiros fixos do código, nunca vêm do usuário.
_LIMPEZAS = (
    ("mensagens antigas",
     f"DELETE FROM processed_messages WHERE received_at < now() - interval '{DIAS_MENSAGENS} days'"),
    ("conversas expiradas",
     "DELETE FROM conversation_state WHERE expires_at IS NOT NULL AND expires_at < now()"),
    ("registro de lembretes",
     f"DELETE FROM reminder_log WHERE created_at < now() - interval '{DIAS_LOGS} days'"),
    ("registro de alertas",
     f"DELETE FROM sent_alerts WHERE sent_at < now() - interval '{DIAS_LOGS} days'"),
    ("avisos não entregues",
     f"DELETE FROM pending_notices WHERE created_at < now() - interval '{DIAS_AVISOS} days'"),
    ("códigos de convite vencidos",
     "UPDATE accounts SET invitation_code = NULL, invitation_expires_at = NULL"
     " WHERE invitation_code IS NOT NULL AND invitation_expires_at < now()"),
)


def limpar_dados_tecnicos() -> dict[str, int]:
    """Roda as limpezas e devolve quantas linhas cada uma atingiu (para o log, sem dado pessoal)."""
    resultado = {}
    for nome, comando in _LIMPEZAS:
        try:
            with get_engine().begin() as connection:
                resultado[nome] = connection.execute(text(comando)).rowcount
        except Exception:
            logger.exception("Falha na limpeza: %s", nome)
    logger.info("Retenção: %s", resultado)
    return resultado
