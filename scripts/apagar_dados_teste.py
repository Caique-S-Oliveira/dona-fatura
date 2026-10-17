"""Apaga os dados criados por scripts/dados_teste.py (tudo marcado com "[teste]").

Uso:  python scripts/apagar_dados_teste.py 5511999998888
Não mexe em lançamentos reais, renda, metas nem no cadastro do número.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.comandos.cadastro import conta_do_usuario  # noqa: E402
from app.db import get_engine  # noqa: E402


def main(telefone: str) -> None:
    _, account_id = conta_do_usuario(telefone)
    with get_engine().begin() as connection:
        transacoes = connection.execute(
            text("DELETE FROM transactions WHERE account_id = :c AND starts_with(description, '[teste]')"),
            {"c": account_id},
        ).rowcount
        fixos = connection.execute(
            text("DELETE FROM recurring_transactions WHERE account_id = :c AND starts_with(payee, '[teste]')"),
            {"c": account_id},
        ).rowcount
    print(f"Apagados: {transacoes} lançamentos e {fixos} fixos de teste de {telefone}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Use: python scripts/apagar_dados_teste.py NUMERO")
    main(sys.argv[1])
