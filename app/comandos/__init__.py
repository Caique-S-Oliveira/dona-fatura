from dataclasses import replace

from app.comandos.acesso import (
    MSG_INATIVO,
    MSG_PENDENTE,
    comando_admin,
    comando_convite,
    eh_admin,
    status_acesso,
)
from app.comandos.ajuda import comando_ajuda
from app.comandos.cadastro import garantir_usuario
from app.comandos.categorias import ESTADO as ESTADO_CATEGORIAS
from app.comandos.categorias import (
    ESTADO_NOVA,
    comando_categorias,
    continuar_categorias,
    continuar_nova,
)
from app.comandos.desfazer import ESTADO as ESTADO_DESFAZER
from app.comandos.desfazer import comando_desfazer, continuar_desfazer
from app.comandos.estado import ler_estado, limpar_estado
from app.comandos.formato import normalizar
from app.comandos.gasto import ESTADO as ESTADO_GASTO
from app.comandos.gasto import comando_gasto, continuar_gasto, frase_de_gasto
from app.comandos.inicio import ESTADO as ESTADO_INICIO
from app.comandos.inicio import comando_inicio, continuar_inicio
from app.comandos.metas import comando_metas
from app.comandos.resposta import Resposta

# Comandos já implementados: nome -> função(argumentos) que devolve a resposta.
COMANDOS = {
    "ajuda": comando_ajuda,
}

# Comandos que precisam saber quem mandou: nome -> função(telefone, argumentos).
COMANDOS_COM_USUARIO = {
    "inicio": comando_inicio,
    "metas": comando_metas,
    "gasto": comando_gasto,
    "categorias": comando_categorias,
    "desfazer": comando_desfazer,
}

# Todos os comandos previstos no CLAUDE.md (os que faltam respondem "Ainda estou aprendendo isso").
COMANDOS_CONHECIDOS = {
    "inicio", "metas", "resumo", "gasto", "entrada", "categorias", "fixos",
    "previsao", "diagnostico", "objetivos", "parcelas", "desfazer", "privacidade",
    "apagar_meus_dados", "ajuda", "grafico", "casal", "entrar", "grupo",
}

# Comandos que só o número em ADMIN_NUMERO pode usar.
COMANDOS_ADMIN = {"liberar", "bloquear"}

BOAS_VINDAS = "Oi, eu sou a Dona Fatura! Vou cuidar das suas contas com você."


def _separar(texto: str) -> tuple[str, str]:
    """"/Gasto 45 mercado" -> ("gasto", "45 mercado"). Frase livre -> ("", "")."""
    texto = texto.strip()
    if not texto.startswith("/"):
        return "", ""
    partes = texto[1:].split(maxsplit=1)
    nome = normalizar(partes[0]) if partes else ""
    argumentos = partes[1] if len(partes) > 1 else ""
    return nome, argumentos


def responder(texto: str) -> str:
    """Escolhe a resposta para uma mensagem de texto (sem acessar o banco)."""
    if not texto.strip().startswith("/"):
        # Frases livres serão entendidas pela IA numa etapa futura.
        return "Não entendi. Mande /ajuda para ver os comandos ou algo como: gastei 45 no mercado"
    nome, argumentos = _separar(texto)
    if nome in COMANDOS:
        return COMANDOS[nome](argumentos)
    if nome in COMANDOS_CONHECIDOS:
        return "Ainda estou aprendendo isso."
    return "Não conheço esse comando. Mande /ajuda para ver a lista."


def _continuar_conversa(telefone: str, texto: str) -> str | Resposta | None:
    """Se houver uma conversa em andamento (ex.: /inicio), trata a resposta nela."""
    conversa = ler_estado(telefone)
    if conversa is None:
        return None
    estado, dados = conversa
    if estado == ESTADO_INICIO:
        return continuar_inicio(telefone, dados, texto)
    if estado == ESTADO_CATEGORIAS:
        return continuar_categorias(telefone, dados, texto)
    if estado == ESTADO_NOVA:
        return continuar_nova(telefone, dados, texto)
    if estado == ESTADO_GASTO:
        return continuar_gasto(telefone, dados, texto)
    if estado == ESTADO_DESFAZER:
        return continuar_desfazer(telefone, dados, texto)
    return None


def processar_mensagem(telefone: str, texto: str) -> str | Resposta:
    """Cadastra o usuário na primeira mensagem, confere o acesso e devolve a resposta."""
    novo = garantir_usuario(telefone)
    nome, argumentos = _separar(texto)
    admin = eh_admin(telefone)
    if admin and nome in COMANDOS_ADMIN:
        return comando_admin(nome, argumentos)
    status = "ativo" if admin else status_acesso(telefone)
    if status == "pendente":
        return comando_convite(telefone, argumentos) if nome == "convite" else MSG_PENDENTE
    if status != "ativo":
        return MSG_INATIVO
    if nome == "convite":
        return "Seu acesso já está ativo. Mande /ajuda para ver os comandos."
    if texto.strip().startswith("/"):
        limpar_estado(telefone)  # um comando novo cancela a conversa em andamento
        if nome in COMANDOS_COM_USUARIO:
            resposta = COMANDOS_COM_USUARIO[nome](telefone, argumentos)
        else:
            resposta = responder(texto)
    else:
        resposta = (
            _continuar_conversa(telefone, texto)
            or frase_de_gasto(telefone, texto)
            or responder(texto)
        )
    if novo:
        if isinstance(resposta, Resposta):
            return replace(resposta, texto=f"{BOAS_VINDAS}\n\n{resposta.texto}")
        return f"{BOAS_VINDAS}\n\n{resposta}"
    return resposta
