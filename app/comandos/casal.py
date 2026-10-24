"""Modo casal: /casal gera um código, /entrar CÓDIGO coloca o parceiro na mesma conta."""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import normalizar
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "casal"
BOTOES = ("Tudo junto", "Com gastos pessoais")
LETRAS_DO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I, que se confundem
TAMANHO_DO_CODIGO = 6
VALIDADE_DO_CODIGO = timedelta(hours=48)
MEMBROS_NO_CASAL = 2
SEM_NOME = "seu parceiro(a)"

PERGUNTA_PRIVACIDADE = (
    "Uma pergunta, só esta vez: como vocês querem registrar os gastos?\n"
    "• Tudo junto (padrão): tudo é do casal. Para esconder um gasto, escreva \"meu\" no fim.\n"
    "• Com gastos pessoais: eu pergunto [Meu] [Conjunto] a cada gasto."
)
MSG_JUNTO = (
    "Combinado: tudo junto. Para um gasto só seu, escreva \"meu\" no fim "
    "(ex.: /gasto 30 padaria meu). A renda de vocês dois é visível para os dois."
)
MSG_PESSOAL = (
    "Combinado: com gastos pessoais. A cada gasto eu pergunto se é seu ou do casal. "
    "Gasto \"meu\": só você vê os detalhes; seu parceiro vê só o total. "
    "A renda de vocês dois é visível para os dois."
)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _gerar_codigo() -> str:
    return "".join(secrets.choice(LETRAS_DO_CODIGO) for _ in range(TAMANHO_DO_CODIGO))


def ler_codigo(argumentos: str) -> str:
    """"abc-123" -> "ABC123" (aceita maiúsculas, minúsculas, espaço e traço)."""
    return "".join(c for c in argumentos.upper() if c.isalnum())


def _membros(account_id) -> list:
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT m.user_id, m.role, u.display_name FROM members m"
                " JOIN users u ON u.id = m.user_id WHERE m.account_id = :conta"
                " ORDER BY m.joined_at"
            ),
            {"conta": account_id},
        ).all()


def _modo_de_privacidade(account_id) -> str:
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT privacy_mode FROM accounts WHERE id = :conta"), {"conta": account_id}
        ).scalar_one()


def deve_perguntar_escopo(account_id) -> bool:
    """True só no casal que escolheu "com gastos pessoais": aí cada gasto pergunta [Meu] [Conjunto]."""
    with get_engine().connect() as connection:
        linha = connection.execute(
            text("SELECT mode, privacy_mode FROM accounts WHERE id = :conta"), {"conta": account_id}
        ).first()
    return linha is not None and linha.mode == "couple" and linha.privacy_mode == "pessoal"


# ---------- /casal ----------

def _gravar_codigo(account_id) -> str:
    """Guarda um código novo na conta (troca o anterior). Tenta de novo se o código já existir."""
    for _ in range(10):
        codigo = _gerar_codigo()
        try:
            with get_engine().begin() as connection:
                connection.execute(
                    text(
                        "UPDATE accounts SET invitation_code = :codigo,"
                        " invitation_expires_at = :validade WHERE id = :conta"
                    ),
                    {"codigo": codigo, "validade": _agora() + VALIDADE_DO_CODIGO, "conta": account_id},
                )
            return codigo
        except IntegrityError:
            continue  # raríssimo: outro casal já usa esse código
    raise RuntimeError("Não consegui gerar um código de convite único.")


def comando_casal(telefone: str, argumentos: str) -> str:
    user_id, account_id = conta_do_usuario(telefone)
    membros = _membros(account_id)
    if len(membros) >= MEMBROS_NO_CASAL:
        parceiro = next((m for m in membros if str(m.user_id) != str(user_id)), None)
        nome = (parceiro.display_name if parceiro else None) or SEM_NOME
        como = "com gastos pessoais" if _modo_de_privacidade(account_id) == "pessoal" else "tudo junto"
        return f"Você já está em casal com {nome} ({como}). Mande /resumo para ver o mês de vocês."
    codigo = _gravar_codigo(account_id)
    return (
        f"Seu código do casal: {codigo}\n"
        f"Peça para seu parceiro(a) me mandar: /entrar {codigo}\n"
        "Vale por 48 horas e só entra uma pessoa."
    )


# ---------- /entrar ----------

def _entrar_na_conta(user_id, codigo: str) -> tuple[object, object] | None:
    """Usa o código: coloca o usuário na conta do casal. Devolve (conta, dono) ou None.

    Tudo numa transação só; o UPDATE com condição faz o código valer para uma pessoa só,
    mesmo que dois parceiros tentem ao mesmo tempo.
    """
    with get_engine().begin() as connection:
        linha = connection.execute(
            text(
                "UPDATE accounts SET mode = 'couple', invitation_code = NULL,"
                " invitation_expires_at = NULL"
                " WHERE invitation_code = :codigo AND invitation_expires_at > :agora"
                " AND (SELECT count(*) FROM members WHERE account_id = accounts.id) < :maximo"
                " RETURNING id, owner_user_id"
            ),
            {"codigo": codigo, "agora": _agora(), "maximo": MEMBROS_NO_CASAL},
        ).first()
        if linha is None:
            return None
        connection.execute(
            # A renda que a pessoa já informou na conta anterior vem junto para o casal.
            text(
                "INSERT INTO members (account_id, user_id, role, expected_income)"
                " SELECT :conta, :usuario, 'partner', (SELECT expected_income FROM members"
                " WHERE user_id = :usuario ORDER BY joined_at DESC LIMIT 1)"
            ),
            {"conta": linha.id, "usuario": user_id},
        )
        connection.execute(
            # E a renda esperada por mês também.
            text(
                "INSERT INTO income_plans (account_id, user_id, month, amount)"
                " SELECT :conta, user_id, month, MAX(amount) FROM income_plans"
                " WHERE user_id = :usuario AND account_id <> :conta GROUP BY user_id, month"
            ),
            {"conta": linha.id, "usuario": user_id},
        )
    return linha.id, linha.owner_user_id


def _dono_do_codigo(codigo: str):
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT id FROM accounts WHERE invitation_code = :codigo"), {"codigo": codigo}
        ).scalar()


def _nome_do_usuario(user_id) -> str:
    with get_engine().connect() as connection:
        nome = connection.execute(
            text("SELECT display_name FROM users WHERE id = :usuario"), {"usuario": user_id}
        ).scalar()
    return nome or SEM_NOME


def comando_entrar(telefone: str, argumentos: str) -> str | Resposta:
    codigo = ler_codigo(argumentos)
    if not codigo:
        return "Use: /entrar CÓDIGO (o código que seu parceiro(a) recebeu no /casal)."
    user_id, account_id = conta_do_usuario(telefone)
    if len(_membros(account_id)) >= MEMBROS_NO_CASAL:
        return "Você já está em um casal. Mande /casal para ver."
    if str(_dono_do_codigo(codigo)) == str(account_id):
        return "Esse código é da sua própria conta. Passe ele para seu parceiro(a)."
    entrou = _entrar_na_conta(user_id, codigo)
    if entrou is None:
        return "Código inválido, vencido ou o casal já está completo. Peça outro com /casal."
    _, dono = entrou
    salvar_estado(telefone, ESTADO, {"passo": "privacidade"})
    return Resposta(
        f"Pronto, você entrou no casal de {_nome_do_usuario(dono)}!\n{PERGUNTA_PRIVACIDADE}", BOTOES
    )


def ler_escolha(texto: str) -> str | None:
    """"Tudo junto" -> "junto"; "Com gastos pessoais" -> "pessoal"; outra coisa -> None."""
    escolha = normalizar(texto).strip(" .!")
    if escolha in ("tudo junto", "junto", "1"):
        return "junto"
    if escolha in ("com gastos pessoais", "gastos pessoais", "pessoais", "pessoal", "2"):
        return "pessoal"
    return None


def continuar_casal(telefone: str, dados: dict, texto: str) -> str | Resposta:
    """Resposta da pergunta única sobre privacidade, feita logo depois do /entrar."""
    escolha = ler_escolha(texto)
    if escolha is None:
        return Resposta("Toque em um dos botões.\n" + PERGUNTA_PRIVACIDADE, BOTOES)
    _, account_id = conta_do_usuario(telefone)
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE accounts SET privacy_mode = :modo WHERE id = :conta"),
            {"modo": escolha, "conta": account_id},
        )
    limpar_estado(telefone)
    return MSG_JUNTO if escolha == "junto" else MSG_PESSOAL


def conta_em_casal(account_id) -> bool:
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT mode FROM accounts WHERE id = :conta"), {"conta": account_id}
        ).scalar() == "couple"
