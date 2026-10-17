import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app import financas, graficos
from app.comandos.previsao import comando_grafico, comando_previsao, montar_previsao
from app.comandos.resposta import Resposta

USUARIO = "5511988887777"
D = Decimal


class TestCalculo(unittest.TestCase):
    def test_formula_do_claude_md(self):
        # 5000 entrou, 2000 saiu, 800 ainda vence, 50/dia x 10 dias = 500
        p = financas.calcular_previsao(D("5000"), D("2000"), D("800"), D("50"), 10)
        self.assertEqual(p.variaveis, D("500.00"))
        self.assertEqual(p.saidas_previstas, D("3300.00"))
        self.assertEqual(p.saldo_final, D("1700.00"))

    def test_ultimo_dia_do_mes_nao_projeta_variaveis(self):
        p = financas.calcular_previsao(D("100"), D("30"), D("0"), D("50"), 0)
        self.assertEqual(p.saldo_final, D("70.00"))

    def test_dias_negativos_viram_zero(self):
        self.assertEqual(financas.calcular_previsao(D("0"), D("0"), D("0"), D("5"), -3).variaveis, D("0.00"))

    def test_ultimo_dia_do_mes(self):
        self.assertEqual(financas.ultimo_dia_do_mes(date(2026, 2, 10)), date(2026, 2, 28))
        self.assertEqual(financas.ultimo_dia_do_mes(date(2026, 12, 31)), date(2026, 12, 31))

    def test_tres_meses_anteriores(self):
        self.assertEqual(financas.tres_meses_anteriores(date(2026, 10, 16)), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(financas.tres_meses_anteriores(date(2026, 2, 3)), (date(2025, 11, 1), date(2026, 1, 31)))


class TestAVencer(unittest.TestCase):
    HOJE = date(2026, 10, 16)

    def test_so_conta_o_que_vence_depois_de_hoje_no_mes(self):
        contas = [
            ("monthly", date(2026, 10, 20), D("100")),  # conta
            ("monthly", date(2026, 10, 16), D("999")),  # vence hoje: já tratado como pago/registrado
            ("monthly", date(2026, 10, 5), D("999")),  # passou
            ("monthly", date(2026, 11, 2), D("999")),  # só no mês que vem
            ("yearly", date(2026, 10, 31), D("50")),  # conta
            ("monthly", None, D("999")),
        ]
        self.assertEqual(financas.valor_a_vencer(contas, self.HOJE), D("150"))

    def test_semanal_conta_cada_ocorrencia(self):
        # vence toda sexta: 23 e 30/10 ainda faltam
        self.assertEqual(financas.valor_a_vencer([("weekly", date(2026, 10, 9), D("10"))], self.HOJE), D("20"))


class TestAcumulado(unittest.TestCase):
    def test_acumula_com_dias_vazios(self):
        self.assertEqual(
            financas.acumular({1: D("10"), 3: D("5")}, 4), [D("10"), D("10"), D("15"), D("15")]
        )


class TestTexto(unittest.TestCase):
    FIM = date(2026, 10, 31)

    def test_texto_curto_e_com_reais(self):
        p = financas.calcular_previsao(D("5000"), D("2000"), D("800"), D("50"), 15)
        texto = montar_previsao(p, self.FIM)
        self.assertIn("Previsão até 31/10 (15 dias restantes)", texto)
        self.assertIn("Já entrou R$ 5.000,00 e saiu R$ 2.000,00", texto)
        self.assertIn("Ainda vence R$ 800,00 e os variáveis devem somar R$ 750,00", texto)
        self.assertIn("Saldo previsto no fim do mês: R$ 1.450,00", texto)
        self.assertLessEqual(len(texto.splitlines()), 5)

    def test_saldo_negativo_avisa_firme(self):
        p = financas.calcular_previsao(D("1000"), D("900"), D("300"), D("20"), 10)
        texto = montar_previsao(p, self.FIM)
        self.assertIn("Saldo previsto no fim do mês: -R$ 400,00", texto)
        self.assertIn("vermelho", texto)

    def test_sem_entradas_pede_entrada(self):
        p = financas.calcular_previsao(D("0"), D("100"), D("0"), D("0"), 5)
        self.assertIn("/entrada", montar_previsao(p, self.FIM))


@patch("app.comandos.previsao.conta_do_usuario", return_value=("u1", "c1"))
@patch("app.comandos.previsao.financas.hoje", return_value=date(2026, 10, 16))
class TestComandos(unittest.TestCase):
    PREVISAO = financas.calcular_previsao(D("5000"), D("2000"), D("800"), D("50"), 15)

    @patch("app.comandos.previsao.financas.previsao_do_mes")
    def test_previsao(self, previsao, *_):
        previsao.return_value = self.PREVISAO
        self.assertIn("Saldo previsto", comando_previsao(USUARIO, ""))

    @patch("app.comandos.previsao.financas.previsao_do_mes")
    def test_sem_registros(self, previsao, *_):
        previsao.return_value = financas.calcular_previsao(D("0"), D("0"), D("0"), D("0"), 15)
        self.assertIn("Ainda não há registros", comando_previsao(USUARIO, ""))
        self.assertIn("Ainda não há registros", comando_grafico(USUARIO, "previsao"))

    @patch("app.comandos.previsao.limite_das_metas", return_value=D("3800"))
    @patch("app.comandos.previsao.financas.gasto_acumulado_por_dia", return_value=[D("100")] * 16)
    @patch("app.comandos.previsao.financas.previsao_do_mes")
    def test_grafico_devolve_imagem_png(self, previsao, *_):
        previsao.return_value = self.PREVISAO
        resposta = comando_grafico(USUARIO, "Previsão")
        self.assertIsInstance(resposta, Resposta)
        self.assertTrue(resposta.imagem.startswith(b"\x89PNG"))
        self.assertIn("metas somam R$ 3.800,00", resposta.texto)

    @patch("app.comandos.previsao.financas.previsao_do_mes")
    def test_outro_grafico_nao_existe(self, previsao, *_):
        self.assertIn("/grafico previsao", comando_grafico(USUARIO, "gastos"))
        previsao.assert_not_called()


class TestGrafico(unittest.TestCase):
    def test_png_com_e_sem_metas(self):
        for limite in (D("3000"), None):
            png = graficos.grafico_previsao([D("10"), D("40")], 31, D("900"), limite, "Teste")
            self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
