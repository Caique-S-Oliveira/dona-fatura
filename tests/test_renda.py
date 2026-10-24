"""/renda e a renda do mês (esperada x recebida). Usa um banco SQLite em memória (nunca o banco real)."""
import sqlite3
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import StaticPool, create_engine, text

from app import financas
from app.comandos import renda
from app.comandos.previsao import montar_previsao
from app.comandos.renda import ler_pedido
from app.comandos.resposta import Resposta
from app.comandos.resumo import montar_resumo

D = Decimal
HOJE = date(2026, 10, 16)
TEL, USUARIO, PARCEIRO, CONTA = "5511988887777", "user-1", "user-2", "conta-1"

SCHEMA = """
CREATE TABLE users (id TEXT PRIMARY KEY, display_name TEXT);
CREATE TABLE members (
    account_id TEXT NOT NULL, user_id TEXT NOT NULL, expected_income NUMERIC,
    joined_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (account_id, user_id));
CREATE TABLE income_plans (
    account_id TEXT NOT NULL, user_id TEXT NOT NULL, month DATE NOT NULL, amount NUMERIC NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (account_id, user_id, month));
CREATE TABLE transactions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))), account_id TEXT NOT NULL,
    created_by_user_id TEXT NOT NULL, transaction_type TEXT NOT NULL, amount NUMERIC NOT NULL,
    description TEXT, transaction_date DATE NOT NULL, scope TEXT NOT NULL, voided_at TEXT,
    source TEXT NOT NULL);
"""

sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, str)
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()))
sqlite3.register_converter("NUMERIC", lambda b: Decimal(b.decode()))


class LerPedido(unittest.TestCase):
    def ler(self, texto):
        return [(i.mes, i.valor, i.recebido, i.dia) for i in ler_pedido(texto, HOJE)]

    def test_nome_abreviacao_numero_e_mm_aaaa(self):
        esperado = [(date(2026, 11, 1), D("5000"), False, None)]
        for pedido in ("novembro 5000", "nov 5000", "11 5000", "11/2026 5000", "Novembro/2026 5.000,00", "novembro R$ 5000"):
            self.assertEqual(self.ler(pedido), esperado, pedido)

    def test_marco_sem_cedilha(self):
        self.assertEqual(self.ler("março 3000")[0][0], date(2027, 3, 1))
        self.assertEqual(self.ler("mar 3000")[0][0], date(2027, 3, 1))

    def test_varios_meses_e_virgula_do_valor(self):
        itens = self.ler("outubro 4.500,00, novembro 3000,50, dez 2000")
        self.assertEqual([(m.month, v) for m, v, _, _ in itens], [(10, D("4500")), (11, D("3000.50")), (12, D("2000"))])
        self.assertEqual(len(self.ler("10 4000, 11 3000")), 2)

    def test_sem_ano_o_mes_passado_vai_para_o_ano_que_vem(self):
        self.assertEqual(self.ler("janeiro 3000")[0][0], date(2027, 1, 1))
        self.assertEqual(self.ler("outubro 3000")[0][0], date(2026, 10, 1))

    def test_recebido_sem_ano_olha_para_tras(self):
        self.assertEqual(self.ler("setembro 5000 recebido")[0], (date(2026, 9, 1), D("5000"), True, None))
        self.assertEqual(self.ler("dezembro 5000 recebido")[0][0], date(2025, 12, 1))

    def test_recebido_com_dia(self):
        self.assertEqual(self.ler("outubro 5000 recebido dia 5")[0], (date(2026, 10, 1), D("5000"), True, 5))
        self.assertEqual(self.ler("outubro 5000, setembro 4000 recebido")[1][2], True)

    def test_zero_remove(self):
        self.assertEqual(self.ler("outubro 0")[0][1], D("0"))

    def test_erros(self):
        for pedido in ("", "outubro", "xyz 5000", "outubro abc", "13 5000", "outubro 5000 recebido dia 40",
                       "fevereiro/2027 5000 recebido dia 30", "outubro 0 recebido", "ju 5000",
                       "outubro 5000, outubro 4000", "outubro 99999999999"):
            with self.assertRaises(ValueError, msg=pedido):
                ler_pedido(pedido, HOJE)

    def test_limite_de_meses(self):
        pedido = ", ".join(f"{m}/2027 1000" for m in range(1, 13)) + ", 1/2028 1000"
        with self.assertRaises(ValueError):
            ler_pedido(pedido, HOJE)


class RegraDaRenda(unittest.TestCase):
    def test_mes_atual_ou_futuro_usa_a_esperada_mas_a_recebida_maior_vale(self):
        self.assertEqual(financas.RendaMes(D("5000"), D("0")).valor(False), D("5000"))
        self.assertEqual(financas.RendaMes(D("5000"), D("6000")).valor(False), D("6000"))
        self.assertEqual(financas.RendaMes(D("5000"), D("2000")).valor(False), D("5000"))
        self.assertEqual(financas.RendaMes(None, D("2000")).valor(False), D("2000"))
        self.assertIsNone(financas.RendaMes(None, D("0")).valor(False))

    def test_mes_passado_usa_a_recebida_ou_a_esperada(self):
        self.assertEqual(financas.RendaMes(D("5000"), D("3000")).valor(True), D("3000"))
        self.assertEqual(financas.RendaMes(D("5000"), D("0")).valor(True), D("5000"))
        self.assertIsNone(financas.RendaMes(None, D("0")).valor(True))


class BancoDeRenda(unittest.TestCase):
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
            ("app.comandos.renda.get_engine", lambda: self.motor),
            ("app.financas.get_engine", lambda: self.motor),
            ("app.comandos.renda.conta_do_usuario", lambda tel: (USUARIO, CONTA)),
            ("app.comandos.renda.salvar_estado", lambda tel, estado, dados: self.estados.update({tel: (estado, dados)})),
            ("app.comandos.renda.limpar_estado", lambda tel: self.estados.pop(tel, None)),
            ("app.financas.hoje", lambda: HOJE),
            ("app.comandos.renda.financas.hoje", lambda: HOJE),
        ]:
            patcher = patch(alvo, novo)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sql("INSERT INTO users VALUES ('user-1', 'Ana'), ('user-2', 'Bia')")
        self.sql("INSERT INTO members (account_id, user_id, expected_income) VALUES (:c, 'user-1', 4500)", c=CONTA)

    # ---------- ajudantes ----------

    def sql(self, comando, **parametros):
        with self.motor.begin() as conexao:
            return conexao.execute(text(comando), parametros)

    def planos(self, usuario=USUARIO):
        return {
            m: v for m, v in self.sql(
                "SELECT month, amount FROM income_plans WHERE user_id = :u ORDER BY month", u=usuario
            ).all()
        }

    def entradas(self):
        return self.sql(
            "SELECT transaction_date, amount, scope, source FROM transactions"
            " WHERE transaction_type = 'income' ORDER BY transaction_date"
        ).all()

    def entrada(self, valor, dia, usuario=USUARIO):
        self.sql(
            "INSERT INTO transactions (account_id, created_by_user_id, transaction_type, amount,"
            " transaction_date, scope, source) VALUES (:c, :u, 'income', :v, :d, 'conjunto', 'manual')",
            c=CONTA, u=usuario, v=valor, d=dia,
        )

    def dizer(self, texto):
        """Manda /renda (ou a resposta da conversa em andamento)."""
        if texto.startswith("/renda"):
            return renda.comando_renda(TEL, texto[len("/renda"):].strip())
        estado, dados = self.estados[TEL]
        self.assertEqual(estado, "renda")
        return renda.continuar_renda(TEL, dados, texto)

    # ---------- /renda ----------

    def test_confirma_com_botoes_e_so_salva_depois_do_sim(self):
        resposta = self.dizer("/renda outubro 5000")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("outubro/2026: R$ 5.000,00", resposta.texto)
        self.assertEqual(self.planos(), {})
        self.assertIn("Pronto", self.dizer("Sim"))
        self.assertEqual(self.planos(), {date(2026, 10, 1): D("5000")})
        self.assertEqual(self.entradas(), [])  # sem "recebido", nenhuma entrada

    def test_varios_meses_de_uma_vez_e_alterar_um_mes(self):
        self.dizer("/renda outubro 5000, novembro 3000, dezembro 2000")
        self.dizer("Sim")
        self.assertEqual(len(self.planos()), 3)
        self.dizer("/renda novembro 3500")
        self.dizer("Sim")
        self.assertEqual(self.planos()[date(2026, 11, 1)], D("3500"))

    def test_corrigir_pede_de_novo(self):
        self.dizer("/renda outubro 5000")
        self.assertIn("Mande de novo", self.dizer("Corrigir"))
        resposta = self.dizer("outubro 5500")
        self.assertIn("R$ 5.500,00", resposta.texto)
        self.dizer("Sim")
        self.assertEqual(self.planos(), {date(2026, 10, 1): D("5500")})

    def test_zero_remove_o_mes_e_volta_ao_padrao(self):
        self.dizer("/renda outubro 5000")
        self.dizer("Sim")
        resposta = self.dizer("/renda outubro 0")
        self.assertIn("padrão: R$ 4.500,00", resposta.texto)
        self.dizer("Sim")
        self.assertEqual(self.planos(), {})
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("4500"))

    def test_recebido_registra_entrada_no_dia_informado(self):
        self.dizer("/renda outubro 5000 recebido dia 5")
        resposta = self.dizer("Sim")
        self.assertIn("05/10/2026", resposta)
        self.assertEqual(self.entradas(), [(date(2026, 10, 5), D("5000"), "conjunto", "manual")])

    def test_recebido_sem_dia_vai_para_o_dia_1(self):
        self.dizer("/renda outubro 5000 recebido")
        self.dizer("Sim")
        self.assertEqual(self.entradas()[0][0], date(2026, 10, 1))

    def test_recebido_com_entrada_igual_pergunta_antes(self):
        self.entrada(5000, date(2026, 10, 3))
        self.dizer("/renda outubro 5000 recebido")
        resposta = self.dizer("Sim")
        self.assertEqual(resposta.botoes, ("Registrar", "Só a renda"))
        self.assertEqual(self.planos(), {})  # nada salvo ainda
        self.assertIn("Pronto", self.dizer("Só a renda"))
        self.assertEqual(self.planos(), {date(2026, 10, 1): D("5000")})
        self.assertEqual(len(self.entradas()), 1)  # não contou duas vezes

    def test_recebido_com_entrada_igual_registrar_mesmo_assim(self):
        self.entrada(5000, date(2026, 10, 3))
        self.dizer("/renda outubro 5000 recebido")
        self.dizer("Sim")
        self.dizer("Registrar")
        self.assertEqual(len(self.entradas()), 2)

    def test_entrada_de_valor_diferente_nao_pergunta(self):
        self.entrada(1000, date(2026, 10, 3))
        self.dizer("/renda outubro 5000 recebido")
        self.assertIn("Pronto", self.dizer("Sim"))
        self.assertEqual(len(self.entradas()), 2)

    def test_pedido_invalido_nao_abre_conversa(self):
        self.assertIn("Não entendi", self.dizer("/renda banana 5000"))
        self.assertNotIn(TEL, self.estados)

    def test_lista_com_o_padrao(self):
        self.sql("INSERT INTO income_plans (account_id, user_id, month, amount) VALUES (:c, 'user-1', '2026-11-01', 3000)", c=CONTA)
        texto = self.dizer("/renda")
        self.assertIn("padrão: R$ 4.500,00", texto)
        self.assertIn("novembro/2026: R$ 3.000,00", texto)

    def test_lista_sem_nada(self):
        self.sql("UPDATE members SET expected_income = NULL")
        self.assertIn("ainda não tem renda", self.dizer("/renda"))

    # ---------- renda do mês ----------

    def test_mes_sem_valor_proprio_usa_o_padrao(self):
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("4500"))

    def test_mes_com_valor_proprio_e_mes_futuro(self):
        self.sql("INSERT INTO income_plans (account_id, user_id, month, amount) VALUES (:c, 'user-1', '2026-10-01', 5000)", c=CONTA)
        self.sql("INSERT INTO income_plans (account_id, user_id, month, amount) VALUES (:c, 'user-1', '2027-02-01', 2500)", c=CONTA)
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("5000"))
        self.assertEqual(financas.renda_do_mes(CONTA, date(2027, 2, 10)), D("2500"))
        self.assertEqual(financas.renda_do_mes(CONTA, date(2027, 3, 10)), D("4500"))

    def test_recebida_maior_vale_no_mes_atual(self):
        self.entrada(6000, date(2026, 10, 5))
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("6000"))

    def test_mes_passado_usa_a_recebida_ou_a_esperada(self):
        setembro = date(2026, 9, 10)
        self.assertEqual(financas.renda_do_mes(CONTA, setembro), D("4500"))  # nada recebido
        self.entrada(3000, date(2026, 9, 5))
        self.assertEqual(financas.renda_do_mes(CONTA, setembro), D("3000"))  # menor que a esperada, mas vale

    def test_entrada_desfeita_nao_conta(self):
        self.entrada(6000, date(2026, 10, 5))
        self.sql("UPDATE transactions SET voided_at = '2026-10-06'")
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("4500"))

    def test_casal_cada_um_tem_a_sua_e_o_mes_soma(self):
        self.sql("INSERT INTO members (account_id, user_id, expected_income) VALUES (:c, 'user-2', 3000)", c=CONTA)
        self.sql("INSERT INTO income_plans (account_id, user_id, month, amount) VALUES (:c, 'user-2', '2026-10-01', 3500)", c=CONTA)
        self.entrada(4800, date(2026, 10, 5))  # recebida da primeira pessoa, maior que a esperada
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE, USUARIO), D("4800"))
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE, PARCEIRO), D("3500"))
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("8300"))
        self.assertEqual(financas.renda_esperada_do_mes(CONTA, HOJE), D("8000"))

    def test_casal_lista_as_duas(self):
        self.sql("INSERT INTO members (account_id, user_id, expected_income) VALUES (:c, 'user-2', 3000)", c=CONTA)
        texto = self.dizer("/renda")
        self.assertIn("Sua renda esperada (padrão: R$ 4.500,00)", texto)
        self.assertIn("A de Bia renda esperada (padrão: R$ 3.000,00)", texto)
        self.assertIn("Renda do casal em outubro/2026: R$ 7.500,00", texto)

    def test_renda_de_uma_pessoa_nao_muda_a_da_outra(self):
        self.sql("INSERT INTO members (account_id, user_id, expected_income) VALUES (:c, 'user-2', 3000)", c=CONTA)
        self.dizer("/renda outubro 5000")
        self.dizer("Sim")
        self.assertEqual(self.planos(PARCEIRO), {})
        self.assertEqual(financas.renda_do_mes(CONTA, HOJE), D("8000"))


class Roteamento(unittest.TestCase):
    def test_so_o_renda_recebido_conta_como_registro_para_o_aviso_de_privacidade(self):
        from app.comandos import _e_registro

        self.assertTrue(_e_registro(TEL, "/renda outubro 5000 recebido", "renda"))
        self.assertTrue(_e_registro(TEL, "/renda outubro 5000 Recebida dia 5", "renda"))
        self.assertFalse(_e_registro(TEL, "/renda outubro 5000", "renda"))
        self.assertFalse(_e_registro(TEL, "/renda", "renda"))

    def test_ia_nao_escolhe_o_renda(self):
        from app.comandos import COMANDOS_CONHECIDOS, COMANDOS_PELA_IA

        self.assertIn("renda", COMANDOS_CONHECIDOS)
        self.assertNotIn("renda", COMANDOS_PELA_IA)


class Textos(unittest.TestCase):
    def previsao(self, entradas, renda_mes):
        p = financas.calcular_previsao(D(entradas), D("1000"), D("500"), D("10"), 10)
        p.renda_mes = None if renda_mes is None else D(renda_mes)
        return p

    def test_previsao_mostra_recebido_x_esperado_e_dois_saldos(self):
        texto = montar_previsao(self.previsao("2000", "5000"), date(2026, 10, 31))
        self.assertIn("recebido R$ 2.000,00 x esperado R$ 5.000,00", texto)
        self.assertIn("com a renda esperada: R$ 3.400,00", texto)  # 5000 - (1000 + 500 + 100)
        self.assertIn("Saldo só com o que já recebeu: R$ 400,00", texto)

    def test_previsao_com_tudo_recebido_tem_um_saldo_so(self):
        texto = montar_previsao(self.previsao("5000", "5000"), date(2026, 10, 31))
        self.assertNotIn("só com o que já recebeu", texto)
        self.assertIn("Saldo previsto no fim do mês: R$ 3.400,00", texto)

    def test_previsao_sem_renda_cadastrada_fica_como_antes(self):
        texto = montar_previsao(self.previsao("2000", None), date(2026, 10, 31))
        self.assertIn("Saldo previsto no fim do mês: R$ 400,00", texto)
        self.assertNotIn("esperado", texto)

    def test_previsao_vermelho_pensa_na_renda_esperada(self):
        texto = montar_previsao(self.previsao("0", "1000"), date(2026, 10, 31))
        self.assertIn("vermelho", texto)  # 1000 - 1600 < 0
        texto = montar_previsao(self.previsao("0", "5000"), date(2026, 10, 31))
        self.assertNotIn("vermelho", texto)

    def test_resumo_mostra_recebido_x_esperado(self):
        atual = financas.Totais()
        atual.entradas = D("2000")
        periodos = (date(2026, 10, 1), date(2026, 10, 16), date(2026, 9, 1), date(2026, 9, 16))
        texto = montar_resumo("Resumo", periodos, atual, financas.Totais(), D("5000"))
        self.assertIn("Renda do mês: recebido R$ 2.000,00 x esperado R$ 5.000,00", texto)
        self.assertNotIn("esperado", montar_resumo("Resumo", periodos, atual, financas.Totais()))


if __name__ == "__main__":
    unittest.main()
