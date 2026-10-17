import re
from dataclasses import dataclass

from sqlalchemy import text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import normalizar
from app.comandos.metas import TIPOS, achar_tipo
from app.comandos.resposta import Resposta
from app.db import get_engine

# Subcategorias criadas para toda conta: nome -> tipo.
PADRAO = {
    "Moradia": "Fixo",
    "Mercado": "Variável",
    "Transporte": "Variável",
    "Saúde": "Variável",
    "Lazer": "Variável",
    "Restaurante": "Variável",
    "Pets": "Variável",
    "Parcelas/dívidas": "Fixo",
    "Viagens": "Variável",
    "Educação": "Fixo",
    "Outros": "Variável",
}

# Palavras comuns -> categoria padrão (regras simples antes de chamar a IA).
PALAVRAS = {
    "Mercado": "supermercado feira padaria pao acougue hortifruti sacolao atacadao",
    "Transporte": "uber 99 taxi onibus metro trem gasolina combustivel posto estacionamento pedagio",
    "Restaurante": "ifood lanche lanchonete pizza hamburguer almoco jantar bar cafe sushi",
    "Saúde": "farmacia remedio medico consulta dentista exame hospital academia",
    "Moradia": "aluguel condominio luz energia agua internet iptu",
    "Pets": "racao veterinario petshop pet",
    "Lazer": "cinema show teatro ingresso jogo",
    "Educação": "escola faculdade curso livro mensalidade",
    "Viagens": "passagem hotel hospedagem airbnb",
    "Parcelas/dívidas": "parcela emprestimo financiamento fatura",
}

ESTADO = "categorias"
ESTADO_NOVA = "categoria_nova"

# Ids das linhas da lista interativa (o WhatsApp devolve o id da linha tocada).
ID_CATEGORIA = "cat:"
ID_ACAO = "acao:"
LIMITE_PRINCIPAIS = 8  # categorias mais usadas na 1ª tela (+ "Outras…" + "Nova" = 10 linhas)
POR_PAGINA = 8  # categorias por tela em "Outras…" (+ "Mais…" + "Nova" = 10 linhas)
LINHA_OUTRAS = (ID_ACAO + "outras", "Outras…", "Ver as demais categorias")
LINHA_MAIS = (ID_ACAO + "mais", "Mais…", "Ver mais categorias")
LINHA_NOVA = (ID_ACAO + "nova", "➕ Nova categoria", "")
# Palavras digitadas que valem como as linhas acima (para quem não usa a lista).
ACOES_DIGITADAS = {"outras": "outras", "mais": "mais", "nova": "nova", "nova categoria": "nova"}

# A Meta aceita só 3 botões; os 5 tipos ficam em duas telas.
BOTOES_TIPO = ("Fixo", "Variável", "Outro tipo…")
BOTOES_TIPO_2 = ("Assinatura", "Investimento", "Reserva emergência")

AJUDA_CRIAR = "Para criar: /categorias criar NOME TIPO\nEx.: /categorias criar Academia variavel"


@dataclass
class Categoria:
    id: str
    nome: str
    tipo: str


def chave(texto: str) -> str:
    """"  Ração  do Rex " -> "racao do rex" (usado para comparar nomes e favorecidos)."""
    return " ".join(normalizar(texto).split())


def _partes(nome: str) -> list[str]:
    """"Parcelas/dívidas" -> ["parcelas", "dividas"]."""
    return chave(nome.replace("/", " ")).split()


def _mesma_palavra(a: str, b: str) -> bool:
    return a == b or a.rstrip("s") == b.rstrip("s")


def achar_categoria(categorias: list[Categoria], texto: str) -> Categoria | None:
    """Acha a categoria cujo nome aparece no texto ("compras no mercado" -> Mercado)."""
    alvo = chave(texto)
    for categoria in categorias:
        if chave(categoria.nome) == alvo:
            return categoria
    palavras = alvo.replace("/", " ").split()
    for categoria in categorias:
        if any(_mesma_palavra(p, w) for p in _partes(categoria.nome) for w in palavras):
            return categoria
    return None


def categoria_por_palavra(categorias: list[Categoria], descricao: str) -> Categoria | None:
    """Usa a lista PALAVRAS ("uber" -> Transporte)."""
    palavras = chave(descricao).split()
    for nome, lista in PALAVRAS.items():
        if any(w in lista.split() for w in palavras):
            return next((c for c in categorias if c.nome == nome), None)
    return None


def interpretar(categorias: list[Categoria], texto: str) -> tuple[str, Categoria | str] | None:
    """Resposta a uma lista de categorias.

    Devolve ("categoria", Categoria) ou ("acao", "outras" | "mais" | "nova"); None se não entendeu.
    Vale o id da linha tocada ou o nome digitado.
    """
    texto = texto.strip()
    if texto.startswith(ID_CATEGORIA):
        achada = next((c for c in categorias if c.id == texto[len(ID_CATEGORIA):]), None)
        return ("categoria", achada) if achada else None
    if texto.startswith(ID_ACAO):
        acao = texto[len(ID_ACAO):]
        return ("acao", acao) if acao in ("outras", "mais", "nova") else None
    # tira a pontuação: "Outras…" vira "outras..." na normalização
    acao = ACOES_DIGITADAS.get(" ".join(re.sub(r"[^a-z0-9 ]", "", chave(texto)).split()))
    if acao:
        return ("acao", acao)
    achada = achar_categoria(categorias, texto)
    return ("categoria", achada) if achada else None


def dividir(categorias: list[Categoria], usadas: list[str]) -> tuple[list[Categoria], list[Categoria]]:
    """Separa (principais, resto): as mais usadas primeiro, completando com as demais até 8."""
    por_id = {c.id: c for c in categorias}
    principais = [por_id[i] for i in usadas if i in por_id][:LIMITE_PRINCIPAIS]
    for categoria in categorias:
        if len(principais) >= LIMITE_PRINCIPAIS:
            break
        if categoria not in principais:
            principais.append(categoria)
    return principais, [c for c in categorias if c not in principais]


def _linha(categoria: Categoria) -> tuple[str, str, str]:
    return ID_CATEGORIA + categoria.id, categoria.nome, categoria.tipo


def lista_categorias(
    texto: str, categorias: list[Categoria], usadas: list[str], pagina: int | None = None
) -> Resposta:
    """Mensagem de lista (máx. 10 linhas). pagina=None: as mais usadas; número: "Outras…"."""
    principais, resto = dividir(categorias, usadas)
    if pagina is None:
        linhas = [_linha(c) for c in principais]
        if resto:
            linhas.append(LINHA_OUTRAS)
    else:
        inicio = pagina * POR_PAGINA
        if inicio >= len(resto):
            inicio = 0
        linhas = [_linha(c) for c in resto[inicio:inicio + POR_PAGINA]]
        if inicio + POR_PAGINA < len(resto):
            linhas.append(LINHA_MAIS)
    linhas.append(LINHA_NOVA)
    return Resposta(texto, lista=tuple(linhas), botao_lista="Escolher categoria")


def abrir_lista(account_id, user_id, texto: str, pagina: int | None = None) -> Resposta:
    categorias = listar_categorias(account_id)
    return lista_categorias(texto, categorias, mais_usadas(account_id, user_id), pagina)


def proxima_pagina(pagina: int | None) -> int:
    """"Outras…" abre a página 0; "Mais…" avança."""
    return 0 if pagina is None else pagina + 1


# ---------- banco de dados ----------

def garantir_padrao(account_id) -> None:
    """Cria as categorias padrão na conta, se ainda não existirem."""
    with get_engine().begin() as connection:
        tem = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM categories WHERE account_id = :conta AND is_default)"),
            {"conta": account_id},
        ).scalar()
        if tem:
            return
        for nome, tipo in PADRAO.items():
            connection.execute(
                text(
                    "INSERT INTO categories (account_id, name, normalized_name, type, is_default)"
                    " VALUES (:conta, :nome, :chave, :tipo, true)"
                    " ON CONFLICT (account_id, normalized_name) DO NOTHING"
                ),
                {"conta": account_id, "nome": nome, "chave": chave(nome), "tipo": tipo},
            )


def listar_categorias(account_id) -> list[Categoria]:
    """Categorias da conta (padrão primeiro, na ordem do PADRAO; depois as criadas)."""
    garantir_padrao(account_id)
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT id, name, type, is_default FROM categories"
                " WHERE account_id = :conta ORDER BY created_at, name"
            ),
            {"conta": account_id},
        ).all()
    ordem = list(PADRAO)
    linhas = sorted(
        linhas,
        key=lambda l: (not l.is_default, ordem.index(l.name) if l.name in ordem else 0),
    )
    return [Categoria(str(l.id), l.name, l.type) for l in linhas]


def mais_usadas(account_id, user_id) -> list[str]:
    """Ids das categorias que o usuário mais usou (as 8 primeiras)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT category_id FROM transactions"
                " WHERE account_id = :conta AND created_by_user_id = :usuario"
                " AND category_id IS NOT NULL AND voided_at IS NULL"
                " GROUP BY category_id ORDER BY count(*) DESC, max(created_at) DESC LIMIT :limite"
            ),
            {"conta": account_id, "usuario": user_id, "limite": LIMITE_PRINCIPAIS},
        ).all()
    return [str(linha.category_id) for linha in linhas]


def criar_categoria(account_id, user_id, nome: str, tipo: str) -> str:
    """Cria a categoria e devolve o id dela."""
    with get_engine().begin() as connection:
        return str(connection.execute(
            text(
                "INSERT INTO categories (account_id, created_by_user_id, name, normalized_name, type)"
                " VALUES (:conta, :usuario, :nome, :chave, :tipo) RETURNING id"
            ),
            {"conta": account_id, "usuario": user_id, "nome": nome, "chave": chave(nome), "tipo": tipo},
        ).scalar_one())


# ---------- comando /categorias ----------

def _mostrar(categorias: list[Categoria]) -> str:
    linhas = ["Suas categorias:"]
    for tipo in TIPOS:
        nomes = [c.nome for c in categorias if c.tipo == tipo]
        if nomes:
            linhas.append(f"{tipo}: {', '.join(nomes)}")
    linhas.append(AJUDA_CRIAR)
    return "\n".join(linhas)


def ler_pedido_criar(argumentos: str) -> tuple[str, str] | None:
    """"Academia variavel" -> ("Academia", "Variável"). Sem tipo, usa Variável."""
    palavras = argumentos.split()
    if not palavras:
        return None
    tipo = "Variável"
    if len(palavras) >= 4 and chave(" ".join(palavras[-3:])) == "reserva de emergencia":
        tipo, palavras = "Reserva de emergência", palavras[:-3]
    elif len(palavras) >= 2 and achar_tipo(palavras[-1]):
        tipo, palavras = achar_tipo(palavras[-1]), palavras[:-1]
    nome = " ".join(palavras)
    return (nome[0].upper() + nome[1:], tipo) if nome else None


def comando_categorias(telefone: str, argumentos: str) -> str:
    user_id, account_id = conta_do_usuario(telefone)
    categorias = listar_categorias(account_id)
    partes = argumentos.strip().split(maxsplit=1)
    if not partes:
        salvar_estado(telefone, ESTADO, {"pagina": None})
        return lista_categorias(
            _mostrar(categorias)[:1000], categorias, mais_usadas(account_id, user_id)
        )
    if normalizar(partes[0]) not in ("criar", "nova", "novo", "adicionar"):
        return "Não entendi.\n" + AJUDA_CRIAR
    pedido = ler_pedido_criar(partes[1] if len(partes) > 1 else "")
    if pedido is None:
        return "Faltou o nome.\n" + AJUDA_CRIAR
    nome, tipo = pedido
    if len(nome) > 30:
        return "Nome muito longo. Use até 30 letras."
    if any(chave(c.nome) == chave(nome) for c in categorias):
        return f"A categoria {nome} já existe."
    criar_categoria(account_id, user_id, nome, tipo)
    return f"Categoria {nome} ({tipo}) criada."


def continuar_categorias(telefone: str, dados: dict, texto: str) -> str | Resposta:
    """Resposta à lista aberta por /categorias."""
    user_id, account_id = conta_do_usuario(telefone)
    categorias = listar_categorias(account_id)
    entendido = interpretar(categorias, texto)
    pagina = dados.get("pagina")
    if entendido is None:
        aviso = "Não achei essa categoria. Toque em uma da lista."
    elif entendido[0] == "categoria":
        limpar_estado(telefone)
        return f"{entendido[1].nome} é do tipo {entendido[1].tipo}."
    elif entendido[1] == "nova":
        return iniciar_nova(telefone)
    else:
        pagina = proxima_pagina(pagina)
        aviso = "Outras categorias:"
    salvar_estado(telefone, ESTADO, {"pagina": pagina})
    return lista_categorias(aviso, categorias, mais_usadas(account_id, user_id), pagina)


# ---------- nova categoria: nome por texto, tipo por botões ----------

def iniciar_nova(telefone: str, retorno: dict | None = None) -> str:
    """Pede o nome. retorno: gasto em andamento, que usa a categoria nova quando ela existir."""
    salvar_estado(telefone, ESTADO_NOVA, {"passo": "nome", "retorno": retorno})
    return "Qual o nome da nova categoria? (até 30 letras)"


def _tipo_digitado(texto: str) -> str | None:
    if chave(texto) == "reserva emergencia":
        return "Reserva de emergência"
    return achar_tipo(texto)


def continuar_nova(telefone: str, dados: dict, texto: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    passo = dados["passo"]

    if passo == "nome":
        nome = " ".join(texto.split())
        if not nome or len(nome) > 30:
            return "Mande só o nome, com até 30 letras."
        if any(chave(c.nome) == chave(nome) for c in listar_categorias(account_id)):
            return f"A categoria {nome} já existe. Mande outro nome."
        nome = nome[0].upper() + nome[1:]
        salvar_estado(telefone, ESTADO_NOVA, {**dados, "passo": "tipo", "nome": nome})
        return Resposta(f"Qual o tipo de {nome}?", BOTOES_TIPO)

    if passo == "tipo" and chave(texto).startswith("outro"):
        salvar_estado(telefone, ESTADO_NOVA, {**dados, "passo": "tipo2"})
        return Resposta(f"Qual o tipo de {dados['nome']}?", BOTOES_TIPO_2)
    tipo = _tipo_digitado(texto)
    if tipo is None:
        botoes = BOTOES_TIPO if passo == "tipo" else BOTOES_TIPO_2
        return Resposta(f"Não entendi. Qual o tipo de {dados['nome']}?", botoes)

    categoria_id = criar_categoria(account_id, user_id, dados["nome"], tipo)
    limpar_estado(telefone)
    resposta = f"Categoria {dados['nome']} ({tipo}) criada."
    if dados.get("retorno"):
        # import aqui dentro porque gasto.py também importa este arquivo
        from app.comandos.gasto import finalizar_registro, registrar

        categoria = Categoria(categoria_id, dados["nome"], tipo)
        resposta += "\n" + registrar(account_id, user_id, dados["retorno"], categoria)
        return finalizar_registro(telefone, account_id, user_id, dados["retorno"], categoria, resposta)
    return resposta
