import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.comandos import processar_comprovante
from app.comandos.entrada import (
    comando_entrada,
    continuar_entrada,
    gravar_entrada,
    ler_entrada,
    receber_holerite,
)
from app.comandos.resposta import Resposta

USUARIO = "5511988887777"
EXTRAIDO = {"valor": "4.500,00", "data": "05/10/2026"}


class TestLeitura(unittest.TestCase):
    def test_ler_entrada(self):
        self.assertEqual(ler_entrada("4.500,00 salário"), (Decimal("4500.00"), "salário"))
        self.assertEqual(ler_entrada("R$ 300 freela extra"), (Decimal("300.00"), "freela extra"))
        self.assertEqual(ler_entrada("4500"), (Decimal("4500.00"), "Entrada"))

    def test_invalida(self):
        for texto in ("", "salário 4500", "0 x", "R$"):
            self.assertIsNone(ler_entrada(texto))


@patch("app.comandos.entrada.salvar_estado")
class TestComando(unittest.TestCase):
    def test_com_valor_pede_confirmacao(self, salvar):
        resposta = comando_entrada(USUARIO, "4500 salário")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("R$ 4.500,00", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["passo"], "confirmar")

    def test_sem_valor_oferece_texto_e_holerite_opcional(self, salvar):
        resposta = comando_entrada(USUARIO, "")
        self.assertIn("/entrada 4500", resposta)
        self.assertIn("opcional", resposta)
        self.assertEqual(salvar.call_args.args[2]["passo"], "aguardando")

    def test_valor_ruim(self, salvar):
        self.assertIn("Não entendi", comando_entrada(USUARIO, "abc"))
        salvar.assert_not_called()


@patch("app.comandos.entrada.salvar_estado")
class TestHolerite(unittest.TestCase):
    @patch("app.comandos.entrada.ia.ler_holerite", return_value=EXTRAIDO)
    def test_le_e_pede_confirmacao(self, _ler, salvar):
        resposta = receber_holerite(USUARIO, "image/jpeg", lambda: b"foto")
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("R$ 4.500,00", resposta.texto)
        self.assertIn("05/10/2026", resposta.texto)
        guardado = salvar.call_args.args[2]
        self.assertEqual(guardado["fonte"], "paystub")
        self.assertNotIn("foto", str(guardado))  # o arquivo não vai para o estado

    @patch("app.comandos.entrada.ia.ler_holerite", return_value=None)
    def test_nao_leu_pede_valor_por_texto(self, _ler, salvar):
        resposta = receber_holerite(USUARIO, "image/png", lambda: b"x")
        self.assertIn("me mande o valor", resposta)
        self.assertEqual(salvar.call_args.args[2]["passo"], "aguardando")

    def test_arquivo_grande_demais_pede_valor(self, salvar):
        self.assertIn("me mande o valor", receber_holerite(USUARIO, "image/png", lambda: None))

    def test_tipo_nao_aceito_nem_baixa(self, salvar):
        baixar = MagicMock()
        self.assertIn("foto", receber_holerite(USUARIO, "video/mp4", baixar))
        baixar.assert_not_called()


@patch("app.comandos.entrada.limpar_estado")
@patch("app.comandos.entrada.salvar_estado")
class TestConversa(unittest.TestCase):
    DADOS = {"valor": "4500.00", "descricao": "Salário", "fonte": "paystub", "passo": "confirmar",
             "data": "2026-10-05"}

    @patch("app.comandos.entrada.gravar_entrada")
    @patch("app.comandos.entrada.conta_do_usuario", return_value=("u1", "c1"))
    def test_sim_grava(self, _conta, gravar, salvar, limpar):
        self.assertIn("Anotado", continuar_entrada(USUARIO, self.DADOS, "Sim"))
        gravar.assert_called_once_with("c1", "u1", self.DADOS)
        limpar.assert_called_once()

    @patch("app.comandos.entrada.gravar_entrada")
    def test_corrigir_pede_valor_e_nao_grava(self, gravar, salvar, limpar):
        self.assertIn("Qual o valor", continuar_entrada(USUARIO, self.DADOS, "Corrigir"))
        self.assertEqual(salvar.call_args.args[2]["passo"], "valor")
        resposta = continuar_entrada(USUARIO, {**self.DADOS, "passo": "valor"}, "5.000,50")
        self.assertIn("R$ 5.000,50", resposta.texto)
        gravar.assert_not_called()

    def test_valor_corrigido_invalido(self, salvar, limpar):
        self.assertIn("Não entendi", continuar_entrada(USUARIO, {**self.DADOS, "passo": "valor"}, "abc"))

    def test_aguardando_texto(self, salvar, limpar):
        resposta = continuar_entrada(USUARIO, {"passo": "aguardando"}, "3000 salário")
        self.assertIn("R$ 3.000,00", resposta.texto)

    @patch("app.comandos.entrada.get_engine")
    def test_gravar_e_renda_conjunta(self, motor, salvar, limpar):
        gravar_entrada("c1", "u1", self.DADOS)
        executar = motor.return_value.begin.return_value.__enter__.return_value.execute
        sql, params = executar.call_args.args
        self.assertIn("'income'", str(sql))
        self.assertIn("'conjunto'", str(sql))
        self.assertEqual(params["fonte"], "paystub")
        self.assertEqual(params["data"], "2026-10-05")


@patch("app.comandos.cadastro_completo", new=lambda telefone: True)
@patch("app.comandos.garantir_usuario", return_value=False)
@patch("app.comandos.eh_admin", return_value=False)
@patch("app.comandos.status_acesso", return_value="ativo")
class TestRoteamento(unittest.TestCase):
    @patch("app.comandos.receber_comprovante", return_value="comprovante")
    @patch("app.comandos.receber_holerite", return_value="holerite")
    @patch("app.comandos.ler_estado", return_value=("entrada", {"passo": "aguardando"}))
    def test_arquivo_depois_de_entrada_vira_holerite(self, _e, holerite, comprovante, *_):
        self.assertEqual(processar_comprovante(USUARIO, "image/png", None), "holerite")
        comprovante.assert_not_called()

    @patch("app.comandos.receber_comprovante", return_value="comprovante")
    @patch("app.comandos.receber_holerite", return_value="holerite")
    @patch("app.comandos.limpar_estado")
    @patch("app.comandos.ler_estado", return_value=None)
    def test_arquivo_sozinho_continua_comprovante(self, _e, _l, holerite, comprovante, *_):
        self.assertEqual(processar_comprovante(USUARIO, "image/png", None), "comprovante")
        holerite.assert_not_called()


if __name__ == "__main__":
    unittest.main()
