from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import text

from app import ia
from app.comandos.cadastro import conta_do_usuario
from app.comandos.comprovante import TIPOS_ACEITOS, ler_data
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais, ler_numero, normalizar
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "entrada"
BOTOES = ("Sim", "Corrigir")
FORMATO = "Use: /entrada 4500 salário"
DESCRICAO_PADRAO = "Entrada"
DESCRICAO_HOLERITE = "Salário"
MSG_OFERTA = (
    "Qual o valor? Mande assim: /entrada 4500 salário\n"
    "Se preferir, mande a foto ou o PDF do holerite (é opcional)."
)
MSG_NAO_ENTENDI = "Não entendi. Mande o valor, ex.: 4500 salário. Ou a foto do holerite."
MSG_NAO_LEU = "Não consegui ler o holerite. Sem problema: me mande o valor líquido, ex.: 4500"
MSG_TIPO = "Só leio foto (JPG ou PNG) ou PDF. Ou me mande o valor, ex.: 4500"


def ler_entrada(argumentos: str) -> tuple[Decimal, str] | None:
    """"4.500,00 salário" ou "R$ 4500" -> (valor, descrição). Sem descrição vale "Entrada"."""
    palavras = argumentos.split()
    if palavras and normalizar(palavras[0]) == "r$":
        palavras = palavras[1:]
    if not palavras:
        return None
    valor = ler_numero(palavras[0])
    if valor is None or valor <= 0:
        return None
    return valor, " ".join(palavras[1:])[:60] or DESCRICAO_PADRAO


def _cabecalho(dados: dict) -> str:
    data = ""
    if dados.get("data"):
        ano, mes, dia = dados["data"].split("-")
        data = f", {dia}/{mes}/{ano}"
    return f"Entrada de {formatar_reais(Decimal(dados['valor']))} — {dados['descricao']}{data}."


def _pergunta_confirmar(dados: dict) -> Resposta:
    return Resposta(f"{_cabecalho(dados)} Confirma?", BOTOES)


def _confirmar(telefone: str, dados: dict) -> Resposta:
    dados = {**dados, "passo": "confirmar"}
    salvar_estado(telefone, ESTADO, dados)
    return _pergunta_confirmar(dados)


def _pedir_valor(telefone: str, mensagem: str) -> str:
    salvar_estado(telefone, ESTADO, {"passo": "aguardando"})
    return mensagem


def gravar_entrada(account_id, user_id, dados: dict) -> None:
    """Renda é sempre "conjunto": o parceiro vê o valor completo."""
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transactions (account_id, created_by_user_id, transaction_type,"
                " amount, description, transaction_date, scope, source)"
                " VALUES (:conta, :usuario, 'income', :valor, :descricao,"
                " COALESCE(CAST(:data AS date), (now() AT TIME ZONE 'America/Sao_Paulo')::date),"
                " 'conjunto', :fonte)"
            ),
            {
                "conta": account_id,
                "usuario": user_id,
                "valor": Decimal(dados["valor"]),
                "descricao": dados["descricao"],
                "data": dados.get("data"),  # "AAAA-MM-DD" do holerite; sem data = hoje
                "fonte": dados.get("fonte", "manual"),
            },
        )


def comando_entrada(telefone: str, argumentos: str) -> str | Resposta:
    if not argumentos.strip():
        # O holerite é só uma alternativa: a próxima foto/PDF será lida como holerite.
        salvar_estado(telefone, ESTADO, {"passo": "aguardando"})
        return MSG_OFERTA
    entrada = ler_entrada(argumentos)
    if entrada is None:
        return f"Não entendi a entrada. {FORMATO}"
    valor, descricao = entrada
    return _confirmar(telefone, {"valor": str(valor), "descricao": descricao, "fonte": "manual"})


def receber_holerite(
    telefone: str, tipo: str, baixar: Callable[[], bytes | None]
) -> str | Resposta:
    """Foto/PDF de holerite -> IA extrai valor líquido e data -> [Sim] [Corrigir].

    O arquivo só existe nesta função e é descartado logo após a leitura.
    Se não der para ler, pede o valor por texto (a conversa continua aberta).
    """
    if tipo not in TIPOS_ACEITOS:
        return MSG_TIPO
    conteudo = baixar()
    if conteudo is None:
        return _pedir_valor(telefone, MSG_NAO_LEU)
    try:
        extraido = ia.ler_holerite(conteudo, tipo)
    finally:
        del conteudo  # descarta o arquivo
    valor = ler_numero(extraido["valor"]) if extraido else None
    if valor is None or valor <= 0:
        return _pedir_valor(telefone, MSG_NAO_LEU)
    dados = {"valor": str(valor), "descricao": DESCRICAO_HOLERITE, "fonte": "paystub"}
    data = ler_data(extraido.get("data"))
    if data:
        dados["data"] = data
    return _confirmar(telefone, dados)


def continuar_entrada(telefone: str, dados: dict, texto: str) -> str | Resposta:
    passo = dados.get("passo")

    if passo == "aguardando":
        entrada = ler_entrada(texto)
        if entrada is None:
            return MSG_NAO_ENTENDI
        valor, descricao = entrada
        return _confirmar(telefone, {"valor": str(valor), "descricao": descricao, "fonte": "manual"})

    if passo == "valor":
        valor = ler_numero(texto)
        if valor is None or valor <= 0:
            return "Não entendi o valor. Mande só o número, ex.: 4500"
        return _confirmar(telefone, {**dados, "valor": str(valor)})

    # passo "confirmar"
    if eh_sim(texto):
        user_id, account_id = conta_do_usuario(telefone)
        gravar_entrada(account_id, user_id, dados)
        limpar_estado(telefone)
        return f"Anotado: entrada de {formatar_reais(Decimal(dados['valor']))}."
    if eh_nao(texto) or normalizar(texto).strip(" .!") == "corrigir":
        salvar_estado(telefone, ESTADO, {**dados, "passo": "valor"})
        return "Qual o valor correto? Ex.: 4500"
    resposta = _pergunta_confirmar(dados)
    resposta.texto = "Responda Sim ou Corrigir.\n" + resposta.texto
    return resposta
