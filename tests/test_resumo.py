import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app import financas
from app.comandos import frase_pela_ia
from app.comandos.resumo import comando_resumo, montar_resumo

USUARIO = "5511988887777"
D = Decimal


def totais(entradas="0", **por_tipo):
    resultado = financas.Totais()
    resultado.entradas = D(entradas)
    resultado.por_tipo = {tipo.replace("_", " "): D(v) for tipo, v in por_tipo.items()}
    return resultado


class TestPeriodos(unittest.TestCase):
    def test_mes(self):
        self.assertEqual(
            financas.periodos_do_mes(date(2026, 10, 16)),
            (date(2026, 10, 1), date(2026, 10, 16), date(2026, 9, 1), date(2026, 9, 16)),
        )

    def test_mes_anterior_mais_curto(self):
        # 31/03 compara com fevereiro inteiro (28 dias em 2026)
        self.assertEqual(financas.periodos_do_mes(date(2026, 3, 31))[2:], (date(2026, 2, 1), date(2026, 2, 28)))

    def test_virada_do_ano(self):
        self.assertEqual(financas.periodos_do_mes(date(2026, 1, 5))[2:], (date(2025, 12, 1), date(2025, 12, 5)))

    def test_semana(self):
        # 16/10/2026 é sexta: semana começa na segunda 12/10
        self.assertEqual(
            financas.periodos_da_semana(date(2026, 10, 16)),
            (date(2026, 10, 12), date(2026, 10, 16), date(2026, 10, 5), date(2026, 10, 9)),
        )


class TestTotais(unittest.TestCase):
    def test_somar_respeita_privacidade(self):
        linhas = [
            ("income", None, False, D("5000")),
            ("expense", "Fixo", False, D("800")),
            ("expense", "Fixo", False, D("100")),
            ("expense", None, False, D("10")),
            ("expense", "Variável", True, D("70")),  # "meu" do parceiro: sem detalhe
        ]
        resultado = financas.somar(linhas)
        self.assertEqual(resultado.entradas, D("5000"))
        self.assertEqual(resultado.por_tipo, {"Fixo": D("900"), "Sem categoria": D("10")})
        self.assertEqual(resultado.pessoais_do_parceiro, D("70"))
        self.assertEqual(resultado.saidas, D("980"))
        self.assertEqual(resultado.saldo, D("4020"))

    def test_variacao(self):
        self.assertEqual(financas.variacao_pct(D("110"), D("100")), 10)
        self.assertEqual(financas.variacao_pct(D("50"), D("100")), -50)
        self.assertIsNone(financas.variacao_pct(D("50"), D("0")))


class TestTexto(unittest.TestCase):
    PERIODOS = financas.periodos_do_mes(date(2026, 10, 16))

    def test_resumo_com_variacao(self):
        atual = totais("5000", Fixo="1200", Variável="300")
        anterior = totais("5000", Fixo="1000", Variável="500")
        texto = montar_resumo("Resumo de outubro/2026", self.PERIODOS, atual, anterior)
        self.assertIn("Entradas: R$ 5.000,00 (igual)", texto)
        self.assertIn("Saídas: R$ 1.500,00 (igual)", texto)
        self.assertIn("• Fixo: R$ 1.200,00", texto)
        self.assertIn("Saldo: R$ 3.500,00", texto)
        self.assertLess(texto.index("Fixo"), texto.index("Variável"))  # maior primeiro

    def test_variacao_percentual_e_saldo_negativo(self):
        atual = totais("1000", Variável="1500")
        anterior = totais("2000", Variável="1000")
        texto = montar_resumo("Resumo", self.PERIODOS, atual, anterior)
        self.assertIn("Entradas: R$ 1.000,00 (-50%)", texto)
        self.assertIn("Saídas: R$ 1.500,00 (+50%)", texto)
        self.assertIn("Saldo: -R$ 500,00", texto)
        self.assertIn("gastou mais do que entrou", texto)

    def test_sem_mes_anterior_avisa(self):
        texto = montar_resumo("Resumo", self.PERIODOS, totais("100"), totais())
        self.assertIn("Sem registros em 01 a 16/09", texto)

    def test_pessoais_do_parceiro_so_total(self):
        atual = totais("100", Fixo="10")
        atual.pessoais_do_parceiro = D("30")
        texto = montar_resumo("Resumo", self.PERIODOS, atual, totais())
        self.assertIn("Saídas: R$ 40,00", texto)
        self.assertIn("Gastos pessoais do parceiro: R$ 30,00", texto)


@patch("app.comandos.resumo.conta_do_usuario", return_value=("u1", "c1"))
@patch("app.comandos.resumo.financas.hoje", return_value=date(2026, 10, 16))
class TestComando(unittest.TestCase):
    @patch("app.comandos.resumo.financas.totais_do_periodo")
    def test_mes_consulta_mes_atual_e_anterior(self, consulta, *_):
        consulta.side_effect = [totais("100"), totais("50")]
        texto = comando_resumo(USUARIO, "")
        self.assertIn("Resumo de outubro/2026 (01 a 16/10)", texto)
        self.assertIn("(+100%)", texto)
        self.assertEqual(consulta.call_args_list[0].args[2:], (date(2026, 10, 1), date(2026, 10, 16)))
        self.assertEqual(consulta.call_args_list[1].args[2:], (date(2026, 9, 1), date(2026, 9, 16)))

    @patch("app.comandos.resumo.financas.totais_do_periodo")
    def test_semana(self, consulta, *_):
        consulta.side_effect = [totais("100"), totais()]
        self.assertIn("Resumo da semana (12 a 16/10)", comando_resumo(USUARIO, "Semana"))

    @patch("app.comandos.resumo.financas.totais_do_periodo", return_value=totais())
    def test_sem_registros(self, *_):
        self.assertIn("Ainda não há registros", comando_resumo(USUARIO, ""))

    @patch("app.comandos.resumo.financas.totais_do_periodo")
    def test_argumento_estranho_nao_consulta(self, consulta, *_):
        self.assertIn("/resumo semana", comando_resumo(USUARIO, "ano"))
        consulta.assert_not_called()


@patch("app.comandos.limpar_estado")
class TestFraseLivrePelaIA(unittest.TestCase):
    @patch("app.comandos.COMANDOS_COM_USUARIO", {"resumo": lambda tel, args: f"resumo:{args}"})
    @patch("app.comandos.ia.identificar_comando", return_value=("resumo", "semana"))
    def test_executa_o_comando_escolhido(self, ia, limpar):
        self.assertEqual(frase_pela_ia(USUARIO, "como foi minha semana?"), "resumo:semana")

    @patch("app.comandos.ia.identificar_comando", return_value=("apagar_meus_dados", ""))
    def test_nunca_apaga_por_frase_livre(self, ia, limpar):
        self.assertIsNone(frase_pela_ia(USUARIO, "quero sumir daqui"))

    @patch("app.comandos.ia.identificar_comando", return_value=("liberar", "123"))
    def test_comando_de_admin_nao_passa(self, ia, limpar):
        self.assertIsNone(frase_pela_ia(USUARIO, "libera o 123"))

    @patch("app.comandos.ia.identificar_comando", return_value=None)
    def test_ia_nao_entendeu(self, ia, limpar):
        self.assertIsNone(frase_pela_ia(USUARIO, "bom dia"))

    @patch("app.comandos.ajuda.eh_admin", return_value=False)
    @patch("app.comandos.ajuda.cadastro_completo", return_value=True)  # sem acessar o banco
    @patch("app.comandos.ia.identificar_comando", return_value=("ajuda", ""))
    def test_comando_sem_usuario(self, ia, *_):
        self.assertIn("Dona Fatura - comandos", frase_pela_ia(USUARIO, "o que você faz?"))


class TestIdentificarComando(unittest.TestCase):
    def _rodar(self, resposta):
        from app import ia
        with patch.object(ia, "pedir_json", return_value=resposta):
            return ia.identificar_comando("qualquer coisa")

    def test_formatos(self):
        self.assertEqual(self._rodar({"comando": "/Resumo", "argumentos": " semana "}), ("resumo", "semana"))
        self.assertEqual(self._rodar({"comando": "ajuda"}), ("ajuda", ""))
        self.assertIsNone(self._rodar({"comando": None}))
        self.assertIsNone(self._rodar(None))


if __name__ == "__main__":
    unittest.main()
