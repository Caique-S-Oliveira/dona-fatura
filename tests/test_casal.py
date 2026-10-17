"""Etapa 15: modo casal.

Os testes de privacidade rodam SQL de verdade, num banco SQLite em memória (nunca no banco real),
com os mesmos comandos do bot: /casal, /entrar, /gasto, /resumo, /metas...
"""
import re
import sqlite3
import sys
import time
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import StaticPool, create_engine, event, text

import app.comandos  # noqa: F401  (carrega todos os módulos que serão trocados nos testes)
from app import financas
from app.comandos import processar_mensagem
from app.comandos.cadastro import conta_do_usuario, garantir_usuario
from app.comandos.casal import ler_codigo, ler_escolha
from app.comandos.categorias import Categoria
from app.comandos.fixos import _contas, _gastos_do_mes
from app.comandos.gasto import ler_comando, tem_sufixo_de_escopo
from app.comandos.inicio import gravar_inicio
from app.comandos.parcelas import listar_parcelas
from app.comandos.recorrentes import _historico, contas_da_conta
from app.comandos.resposta import Resposta
from app.comandos.sair_casal import pegar_avisos, separar_casal

ANA = "5511911110001"
BIA = "5511922220002"
CAIO = "5511933330003"

SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    phone_number TEXT NOT NULL UNIQUE, display_name TEXT,
    access_status TEXT NOT NULL DEFAULT 'pendente', access_expires_at TEXT,
    cadastro_completo INTEGER NOT NULL DEFAULT 0, profile_name TEXT,
    pending_reply_sent INTEGER NOT NULL DEFAULT 0, admin_notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE accounts (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    owner_user_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'individual',
    invitation_code TEXT UNIQUE, invitation_expires_at TEXT,
    privacy_mode TEXT NOT NULL DEFAULT 'junto');
CREATE TABLE members (
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE, user_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'partner',
    expected_income INTEGER,
    joined_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (account_id, user_id));
CREATE TABLE categories (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    name TEXT, normalized_name TEXT, type TEXT, is_default INTEGER NOT NULL DEFAULT 0,
    created_by_user_id TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE classification_rules (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id TEXT NOT NULL, category_id TEXT NOT NULL, normalized_payee TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE savings_goals (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id TEXT NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
    target_amount INTEGER NOT NULL, target_date TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE savings_contributions (
    id TEXT PRIMARY KEY, goal_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id TEXT NOT NULL, amount INTEGER NOT NULL, contribution_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE pending_notices (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))), user_id TEXT NOT NULL,
    message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE goals (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE, member_user_id TEXT, type TEXT NOT NULL,
    value_type TEXT NOT NULL, value INTEGER NOT NULL, updated_at TEXT);
CREATE UNIQUE INDEX goals_account_type_idx ON goals (account_id, type) WHERE member_user_id IS NULL;
CREATE UNIQUE INDEX goals_member_type_idx ON goals (account_id, member_user_id, type)
    WHERE member_user_id IS NOT NULL;
CREATE TABLE transactions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE, created_by_user_id TEXT NOT NULL, category_id TEXT,
    transaction_type TEXT NOT NULL, amount INTEGER NOT NULL, description TEXT, payee TEXT,
    transaction_date TEXT NOT NULL, scope TEXT NOT NULL, voided_at TEXT,
    recurring_transaction_id TEXT, source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE recurring_transactions (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE, created_by_user_id TEXT NOT NULL, payee TEXT NOT NULL,
    amount INTEGER NOT NULL, frequency TEXT NOT NULL DEFAULT 'monthly', next_due_date TEXT,
    scope TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
    category_id TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
CREATE TABLE installments (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE, created_by_user_id TEXT NOT NULL, description TEXT NOT NULL,
    installment_amount INTEGER NOT NULL, total_installments INTEGER NOT NULL,
    first_due_date TEXT NOT NULL, due_day INTEGER NOT NULL, scope TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')));
"""

# O SQLite do Python não sabe guardar estes tipos sozinho.
sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, str)


class Conversa:
    """Troca a conversa em andamento (que usa recursos só do PostgreSQL) por um dicionário."""

    def __init__(self):
        self.estados: dict[str, tuple[str, dict]] = {}

    def ler(self, telefone):
        return self.estados.get(telefone)

    def salvar(self, telefone, estado, dados):
        self.estados[telefone] = (estado, dados)

    def limpar(self, telefone):
        self.estados.pop(telefone, None)


class BancoDeTeste(unittest.TestCase):
    """Cada teste ganha um banco novo e vazio; o bot enxerga só ele."""

    def setUp(self):
        self.motor = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.motor, "connect")
        def _funcoes(conexao, _):
            conexao.create_function("now", 0, lambda: datetime.now().isoformat(" "))
            conexao.execute("PRAGMA foreign_keys = ON")  # para o DELETE em cascata valer como no Postgres

        with self.motor.begin() as conexao:
            for comando in SCHEMA.split(";\n"):
                if comando.strip():
                    conexao.exec_driver_sql(comando)
        self.addCleanup(self.motor.dispose)
        self.conversa = Conversa()
        self._trocar("get_engine", lambda: self.motor)
        self._trocar("ler_estado", self.conversa.ler)
        self._trocar("salvar_estado", self.conversa.salvar)
        self._trocar("limpar_estado", self.conversa.limpar)

    def _trocar(self, nome, novo):
        """Troca `nome` em todo módulo do app que o importou."""
        for modulo in list(sys.modules.values()):
            if getattr(modulo, "__name__", "").startswith("app") and hasattr(modulo, nome):
                patcher = patch.object(modulo, nome, novo)
                patcher.start()
                self.addCleanup(patcher.stop)

    # ---------- ajudantes ----------

    def cadastrar(self, telefone, nome, renda=None):
        garantir_usuario(telefone)
        user_id, account_id = conta_do_usuario(telefone)
        self.sql("UPDATE users SET access_status = 'ativo', cadastro_completo = 1, display_name = :n"
                 " WHERE id = :u",
                 n=nome, u=user_id)
        if renda is not None:
            self.sql("UPDATE members SET expected_income = :r WHERE user_id = :u", r=renda, u=user_id)

    def sql(self, comando, **parametros):
        with self.motor.begin() as conexao:
            return conexao.execute(text(comando), parametros)

    def ids(self, telefone):
        return conta_do_usuario(telefone)

    def formar_casal(self, modo="junto"):
        """Ana (dona) e Bia entram no casal pelo caminho real: /casal e /entrar."""
        self.cadastrar(ANA, "Ana", 4500)
        self.cadastrar(BIA, "Bia", 3000)
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(ANA, "/casal")).group(1)
        time.sleep(0.01)  # a conta do casal precisa ser a mais nova da Bia
        processar_mensagem(BIA, f"/entrar {codigo}")
        processar_mensagem(BIA, "Tudo junto" if modo == "junto" else "Com gastos pessoais")
        return codigo

    def categoria(self, telefone, nome, tipo):
        _, conta = self.ids(telefone)
        id_ = f"cat-{nome}"
        self.sql("INSERT OR IGNORE INTO categories (id, account_id, name, type) VALUES (:i, :c, :n, :t)",
                 i=id_, c=conta, n=nome, t=tipo)
        return Categoria(id_, nome, tipo)

    def registrar(self, telefone, valor, escopo, tipo="expense", categoria=None, descricao="algo"):
        usuario, conta = self.ids(telefone)
        self.sql(
            "INSERT INTO transactions (account_id, created_by_user_id, category_id, transaction_type,"
            " amount, description, transaction_date, scope)"
            " VALUES (:c, :u, :k, :t, :v, :d, :data, :s)",
            c=conta, u=usuario, k=categoria.id if categoria else None, t=tipo, v=valor,
            d=descricao, data=financas.hoje(), s=escopo,
        )


# ---------- leitura de texto (sem banco) ----------

class TestLeitura(unittest.TestCase):
    def test_codigo(self):
        self.assertEqual(ler_codigo(" abc-234 "), "ABC234")
        self.assertEqual(ler_codigo(""), "")

    def test_escolha_da_pergunta_unica(self):
        self.assertEqual(ler_escolha("Tudo junto"), "junto")
        self.assertEqual(ler_escolha("com gastos pessoais"), "pessoal")
        self.assertEqual(ler_escolha("2"), "pessoal")
        self.assertIsNone(ler_escolha("sei lá"))

    def test_sufixo_de_escopo(self):
        self.assertTrue(tem_sufixo_de_escopo("padaria meu"))
        self.assertTrue(tem_sufixo_de_escopo("mercado casal"))
        self.assertFalse(tem_sufixo_de_escopo("padaria"))
        self.assertFalse(tem_sufixo_de_escopo("meu"))  # só a palavra: é a descrição
        self.assertEqual(ler_comando("30 padaria meu")[2], "meu")


# ---------- /casal e /entrar ----------

class TestCasalEEntrar(BancoDeTeste):
    def test_casal_gera_codigo_e_entrar_junta_os_dois_na_mesma_conta(self):
        self.cadastrar(ANA, "Ana")
        self.cadastrar(BIA, "Bia")
        resposta = processar_mensagem(ANA, "/casal")
        codigo = re.search(r"código do casal: (\w{6})", resposta).group(1)
        self.assertIn(f"/entrar {codigo}", resposta)
        time.sleep(0.01)

        pergunta = processar_mensagem(BIA, f"/entrar {codigo.lower()}")  # minúsculas também vale
        self.assertIsInstance(pergunta, Resposta)
        self.assertIn("casal de Ana", pergunta.texto)
        self.assertEqual(pergunta.botoes, ("Tudo junto", "Com gastos pessoais"))
        self.assertEqual(self.ids(ANA)[1], self.ids(BIA)[1])  # mesma conta
        self.assertEqual(
            self.sql("SELECT mode FROM accounts WHERE id = :c", c=self.ids(ANA)[1]).scalar(), "couple"
        )

    def test_codigo_vale_para_uma_pessoa_so(self):
        self.cadastrar(ANA, "Ana")
        self.cadastrar(BIA, "Bia")
        self.cadastrar(CAIO, "Caio")
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(ANA, "/casal")).group(1)
        time.sleep(0.01)
        processar_mensagem(BIA, f"/entrar {codigo}")
        resposta = processar_mensagem(CAIO, f"/entrar {codigo}")
        self.assertIn("inválido", resposta)
        self.assertNotEqual(self.ids(CAIO)[1], self.ids(ANA)[1])

    def test_codigo_vencido_ou_errado(self):
        self.cadastrar(ANA, "Ana")
        self.cadastrar(BIA, "Bia")
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(ANA, "/casal")).group(1)
        self.sql("UPDATE accounts SET invitation_expires_at = '2000-01-01 00:00:00+00:00'")
        self.assertIn("inválido", processar_mensagem(BIA, f"/entrar {codigo}"))
        self.assertIn("inválido", processar_mensagem(BIA, "/entrar ZZZZZZ"))
        self.assertIn("Use: /entrar", processar_mensagem(BIA, "/entrar"))
        self.assertNotEqual(self.ids(ANA)[1], self.ids(BIA)[1])

    def test_nao_entra_no_proprio_codigo(self):
        self.cadastrar(ANA, "Ana")
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(ANA, "/casal")).group(1)
        self.assertIn("sua própria conta", processar_mensagem(ANA, f"/entrar {codigo}"))

    def test_casal_ja_formado_so_informa(self):
        self.formar_casal()
        self.assertIn("em casal com Bia", processar_mensagem(ANA, "/casal"))
        self.assertIn("em casal com Ana", processar_mensagem(BIA, "/casal"))
        self.assertIn("já está em um casal", processar_mensagem(BIA, "/entrar ABC234"))

    def test_pergunta_unica_grava_a_escolha(self):
        self.formar_casal(modo="pessoal")
        conta = self.ids(ANA)[1]
        self.assertEqual(self.sql("SELECT privacy_mode FROM accounts WHERE id = :c", c=conta).scalar(), "pessoal")
        self.assertIsNone(self.conversa.ler(BIA))  # a pergunta não se repete

    def test_resposta_estranha_repete_a_pergunta_com_botoes(self):
        self.cadastrar(ANA, "Ana")
        self.cadastrar(BIA, "Bia")
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(ANA, "/casal")).group(1)
        time.sleep(0.01)
        processar_mensagem(BIA, f"/entrar {codigo}")
        resposta = processar_mensagem(BIA, "hmm")
        self.assertEqual(resposta.botoes, ("Tudo junto", "Com gastos pessoais"))
        conta = self.ids(BIA)[1]
        # sem resposta, vale o padrão "tudo junto"
        self.assertEqual(self.sql("SELECT privacy_mode FROM accounts WHERE id = :c", c=conta).scalar(), "junto")


# ---------- [Meu] [Conjunto] só em "com gastos pessoais" ----------

@patch("app.comandos.gasto.verificar_recorrente", return_value=None)
class TestEscopoNoRegistro(BancoDeTeste):
    def setUp(self):
        super().setUp()
        self.mercado = Categoria("cat-mercado", "Mercado", "Variável")
        for nome, novo in (
            ("listar_categorias", lambda account_id: [self.mercado]),
            ("sugerir", lambda *args: self.mercado),
        ):
            patcher = patch(f"app.comandos.gasto.{nome}", novo)
            patcher.start()
            self.addCleanup(patcher.stop)

    def gravados(self):
        gravar = patch("app.comandos.gasto.gravar_gasto")
        mock = gravar.start()
        self.addCleanup(gravar.stop)
        return mock

    def test_com_gastos_pessoais_pergunta_meu_ou_conjunto(self, _rec):
        self.formar_casal(modo="pessoal")
        gravar = self.gravados()
        pergunta = processar_mensagem(BIA, "/gasto 30 padaria")
        self.assertEqual(pergunta.botoes, ("Meu", "Conjunto"))
        confirma = processar_mensagem(BIA, "Meu")
        self.assertEqual(confirma.botoes, ("Sim", "Corrigir"))
        self.assertIn("só seu", confirma.texto)
        processar_mensagem(BIA, "Sim")
        self.assertEqual(gravar.call_args.args[2]["escopo"], "meu")

    def test_com_gastos_pessoais_conjunto(self, _rec):
        self.formar_casal(modo="pessoal")
        gravar = self.gravados()
        processar_mensagem(ANA, "gastei 80 no mercado")  # frase livre também pergunta
        processar_mensagem(ANA, "Conjunto")
        processar_mensagem(ANA, "Sim")
        self.assertEqual(gravar.call_args.args[2]["escopo"], "conjunto")

    def test_resposta_fora_dos_botoes_pergunta_de_novo(self, _rec):
        self.formar_casal(modo="pessoal")
        processar_mensagem(BIA, "/gasto 30 padaria")
        resposta = processar_mensagem(BIA, "talvez")
        self.assertEqual(resposta.botoes, ("Meu", "Conjunto"))

    def test_sufixo_dispensa_a_pergunta_mesmo_em_gastos_pessoais(self, _rec):
        self.formar_casal(modo="pessoal")
        resposta = processar_mensagem(BIA, "/gasto 30 padaria meu")
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("só seu", resposta.texto)

    def test_comprovante_tambem_pergunta(self, _rec):
        self.formar_casal(modo="pessoal")
        from app.comandos.comprovante import receber_comprovante

        extraido = {"valor": "45,90", "data": None, "favorecido": "Padaria"}
        with patch("app.comandos.comprovante.ia.ler_comprovante", return_value=extraido):
            resposta = receber_comprovante(BIA, "image/jpeg", lambda: b"foto")
        self.assertEqual(resposta.botoes, ("Meu", "Conjunto"))

    def test_tudo_junto_nao_pergunta_e_o_sufixo_meu_ainda_vale(self, _rec):
        self.formar_casal(modo="junto")
        gravar = self.gravados()
        comum = processar_mensagem(BIA, "/gasto 30 padaria")
        self.assertEqual(comum.botoes, ("Sim", "Corrigir"))  # direto para a categoria
        self.assertNotIn("só seu", comum.texto)
        processar_mensagem(BIA, "Sim")
        self.assertEqual(gravar.call_args.args[2]["escopo"], "conjunto")

        privado = processar_mensagem(BIA, "/gasto 30 padaria meu")
        self.assertIn("só seu", privado.texto)
        processar_mensagem(BIA, "Sim")
        self.assertEqual(gravar.call_args.args[2]["escopo"], "meu")

    def test_conta_individual_nunca_pergunta(self, _rec):
        self.cadastrar(CAIO, "Caio")
        self.sql("UPDATE accounts SET privacy_mode = 'pessoal'")  # mesmo que sobrasse a escolha
        resposta = processar_mensagem(CAIO, "/gasto 30 padaria")
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))


# ---------- um parceiro NÃO vê os gastos "meu" do outro ----------

class TestPrivacidadeEntreParceiros(BancoDeTeste):
    def setUp(self):
        super().setUp()
        self.formar_casal()
        self.lazer = self.categoria(ANA, "Lazer", "Variável")
        self.moradia = self.categoria(ANA, "Moradia", "Fixo")
        self.registrar(ANA, 5000, "conjunto", tipo="income", descricao="Salário")
        self.registrar(ANA, 100, "conjunto", categoria=self.moradia)
        self.registrar(ANA, 700, "meu", categoria=self.lazer, descricao="presente surpresa")

    def test_resumo_da_bia_nao_detalha_o_meu_da_ana(self):
        texto = processar_mensagem(BIA, "/resumo")
        self.assertNotIn("Variável", texto)  # o gasto "meu" da Ana é de Variável: sem detalhe
        self.assertIn("• Fixo: R$ 100,00", texto)  # o conjunto aparece
        self.assertIn("Gastos pessoais do parceiro: R$ 700,00", texto)  # só o total somado
        self.assertIn("Saídas: R$ 800,00", texto)
        self.assertNotIn("presente", texto)

    def test_resumo_da_ana_mostra_o_proprio_meu_em_detalhe(self):
        texto = processar_mensagem(ANA, "/resumo")
        self.assertIn("• Variável: R$ 700,00", texto)
        self.assertIn("• Fixo: R$ 100,00", texto)
        self.assertNotIn("Gastos pessoais do parceiro", texto)

    def test_vale_nos_dois_sentidos(self):
        categoria_bia = self.categoria(BIA, "Saúde", "Variável")
        self.registrar(BIA, 40, "meu", categoria=categoria_bia)
        da_ana = processar_mensagem(ANA, "/resumo")
        self.assertIn("Gastos pessoais do parceiro: R$ 40,00", da_ana)
        self.assertIn("• Variável: R$ 700,00", da_ana)  # sem somar os R$ 40 da Bia no detalhe
        da_bia = processar_mensagem(BIA, "/resumo")
        self.assertIn("• Variável: R$ 40,00", da_bia)
        self.assertIn("Gastos pessoais do parceiro: R$ 700,00", da_bia)

    def test_totais_do_periodo_separam_o_que_pode_ser_visto(self):
        inicio, fim = financas.hoje().replace(day=1), financas.hoje()
        bia = financas.totais_do_periodo(*reversed(self.ids(BIA)), inicio, fim)
        self.assertEqual(bia.por_tipo, {"Fixo": Decimal(100)})
        self.assertEqual(bia.pessoais_do_parceiro, Decimal(700))
        ana = financas.totais_do_periodo(*reversed(self.ids(ANA)), inicio, fim)
        self.assertEqual(ana.por_tipo, {"Fixo": Decimal(100), "Variável": Decimal(700)})
        self.assertEqual(ana.pessoais_do_parceiro, Decimal(0))

    def test_quem_nao_e_do_casal_nao_ve_nada(self):
        self.cadastrar(CAIO, "Caio")
        self.assertIn("Ainda não há registros", processar_mensagem(CAIO, "/resumo"))

    def test_fixos_recorrentes_e_parcelas_meu_ficam_so_com_o_dono(self):
        usuario_ana, conta = self.ids(ANA)
        usuario_bia, _ = self.ids(BIA)
        for nome, escopo in (("Terapia", "meu"), ("Aluguel", "conjunto")):
            self.sql(
                "INSERT INTO recurring_transactions (account_id, created_by_user_id, payee, amount,"
                " scope) VALUES (:c, :u, :n, 200, :s)", c=conta, u=usuario_ana, n=nome, s=escopo)
        for nome, escopo in (("Moto", "meu"), ("Geladeira", "conjunto")):
            self.sql(
                "INSERT INTO installments (account_id, created_by_user_id, description,"
                " installment_amount, total_installments, first_due_date, due_day, scope)"
                " VALUES (:c, :u, :n, 300, 10, '2026-01-20', 20, :s)",
                c=conta, u=usuario_ana, n=nome, s=escopo)
        dia = financas.hoje()

        self.assertEqual({c.nome for c in _contas(conta, usuario_bia)}, {"Aluguel"})
        self.assertEqual({c.nome for c in _contas(conta, usuario_ana)}, {"Aluguel", "Terapia"})
        self.assertEqual({c.nome for c in contas_da_conta(conta, usuario_bia)}, {"Aluguel"})
        self.assertEqual({p.nome for p in listar_parcelas(conta, usuario_bia)}, {"Geladeira"})
        self.assertEqual({p.nome for p in listar_parcelas(conta, usuario_ana)}, {"Geladeira", "Moto"})

        # o histórico usado para achar recorrentes e o /fixos também não traz o "meu" do outro
        chaves_bia = {chave for chave, _, _ in _gastos_do_mes(conta, usuario_bia, dia)}
        self.assertEqual(chaves_bia, {"algo"})  # o gasto "conjunto" de Moradia (descrição padrão)
        historico = _historico(conta, usuario_bia, "presente surpresa", dia)
        self.assertEqual(historico, [])
        self.assertEqual(len(_historico(conta, usuario_ana, "presente surpresa", dia)), 1)  # a dona vê

    def test_desfazer_nunca_apaga_registro_do_parceiro(self):
        self.registrar(ANA, 15, "conjunto", descricao="registro da Ana")
        resposta = processar_mensagem(BIA, "/desfazer")
        self.assertIn("nenhum registro para desfazer", resposta)  # a Bia não registrou nada

    def test_rendas_sao_visiveis_aos_dois(self):
        da_bia = processar_mensagem(BIA, "/metas")
        da_ana = processar_mensagem(ANA, "/metas")
        for texto in (da_bia, da_ana):
            self.assertIn("R$ 4.500,00", texto)
            self.assertIn("R$ 3.000,00", texto)
            self.assertIn("renda junta R$ 7.500,00", texto)
        self.assertIn("Você R$ 3.000,00", da_bia)
        self.assertIn("Ana R$ 4.500,00", da_bia)


# ---------- metas do casal e metas individuais ----------

class TestMetas(BancoDeTeste):
    def setUp(self):
        super().setUp()
        self.formar_casal()

    def test_meta_do_casal_vale_para_os_dois(self):
        processar_mensagem(ANA, "/metas fixo 2000")
        self.assertIn("Fixo: R$ 2.000,00", processar_mensagem(BIA, "/metas").split("Suas metas")[0])

    def test_meta_individual_so_o_dono_ve(self):
        resposta = processar_mensagem(ANA, "/metas variavel 650 meu")
        self.assertIn("(só sua)", resposta)
        da_ana = processar_mensagem(ANA, "/metas")
        da_bia = processar_mensagem(BIA, "/metas")
        self.assertIn("Variável: R$ 650,00", da_ana.split("Suas metas")[1])
        self.assertNotIn("650", da_bia)
        self.assertNotIn("Variável", da_bia.split("Suas metas")[0])  # nem como meta do casal

    def test_meta_em_porcentagem_do_casal_usa_as_duas_rendas(self):
        resposta = processar_mensagem(ANA, "/metas variavel 10%")
        self.assertIn("R$ 750,00", resposta)  # 10% de 7.500

    def test_meta_individual_em_porcentagem_usa_a_propria_renda(self):
        resposta = processar_mensagem(BIA, "/metas variavel 10% meu")
        self.assertIn("R$ 300,00", resposta)  # 10% de 3.000

    def test_inicio_no_casal_nao_apaga_as_metas_do_casal(self):
        processar_mensagem(ANA, "/metas fixo 2000")
        gravar_inicio(BIA, {"nome": "Bia", "renda": "3200", "formato": "amount",
                            "metas": {"Variável": "500"}})
        da_ana = processar_mensagem(ANA, "/metas")
        self.assertIn("Fixo: R$ 2.000,00", da_ana.split("Suas metas")[0])  # do casal: intacta
        self.assertNotIn("R$ 500,00", da_ana)  # a meta que a Bia criou no /inicio é só dela
        self.assertIn("Variável: R$ 500,00", processar_mensagem(BIA, "/metas").split("Suas metas")[1])

    def test_fora_do_casal_meu_e_ignorado(self):
        self.cadastrar(CAIO, "Caio", 2000)
        processar_mensagem(CAIO, "/metas variavel 300 meu")
        _, conta = self.ids(CAIO)
        dono = self.sql("SELECT member_user_id FROM goals WHERE account_id = :c", c=conta).scalar()
        self.assertIsNone(dono)  # sem casal só existe a meta da conta


# ---------- /sair_casal ----------

class TestSairCasal(BancoDeTeste):
    def setUp(self):
        super().setUp()
        self.formar_casal()
        self.lazer = self.categoria(ANA, "Lazer", "Variável")
        self.moradia = self.categoria(ANA, "Moradia", "Fixo")
        self.saude = self.categoria(ANA, "Saúde", "Variável")
        self.registrar(ANA, 5000, "conjunto", tipo="income", descricao="Salário")
        self.registrar(ANA, 100, "conjunto", categoria=self.moradia, descricao="aluguel")
        self.registrar(ANA, 700, "meu", categoria=self.lazer, descricao="presente surpresa")
        self.registrar(BIA, 40, "meu", categoria=self.saude, descricao="terapia")
        processar_mensagem(ANA, "/metas fixo 2000")
        processar_mensagem(ANA, "/metas variavel 650 meu")
        processar_mensagem(BIA, "/metas variavel 300 meu")
        usuario_ana, conta = self.ids(ANA)
        usuario_bia, _ = self.ids(BIA)
        self.conta_antiga = conta
        for nome, escopo, dono in (("Aluguel", "conjunto", usuario_ana), ("Terapia", "meu", usuario_bia)):
            self.sql("INSERT INTO recurring_transactions (account_id, created_by_user_id, payee, amount,"
                     " scope) VALUES (:c, :u, :n, 200, :s)", c=conta, u=dono, n=nome, s=escopo)
        for nome, escopo, dono in (("Geladeira", "conjunto", usuario_bia), ("Moto", "meu", usuario_ana)):
            self.sql("INSERT INTO installments (account_id, created_by_user_id, description,"
                     " installment_amount, total_installments, first_due_date, due_day, scope)"
                     " VALUES (:c, :u, :n, 300, 10, '2026-01-20', 20, :s)", c=conta, u=dono, n=nome, s=escopo)
        self.sql("INSERT INTO savings_goals (id, account_id, created_by_user_id, name, normalized_name,"
                 " target_amount, target_date) VALUES ('sg1', :c, :u, 'Viagem', 'viagem', 4000, '2027-01-01')",
                 c=conta, u=usuario_ana)
        self.sql("INSERT INTO savings_contributions (id, goal_id, account_id, created_by_user_id, amount,"
                 " contribution_date) VALUES ('sc1', 'sg1', :c, :u, 200, '2026-10-01')", c=conta, u=usuario_bia)
        self.sql("INSERT INTO classification_rules (id, account_id, created_by_user_id, category_id,"
                 " normalized_payee) VALUES ('r1', :c, :u, :k, 'padaria')",
                 c=conta, u=usuario_ana, k=self.moradia.id)
        self.enviado = patch("app.whatsapp.send_text")
        self.send_text = self.enviado.start()
        self.addCleanup(self.enviado.stop)

    def sair(self, telefone=ANA):
        pergunta = processar_mensagem(telefone, "/sair_casal")
        return pergunta, processar_mensagem(telefone, "Sim")

    def test_pede_confirmacao_com_botoes(self):
        pergunta = processar_mensagem(ANA, "/sair_casal")
        self.assertIsInstance(pergunta, Resposta)
        self.assertEqual(pergunta.botoes, ("Sim", "Não"))
        self.assertIn("Bia", pergunta.texto)
        self.assertEqual(processar_mensagem(ANA, "hmm").botoes, ("Sim", "Não"))  # repete a pergunta

    def test_nao_mantem_tudo_como_estava(self):
        processar_mensagem(ANA, "/sair_casal")
        self.assertIn("continuam em casal", processar_mensagem(ANA, "Não"))
        self.assertEqual(self.ids(ANA)[1], self.ids(BIA)[1])
        self.send_text.assert_not_called()

    def test_sem_casal_nao_ha_o_que_sair(self):
        self.cadastrar(CAIO, "Caio")
        self.assertIn("não está em um casal", processar_mensagem(CAIO, "/sair_casal"))

    def test_sim_separa_em_duas_contas_individuais(self):
        _, resposta = self.sair()
        self.assertIn("voltou ao modo individual", resposta)
        conta_ana, conta_bia = self.ids(ANA)[1], self.ids(BIA)[1]
        self.assertNotEqual(conta_ana, conta_bia)
        for conta in (conta_ana, conta_bia):
            modo = self.sql("SELECT mode, privacy_mode FROM accounts WHERE id = :c", c=conta).one()
            self.assertEqual(tuple(modo), ("individual", "junto"))
            self.assertEqual(self.sql("SELECT count(*) FROM members WHERE account_id = :c", c=conta).scalar(), 1)
        self.assertEqual(self.sql("SELECT count(*) FROM accounts WHERE id = :c", c=self.conta_antiga).scalar(), 0)
        self.assertEqual(self.sql("SELECT count(*) FROM transactions WHERE account_id = :c",
                                  c=self.conta_antiga).scalar(), 0)  # nada sobrou na conta antiga
        rendas = {t: r for t, r in self.sql(
            "SELECT u.phone_number, m.expected_income FROM members m JOIN users u ON u.id = m.user_id"
            " WHERE m.account_id IN (:a, :b)", a=conta_ana, b=conta_bia).all()}
        self.assertEqual(rendas, {ANA: 4500, BIA: 3000})

    def test_cada_um_fica_com_seus_meu_e_os_dois_com_o_historico_conjunto(self):
        self.sair()
        da_ana = processar_mensagem(ANA, "/resumo")
        self.assertIn("Entradas: R$ 5.000,00", da_ana)  # cópia do histórico conjunto
        self.assertIn("• Fixo: R$ 100,00", da_ana)
        self.assertIn("• Variável: R$ 700,00", da_ana)  # o "meu" dela
        self.assertIn("Saídas: R$ 800,00", da_ana)
        da_bia = processar_mensagem(BIA, "/resumo")
        self.assertIn("Entradas: R$ 5.000,00", da_bia)
        self.assertIn("• Fixo: R$ 100,00", da_bia)
        self.assertIn("• Variável: R$ 40,00", da_bia)  # o "meu" dela
        self.assertIn("Saídas: R$ 140,00", da_bia)
        self.assertNotIn("700", da_bia)  # o "meu" da Ana não foi para a Bia
        self.assertNotIn("parceiro", da_bia + da_ana)

    def test_o_meu_de_um_nao_aparece_na_conta_do_outro(self):
        self.sair()
        descricoes_bia = {d for (d,) in self.sql(
            "SELECT description FROM transactions WHERE account_id = :c", c=self.ids(BIA)[1]).all()}
        descricoes_ana = {d for (d,) in self.sql(
            "SELECT description FROM transactions WHERE account_id = :c", c=self.ids(ANA)[1]).all()}
        self.assertEqual(descricoes_bia, {"Salário", "aluguel", "terapia"})
        self.assertEqual(descricoes_ana, {"Salário", "aluguel", "presente surpresa"})

    def test_metas_conjuntas_copiadas_e_individuais_ficam_com_o_dono(self):
        self.sair()
        da_ana, da_bia = processar_mensagem(ANA, "/metas"), processar_mensagem(BIA, "/metas")
        self.assertNotIn("Metas do casal", da_ana + da_bia)  # voltaram ao modo individual
        self.assertIn("Fixo: R$ 2.000,00", da_ana)  # meta do casal: cópia para os dois
        self.assertIn("Fixo: R$ 2.000,00", da_bia)
        self.assertIn("Variável: R$ 650,00", da_ana)  # a individual de cada um
        self.assertNotIn("300", da_ana)
        self.assertIn("Variável: R$ 300,00", da_bia)
        self.assertNotIn("650", da_bia)

    def test_contas_parcelas_objetivos_e_regras(self):
        self.sair()
        usuario_ana, conta_ana = self.ids(ANA)
        usuario_bia, conta_bia = self.ids(BIA)
        self.assertEqual({c.nome for c in _contas(conta_ana, usuario_ana)}, {"Aluguel"})
        self.assertEqual({c.nome for c in _contas(conta_bia, usuario_bia)}, {"Aluguel", "Terapia"})
        self.assertEqual({p.nome for p in listar_parcelas(conta_ana, usuario_ana)}, {"Geladeira", "Moto"})
        self.assertEqual({p.nome for p in listar_parcelas(conta_bia, usuario_bia)}, {"Geladeira"})
        for conta in (conta_ana, conta_bia):
            self.assertEqual(self.sql("SELECT count(*) FROM savings_goals WHERE account_id = :c", c=conta).scalar(), 1)
            self.assertEqual(self.sql("SELECT count(*) FROM savings_contributions WHERE account_id = :c", c=conta).scalar(), 1)
            self.assertEqual(self.sql("SELECT count(*) FROM classification_rules WHERE account_id = :c", c=conta).scalar(), 1)
            # a regra aponta para uma categoria da própria conta nova
            self.assertEqual(self.sql(
                "SELECT count(*) FROM classification_rules r JOIN categories c ON c.id = r.category_id"
                " WHERE r.account_id = :c AND c.account_id = :c", c=conta).scalar(), 1)

    def test_parceiro_e_avisado_na_hora(self):
        self.sair()
        self.send_text.assert_called_once()
        destino, mensagem = self.send_text.call_args.args
        self.assertEqual(destino, BIA)
        self.assertIn("Ana saiu do casal", mensagem)
        self.assertEqual(pegar_avisos(BIA), [])

    def test_se_nao_da_para_avisar_o_aviso_espera_a_proxima_mensagem(self):
        self.send_text.side_effect = RuntimeError("fora da janela de 24h")
        _, resposta = self.sair()
        self.assertIn("Não consegui avisar Bia", resposta)
        avisos = pegar_avisos(BIA)
        self.assertEqual(len(avisos), 1)
        self.assertIn("Ana saiu do casal", avisos[0])
        self.assertEqual(pegar_avisos(BIA), [])  # chega uma vez só
        self.assertEqual(pegar_avisos(ANA), [])

    def test_conversa_aberta_do_parceiro_e_descartada(self):
        self.conversa.salvar(BIA, "gasto", {"categoria_id": "cat-antiga"})
        self.sair()
        self.assertIsNone(self.conversa.ler(BIA))

    def test_depois_de_sair_cada_um_pode_formar_outro_casal(self):
        self.sair()
        self.cadastrar(CAIO, "Caio", 2000)
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem(BIA, "/casal")).group(1)
        time.sleep(0.01)
        processar_mensagem(CAIO, f"/entrar {codigo}")
        self.assertEqual(self.ids(BIA)[1], self.ids(CAIO)[1])
        self.assertNotEqual(self.ids(BIA)[1], self.ids(ANA)[1])
        # quem saiu antes também entra em outro casal
        self.cadastrar("5511944440004", "Duda")
        codigo = re.search(r"código do casal: (\w+)", processar_mensagem("5511944440004", "/casal")).group(1)
        time.sleep(0.01)
        self.assertIsInstance(processar_mensagem(ANA, f"/entrar {codigo}"), Resposta)

    def test_so_o_primeiro_a_confirmar_separa(self):
        usuario, conta = self.ids(ANA)
        self.assertIsNotNone(separar_casal(usuario, conta))
        self.assertIsNone(separar_casal(usuario, conta))  # a conta antiga já não existe como casal

    def test_se_der_erro_no_meio_nada_muda(self):
        antes = self.sql("SELECT count(*) FROM accounts").scalar()
        usuario, conta = self.ids(ANA)
        with patch("app.comandos.sair_casal._copiar_dados", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                separar_casal(usuario, conta)
        self.assertEqual(self.sql("SELECT count(*) FROM accounts").scalar(), antes)
        self.assertEqual(self.ids(ANA)[1], self.ids(BIA)[1])
        self.assertEqual(self.sql("SELECT mode FROM accounts WHERE id = :c", c=conta).scalar(), "couple")


if __name__ == "__main__":
    unittest.main()
