from decimal import Decimal

from sqlalchemy import Connection, text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.casal import conta_em_casal
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
AJUDA_METAS_CASAL = (
    "Terminando com \"meu\", a meta é só sua; sem isso, é do casal.\n"
    "Ex.: /metas variavel 600 meu"
)
SUFIXOS_MEU = ("meu", "minha")
SUFIXOS_CASAL = ("casal", "conjunto", "conjunta")


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

def _dono_da_meta(user_id) -> str:
    """Metas do casal não têm dono (NULL); as individuais têm o id do usuário."""
    return "member_user_id IS NULL" if user_id is None else "member_user_id = :usuario"


def ler_metas(account_id, user_id=None) -> Metas:
    """Metas do casal/da conta (user_id=None) ou as individuais desse usuário."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT type, value_type, value FROM goals"
                f" WHERE account_id = :conta AND {_dono_da_meta(user_id)}"
            ),
            {"conta": account_id, "usuario": user_id},
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


def ler_renda_conjunta(account_id) -> Decimal | None:
    """Renda de todos da conta somada (no casal, as metas do casal usam as duas rendas)."""
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT SUM(expected_income) FROM members WHERE account_id = :conta"),
            {"conta": account_id},
        ).scalar()


def ler_rendas(account_id, user_id) -> list[tuple[str, Decimal | None]]:
    """(nome, renda) de cada um da conta, com "Você" no lugar do próprio nome.
    A renda de cada um é visível ao parceiro."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT m.user_id, u.display_name, m.expected_income FROM members m"
                " JOIN users u ON u.id = m.user_id WHERE m.account_id = :conta"
                " ORDER BY m.joined_at"
            ),
            {"conta": account_id},
        ).all()
    return [
        ("Você" if str(l.user_id) == str(user_id) else l.display_name or "Parceiro(a)", l.expected_income)
        for l in linhas
    ]


def gravar_meta(
    connection: Connection, account_id, tipo: str, formato: str, valor: Decimal, user_id=None
) -> None:
    """Cria ou altera a meta do tipo. Valor 0 apaga a meta. user_id: meta individual."""
    parametros = {"conta": account_id, "tipo": tipo, "formato": formato, "valor": valor,
                  "usuario": user_id}
    if valor == 0:
        connection.execute(
            text(
                f"DELETE FROM goals WHERE account_id = :conta AND {_dono_da_meta(user_id)}"
                " AND type = :tipo"
            ),
            parametros,
        )
        return
    if user_id is None:
        colunas, valores = "", ""
        alvo = "(account_id, type) WHERE member_user_id IS NULL"
    else:
        colunas, valores = ", member_user_id", ", :usuario"
        alvo = "(account_id, member_user_id, type) WHERE member_user_id IS NOT NULL"
    connection.execute(
        text(
            f"INSERT INTO goals (account_id, type, value_type, value{colunas})"
            f" VALUES (:conta, :tipo, :formato, :valor{valores})"
            f" ON CONFLICT {alvo}"
            " DO UPDATE SET value_type = EXCLUDED.value_type,"
            " value = EXCLUDED.value, updated_at = now()"
        ),
        parametros,
    )


def substituir_metas(connection: Connection, account_id, metas: Metas, user_id=None) -> None:
    """Apaga as metas (da conta, ou só as individuais do usuário) e grava as novas."""
    connection.execute(
        text(f"DELETE FROM goals WHERE account_id = :conta AND {_dono_da_meta(user_id)}"),
        {"conta": account_id, "usuario": user_id},
    )
    for tipo, (formato, valor) in metas.items():
        gravar_meta(connection, account_id, tipo, formato, valor, user_id)


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


def _mostrar_casal(
    conjuntas: Metas, minhas: Metas, rendas: list[tuple[str, Decimal | None]]
) -> str:
    """No casal: a renda de cada um (visível aos dois), as metas do casal e as metas só suas."""
    renda_junta = sum((r for _, r in rendas if r is not None), Decimal("0")) or None
    renda_propria = next((r for nome, r in rendas if nome == "Você"), None)
    por_pessoa = " · ".join(
        f"{nome} {formatar_reais(renda) if renda is not None else 'sem renda'}" for nome, renda in rendas
    )
    partes = [f"Renda: {por_pessoa}"]
    partes.append("Metas do casal:" + (f" (renda junta {formatar_reais(renda_junta)})" if renda_junta else ""))
    partes.append(linhas_metas(conjuntas, renda_junta))
    aviso = aviso_acima_da_renda(conjuntas, renda_junta)
    if aviso:
        partes.append(aviso)
    partes += ["Suas metas (só suas):", linhas_metas(minhas, renda_propria)]
    aviso = aviso_acima_da_renda(minhas, renda_propria)
    if aviso:
        partes.append(aviso)
    partes += [AJUDA_METAS, AJUDA_METAS_CASAL]
    return "\n".join(partes)


def _separar_dono(pedido: str) -> tuple[str, bool]:
    """"variavel 600 meu" -> ("variavel 600", True). "casal" no fim é o mesmo que nada."""
    palavras = pedido.split()
    if len(palavras) >= 2 and normalizar(palavras[-1]) in SUFIXOS_MEU:
        return " ".join(palavras[:-1]), True
    if len(palavras) >= 2 and normalizar(palavras[-1]) in SUFIXOS_CASAL:
        return " ".join(palavras[:-1]), False
    return pedido, False


def comando_metas(telefone: str, argumentos: str) -> str:
    user_id, account_id = conta_do_usuario(telefone)
    casal = conta_em_casal(account_id)
    pedido, individual = _separar_dono(argumentos.strip())
    individual = individual and casal  # meta "só sua" só existe no casal
    dono = user_id if individual else None  # None = meta da conta (do casal)
    if not pedido and casal:
        return _mostrar_casal(
            ler_metas(account_id), ler_metas(account_id, user_id), ler_rendas(account_id, user_id)
        )
    if casal and not individual:
        renda = ler_renda_conjunta(account_id)  # metas do casal usam as duas rendas
    else:
        renda = ler_renda(account_id, user_id)
    metas = ler_metas(account_id, dono)
    if not pedido:
        return _mostrar(metas, renda)

    if pedido.replace(" ", "") in ("50/30/20", "503020"):
        novas = {tipo: ("percentage", pct) for tipo, pct in PADRAO_50_30_20.items()}
        with get_engine().begin() as connection:
            substituir_metas(connection, account_id, novas, dono)
        return "Pronto, apliquei o 50/30/20:\n" + linhas_metas(novas, renda)

    formato = "percentage" if pedido.endswith("%") else "amount"
    partes = pedido.rstrip("%").strip().rsplit(maxsplit=1)
    tipo = achar_tipo(partes[0]) if len(partes) == 2 else None
    valor = ler_numero(partes[1]) if len(partes) == 2 else None
    if tipo is None or valor is None:
        return "Não entendi.\n" + (AJUDA_METAS + "\n" + AJUDA_METAS_CASAL if casal else AJUDA_METAS)
    erro = validar_meta(metas, tipo, formato, valor)
    if erro:
        return erro
    with get_engine().begin() as connection:
        gravar_meta(connection, account_id, tipo, formato, valor, dono)
    de_quem = " (só sua)" if individual else ""
    if valor == 0:
        return f"Meta de {tipo}{de_quem} removida."
    metas[tipo] = (formato, valor)
    resposta = f"Meta de {tipo}{de_quem} atualizada:\n" + linhas_metas({tipo: metas[tipo]}, renda)
    aviso = aviso_acima_da_renda(metas, renda)
    return f"{resposta}\n{aviso}" if aviso else resposta
