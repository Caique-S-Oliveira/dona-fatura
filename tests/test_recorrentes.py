import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.comandos import COMANDOS_COM_USUARIO
from app.comandos.categorias import Categoria
from app.comandos.fixos import SEM_CONTAS, comando_fixos, montar_fixos
from app.comandos.gasto import finalizar_registro
from app.comandos.recorrentes import (
    ContaRecorrente,
    avancar_vencimento,
    continuar_recorrente,
    meses_parecidos,
    parecido,
    proximo_mes,
    verificar_recorrente,
)
from app.comandos.resposta import Resposta

USUARIO = "5511988887777"
D = Decimal
HOJE = date(2026, 10, 16)
NETFLIX = Categoria("9", "Lazer", "Assinatura")
DADOS = {"valor": "39.90", "descricao": "Netflix", "escopo": "conjunto"}


def conta(nome, valor, proximo, frequencia="monthly", ativa=True):
    return ContaRecorrente("r1", nome, D(valor), frequencia, proximo, ativa)


class TestRegras(unittest.TestCase):
    def test_valor_parecido_ate_10_por_cento(self):
        self.assertTrue(parecido(D("39.90"), D("42")))
        self.assertFalse(parecido(D("39.90"), D("60")))

    def test_conta_meses_diferentes_incluindo_o_atual(self):
        historico = [(date(2026, 9, 10), D("40")), (date(2026, 9, 25), D("40")), (date(2026, 8, 10), D("300"))]
        self.assertEqual(meses_parecidos(D("39.90"), HOJE, historico), 2)  # outubro + setembro
        self.assertEqual(meses_parecidos(D("39.90"), HOJE, []), 1)

    def test_proximo_mes_ajusta_fim_de_mes(self):
        self.assertEqual(proximo_mes(date(2026, 10, 16)), date(2026, 11, 16))
        self.assertEqual(proximo_mes(date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(proximo_mes(date(2026, 12, 5)), date(2027, 1, 5))

    def test_avancar_vencimento(self):
        self.assertEqual(avancar_vencimento(date(2026, 10, 20), date(2026, 10, 18)), date(2026, 11, 20))
        self.assertIsNone(avancar_vencimento(date(2026, 11, 20), date(2026, 10, 18)))  # já adiantado
        self.assertIsNone(avancar_vencimento(None, date(2026, 10, 18)))


@patch("app.comandos.recorrentes.financas.hoje", return_value=HOJE)
@patch("app.comandos.recorrentes.salvar_estado")
class TestDeteccao(unittest.TestCase):
    @patch("app.comandos.recorrentes._historico", return_value=[(date(2026, 9, 16), D("39.90"))])
    @patch("app.comandos.recorrentes.contas_da_conta", return_value=[])
    def test_dois_meses_parecidos_pergunta_com_botoes(self, _contas, _hist, salvar, _hoje):
        resposta = verificar_recorrente(USUARIO, "c1", "u1", DADOS, NETFLIX)
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        self.assertIn("Netflix", resposta.texto)
        self.assertIn("2 meses", resposta.texto)
        estado = salvar.call_args.args
        self.assertEqual(estado[1], "recorrente")
        self.assertEqual(estado[2]["data"], "2026-10-16")

    @patch("app.comandos.recorrentes._historico", return_value=[])
    @patch("app.comandos.recorrentes.contas_da_conta", return_value=[])
    def test_primeiro_mes_nao_pergunta(self, _contas, _hist, salvar, _hoje):
        self.assertIsNone(verificar_recorrente(USUARIO, "c1", "u1", DADOS, NETFLIX))
        salvar.assert_not_called()

    @patch("app.comandos.recorrentes._historico", return_value=[(date(2026, 9, 16), D("200"))])
    @patch("app.comandos.recorrentes.contas_da_conta", return_value=[])
    def test_valor_muito_diferente_nao_pergunta(self, _contas, _hist, salvar, _hoje):
        self.assertIsNone(verificar_recorrente(USUARIO, "c1", "u1", DADOS, NETFLIX))

    @patch("app.comandos.recorrentes._historico", return_value=[(date(2026, 9, 16), D("39.90"))])
    @patch("app.comandos.recorrentes.contas_da_conta", return_value=[conta("netflix", "39.90", None, ativa=False)])
    def test_ja_respondida_nao_pergunta_de_novo(self, _contas, _hist, salvar, _hoje):
        self.assertIsNone(verificar_recorrente(USUARIO, "c1", "u1", DADOS, NETFLIX))
        salvar.assert_not_called()

    @patch("app.comandos.recorrentes._guardar_vencimento")
    @patch("app.comandos.recorrentes.contas_da_conta", return_value=[conta("Netflix", "39.90", date(2026, 10, 20))])
    def test_conta_conhecida_avanca_o_vencimento(self, _contas, guardar, salvar, _hoje):
        self.assertIsNone(verificar_recorrente(USUARIO, "c1", "u1", DADOS, NETFLIX))
        guardar.assert_called_once_with("c1", "r1", date(2026, 11, 20))

    @patch("app.comandos.recorrentes.contas_da_conta")
    def test_comprovante_sem_favorecido_nao_entra(self, contas, salvar, _hoje):
        self.assertIsNone(verificar_recorrente(USUARIO, "c1", "u1", {**DADOS, "aprender": False}, NETFLIX))
        contas.assert_not_called()


@patch("app.comandos.recorrentes.limpar_estado")
@patch("app.comandos.recorrentes.conta_do_usuario", return_value=("u1", "c1"))
class TestResposta(unittest.TestCase):
    ESTADO = {"nome": "Netflix", "valor": "39.90", "data": "2026-10-16", "categoria_id": "9",
              "escopo": "conjunto", "meses": 2}

    @patch("app.comandos.recorrentes._criar")
    def test_sim_cria_conta_ativa(self, criar, _conta, limpar):
        texto = continuar_recorrente(USUARIO, self.ESTADO, "Sim")
        criar.assert_called_once_with("c1", "u1", self.ESTADO, True)
        self.assertIn("16/11/2026", texto)
        limpar.assert_called_once()

    @patch("app.comandos.recorrentes._criar")
    def test_nao_guarda_como_dispensada(self, criar, _conta, _limpar):
        texto = continuar_recorrente(USUARIO, self.ESTADO, "Não")
        criar.assert_called_once_with("c1", "u1", self.ESTADO, False)
        self.assertIn("não pergunto mais", texto)

    @patch("app.comandos.recorrentes._criar")
    def test_outra_resposta_repete_a_pergunta(self, criar, _conta, limpar):
        resposta = continuar_recorrente(USUARIO, self.ESTADO, "talvez")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        criar.assert_not_called()
        limpar.assert_not_called()


@patch("app.comandos.gasto.limpar_estado")
class TestFinalizar(unittest.TestCase):
    @patch("app.comandos.gasto.verificar_recorrente", return_value=None)
    def test_sem_recorrencia_devolve_so_o_texto(self, _v, limpar):
        self.assertEqual(finalizar_registro(USUARIO, "c1", "u1", DADOS, NETFLIX, "Anotado."), "Anotado.")
        limpar.assert_called_once()

    def test_com_recorrencia_junta_texto_e_botoes(self, _limpar):
        pergunta = Resposta("É recorrente?", ("Sim", "Não"))
        with patch("app.comandos.gasto.verificar_recorrente", return_value=pergunta):
            resposta = finalizar_registro(USUARIO, "c1", "u1", DADOS, NETFLIX, "Anotado.")
        self.assertEqual(resposta.texto, "Anotado.\nÉ recorrente?")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))


class TestFixos(unittest.TestCase):
    def test_pagas_a_vencer_e_atrasadas(self):
        contas = [
            conta("Aluguel", "1200", date(2026, 11, 5)),
            conta("Netflix", "39.90", date(2026, 11, 20)),
            conta("Internet", "100", date(2026, 11, 10)),
        ]
        gastos = [("aluguel", date(2026, 10, 5), D("1200"))]
        linhas = montar_fixos(contas, gastos, HOJE).splitlines()
        self.assertEqual(linhas[0], "Fixos de outubro (3 contas):")
        self.assertEqual(linhas[1], "✅ Aluguel R$ 1.200,00 — pago em 05/10")
        self.assertEqual(linhas[2], "⚠️ Internet R$ 100,00 — venceu dia 10, não achei o pagamento")
        self.assertEqual(linhas[3], "⏳ Netflix R$ 39,90 — vence dia 20")
        self.assertEqual(linhas[4], "Pago R$ 1.200,00. Ainda falta R$ 139,90.")

    def test_pagamento_casa_sem_acento_e_maiuscula(self):
        texto = montar_fixos([conta("Padaria Pão", "50", date(2026, 11, 3))],
                             [("padaria pao", date(2026, 10, 3), D("52"))], HOJE)
        self.assertIn("✅ Padaria Pão R$ 52,00", texto)

    def test_vence_hoje(self):
        self.assertIn("vence hoje", montar_fixos([conta("Luz", "90", date(2026, 11, 16))], [], HOJE))

    def test_anual_so_aparece_no_mes_do_vencimento(self):
        anual = conta("Seguro", "800", date(2026, 12, 3), frequencia="yearly")
        self.assertEqual(montar_fixos([anual], [], HOJE), SEM_CONTAS)

    def test_dia_31_em_mes_curto(self):
        texto = montar_fixos([conta("Plano", "10", date(2026, 3, 31))], [], date(2026, 2, 10))
        self.assertIn("vence dia 28", texto)

    def test_sem_contas(self):
        self.assertEqual(montar_fixos([], [], HOJE), SEM_CONTAS)

    def test_comando_registrado(self):
        self.assertIs(COMANDOS_COM_USUARIO["fixos"], comando_fixos)
