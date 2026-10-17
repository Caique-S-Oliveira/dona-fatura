import unittest
from unittest.mock import MagicMock, patch

from app.comandos.privacidade import (
    TEXTO_APAGADO,
    comando_apagar,
    comando_privacidade,
    continuar_apagar,
)
from app.comandos.resposta import Resposta

USUARIO = "5511988887777"


class TestPrivacidade(unittest.TestCase):
    def test_diz_a_verdade(self):
        texto = comando_privacidade("")
        self.assertIn("administra o banco de dados", texto)
        self.assertIn("/apagar_meus_dados", texto)
        self.assertNotIn("criptografados", texto)


@patch("app.comandos.privacidade.limpar_estado")
@patch("app.comandos.privacidade.salvar_estado")
class TestApagar(unittest.TestCase):
    def test_pede_confirmacao_com_botoes(self, salvar, limpar):
        resposta = comando_apagar(USUARIO, "")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Apagar tudo", "Cancelar"))
        self.assertEqual(salvar.call_args.args[1], "apagar")

    @patch("app.comandos.privacidade._apagar")
    def test_cancelar_nao_apaga(self, apagar, salvar, limpar):
        self.assertIn("não apaguei", continuar_apagar(USUARIO, {}, "Cancelar"))
        apagar.assert_not_called()
        limpar.assert_called_once()

    @patch("app.comandos.privacidade._apagar")
    def test_resposta_estranha_pede_de_novo(self, apagar, salvar, limpar):
        self.assertIsInstance(continuar_apagar(USUARIO, {}, "talvez"), Resposta)
        apagar.assert_not_called()
        limpar.assert_not_called()

    @patch("app.comandos.privacidade._apagar", return_value=True)
    @patch("app.comandos.privacidade.conta_do_usuario", return_value=("u1", "c1"))
    def test_apagar_tudo(self, _conta, apagar, salvar, limpar):
        self.assertEqual(continuar_apagar(USUARIO, {}, "Apagar tudo"), TEXTO_APAGADO)
        apagar.assert_called_once_with(USUARIO, "u1", "c1")
        limpar.assert_called_once()

    @patch("app.comandos.privacidade._apagar", return_value=False)
    @patch("app.comandos.privacidade.conta_do_usuario", return_value=("u1", "c1"))
    def test_conta_compartilhada_nao_apaga(self, _conta, apagar, salvar, limpar):
        self.assertIn("Nada foi apagado", continuar_apagar(USUARIO, {}, "Apagar tudo"))


class TestSql(unittest.TestCase):
    @patch("app.comandos.privacidade.get_engine")
    def test_apaga_as_tabelas_do_usuario(self, motor):
        from app.comandos.privacidade import _apagar
        conexao = motor.return_value.begin.return_value.__enter__.return_value
        conexao.execute.return_value.scalar_one.return_value = 1
        self.assertTrue(_apagar(USUARIO, "u1", "c1"))
        sqls = " | ".join(str(c.args[0]) for c in conexao.execute.call_args_list)
        for tabela in ("transactions", "goals", "categories", "classification_rules", "processed_messages"):
            self.assertIn(f"DELETE FROM {tabela}", sqls)
        self.assertNotIn("DELETE FROM users", sqls)  # mantém o acesso liberado
        self.assertLess(sqls.index("DELETE FROM transactions"), sqls.index("DELETE FROM categories"))

    @patch("app.comandos.privacidade.get_engine")
    def test_conta_com_dois_membros_nao_apaga(self, motor):
        from app.comandos.privacidade import _apagar
        conexao = motor.return_value.begin.return_value.__enter__.return_value
        conexao.execute.return_value.scalar_one.return_value = 2
        self.assertFalse(_apagar(USUARIO, "u1", "c1"))
        self.assertEqual(conexao.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
