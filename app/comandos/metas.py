from decimal import Decimal

from sqlalchemy import Connection, text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.formato import formatar_pct, formatar_reais, ler_numero, normalizar
from app.db import get_engine

TIPOS = ("Fixo", "Variável", "Assinatura", "Investimento", "Reserva de emergência")

# Atalho "usar 50/30/20": 50% necessidades, 30% desejos, 20% poupança.
PADRAO_50_30_20 = {
    "Fixo": Decimal("50"),
    "Variável": Decimal("25"),
    "Assinatura": Decimal("5"),
    "Investimento": Decimal("10"),
    "Reserva de emergência": Decimal("10"),
}

# Metas: tipo -> (value_type, valor), com value_type "amount" (R$) ou "percentage" (%).
Metas = dict[str, tuple[str, Decimal]]

AJUDA_METAS = (
    "Para alterar: /metas TIPO VALOR\n"
    "Ex.: /metas variavel 1200 ou /metas variavel 30%\n"
    "Use 0 para tirar a meta. /metas 50/30/20 aplica o atalho."
)


def achar_tipo(texto: str) -> str | None:
    """"variavel", "fixos", "reserva de emergencia" -> nome oficial do tipo."""
    palavras = normalizar(texto).split()
    if not palavras or len(palavras[0]) < 3:
        return None
    for tipo in TIPOS:
        chave = normalizar(tipo).split()[0]
        if palavras[0].startswith(chave) or chave.startswith(palavras[0]):
            return tipo
    return None


def soma_pct(metas: Metas, exceto: str | None = None) -> Decimal:
    return sum(
        (valor for tipo, (formato, valor) in metas.items()
         if formato == "percentage" and tipo != exceto),
        Decimal("0"),
    )


def em_reais(formato: str, valor: Decimal, renda: Decimal | None) -> Decimal | None:
    if formato == "amount":
        return valor
    if renda is None:
        return None
    return (renda * valor / 100).quantize(Decimal("0.01"))


def linhas_metas(metas: Metas, renda: Decimal | None) -> str:
    """Uma linha por tipo, na ordem dos TIPOS. % mostra também o valor em R$."""
    linhas = []
    for tipo in TIPOS:
        if tipo not in metas:
            continue
        formato, valor = metas[tipo]
        if formato == "amount":
            linhas.append(f"{tipo}: {formatar_reais(valor)}")
            continue
        reais = em_reais(formato, valor, renda)
        extra = f" ({formatar_reais(reais)})" if reais is not None else ""
        linhas.append(f"{tipo}: {formatar_pct(valor)}{extra}")
    return "\n".join(linhas) if linhas else "Nenhuma meta definida."


def aviso_acima_da_renda(metas: Metas, renda: Decimal | None) -> str:
    """Aviso firme se as metas somam mais que a renda (vazio se está tudo certo)."""
    if renda is None:
        return ""
    total = sum(
        (em_reais(formato, valor, renda) for formato, valor in metas.values()),
        Decimal("0"),
    )
    if total <= renda:
        return ""
    return (
        f"Atenção: as metas somam {formatar_reais(total)}, "
        f"acima da renda de {formatar_reais(renda)}."
    )


def validar_meta(metas: Metas, tipo: str, formato: str, valor: Decimal) -> str | None:
    """Devolve a mensagem de erro, ou None se a meta pode ser gravada."""
    if formato == "percentage":
        livre = Decimal("100") - soma_pct(metas, exceto=tipo)
        if valor > livre:
            return (
                f"Assim as metas em % passam de 100%. "
                f"Para {tipo} você pode usar até {formatar_pct(livre)}."
            )
    return None


# ---------- banco de dados ----------

def ler_metas(account_id) -> Metas:
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT type, value_type, value FROM goals"
                " WHERE account_id = :conta AND member_user_id IS NULL"
            ),
            {"conta": account_id},
        ).all()
    return {linha.type: (linha.value_type, linha.value) for linha in linhas}


def ler_renda(account_id, user_id) -> Decimal | None:
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT expected_income FROM members"
                " WHERE account_id = :conta AND user_id = :usuario"
            ),
            {"conta": account_id, "usuario": user_id},
        ).scalar()


def gravar_meta(connection: Connection, account_id, tipo: str, formato: str, valor: Decimal) -> None:
    """Cria ou altera a meta do tipo. Valor 0 apaga a meta."""
    if valor == 0:
        connection.execute(
            text(
                "DELETE FROM goals WHERE account_id = :conta"
                " AND member_user_id IS NULL AND type = :tipo"
            ),
            {"conta": account_id, "tipo": tipo},
        )
        return
    connection.execute(
        text(
            "INSERT INTO goals (account_id, type, value_type, value)"
            " VALUES (:conta, :tipo, :formato, :valor)"
            " ON CONFLICT (account_id, type) WHERE member_user_id IS NULL"
            " DO UPDATE SET value_type = EXCLUDED.value_type,"
            " value = EXCLUDED.value, updated_at = now()"
        ),
        {"conta": account_id, "tipo": tipo, "formato": formato, "valor": valor},
    )


def substituir_metas(connection: Connection, account_id, metas: Metas) -> None:
    """Apaga as metas da conta e grava as novas."""
    connection.execute(
        text("DELETE FROM goals WHERE account_id = :conta AND member_user_id IS NULL"),
        {"conta": account_id},
    )
    for tipo, (formato, valor) in metas.items():
        gravar_meta(connection, account_id, tipo, formato, valor)


# ---------- comando /metas ----------

def _mostrar(metas: Metas, renda: Decimal | None) -> str:
    if not metas and renda is None:
        return "Você ainda não tem metas. Mande /inicio para configurar."
    cabecalho = f"Suas metas (renda {formatar_reais(renda)}):" if renda else "Suas metas:"
    partes = [cabecalho, linhas_metas(metas, renda)]
    aviso = aviso_acima_da_renda(metas, renda)
    if aviso:
        partes.append(aviso)
    partes.append(AJUDA_METAS)
    return "\n".join(partes)


def comando_metas(telefone: str, argumentos: str) -> str:
    user_id, account_id = conta_do_usuario(telefone)
    metas = ler_metas(account_id)
    renda = ler_renda(account_id, user_id)
    pedido = argumentos.strip()
    if not pedido:
        return _mostrar(metas, renda)

    if pedido.replace(" ", "") in ("50/30/20", "503020"):
        novas = {tipo: ("percentage", pct) for tipo, pct in PADRAO_50_30_20.items()}
        with get_engine().begin() as connection:
            substituir_metas(connection, account_id, novas)
        return "Pronto, apliquei o 50/30/20:\n" + linhas_metas(novas, renda)

    formato = "percentage" if pedido.endswith("%") else "amount"
    partes = pedido.rstrip("%").strip().rsplit(maxsplit=1)
    tipo = achar_tipo(partes[0]) if len(partes) == 2 else None
    valor = ler_numero(partes[1]) if len(partes) == 2 else None
    if tipo is None or valor is None:
        return "Não entendi.\n" + AJUDA_METAS
    erro = validar_meta(metas, tipo, formato, valor)
    if erro:
        return erro
    with get_engine().begin() as connection:
        gravar_meta(connection, account_id, tipo, formato, valor)
    if valor == 0:
        return f"Meta de {tipo} removida."
    metas[tipo] = (formato, valor)
    resposta = f"Meta de {tipo} atualizada:\n" + linhas_metas({tipo: metas[tipo]}, renda)
    aviso = aviso_acima_da_renda(metas, renda)
    return f"{resposta}\n{aviso}" if aviso else resposta
