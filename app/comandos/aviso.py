"""Aviso de privacidade com botão [Entendi], mostrado uma vez antes do primeiro registro."""
from sqlalchemy import text

from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import normalizar
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "aviso"
BOTOES = ("Entendi",)

TEXTO_AVISO = (
    "Antes de registrar, um aviso rápido de privacidade:\n"
    "Guardo seu nome, renda, metas e os registros que você confirmar. Fotos e PDFs são lidos por IA "
    "(Anthropic, nos EUA) e descartados. Quem administra o banco de dados consegue ver esses dados. "
    "Veja tudo com /meus_dados e apague com /apagar_meus_dados."
)


def aceitou(telefone: str) -> bool:
    with get_engine().connect() as connection:
        return bool(connection.execute(
            text("SELECT privacidade_aceita_em IS NOT NULL FROM users WHERE phone_number = :t"),
            {"t": telefone},
        ).scalar())


def pedir(telefone: str, original: str) -> Resposta:
    """Guarda a mensagem que gerou o pedido, para refazê-la depois do [Entendi]."""
    salvar_estado(telefone, ESTADO, {"texto": original})
    return Resposta(TEXTO_AVISO, BOTOES)


def pedir_reenvio(telefone: str) -> Resposta:
    """Para foto/PDF: nada foi baixado nem enviado à IA; a pessoa manda o arquivo de novo."""
    salvar_estado(telefone, ESTADO, {"texto": ""})
    return Resposta(TEXTO_AVISO + "\nDepois, mande o arquivo de novo.", BOTOES)


def continuar(telefone: str, dados: dict, texto: str) -> tuple[Resposta | None, str | None]:
    """Devolve (resposta, mensagem_para_refazer). Só o [Entendi] libera."""
    if normalizar(texto).strip(" .!") != "entendi":
        return Resposta("Toque em Entendi para continuar.", BOTOES), None
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE users SET privacidade_aceita_em = now() WHERE phone_number = :t"),
            {"t": telefone},
        )
    limpar_estado(telefone)
    original = dados.get("texto") or ""
    if original:
        return None, original
    return Resposta("Obrigada! Pode mandar o arquivo de novo."), None
