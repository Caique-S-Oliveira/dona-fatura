import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from app import financas
from app.comandos import entrada, gasto
from app.comandos.formato import separar_data
from app.comandos.previsao import montar_previsao

HOJE = date(2026, 10, 24)
USUARIO = "5511999990000"


class TestSepararData(unittest.TestCase):
    def test_formas_de_data(self):
        self.assertEqual(separar_data("45 mercado dia 3", HOJE), ("45 mercado", date(2026, 10, 3)))
        self.assertEqual(separar_data("45 mercado ontem", HOJE), ("45 mercado", date(2026, 10, 23)))
        self.assertEqual(separar_data("anteontem 45 mercado", HOJE), ("45 mercado", date(2026, 10, 22)))
        self.assertEqual(separar_data("45 mercado 03/10", HOJE), ("45 mercado", date(2026, 10, 3)))
        self.assertEqual(separar_data("45 mercado 03/10/2025", HOJE), ("45 mercado", date(2025, 10, 3)))

    def test_sem_data_e_valor_nao_confundem(self):
        self.assertEqual(separar_data("1.234,56 mercado meu", HOJE), ("1.234,56 mercado meu", None))
        self.assertEqual(separar_data("45 festa dia das mães", HOJE)[1], None)

    def test_data_que_nao_existe(self):
        with self.assertRaises(ValueError):
            separar_data("45 mercado 31/02", HOJE)
        with self.assertRaises(ValueError):
            separar_data("45 mercado dia 40", HOJE)


@patch("app.comandos.gasto.financas.hoje", return_value=HOJE)
@patch("app.comandos.gasto.conta_do_usuario", return_value=("u1", "c1"))
class TestGastoComData(unittest.TestCase):
    @patch("app.comandos.gasto.comecar_gasto", return_value="ok")
    def test_data_vai_nos_dados(self, comecar, *_):
        gasto.comando_gasto(USUARIO, "45 mercado dia 3")
        dados = comecar.call_args[0][2]
        self.assertEqual((dados["data"], dados["descricao"]), ("2026-10-03", "mercado"))

    @patch("app.comandos.gasto.comecar_gasto", return_value="ok")
    def test_sem_data_nao_define(self, comecar, *_):
        gasto.comando_gasto(USUARIO, "45 mercado")
        self.assertNotIn("data", comecar.call_args[0][2])

    @patch("app.comandos.gasto.salvar_estado")
    def test_data_futura_pede_confirmacao(self, salvar, *_):
        resposta = gasto.comando_gasto(USUARIO, "45 mercado 30/10")
        self.assertIn("ainda não chegou", resposta.texto)
        self.assertEqual(salvar.call_args[0][2]["passo"], "data_futura")

    def test_data_invalida(self, *_):
        self.assertIn("Não entendi a data", gasto.comando_gasto(USUARIO, "45 mercado 31/02"))

    @patch("app.comandos.gasto.comecar_gasto", return_value="seguiu")
    def test_confirmar_data_futura(self, comecar, *_):
        dados = {"valor": "45", "descricao": "mercado", "escopo": "conjunto", "data": "2026-10-30",
                 "passo": "data_futura", "escopo_explicito": False}
        self.assertEqual(gasto.continuar_gasto(USUARIO, dados, "Sim"), "seguiu")
        self.assertNotIn("passo", comecar.call_args[0][2])

    @patch("app.comandos.gasto.limpar_estado")
    def test_recusar_data_futura(self, limpar, *_):
        dados = {"valor": "45", "descricao": "x", "escopo": "conjunto", "data": "2026-10-30",
                 "passo": "data_futura"}
        self.assertIn("não registrei", gasto.continuar_gasto(USUARIO, dados, "Não"))
        limpar.assert_called_once()


@patch("app.comandos.entrada.financas.hoje", return_value=HOJE)
class TestEntradaComData(unittest.TestCase):
    @patch("app.comandos.entrada.salvar_estado")
    def test_data_na_confirmacao(self, salvar, *_):
        resposta = entrada.comando_entrada(USUARIO, "4500 salário ontem")
        self.assertEqual(salvar.call_args[0][2]["data"], "2026-10-23")
        self.assertIn("23/10/2026", resposta.texto)

    @patch("app.comandos.entrada.salvar_estado")
    def test_data_futura_avisa(self, salvar, *_):
        resposta = entrada.comando_entrada(USUARIO, "4500 salário 05/11")
        self.assertIn("ainda não chegou", resposta.texto)


class TestMedia(unittest.TestCase):
    def _media(self, primeiro, gastos):
        """gastos: função (inicio, fim) -> total; devolve (média, base)."""
        with patch("app.financas._gasto_variavel", side_effect=lambda c, i, f, u=None: gastos(i, f)):
            return financas.media_diaria_variaveis("c1", HOJE, primeiro=primeiro)

    def test_so_conta_dias_depois_do_primeiro_registro(self):
        # primeiro registro em 01/10: sem histórico nos meses passados; 24 dias no mês atual
        media, base = self._media(date(2026, 10, 1), lambda i, f: D("240") if i == date(2026, 10, 1) else D("0"))
        self.assertEqual((media, base), (D("10"), "mes atual"))

    def test_primeiro_registro_no_meio_do_mes_atual(self):
        # primeiro em 15/10: 10 dias (15..24), não 24
        media, _ = self._media(date(2026, 10, 15), lambda i, f: D("100"))
        self.assertEqual(media, D("10"))

    def test_tres_meses_comeca_no_primeiro_registro(self):
        # primeiro em 01/09: 30 dias de setembro, não os 92 dos 3 meses
        medias = []

        def gastos(i, f):
            medias.append(i)
            return D("300")

        media, base = self._media(date(2026, 9, 1), gastos)
        self.assertEqual((media, base), (D("300") / 30, "3 meses"))
        self.assertEqual(medias[0], date(2026, 9, 1))

    def test_sem_registro_nenhum(self):
        with patch("app.financas.primeiro_registro", return_value=None):
            self.assertEqual(financas.media_diaria_variaveis("c1", HOJE), (D("0"), "mes atual"))


class TestAvisoPoucoHistorico(unittest.TestCase):
    def _previsao(self, dias):
        p = financas.calcular_previsao(D("5000"), D("2000"), D("800"), D("50"), 7)
        p.dias_historico = dias
        return p

    def test_menos_de_14_dias_avisa(self):
        self.assertIn("pouco confiável", montar_previsao(self._previsao(5), HOJE))

    def test_14_dias_ou_mais_nao_avisa(self):
        self.assertNotIn("pouco confiável", montar_previsao(self._previsao(14), HOJE))

    def test_dias_de_historico(self):
        self.assertEqual(financas.dias_de_historico(HOJE, HOJE), 1)
        self.assertEqual(financas.dias_de_historico(None, HOJE), 0)


if __name__ == "__main__":
    unittest.main()
