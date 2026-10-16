import unittest
from decimal import Decimal
from unittest.mock import patch

from app.comandos import processar_mensagem
from app.comandos.formato import formatar_pct, formatar_reais, ler_numero
from app.comandos.inicio import MSG_PRIVACIDADE, mensagem_final, proximo_passo
from app.comandos.metas import achar_tipo, aviso_acima_da_renda, validar_meta

USUARIO = "5511988887777"


class TestFormato(unittest.TestCase):
    def test_ler_numero(self):
        self.assertEqual(ler_numero("4500"), Decimal("4500.00"))
        self.assertEqual(ler_numero("4.500,00"), Decimal("4500.00"))
        self.assertEqual(ler_numero("R$ 45,90"), Decimal("45.90"))
        self.assertEqual(ler_numero("4.500"), Decimal("4500.00"))
        self.assertEqual(ler_numero("45.90"), Decimal("45.90"))
        self.assertEqual(ler_numero("30%"), Decimal("30.00"))
        self.assertIsNone(ler_numero("muito"))
        self.assertIsNone(ler_numero("1,2,3"))

    def test_formatar(self):
        self.assertEqual(formatar_reais(Decimal("1234.5")), "R$ 1.234,50")
        self.assertEqual(formatar_pct(Decimal("30.00")), "30%")
        self.assertEqual(formatar_pct(Decimal("12.50")), "12,5%")


class TestInicio(unittest.TestCase):
    def conversa(self, *respostas):
        dados = {"passo": "nome"}
        for resposta in respostas:
            mensagem, dados = proximo_passo(dados, resposta)
        return mensagem, dados

    def test_fluxo_em_reais(self):
        _, dados = self.conversa("Ana", "4.500,00", "1", "2000", "1500", "0", "300", "200")
        self.assertEqual(dados["passo"], "fim")
        self.assertEqual(dados["renda"], "4500.00")
        self.assertEqual(dados["formato"], "amount")
        self.assertNotIn("Assinatura", dados["metas"])  # 0 = pular
        texto = mensagem_final(dados)
        self.assertIn("Pronto, Ana!", texto)
        self.assertIn("Fixo: R$ 2.000,00", texto)
        self.assertIn(MSG_PRIVACIDADE, texto)

    def test_atalho_50_30_20(self):
        _, dados = self.conversa("Ana", "4000", "3")
        self.assertEqual(dados["passo"], "fim")
        self.assertIn("Fixo: 50% (R$ 2.000,00)", mensagem_final(dados))

    def test_pct_nao_passa_de_100(self):
        mensagem, dados = self.conversa("Ana", "4000", "2", "60", "50")
        self.assertIn("passa de 100%", mensagem)
        self.assertIn("40%", mensagem)
        self.assertEqual(dados["indice"], 1)  # continua perguntando o mesmo tipo

    def test_renda_invalida_pergunta_de_novo(self):
        mensagem, dados = self.conversa("Ana", "não sei")
        self.assertEqual(dados["passo"], "renda")
        self.assertIn("Não entendi", mensagem)

    def test_formato_invalido(self):
        mensagem, dados = self.conversa("Ana", "4000", "talvez")
        self.assertEqual(dados["passo"], "formato")

    def test_aviso_metas_acima_da_renda(self):
        metas = {"Fixo": ("amount", Decimal("3000")), "Variável": ("amount", Decimal("2000"))}
        self.assertIn("acima da renda", aviso_acima_da_renda(metas, Decimal("4000")))


class TestMetas(unittest.TestCase):
    def test_achar_tipo(self):
        self.assertEqual(achar_tipo("variavel"), "Variável")
        self.assertEqual(achar_tipo("fixos"), "Fixo")
        self.assertEqual(achar_tipo("reserva de emergencia"), "Reserva de emergência")
        self.assertIsNone(achar_tipo("xyz"))

    def test_validar_pct(self):
        metas = {"Fixo": ("percentage", Decimal("50")), "Variável": ("percentage", Decimal("30"))}
        self.assertIsNone(validar_meta(metas, "Variável", "percentage", Decimal("50")))
        self.assertIn("até 20%", validar_meta(metas, "Investimento", "percentage", Decimal("30")))
        self.assertIsNone(validar_meta(metas, "Investimento", "amount", Decimal("5000")))


@patch("app.comandos.garantir_usuario", return_value=False)
@patch("app.comandos.status_acesso", return_value="ativo")
@patch("app.comandos.limpar_estado")
class TestRoteamento(unittest.TestCase):
    @patch("app.comandos.inicio.salvar_estado")
    def test_inicio_comeca_conversa(self, salvar, *_):
        self.assertIn("como você quer ser chamado", processar_mensagem(USUARIO, "/inicio"))
        salvar.assert_called_once_with(USUARIO, "inicio", {"passo": "nome"})

    @patch("app.comandos.inicio.salvar_estado")
    @patch("app.comandos.ler_estado", return_value=("inicio", {"passo": "nome"}))
    def test_resposta_vai_para_conversa(self, _ler, salvar, *_):
        self.assertIn("Prazer, Ana", processar_mensagem(USUARIO, "Ana"))
        self.assertEqual(salvar.call_args.args[2]["passo"], "renda")

    @patch("app.comandos.ler_estado", return_value=None)
    def test_sem_conversa_frase_livre(self, *_):
        self.assertIn("/ajuda", processar_mensagem(USUARIO, "Ana"))


if __name__ == "__main__":
    unittest.main()
