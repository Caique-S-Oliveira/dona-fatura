import unicodedata

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

# Comandos já implementados: nome -> função(argumentos) que devolve a resposta.
COMANDOS = {
    "ajuda": comando_ajuda,
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


def _normalizar(nome: str) -> str:
    """Minúsculas e sem acento: "/Previsão" -> "previsao"."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _separar(texto: str) -> tuple[str, str]:
    """"/Gasto 45 mercado" -> ("gasto", "45 mercado"). Frase livre -> ("", "")."""
    texto = texto.strip()
    if not texto.startswith("/"):
        return "", ""
    partes = texto[1:].split(maxsplit=1)
    nome = _normalizar(partes[0]) if partes else ""
    argumentos = partes[1] if len(partes) > 1 else ""
    return nome, argumentos


def responder(texto: str) -> str:
    """Escolhe a resposta para uma mensagem de texto (sem acessar o banco)."""
    if not texto.strip().startswith("/"):
        # Frases livres serão entendidas pela IA numa etapa futura.
        return "Ainda não entendo frases soltas. Mande /ajuda para ver os comandos."
    nome, argumentos = _separar(texto)
    if nome in COMANDOS:
        return COMANDOS[nome](argumentos)
    if nome in COMANDOS_CONHECIDOS:
        return "Ainda estou aprendendo isso."
    return "Não conheço esse comando. Mande /ajuda para ver a lista."


def processar_mensagem(telefone: str, texto: str) -> str:
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
    resposta = responder(texto)
    if novo:
        return f"{BOAS_VINDAS}\n\n{resposta}"
    return resposta
