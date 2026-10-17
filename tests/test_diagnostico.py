import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app import financas
from app.comandos.diagnostico import comando_diagnostico, montar_diagnostico, texto_final

D = Decimal
HOJE = date(2026, 10, 16)  # faltam 15 dias


def itens(metas, real, variaveis=D("0")):
    return financas.diagnosticar(metas, real, variaveis)


class TestCalculo(unittest.TestCase):
    def test_dentro_da_meta(self):
        [item] = itens({"Variável": D("1000")}, {"Variável": D("400")}, D("300"))
        self.assertEqual(item.situacao, "ok")

    def test_vai_estourar_corta_por_semana(self):
        # gastou 800, deve gastar mais 400 -> fecha em 1200 (meta 1000): corte de 200 em 15 dias
        [item] = itens({"Variável": D("1000")}, {"Variável": D("800")}, D("400"))
        self.assertEqual(item.situacao, "vai_estourar")
        self.assertEqual(item.projetado, D("1200"))
        self.assertEqual(item.ajuste, D("200"))
        self.assertEqual(financas.ajuste_por_semana(item, 14), D("100.00"))

    def test_estourou(self):
        [item] = itens({"Variável": D("1000")}, {"Variável": D("1100")}, D("200"))
        self.assertEqual(item.situacao, "estourou")
        self.assertEqual(item.excesso, D("100"))

    def test_investimento_abaixo_do_minimo(self):
        [item] = itens({"Investimento": D("500")}, {"Investimento": D("200")})
        self.assertEqual(item.situacao, "falta")
        self.assertEqual(item.ajuste, D("300"))

    def test_investimento_acima_do_minimo_esta_ok(self):
        [item] = itens({"Investimento": D("500")}, {"Investimento": D("600")})
        self.assertEqual(item.situacao, "ok")

    def test_ultima_semana_nao_divide_por_menos_de_uma_semana(self):
        [item] = itens({"Variável": D("100")}, {"Variável": D("50")}, D("100"))
        self.assertEqual(financas.ajuste_por_semana(item, 2), D("50.00"))

    def test_so_tipos_com_meta(self):
        self.assertEqual(len(itens({"Fixo": D("10")}, {"Fixo": D("5"), "Lazer": D("9")})), 1)


class TestTexto(unittest.TestCase):
    def test_panorama_ajustes_e_saldo(self):
        lista = itens(
            {"Variável": D("1000"), "Fixo": D("2000"), "Investimento": D("500")},
            {"Variável": D("800"), "Fixo": D("1500"), "Investimento": D("100")},
            D("400"),
        )
        texto = montar_diagnostico(lista, HOJE, D("1700"))
        self.assertIn("outubro/2026", texto)
        self.assertIn("✅ Fixo: R$ 1.500,00 de R$ 2.000,00", texto)
        self.assertIn("❌ Variável: R$ 800,00 de R$ 1.000,00", texto)
        self.assertIn("❌ Investimento: R$ 100,00 de R$ 500,00", texto)
        self.assertIn("ficar abaixo da meta", texto)
        self.assertIn("Variável: fecha em R$ 1.200,00; corte R$ 93,33 por semana até 31/10", texto)
        self.assertIn("Investimento: guarde R$ 186,67 por semana até 31/10", texto)
        self.assertNotIn("Fixo: guarde", texto)
        self.assertTrue(texto.endswith("Saldo previsto no fim do mês: R$ 1.700,00"))

    def test_perto_do_limite(self):
        [item] = itens({"Variável": D("1000")}, {"Variável": D("500")}, D("450"))
        self.assertEqual(item.sinal, "⚠️")
        [minimo] = itens({"Reserva de emergência": D("100")}, {"Reserva de emergência": D("95")})
        self.assertEqual(minimo.sinal, "⚠️")

    def test_tipos_sem_meta_sugerem_metas(self):
        texto = montar_diagnostico(itens({"Fixo": D("2000")}, {}), HOJE, D("0"))
        self.assertIn("Sem meta: Variável, Assinatura, Investimento, Reserva de emergência. Defina em /metas.", texto)
        self.assertNotIn("Ajustes:", texto)

    def test_nota_de_gastos_pessoais_do_parceiro(self):
        texto = montar_diagnostico(itens({"Fixo": D("2000")}, {}), HOJE, D("0"), D("150"))
        self.assertIn("R$ 150,00 de gastos pessoais do parceiro", texto)


class TestIA(unittest.TestCase):
    FATOS = "Variável: gastou R$ 800,00 de R$ 1.000,00. Corte R$ 93,33 por semana até 31/10."

    def test_usa_o_texto_da_ia(self):
        with patch("app.ia.escrever_diagnostico", return_value="Variável: R$ 800,00 de R$ 1.000,00. Corte R$ 93,33 por semana."):
            self.assertTrue(texto_final(self.FATOS).startswith("Variável: R$ 800,00"))

    def test_numero_inventado_volta_ao_texto_pronto(self):
        with patch("app.ia.escrever_diagnostico", return_value="Corte R$ 150,00 por semana."):
            self.assertEqual(texto_final(self.FATOS), self.FATOS)

    def test_ia_desligada_volta_ao_texto_pronto(self):
        with patch("app.ia.escrever_diagnostico", return_value=None):
            self.assertEqual(texto_final(self.FATOS), self.FATOS)


class TestComando(unittest.TestCase):
    def _rodar(self, metas, renda=D("5000")):
        previsao = financas.calcular_previsao(D("5000"), D("800"), D("0"), D("26.67"), 15)
        totais = financas.Totais()
        totais.entradas = D("5000")
        totais.por_tipo = {"Variável": D("800")}
        with patch("app.comandos.diagnostico.financas.hoje", return_value=HOJE), \
             patch("app.comandos.diagnostico.conta_do_usuario", return_value=(1, 1)), \
             patch("app.comandos.diagnostico.ler_renda_conjunta", return_value=renda), \
             patch("app.comandos.diagnostico.conta_em_casal", return_value=False), \
             patch("app.comandos.diagnostico.ler_metas", return_value=metas), \
             patch("app.comandos.diagnostico.financas.totais_do_periodo", return_value=totais), \
             patch("app.comandos.diagnostico.financas.previsao_do_mes", return_value=previsao), \
             patch("app.ia.escrever_diagnostico", return_value=None):
            return comando_diagnostico("5511988887777", "")

    def test_sem_metas(self):
        self.assertIn("ainda não tem metas", self._rodar({}))

    def test_meta_em_porcentagem_vira_reais(self):
        # 20% de 5000 = 1000; gastou 800, +400 previstos -> estoura
        texto = self._rodar({"Variável": ("percentage", D("20"))})
        self.assertIn("de R$ 1.000,00", texto)
        self.assertIn("corte", texto)
        self.assertIn("Saldo previsto", texto)


if __name__ == "__main__":
    unittest.main()
