"""Lembrete de inatividade: preferência do usuário, /lembretes e os botões do modelo."""
from sqlalchemy import text

from app.comandos.formato import normalizar
from app.db import get_engine

PAYLOAD_REGISTRAR = "lembrete_registrar"
PAYLOAD_PARAR = "lembrete_parar"
# Textos dos botões do modelo (usados se a Meta devolver o toque sem o payload).
TITULO_REGISTRAR = "Registrar agora"
TITULO_PARAR = "Parar lembretes"

# Botões da resposta a "Registrar agora": o id vira o comando que o toque executa.
COMANDO_DO_BOTAO = {"lembrete_resumo": "/resumo", "lembrete_ajuda": "/ajuda"}
BOTOES_REGISTRAR = [("lembrete_resumo", "Ver meu resumo"), ("lembrete_ajuda", "Ver comandos")]

TEXTO_REGISTRAR = (
    "Bora! Mande /gasto 45,90 mercado ou escreva \"gastei 45 no mercado\". "
    "Se preferir, é só mandar a foto ou o PDF do comprovante que eu leio."
)
TEXTO_PARADO = "Combinado, parei os lembretes. Para voltar a receber, mande /lembretes."
TEXTO_LIGADO = "Pronto, lembretes ligados de novo. Para parar, mande /lembretes parar."


def lembretes_ligados(user_id) -> bool:
    with get_engine().connect() as connection:
        valor = connection.execute(
            text("SELECT lembretes_ativos FROM users WHERE id = :u"), {"u": user_id}
        ).scalar()
    return valor is None or bool(valor)


def definir_lembretes(telefone: str, ligado: bool) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE users SET lembretes_ativos = :v WHERE phone_number = :t"),
            {"v": ligado, "t": telefone},
        )


def comando_lembretes(telefone: str, argumentos: str) -> str:
    """/lembretes religa; /lembretes parar desliga."""
    if normalizar(argumentos) in ("parar", "desligar", "off", "nao"):
        definir_lembretes(telefone, False)
        return TEXTO_PARADO
    definir_lembretes(telefone, True)
    return TEXTO_LIGADO


def _nome_para_teste(telefone: str) -> str:
    with get_engine().connect() as connection:
        linha = connection.execute(
            text("SELECT display_name, profile_name FROM users WHERE phone_number = :t"),
            {"t": telefone},
        ).first()
    nome = (linha.display_name or linha.profile_name or "") if linha else ""
    return " ".join(nome.split()) or "Teste"


def comando_testar_lembrete(admin: str, argumentos: str) -> str:
    """Admin: envia já o modelo de lembrete, sem janela de 24h, limites nem registro de envio."""
    # imports tardios: alertas e whatsapp importam este módulo
    from datetime import datetime, timedelta

    from app import alertas, whatsapp
    from app.comandos.acesso import so_digitos

    if argumentos.strip():
        destino = so_digitos(argumentos)
        if len(destino) < 10:
            return "Use: /testar_lembrete NÚMERO (ex.: /testar_lembrete 5511999998888)"
    else:
        destino = so_digitos(admin)
    modelo = alertas.modelo_lembrete()
    data = (datetime.now(alertas.BRASIL) - timedelta(days=3)).date()
    try:
        whatsapp.send_template(destino, modelo, [_nome_para_teste(destino), f"{data:%d/%m}"],
                               botoes=(PAYLOAD_REGISTRAR, PAYLOAD_PARAR))
    except Exception as erro:
        return f"Não enviou o modelo {modelo}. {alertas._motivo_do_erro(erro)}"
    return f"Enviado o modelo {modelo} para +{destino}."


def _acao(botao: str | None, texto: str | None) -> str | None:
    if botao in (PAYLOAD_REGISTRAR, PAYLOAD_PARAR):
        return botao
    titulo = normalizar(texto or "")
    if titulo == normalizar(TITULO_REGISTRAR):
        return PAYLOAD_REGISTRAR
    if titulo == normalizar(TITULO_PARAR):
        return PAYLOAD_PARAR
    return None


def tratar_botao(telefone: str, botao: str | None, texto: str | None):
    """Toque num botão do modelo de lembrete. Devolve (texto, botões com id) ou None se o toque
    não for desse modelo."""
    acao = _acao(botao, texto)
    if botao in COMANDO_DO_BOTAO or acao is None:
        return None
    if acao == PAYLOAD_PARAR:
        definir_lembretes(telefone, False)
        return TEXTO_PARADO, []
    return TEXTO_REGISTRAR, BOTOES_REGISTRAR
