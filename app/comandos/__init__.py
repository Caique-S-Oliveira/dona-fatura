from dataclasses import replace

from app import ia
from app.comandos.acesso import (
    MSG_ANTES_DO_INICIO,
    cadastro_completo,
    comando_admin,
    comando_convite,
    eh_admin,
    status_acesso,
)
from app.comandos.ajuda import comando_ajuda, comando_ajuda_usuario
from app.comandos.cadastro import garantir_usuario
from app.comandos.casal import ESTADO as ESTADO_CASAL
from app.comandos.casal import comando_casal, comando_entrar, continuar_casal
from app.comandos.categorias import ESTADO as ESTADO_CATEGORIAS
from app.comandos.categorias import (
    ESTADO_NOVA,
    comando_categorias,
    continuar_categorias,
    continuar_nova,
)
from app.comandos.comprovante import receber_comprovante
from app.comandos.desfazer import ESTADO as ESTADO_DESFAZER
from app.comandos.desfazer import comando_desfazer, continuar_desfazer
from app.comandos.diagnostico import comando_diagnostico
from app.comandos.entrada import ESTADO as ESTADO_ENTRADA
from app.comandos.entrada import comando_entrada, continuar_entrada, receber_holerite
from app.comandos.estado import ler_estado, limpar_estado
from app.comandos.fixos import comando_fixos
from app.comandos.formato import normalizar
from app.comandos.gasto import ESTADO as ESTADO_GASTO
from app.comandos.gasto import comando_gasto, continuar_gasto, frase_de_gasto
from app.comandos.inicio import ESTADO as ESTADO_INICIO
from app.comandos.inicio import comando_inicio, continuar_inicio
from app.comandos.metas import comando_metas
from app.comandos.objetivos import ESTADO as ESTADO_OBJETIVO
from app.comandos.objetivos import ESTADO_GERIR as ESTADO_OBJETIVO_GERIR
from app.comandos.objetivos import (
    comando_objetivos,
    continuar_gerir as continuar_objetivo_gerir,
    continuar_objetivo,
    frase_de_aporte,
)
from app.comandos.parcelas import ESTADO as ESTADO_PARCELA
from app.comandos.parcelas import ESTADO_GERIR as ESTADO_PARCELA_GERIR
from app.comandos.parcelas import (
    comando_parcelas,
    continuar_gerir as continuar_parcela_gerir,
    continuar_parcela,
)
from app.comandos.pagar import ESTADO as ESTADO_PAGAR
from app.comandos.pagar import comando_pagar, continuar_pagar
from app.comandos.previsao import comando_grafico, comando_previsao
from app.comandos.privacidade import ESTADO as ESTADO_APAGAR
from app.comandos.privacidade import comando_apagar, comando_privacidade, continuar_apagar
from app.comandos.recorrentes import ESTADO as ESTADO_RECORRENTE
from app.comandos.recorrentes import continuar_recorrente
from app.comandos.resposta import Resposta
from app.comandos.sair_casal import ESTADO as ESTADO_SAIR_CASAL
from app.comandos.sair_casal import comando_sair_casal, continuar_sair_casal
from app.comandos.resumo import comando_resumo

# Comandos já implementados: nome -> função(argumentos) que devolve a resposta.
COMANDOS = {
    "ajuda": comando_ajuda,
    "privacidade": comando_privacidade,
}

# Comandos que precisam saber quem mandou: nome -> função(telefone, argumentos).
COMANDOS_COM_USUARIO = {
    "ajuda": comando_ajuda_usuario,
    "inicio": comando_inicio,
    "metas": comando_metas,
    "gasto": comando_gasto,
    "entrada": comando_entrada,
    "categorias": comando_categorias,
    "desfazer": comando_desfazer,
    "resumo": comando_resumo,
    "fixos": comando_fixos,
    "previsao": comando_previsao,
    "diagnostico": comando_diagnostico,
    "objetivos": comando_objetivos,
    "parcelas": comando_parcelas,
    "pagar": comando_pagar,
    "grafico": comando_grafico,
    "apagar_meus_dados": comando_apagar,
    "casal": comando_casal,
    "entrar": comando_entrar,
    "sair_casal": comando_sair_casal,
}

# Todos os comandos previstos no CLAUDE.md (os que faltam respondem "Ainda estou aprendendo isso").
COMANDOS_CONHECIDOS = {
    "inicio", "metas", "resumo", "gasto", "entrada", "categorias", "fixos",
    "previsao", "diagnostico", "objetivos", "parcelas", "pagar", "desfazer", "privacidade",
    "apagar_meus_dados", "ajuda", "grafico", "casal", "entrar", "grupo", "sair_casal",
}

# Comandos que só o número em ADMIN_PHONE pode usar (de qualquer outro, nem parecem existir).
COMANDOS_ADMIN = {"liberar", "negar", "bloquear", "pendentes", "usuarios"}

# Comandos que a IA pode escolher numa frase livre (apagar dados só por comando explícito).
COMANDOS_PELA_IA = COMANDOS_CONHECIDOS - {"apagar_meus_dados"}

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


def processar_comprovante(telefone: str, tipo: str, baixar) -> str | Resposta | None:
    """Foto ou PDF recebido: confere o acesso (antes de baixar ou gastar IA) e lê o comprovante."""
    if not eh_admin(telefone) and status_acesso(telefone) != "ativo":
        return None  # não liberado: nada é baixado nem enviado à IA
    garantir_usuario(telefone)
    if not cadastro_completo(telefone):
        return MSG_ANTES_DO_INICIO
    conversa = ler_estado(telefone)
    if conversa is not None and conversa[0] == ESTADO_ENTRADA:
        # Depois de /entrada sem valor, o arquivo é lido como holerite.
        return receber_holerite(telefone, tipo, baixar)
    limpar_estado(telefone)  # um arquivo novo cancela a conversa em andamento
    return receber_comprovante(telefone, tipo, baixar)


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
    if estado == ESTADO_ENTRADA:
        return continuar_entrada(telefone, dados, texto)
    if estado == ESTADO_DESFAZER:
        return continuar_desfazer(telefone, dados, texto)
    if estado == ESTADO_RECORRENTE:
        return continuar_recorrente(telefone, dados, texto)
    if estado == ESTADO_OBJETIVO:
        return continuar_objetivo(telefone, dados, texto)
    if estado == ESTADO_PARCELA:
        return continuar_parcela(telefone, dados, texto)
    if estado == ESTADO_OBJETIVO_GERIR:
        return continuar_objetivo_gerir(telefone, dados, texto)
    if estado == ESTADO_PARCELA_GERIR:
        return continuar_parcela_gerir(telefone, dados, texto)
    if estado == ESTADO_PAGAR:
        return continuar_pagar(telefone, dados, texto)
    if estado == ESTADO_APAGAR:
        return continuar_apagar(telefone, dados, texto)
    if estado == ESTADO_CASAL:
        return continuar_casal(telefone, dados, texto)
    if estado == ESTADO_SAIR_CASAL:
        return continuar_sair_casal(telefone, dados, texto)
    return None


def _executar_comando(telefone: str, nome: str, argumentos: str) -> str | Resposta:
    limpar_estado(telefone)  # um comando novo cancela a conversa em andamento
    if nome in COMANDOS_COM_USUARIO:
        return COMANDOS_COM_USUARIO[nome](telefone, argumentos)
    return responder(f"/{nome} {argumentos}")


def frase_pela_ia(telefone: str, texto: str) -> str | Resposta | None:
    """Frase livre que nenhuma regra entendeu: a IA diz qual comando é. None se não souber."""
    entendido = ia.identificar_comando(texto)
    if entendido is None:
        return None
    nome, argumentos = entendido
    if nome not in COMANDOS_PELA_IA:
        return None
    return _executar_comando(telefone, nome, argumentos)


def _inicio_em_andamento(telefone: str) -> bool:
    conversa = ler_estado(telefone)
    return conversa is not None and conversa[0] == ESTADO_INICIO


def processar_mensagem(telefone: str, texto: str) -> str | Resposta | None:
    """Confere o acesso, cria a conta na primeira mensagem de quem foi liberado e devolve a resposta.

    None = não responder (número não liberado)."""
    nome, argumentos = _separar(texto)
    admin = eh_admin(telefone)
    if admin and nome in COMANDOS_ADMIN:
        return comando_admin(nome, argumentos)
    status = "ativo" if admin else status_acesso(telefone)
    if status == "pendente" and nome == "convite":
        return comando_convite(telefone, argumentos)
    if status != "ativo":
        return None  # pendente ou negado: a porta de entrada (acesso.avaliar) já cuidou do aviso
    novo = garantir_usuario(telefone)
    if nome == "convite":
        return "Seu acesso já está ativo. Mande /ajuda para ver os comandos."
    if not cadastro_completo(telefone):
        permitido = nome in ("inicio", "ajuda") if texto.strip().startswith("/") else _inicio_em_andamento(telefone)
        if not permitido:
            return MSG_ANTES_DO_INICIO  # sem IA, sem comando: só pede o /inicio
    if texto.strip().startswith("/"):
        resposta = _executar_comando(telefone, nome, argumentos)
    else:
        resposta = (
            _continuar_conversa(telefone, texto)
            or frase_de_aporte(telefone, texto)
            or frase_de_gasto(telefone, texto)
            or frase_pela_ia(telefone, texto)
            or responder(texto)
        )
    if novo:
        if isinstance(resposta, Resposta):
            return replace(resposta, texto=f"{BOAS_VINDAS}\n\n{resposta.texto}")
        return f"{BOAS_VINDAS}\n\n{resposta}"
    return resposta
