import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from app import limites
from app.db import get_engine

logger = logging.getLogger(__name__)

# Nomes no banco: "ativo" = liberado, "bloqueado" = negado, "pendente" = esperando o admin.
MSG_PENDENTE = (
    "Oi! Esse assistente é de acesso restrito. Já avisei o administrador do seu pedido. "
    "Assim que for liberado, eu te aviso."
)
MSG_INATIVO = (
    "Seu acesso à Dona Fatura não está ativo no momento.\n"
    "Fale com quem te convidou, por favor."
)
MSG_LIBERADO = "Acesso liberado! Mande /inicio para começar."
MSG_ANTES_DO_INICIO = "Antes de tudo, mande /inicio para configurar."

PREFIXO_BOTAO = "acesso:"  # id dos botões [Liberar] [Negar]: "acesso:liberar:5511999999999"
MAX_PEDIDOS_POR_VEZ = 5
MAX_TENTATIVAS_CONVITE = 5  # por número, por hora


def so_digitos(telefone: str) -> str:
    """"+55 (11) 99999-8888" -> "5511999998888" (formato que o WhatsApp envia)."""
    return "".join(c for c in telefone if c.isdigit())


def mascarar(telefone: str) -> str:
    """Para logs: só os 4 últimos dígitos."""
    return "***" + so_digitos(telefone)[-4:]


def eh_admin(telefone: str) -> bool:
    admin = so_digitos(os.getenv("ADMIN_PHONE") or os.getenv("ADMIN_NUMERO", ""))
    return bool(admin) and so_digitos(telefone) == admin


def codigo_convite_valido(codigo: str) -> bool:
    esperado = os.getenv("CODIGO_CONVITE", "").strip()
    return bool(esperado) and secrets.compare_digest(codigo.strip(), esperado)


def status_acesso(telefone: str) -> str:
    """Devolve "ativo", "pendente" ou "bloqueado" (acesso vencido conta como "bloqueado")."""
    with get_engine().connect() as connection:
        linha = connection.execute(
            text(
                "SELECT access_status, access_expires_at <= now() AS vencido"
                " FROM users WHERE phone_number = :telefone"
            ),
            {"telefone": telefone},
        ).first()
    if linha is None:
        return "pendente"
    if linha.access_status == "ativo" and linha.vencido:
        return "bloqueado"
    return linha.access_status


def cadastro_completo(telefone: str) -> bool:
    """True se a pessoa já terminou o /inicio (marca gravada no banco)."""
    with get_engine().connect() as connection:
        return bool(connection.execute(
            text("SELECT cadastro_completo FROM users WHERE phone_number = :telefone"),
            {"telefone": telefone},
        ).scalar())


def _mudar_status(telefone: str, status: str, validade: datetime | None) -> bool:
    with get_engine().begin() as connection:
        resultado = connection.execute(
            text(
                "UPDATE users SET access_status = :status, access_expires_at = :validade"
                " WHERE phone_number = :telefone"
            ),
            {"status": status, "validade": validade, "telefone": so_digitos(telefone)},
        )
        return resultado.rowcount > 0


def liberar_acesso(telefone: str, validade: datetime | None = None) -> bool:
    """Deixa o usuário ativo até `validade` (None = sem data de fim).

    Usada pelo /convite, pelo /liberar e, no futuro, pela confirmação de pagamento.
    Devolve False se o número ainda não estiver cadastrado.
    """
    return _mudar_status(telefone, "ativo", validade)


def bloquear_acesso(telefone: str) -> bool:
    return _mudar_status(telefone, "bloqueado", None)


# ---------- porta de entrada (roda antes de qualquer comando, IA ou download) ----------


@dataclass
class Porta:
    liberado: bool
    resposta: str | None = None  # texto único para quem está pendente
    novo_pedido: bool = False  # o admin precisa ser avisado


def registrar_pendente(telefone: str, nome_perfil: str | None = None) -> None:
    """Anota o número como pendente, sem criar conta financeira."""
    with get_engine().begin() as connection:
        connection.execute(
            text("INSERT INTO users (phone_number) VALUES (:telefone)"
                 " ON CONFLICT (phone_number) DO NOTHING"),
            {"telefone": telefone},
        )
        if nome_perfil:
            connection.execute(
                text("UPDATE users SET profile_name = :nome WHERE phone_number = :telefone"),
                {"nome": nome_perfil[:100], "telefone": telefone},
            )


def _primeira_resposta(telefone: str) -> bool:
    """True só na primeira vez (UPDATE atômico: duas mensagens juntas não respondem duas vezes)."""
    with get_engine().begin() as connection:
        return connection.execute(
            text("UPDATE users SET pending_reply_sent = TRUE"
                 " WHERE phone_number = :telefone AND pending_reply_sent = FALSE"),
            {"telefone": telefone},
        ).rowcount == 1


def avaliar(telefone: str, nome_perfil: str | None = None, texto: str | None = None) -> Porta:
    """Decide se a mensagem pode seguir. Número não liberado nunca chega a comando, IA ou mídia."""
    if eh_admin(telefone):
        if (texto or "").strip().lower().split(" ")[0] != "/pendentes":
            try:
                enviar_pedidos(cabecalho=True)  # pedidos que não chegaram porque a janela estava fechada
            except Exception:
                logger.exception("Erro ao reenviar pedidos de acesso")
        return Porta(True)
    registrar_pendente(telefone, nome_perfil)
    status = status_acesso(telefone)
    if status == "ativo":
        return Porta(True)
    if status != "pendente":
        return Porta(False)  # negado: silêncio
    if (texto or "").strip().lower().split(" ")[0] == "/convite":
        return Porta(True)  # quem tem código de convite ainda pode usá-lo
    if _primeira_resposta(telefone):
        return Porta(False, MSG_PENDENTE, novo_pedido=True)
    return Porta(False)  # já respondido uma vez: silêncio


# ---------- pedidos ao admin ----------


def _pedidos(so_sem_aviso: bool) -> list:
    consulta = ("SELECT phone_number, profile_name FROM users WHERE access_status = 'pendente'"
                + (" AND admin_notified = FALSE" if so_sem_aviso else "")
                + " ORDER BY created_at")
    with get_engine().connect() as connection:
        linhas = connection.execute(text(consulta)).all()
    return [l for l in linhas if not eh_admin(l.phone_number)]


def _texto_pedido(telefone: str, nome: str | None) -> str:
    return f"Pedido de acesso: +{telefone}" + (f" ({nome})" if nome else "")


def _botoes_pedido(telefone: str) -> list[tuple[str, str]]:
    return [(f"{PREFIXO_BOTAO}liberar:{telefone}", "Liberar"), (f"{PREFIXO_BOTAO}negar:{telefone}", "Negar")]


def enviar_pedidos(cabecalho: bool = False, todos: bool = False) -> int:
    """Manda ao admin um aviso com [Liberar] [Negar] por pedido. Devolve quantos foram enviados.

    Só texto comum e botões (nunca modelo pago): se a janela de 24h do admin estiver fechada o envio
    falha, o pedido continua sem aviso e vai na próxima mensagem do admin ao bot.
    """
    from app import whatsapp  # import aqui dentro: o whatsapp importa este módulo

    admin = so_digitos(os.getenv("ADMIN_PHONE") or os.getenv("ADMIN_NUMERO", ""))
    pedidos = _pedidos(so_sem_aviso=not todos)
    if not admin or not pedidos:
        return 0
    enviados = 0
    try:
        if cabecalho:
            total = len(_pedidos(so_sem_aviso=False))
            whatsapp.send_text(admin, f"Você tem {total} pedido{'s' if total != 1 else ''} pendente{'s' if total != 1 else ''}.")
        for pedido in pedidos[:MAX_PEDIDOS_POR_VEZ]:
            whatsapp.send_buttons_ids(admin, _texto_pedido(pedido.phone_number, pedido.profile_name),
                                      _botoes_pedido(pedido.phone_number))
            with get_engine().begin() as connection:
                connection.execute(
                    text("UPDATE users SET admin_notified = TRUE WHERE phone_number = :telefone"),
                    {"telefone": pedido.phone_number},
                )
            enviados += 1
    except Exception:
        logger.warning("Não consegui avisar o admin agora (janela de 24h fechada?); o pedido fica "
                       "guardado e vai na próxima mensagem dele.")
    return enviados


# ---------- decisão do admin ----------


def decidir(acao: str, numero: str) -> str:
    """Libera ou nega o número, avisa o usuário (se der) e devolve o texto para o admin."""
    numero = so_digitos(numero)
    if acao == "liberar":
        if not liberar_acesso(numero):
            return f"O número {numero} ainda não mandou mensagem para a Dona Fatura."
        _avisar_usuario(numero, MSG_LIBERADO)
        return f"Número {numero} liberado."
    if not bloquear_acesso(numero):
        return f"O número {numero} ainda não mandou mensagem para a Dona Fatura."
    return f"Número {numero} negado."


def _avisar_usuario(numero: str, mensagem: str) -> None:
    """Tenta avisar. Se a janela de 24h fechou, só registra: o status já mudou e a próxima mensagem
    dele é respondida normalmente (nada de modelo pago)."""
    from app import whatsapp

    try:
        whatsapp.send_text(numero, mensagem)
    except Exception:
        logger.warning("Não consegui avisar o usuário %s da liberação (janela de 24h fechada?).",
                       mascarar(numero))


def tratar_botao(telefone: str, botao_id: str) -> str | None:
    """Toque em [Liberar] ou [Negar]. Devolve a confirmação para o admin; None se o toque for ignorado
    (qualquer outro número, sem revelar que o botão existe)."""
    if not botao_id.startswith(PREFIXO_BOTAO) or not eh_admin(telefone):
        return None
    partes = botao_id.split(":")
    if len(partes) != 3 or partes[1] not in ("liberar", "negar"):
        return None
    return decidir(partes[1], partes[2])


# ---------- comandos só do admin ----------


def comando_convite(telefone: str, argumentos: str) -> str:
    if limites.excedeu(f"convite:{telefone}", MAX_TENTATIVAS_CONVITE, 3600):
        return "Muitas tentativas. Tente de novo mais tarde."  # freio contra adivinhar o código
    if not codigo_convite_valido(argumentos):
        return "Código inválido. Confira e tente de novo."
    liberar_acesso(telefone)
    return "Acesso liberado! Bem-vindo(a). Mande /ajuda para ver os comandos."


def _listar_usuarios() -> str:
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text("SELECT phone_number, access_status, profile_name FROM users ORDER BY created_at")
        ).all()
    if not linhas:
        return "Nenhum usuário ainda."
    nomes = {"ativo": "liberado", "pendente": "pendente", "bloqueado": "negado"}
    return "\n".join(
        f"+{l.phone_number} - {'admin' if eh_admin(l.phone_number) else nomes.get(l.access_status, l.access_status)}"
        for l in linhas
    )


def comando_admin(nome: str, argumentos: str) -> str:
    if nome == "usuarios":
        return _listar_usuarios()
    if nome == "pendentes":
        enviados = enviar_pedidos(todos=True)
        total = len(_pedidos(so_sem_aviso=False))
        if total == 0:
            return "Nenhum pedido pendente."
        return f"{total} pedido{'s' if total != 1 else ''} pendente{'s' if total != 1 else ''}." + (
            "" if enviados >= total else " Resolva estes e mande /pendentes de novo."
        )
    if nome == "bloquear":
        nome = "negar"
    numero = so_digitos(argumentos)
    if not numero:
        return f"Use: /{nome} NÚMERO (ex.: /{nome} 5511999998888)"
    return decidir(nome, numero)
