"""Insere 3 meses de dados fictícios (mais o mês atual) para um número de WhatsApp.

Uso:  python scripts/dados_teste.py 5511999998888
Tudo que o script cria leva "[teste]" na descrição; scripts/apagar_dados_teste.py remove só isso.
"""
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app import financas  # noqa: E402
from app.comandos.cadastro import conta_do_usuario, garantir_usuario  # noqa: E402
from app.comandos.categorias import garantir_padrao, listar_categorias  # noqa: E402
from app.comandos.metas import ler_metas, ler_renda  # noqa: E402
from app.db import get_engine  # noqa: E402

MARCA = "[teste]"
SALARIO = Decimal("5000.00")
FIXOS = (("Aluguel", "Moradia", "1200.00"), ("Internet", "Moradia", "100.00"))
# (descrição, categoria, valor mínimo, valor máximo)
VARIAVEIS = (
    ("Supermercado", "Mercado", 40, 180),
    ("Uber", "Transporte", 12, 45),
    ("Ifood", "Restaurante", 25, 70),
    ("Cinema", "Lazer", 30, 80),
)
METAS = (("Fixo", 1800), ("Variável", 1500), ("Investimento", 500))


def meses_atras(dia: date, n: int) -> date:
    """Dia 1 do mês, n meses antes do mês de `dia`."""
    primeiro = dia.replace(day=1)
    for _ in range(n):
        primeiro = (primeiro - timedelta(days=1)).replace(day=1)
    return primeiro


def gerar(hoje: date, rng: random.Random) -> list[tuple]:
    """Lista de (data, tipo, descrição, categoria, valor)."""
    linhas = []
    for atras in (3, 2, 1, 0):
        inicio = meses_atras(hoje, atras)
        fim = min(financas.ultimo_dia_do_mes(inicio), hoje)
        dia = inicio
        while dia <= fim:
            if dia.day == 5:
                linhas.append((dia, "income", "Salário", None, SALARIO))
                for nome, categoria, valor in FIXOS:
                    linhas.append((dia, "expense", nome, categoria, Decimal(valor)))
            if rng.random() < 0.6:
                nome, categoria, minimo, maximo = rng.choice(VARIAVEIS)
                valor = Decimal(rng.randint(minimo * 100, maximo * 100)) / 100
                linhas.append((dia, "expense", nome, categoria, valor))
            dia += timedelta(days=1)
    return linhas


def main(telefone: str) -> None:
    garantir_usuario(telefone)
    user_id, account_id = conta_do_usuario(telefone)
    garantir_padrao(account_id)
    categorias = {c.nome: c.id for c in listar_categorias(account_id)}
    hoje = financas.hoje()
    linhas = gerar(hoje, random.Random(42))
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE users SET access_status = 'ativo' WHERE id = :u"), {"u": user_id}
        )
        for data, tipo, nome, categoria, valor in linhas:
            connection.execute(
                text(
                    "INSERT INTO transactions (account_id, created_by_user_id, category_id,"
                    " transaction_type, amount, description, transaction_date, scope, source)"
                    " VALUES (:conta, :usuario, :categoria, :tipo, :valor, :descricao,"
                    " :data, 'conjunto', 'manual')"
                ),
                {"conta": account_id, "usuario": user_id, "categoria": categorias.get(categoria),
                 "tipo": tipo, "valor": valor, "descricao": f"{MARCA} {nome}", "data": data},
            )
        # um fixo que ainda vai vencer neste mês (para a previsão ter o que somar)
        vence = hoje + timedelta(days=3)
        if vence.month == hoje.month:
            connection.execute(
                text(
                    "INSERT INTO recurring_transactions (account_id, created_by_user_id, category_id,"
                    " payee, amount, frequency, next_due_date, scope)"
                    " VALUES (:conta, :usuario, :categoria, :nome, 150, 'monthly', :vence, 'conjunto')"
                ),
                {"conta": account_id, "usuario": user_id, "categoria": categorias.get("Moradia"),
                 "nome": f"{MARCA} Condomínio", "vence": vence},
            )
        # renda e metas só se a conta ainda não tem (não mexe no que você configurou)
        if ler_renda(account_id, user_id) is None:
            connection.execute(
                text("UPDATE members SET expected_income = :r WHERE account_id = :c AND user_id = :u"),
                {"r": SALARIO, "c": account_id, "u": user_id},
            )
        if not ler_metas(account_id):
            for tipo, valor in METAS:
                connection.execute(
                    text("INSERT INTO goals (account_id, type, value_type, value)"
                         " VALUES (:c, :t, 'amount', :v)"),
                    {"c": account_id, "t": tipo, "v": valor},
                )
    print(f"Pronto: {len(linhas)} lançamentos de teste para {telefone}. Teste /resumo, /previsao e /grafico previsao.")
    print("Para apagar: python scripts/apagar_dados_teste.py", telefone)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Use: python scripts/dados_teste.py NUMERO   (ex.: 5511999998888)")
    main(sys.argv[1])
