"""Etapa 18: /pagar (e /parcelas pagar). Usa um banco SQLite em memória (nunca o banco real)."""
import sqlite3
import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import StaticPool, create_engine, text

from app import financas
from app.comandos import desfazer, pagar, parcelas
from app.comandos.categorias import Categoria
from app.comandos.resposta import Resposta

D = Decimal
HOJE = date(2026, 10, 16)
TEL, USUARIO, CONTA = "5511988887777", "user-1", "conta-1"
CATEGORIA = Categoria("cat-parcelas", "Parcelas/dívidas", "Fixo")

SCHEMA = """
CREATE TABLE installments (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL, created_by_user_id TEXT NOT NULL,
    description TEXT NOT NULL, installment_amount NUMERIC NOT NULL, total_installments INTEGER NOT NULL,
    first_due_date DATE NOT NULL, due_day INTEGER NOT NULL, scope TEXT NOT NULL,
    paid_installments INTEGER, last_payment_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE transactions (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL, created_by_user_id TEXT NOT NULL, category_id TEXT,
    transaction_type TEXT NOT NULL, amount NUMERIC NOT NULL, description TEXT, payee TEXT,
    transaction_date DATE NOT NULL, scope TEXT NOT NULL, voided_at TEXT, source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE recurring_transactions (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL, amount NUMERIC, frequency TEXT,
    next_due_date DATE, is_active INTEGER NOT NULL DEFAULT 1);
"""

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, str)
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()))
sqlite3.register_converter("NUMERIC", lambda b: Decimal(b.decode()))


class BancoDePagar(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False, "detect_types": sqlite3.PARSE_DECLTYPES},
        )
        with self.motor.begin() as conexao:
            for comando in SCHEMA.split(";\n"):
                if comando.strip():
                    conexao.exec_driver_sql(comando)
        self.addCleanup(self.motor.dispose)
        self.estados: dict[str, tuple[str, dict]] = {}
        for alvo, novo in [
            ("app.comandos.pagar.get_engine", lambda: self.motor),
            ("app.comandos.parcelas.get_engine", lambda: self.motor),
            ("app.comandos.desfazer.get_engine", lambda: self.motor),
            ("app.financas.get_engine", lambda: self.motor),
            ("app.comandos.pagar.conta_do_usuario", lambda tel: (USUARIO, CONTA)),
            ("app.comandos.parcelas.conta_do_usuario", lambda tel: (USUARIO, CONTA)),
            ("app.comandos.desfazer.conta_do_usuario", lambda tel: (USUARIO, CONTA)),
            ("app.comandos.pagar.listar_categorias", lambda conta: [CATEGORIA]),
            ("app.comandos.pagar.salvar_estado", lambda tel, estado, dados: self.estados.update({tel: (estado, dados)})),
            ("app.comandos.pagar.limpar_estado", lambda tel: self.estados.pop(tel, None)),
            ("app.comandos.desfazer.limpar_estado", lambda tel: self.estados.pop(tel, None)),
            ("app.financas.hoje", lambda: HOJE),
        ]:
            patcher = patch(alvo, novo)
            patcher.start()
            self.addCleanup(patcher.stop)

    # ---------- ajudantes ----------

    def sql(self, comando, **parametros):
        with self.motor.begin() as conexao:
            return conexao.execute(text(comando), parametros)

    def criar(self, nome, valor, total, primeiro, dia, pagas=None, escopo="conjunto"):
        id_ = str(uuid.uuid4())
        self.sql(
            "INSERT INTO installments (id, account_id, created_by_user_id, description, installment_amount,"
            " total_installments, first_due_date, due_day, scope, paid_installments)"
            " VALUES (:i, :c, :u, :n, :v, :t, :p, :d, :e, :g)",
            i=id_, c=CONTA, u=USUARIO, n=nome, v=valor, t=total, p=primeiro, d=dia, e=escopo, g=pagas,
        )
        return id_

    def carro(self, **extra):
        """1.200,00 x 48, vence dia 20; pela data já passaram 5 (mai-set): a próxima é a 6/48, em 20/10."""
        return self.criar("Carro", D("1200"), 48, date(2026, 5, 20), 20, **extra)

    def pagar(self, nome="carro"):
        """Pede o pagamento e responde Sim. Devolve a resposta final."""
        pergunta = pagar.comando_pagar(TEL, nome)
        self.assertIsInstance(pergunta, Resposta, pergunta)
        return pagar.continuar_pagar(TEL, self.estados[TEL][1], "Sim")

    def parcela(self, nome="Carro"):
        return next(p for p in parcelas.listar_parcelas(CONTA, USUARIO) if p.nome == nome)

    def saidas(self):
        return self.sql("SELECT id, amount, category_id, scope, source, description FROM transactions").all()

    def linha(self, nome="Carro"):
        return self.sql("SELECT paid_installments, last_payment_id FROM installments WHERE description = :n",
                        n=nome).one()


# ---------- pagar ----------

class TestPagar(BancoDePagar):
    def test_pagar_parcela_pede_confirmacao_e_so_salva_no_sim(self):
        self.carro(escopo="meu")
        pergunta = pagar.comando_pagar(TEL, "carro")
        self.assertEqual(pergunta.texto, "Carro, parcela 6/48, R$ 1.200,00. Confirmar?")
        self.assertEqual(pergunta.botoes, ("Sim", "Cancelar"))
        self.assertEqual(self.saidas(), [])  # nada salvo antes do Sim
        self.assertIsNone(self.linha().paid_installments)

        resposta = pagar.continuar_pagar(TEL, self.estados[TEL][1], "Sim")
        self.assertIn("Anotado: Carro, parcela 6/48, R$ 1.200,00 em Parcelas/dívidas", resposta)
        (saida,) = self.saidas()
        self.assertEqual(
            (saida.amount, saida.category_id, saida.scope, saida.source),
            (D("1200"), "cat-parcelas", "meu", "manual"),  # escopo da parcela
        )
        self.assertEqual(self.linha().paid_installments, 6)
        self.assertNotIn(TEL, self.estados)

    def test_cancelar_nao_salva(self):
        self.carro()
        pagar.comando_pagar(TEL, "carro")
        self.assertIn("não registrei", pagar.continuar_pagar(TEL, self.estados[TEL][1], "Cancelar"))
        self.assertEqual(self.saidas(), [])
        self.assertIsNone(self.linha().paid_installments)

    def test_pagar_antes_do_vencimento(self):
        self.carro()
        # hoje é 16/10 e a parcela vence em 20/10: pela data ainda seria a 5ª paga
        self.assertEqual(self.parcela().pagas(HOJE), 5)
        self.pagar()
        depois = self.parcela()
        self.assertEqual(depois.pagas(HOJE), 6)  # conta a paga de fato, mesmo antes do dia 20
        self.assertEqual(depois.proximo_vencimento(HOJE), date(2026, 11, 20))
        self.assertFalse(depois.pendente_no_mes(HOJE))

    def test_nao_paga_duas_vezes(self):
        self.carro()
        self.pagar()
        self.assertIn("já está paga", pagar.comando_pagar(TEL, "carro"))  # pedir de novo
        # confirmação antiga tocada de novo (ex.: mensagem repetida): também não registra
        antiga = {"etapa": "confirmar", "id": self.parcela().id, "esperado": 5}
        self.assertIn("já está paga", pagar.continuar_pagar(TEL, antiga, "Sim"))
        self.assertIsNone(pagar.registrar_pagamento(CONTA, USUARIO, self.parcela().id, 5, HOJE))
        self.assertEqual(len(self.saidas()), 1)
        self.assertEqual(self.linha().paid_installments, 6)

    def test_pagar_a_ultima_avisa_que_quitou(self):
        # TV: 3x de 100, venceram 20/08 e 20/09 (parcela antiga, sem a coluna): falta a 3/3, em 20/10
        self.criar("TV", D("100"), 3, date(2026, 8, 20), 20)
        resposta = self.pagar("tv")
        self.assertIn("parcela 3/3", resposta)
        self.assertIn("quitada", resposta)
        self.assertEqual(self.linha("TV").paid_installments, 3)
        self.assertIn("já está quitada", pagar.comando_pagar(TEL, "tv"))
        self.assertEqual(len(self.saidas()), 1)

    def test_desfazer_reverte_a_marcacao_da_parcela(self):
        self.carro()
        self.pagar()
        (saida,) = self.saidas()
        self.assertEqual(self.linha().last_payment_id, saida.id)

        resposta = desfazer.continuar_desfazer(TEL, {"id": saida.id, "descricao": "Carro"}, "Sim")
        self.assertIn("voltou a ficar em aberto", resposta)
        self.assertEqual(self.saidas(), [])  # a saída foi apagada
        self.assertEqual(tuple(self.linha()), (5, None))  # contagem de pagas voltou
        self.assertTrue(self.parcela().pendente_no_mes(HOJE))
        self.assertIn("parcela 6/48", self.pagar())  # e dá para pagar de novo

    def test_desfazer_de_gasto_comum_nao_mexe_nas_parcelas(self):
        self.carro(pagas=6)
        self.sql("INSERT INTO transactions (id, account_id, created_by_user_id, transaction_type, amount,"
                 " description, transaction_date, scope, source)"
                 " VALUES ('t1', :c, :u, 'expense', 45, 'mercado', :d, 'conjunto', 'manual')",
                 c=CONTA, u=USUARIO, d=HOJE)
        resposta = desfazer.continuar_desfazer(TEL, {"id": "t1", "descricao": "mercado"}, "Sim")
        self.assertNotIn("parcela", resposta)
        self.assertEqual(self.linha().paid_installments, 6)

    def test_previsao_nao_conta_a_parcela_duas_vezes(self):
        self.carro()
        saidas_antes = D(str(self.sql("SELECT COALESCE(SUM(amount), 0) FROM transactions").scalar()))
        a_vencer_antes = financas.a_vencer_no_mes(CONTA, HOJE)
        self.assertEqual((saidas_antes, a_vencer_antes), (D("0"), D("1200")))  # vence 20/10

        self.pagar()
        saidas_depois = D(str(self.sql("SELECT COALESCE(SUM(amount), 0) FROM transactions").scalar()))
        a_vencer_depois = financas.a_vencer_no_mes(CONTA, HOJE)
        self.assertEqual((saidas_depois, a_vencer_depois), (D("1200"), D("0")))  # saiu de "a vencer"
        previsao = financas.calcular_previsao(D("0"), saidas_depois, a_vencer_depois, D("0"), 15)
        self.assertEqual(previsao.saidas_previstas, D("1200"))  # e não 2.400


# ---------- escolher a parcela ----------

class TestEscolher(BancoDePagar):
    def test_ate_3_parcelas_usa_botoes(self):
        self.carro()
        self.criar("Geladeira", D("250"), 10, date(2026, 8, 25), 25)  # a 3/10 vence 25/10
        self.criar("TV", D("100"), 5, date(2026, 8, 5), 5, pagas=2)  # a 3/5 venceu 05/10: atrasada, ainda conta
        self.criar("Sofá", D("90"), 4, date(2026, 11, 10), 10)  # só vence em novembro: fica de fora
        resposta = pagar.comando_pagar(TEL, "")
        self.assertEqual(resposta.botoes, ("TV", "Carro", "Geladeira"))  # do vencimento mais próximo
        self.assertEqual(resposta.lista, ())
        resposta = pagar.continuar_pagar(TEL, self.estados[TEL][1], "Geladeira")
        self.assertEqual(resposta.texto, "Geladeira, parcela 3/10, R$ 250,00. Confirmar?")

    def test_mais_de_3_parcelas_usa_lista(self):
        for n in range(4):
            self.criar(f"Compra {n}", D("10"), 5, date(2026, 8, 20), 20)
        resposta = pagar.comando_pagar(TEL, "")
        self.assertEqual(resposta.botoes, ())
        self.assertEqual(len(resposta.lista), 4)
        linha_id, titulo, descricao = resposta.lista[0]
        self.assertTrue(linha_id.startswith("pag:"))
        self.assertIn("3/5 de R$ 10,00", descricao)
        confirmar = pagar.continuar_pagar(TEL, self.estados[TEL][1], linha_id)  # toque na linha
        self.assertEqual(confirmar.botoes, ("Sim", "Cancelar"))

    def test_lista_tem_no_maximo_10_e_avisa(self):
        for n in range(12):
            self.criar(f"Compra {n:02d}", D("10"), 5, date(2026, 8, 20), 20)
        resposta = pagar.comando_pagar(TEL, "")
        self.assertEqual(len(resposta.lista), 10)
        self.assertIn("10 mais próximas do vencimento, de 12", resposta.texto)

    def test_nome_sem_acento_e_maiusculas(self):
        self.criar("Sofá", D("90"), 4, date(2026, 8, 20), 20)
        self.assertEqual(pagar.comando_pagar(TEL, "SOFA").texto, "Sofá, parcela 3/4, R$ 90,00. Confirmar?")

    def test_varias_achadas_mostra_lista_para_escolher(self):
        self.criar("Carro Ana", D("1200"), 48, date(2026, 5, 20), 20)
        self.criar("Carro Bia", D("900"), 48, date(2026, 5, 20), 20)
        self.criar("Geladeira", D("250"), 10, date(2026, 8, 20), 20)
        resposta = pagar.comando_pagar(TEL, "carro")
        self.assertEqual(sorted(resposta.botoes), ["Carro Ana", "Carro Bia"])

    def test_nome_nao_achado_diz_e_mostra_a_lista(self):
        self.carro()
        resposta = pagar.comando_pagar(TEL, "moto")
        self.assertIn("Não achei nenhuma parcela chamada \"moto\"", resposta.texto)
        self.assertEqual(resposta.botoes, ("Carro",))

    def test_sem_parcelas_no_mes(self):
        self.assertIn("Nenhuma parcela para pagar", pagar.comando_pagar(TEL, ""))

    def test_parcelas_pagar_e_o_mesmo_que_pagar(self):
        self.carro()
        resposta = parcelas.comando_parcelas(TEL, "pagar carro")
        self.assertEqual(resposta.texto, pagar.comando_pagar(TEL, "carro").texto)

    def test_parcela_meu_do_parceiro_nao_aparece(self):
        id_ = self.carro(escopo="meu")
        self.sql("UPDATE installments SET created_by_user_id = 'outro' WHERE id = :i", i=id_)
        self.assertIn("Nenhuma parcela", pagar.comando_pagar(TEL, ""))


class TestCalculoComColuna(unittest.TestCase):
    def test_sem_a_coluna_vale_a_data(self):
        p = financas.Parcelamento("Carro", D("1200"), 48, date(2026, 5, 20), 20)
        self.assertEqual((p.pagas(HOJE), p.proximo_vencimento(HOJE)), (5, date(2026, 10, 20)))

    def test_com_a_coluna_vale_a_contagem(self):
        p = financas.Parcelamento("Carro", D("1200"), 48, date(2026, 5, 20), 20, pagas_registradas=6)
        self.assertEqual((p.pagas(HOJE), p.restantes(HOJE), p.proximo_vencimento(HOJE)), (6, 42, date(2026, 11, 20)))
        self.assertEqual(financas.valor_parcelas_a_vencer([p], HOJE), D("0"))

    def test_atrasada_continua_a_vencer(self):
        p = financas.Parcelamento("Carro", D("1200"), 48, date(2026, 5, 20), 20, pagas_registradas=4)
        self.assertEqual(p.proximo_vencimento(HOJE), date(2026, 9, 20))  # a de setembro nunca foi paga
        self.assertEqual(financas.valor_parcelas_a_vencer([p], HOJE), D("1200"))


if __name__ == "__main__":
    unittest.main()
