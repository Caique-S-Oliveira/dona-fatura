import re
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import ia
from app.comandos.cadastro import conta_do_usuario
from app.comandos.casal import deve_perguntar_escopo
from app.comandos.categorias import (
    Categoria,
    achar_categoria,
    categoria_por_palavra,
    abrir_lista,
    chave,
    interpretar,
    iniciar_nova,
    listar_categorias,
    proxima_pagina,
)
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais, ler_numero, normalizar
from app.comandos.recorrentes import verificar_recorrente
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "gasto"
BOTOES = ("Sim", "Corrigir")
BOTOES_CORRIGIR = ("Valor", "Categoria")
BOTOES_ESCOPO = ("Meu", "Conjunto")
FORMATO = "Use: /gasto 45,90 mercado"

# "gastei 45 no mercado", "paguei R$ 30,50 de uber", "comprei 12 reais de pão"
FRASE = re.compile(
    r"^\s*(?:eu\s+)?(?:gastei|paguei|comprei|torrei)\s+(?:r\$\s*)?(?P<valor>\d[\d.,]*)"
    r"\s*(?:reais|real|conto|contos)?\s+"
    r"(?:(?:no|na|nos|nas|num|numa|em|de|do|da|dos|das|com|pro|pra)\s+)?(?P<descricao>.+?)\s*$",
    re.IGNORECASE,
)
PALAVRAS_DE_GASTO = ("gastei", "paguei", "comprei", "torrei", "gasto", "gastamos", "pagamos")

Gasto = tuple[Decimal, str, str]  # (valor, descrição, escopo)


SUFIXOS_MEU = ("meu", "minha")
SUFIXOS_CONJUNTO = ("casal", "conjunto")


def separar_escopo(descricao: str) -> tuple[str, str]:
    """"padaria meu" -> ("padaria", "meu"). Sem sufixo, o gasto é "conjunto"."""
    palavras = descricao.split()
    if len(palavras) >= 2 and normalizar(palavras[-1]) in SUFIXOS_MEU:
        return " ".join(palavras[:-1]), "meu"
    if len(palavras) >= 2 and normalizar(palavras[-1]) in SUFIXOS_CONJUNTO:
        return " ".join(palavras[:-1]), "conjunto"
    return descricao.strip(), "conjunto"


def tem_sufixo_de_escopo(descricao: str) -> bool:
    """O usuário escreveu "meu" ou "casal" no fim? Aí não precisa perguntar [Meu] [Conjunto]."""
    palavras = descricao.split()
    return len(palavras) >= 2 and normalizar(palavras[-1]) in SUFIXOS_MEU + SUFIXOS_CONJUNTO


def _montar(valor: Decimal | None, descricao: str) -> Gasto | None:
    if valor is None or valor <= 0:
        return None
    descricao, escopo = separar_escopo(descricao)
    if not descricao:
        return None
    return valor, descricao[:60], escopo


def ler_comando(argumentos: str) -> Gasto | None:
    """"45,90 mercado" ou "R$ 45,90 padaria meu" -> (valor, descrição, escopo)."""
    palavras = argumentos.split()
    if palavras and normalizar(palavras[0]) == "r$":
        palavras = palavras[1:]
    if len(palavras) < 2:
        return None
    return _montar(ler_numero(palavras[0]), " ".join(palavras[1:]))


def ler_frase(texto: str) -> Gasto | None:
    """"gastei 45 no mercado" -> (Decimal("45.00"), "mercado", "conjunto")."""
    achado = FRASE.match(texto)
    if achado is None:
        return None
    return _montar(ler_numero(achado["valor"]), achado["descricao"])


def parece_gasto(texto: str) -> bool:
    """Frase fala de gasto? Só nesse caso vale a pena chamar a IA."""
    return any(p in normalizar(texto).split() for p in PALAVRAS_DE_GASTO)


# ---------- sugestão de categoria ----------

def regra_aprendida(account_id, descricao: str) -> str | None:
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT category_id FROM classification_rules"
                " WHERE account_id = :conta AND normalized_payee = :chave"
            ),
            {"conta": account_id, "chave": chave(descricao)},
        ).scalar()


def sugerir(account_id, descricao: str, categorias: list[Categoria]) -> Categoria | None:
    """Regras aprendidas -> nome da categoria -> palavras comuns -> IA."""
    aprendida = regra_aprendida(account_id, descricao)
    if aprendida is not None:
        achada = next((c for c in categorias if c.id == str(aprendida)), None)
        if achada:
            return achada
    achada = achar_categoria(categorias, descricao) or categoria_por_palavra(categorias, descricao)
    if achada:
        return achada
    nome = ia.sugerir_categoria(descricao, [c.nome for c in categorias])
    return achar_categoria(categorias, nome) if nome else None


# ---------- banco de dados ----------

def gravar_gasto(account_id, user_id, dados: dict, categoria_id: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transactions (account_id, created_by_user_id, category_id,"
                " transaction_type, amount, description, payee, transaction_date, scope, source)"
                " VALUES (:conta, :usuario, :categoria, 'expense', :valor, :descricao, :favorecido,"
                " COALESCE(CAST(:data AS date), (now() AT TIME ZONE 'America/Sao_Paulo')::date),"
                " :escopo, :fonte)"
            ),
            {
                "conta": account_id,
                "usuario": user_id,
                "categoria": categoria_id,
                "valor": Decimal(dados["valor"]),
                "descricao": dados["descricao"],
                "favorecido": dados.get("favorecido"),
                "data": dados.get("data"),  # "AAAA-MM-DD" do comprovante; sem data = hoje
                "escopo": dados["escopo"],
                "fonte": dados.get("fonte", "manual"),
            },
        )


def salvar_regra(account_id, user_id, descricao: str, categoria_id: str) -> None:
    """Aprende: da próxima vez, essa descrição vai direto para a categoria escolhida."""
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO classification_rules"
                " (account_id, created_by_user_id, category_id, normalized_payee)"
                " VALUES (:conta, :usuario, :categoria, :chave)"
                " ON CONFLICT (account_id, normalized_payee) DO UPDATE SET"
                " category_id = EXCLUDED.category_id,"
                " created_by_user_id = EXCLUDED.created_by_user_id"
            ),
            {"conta": account_id, "usuario": user_id, "categoria": categoria_id,
             "chave": chave(descricao)},
        )


# ---------- conversa ----------

def _cabecalho(dados: dict) -> str:
    privado = " (só seu)" if dados["escopo"] == "meu" else ""
    data = ""
    if dados.get("data"):
        data = f", {date.fromisoformat(dados['data']).strftime('%d/%m/%Y')}"
    return f"Gasto de {formatar_reais(Decimal(dados['valor']))} — {dados['descricao']}{data}{privado}."


def _lista_categorias(telefone: str, dados: dict, pagina: int | None, aviso: str = "") -> Resposta:
    """Guarda o ponto da conversa e mostra a lista de categorias (principal ou "Outras…")."""
    user_id, account_id = conta_do_usuario(telefone)
    dados = {**dados, "passo": "categoria", "pagina": pagina}
    salvar_estado(telefone, ESTADO, dados)
    texto = f"{aviso}{_cabecalho(dados)}\nQual a categoria?"
    return abrir_lista(account_id, user_id, texto, pagina)


def _pergunta_corrigir() -> Resposta:
    return Resposta("O que você quer corrigir?", BOTOES_CORRIGIR)


def _pergunta_confirmar(dados: dict) -> Resposta:
    return Resposta(
        f"{_cabecalho(dados)}\nCategoria: {dados['categoria_nome']}. Confirma?", BOTOES
    )


def _pergunta_escopo(dados: dict) -> Resposta:
    return Resposta(f"{_cabecalho(dados)}\nÉ um gasto seu ou do casal?", BOTOES_ESCOPO)


def sugerir_e_confirmar(telefone: str, account_id, dados: dict) -> str | Resposta:
    """Sugere a categoria e pede confirmação (nada é salvo ainda)."""
    categorias = listar_categorias(account_id)
    sugestao = sugerir(account_id, dados["descricao"], categorias)
    if sugestao is None:
        return _lista_categorias(telefone, dados, None)
    dados = {**dados, "passo": "confirmar", "categoria_id": sugestao.id, "categoria_nome": sugestao.nome}
    salvar_estado(telefone, ESTADO, dados)
    return _pergunta_confirmar(dados)


def comecar_gasto(telefone: str, account_id, dados: dict, escopo_explicito: bool) -> str | Resposta:
    """No casal "com gastos pessoais", pergunta [Meu] [Conjunto] antes (a menos que o usuário
    tenha escrito "meu"/"casal"). Nos outros casos vai direto para a categoria."""
    if not escopo_explicito and deve_perguntar_escopo(account_id):
        dados = {**dados, "passo": "escopo"}
        salvar_estado(telefone, ESTADO, dados)
        return _pergunta_escopo(dados)
    return sugerir_e_confirmar(telefone, account_id, dados)


def iniciar_gasto(telefone: str, gasto: Gasto, escopo_explicito: bool = True) -> str | Resposta:
    valor, descricao, escopo = gasto
    _, account_id = conta_do_usuario(telefone)
    dados = {"valor": str(valor), "descricao": descricao, "escopo": escopo}
    return comecar_gasto(telefone, account_id, dados, escopo_explicito)


def comando_gasto(telefone: str, argumentos: str) -> str | Resposta:
    gasto = ler_comando(argumentos)
    if gasto is None:
        return f"Não entendi o gasto. {FORMATO}"
    return iniciar_gasto(telefone, gasto, tem_sufixo_de_escopo(argumentos))


def frase_de_gasto(telefone: str, texto: str) -> str | Resposta | None:
    """Frase livre: tenta as regras; se falar de gasto e não der, pede ajuda à IA.

    Devolve None se a frase não for sobre gasto.
    """
    gasto = ler_frase(texto)
    explicito = tem_sufixo_de_escopo(texto)
    if gasto is None and parece_gasto(texto):
        extraido = ia.entender_gasto(texto)
        if extraido:
            gasto = _montar(ler_numero(extraido["valor"]), extraido["descricao"])
            explicito = tem_sufixo_de_escopo(extraido["descricao"])
        if gasto is None:
            return f"Não entendi o gasto. {FORMATO}"
    if gasto is None:
        return None
    return iniciar_gasto(telefone, gasto, explicito)


def registrar(account_id, user_id, dados: dict, categoria: Categoria) -> str:
    """Grava o gasto na categoria escolhida. Se mudou da sugestão, aprende a regra."""
    gravar_gasto(account_id, user_id, dados, categoria.id)
    resposta = f"Anotado: {formatar_reais(Decimal(dados['valor']))} em {categoria.nome}."
    if categoria.id != dados.get("categoria_id") and dados.get("aprender", True):
        salvar_regra(account_id, user_id, dados["descricao"], categoria.id)
        resposta += f"\nAprendi: \"{dados['descricao']}\" vai para {categoria.nome}."
    return resposta


def finalizar_registro(
    telefone: str, account_id, user_id, dados: dict, categoria: Categoria, resposta: str
) -> str | Resposta:
    """Fecha a conversa do gasto; se a conta parecer recorrente, acrescenta a pergunta com botões."""
    limpar_estado(telefone)
    from app import alertas  # import tardio: alertas usa os comandos

    alertas.preparar_alerta_gasto(telefone, account_id, user_id, dados, categoria)
    pergunta = verificar_recorrente(telefone, account_id, user_id, dados, categoria)
    if pergunta is None:
        return resposta
    pergunta.texto = f"{resposta}\n{pergunta.texto}"
    return pergunta


def continuar_gasto(telefone: str, dados: dict, texto: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    passo = dados.get("passo")
    escolha = normalizar(texto).strip(" .!")

    if passo == "escopo":
        if escolha in SUFIXOS_MEU:
            return sugerir_e_confirmar(telefone, account_id, {**dados, "escopo": "meu"})
        if escolha in SUFIXOS_CONJUNTO:
            return sugerir_e_confirmar(telefone, account_id, {**dados, "escopo": "conjunto"})
        resposta = _pergunta_escopo(dados)
        resposta.texto = "Toque em Meu ou Conjunto.\n" + resposta.texto
        return resposta

    if passo == "confirmar":
        if eh_sim(texto):
            categoria = Categoria(dados["categoria_id"], dados["categoria_nome"], "")
            resposta = registrar(account_id, user_id, dados, categoria)
            return finalizar_registro(telefone, account_id, user_id, dados, categoria, resposta)
        if eh_nao(texto) or escolha == "corrigir":
            salvar_estado(telefone, ESTADO, {**dados, "passo": "corrigir"})
            return _pergunta_corrigir()
        resposta = _pergunta_confirmar(dados)
        resposta.texto = "Responda Sim ou Corrigir.\n" + resposta.texto
        return resposta

    if passo == "corrigir":
        if escolha == "valor":
            salvar_estado(telefone, ESTADO, {**dados, "passo": "valor"})
            return "Qual o valor correto? Ex.: 45,90"
        if escolha == "categoria":
            return _lista_categorias(telefone, dados, None)
        resposta = _pergunta_corrigir()
        resposta.texto = "Toque em Valor ou Categoria.\n" + resposta.texto
        return resposta

    if passo == "valor":
        valor = ler_numero(texto)
        if valor is None or valor <= 0:
            return "Não entendi o valor. Mande só o número, ex.: 45,90"
        dados = {**dados, "passo": "confirmar", "valor": str(valor)}
        salvar_estado(telefone, ESTADO, dados)
        return _pergunta_confirmar(dados)

    # passo "categoria": toque numa linha da lista ou nome digitado
    entendido = interpretar(listar_categorias(account_id), texto)
    pagina = dados.get("pagina")
    if entendido is None:
        return _lista_categorias(telefone, dados, pagina, "Não achei essa categoria.\n")
    tipo, valor = entendido
    if tipo == "categoria":
        resposta = registrar(account_id, user_id, dados, valor)
        return finalizar_registro(telefone, account_id, user_id, dados, valor, resposta)
    if valor == "nova":
        return iniciar_nova(telefone, retorno=dados)
    return _lista_categorias(telefone, dados, proxima_pagina(pagina))
