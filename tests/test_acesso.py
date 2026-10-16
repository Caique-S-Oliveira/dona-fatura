import os
import unittest
from unittest.mock import patch

from app.comandos import processar_mensagem
from app.comandos.acesso import MSG_INATIVO, MSG_PENDENTE, so_digitos
from app.comandos.ajuda import TEXTO_AJUDA

ADMIN = "5511900000000"
USUARIO = "5511988887777"


@patch.dict(os.environ, {"ADMIN_NUMERO": "+55 (11) 90000-0000", "CODIGO_CONVITE": "abc123"})
@patch("app.comandos.garantir_usuario", return_value=False)
class TestAcesso(unittest.TestCase):
    def test_so_digitos(self, _):
        self.assertEqual(so_digitos("+55 (11) 98888-7777"), USUARIO)

    @patch("app.comandos.status_acesso", return_value="ativo")
    def test_ativo_usa_normalmente(self, *_):
        self.assertEqual(processar_mensagem(USUARIO, "/ajuda"), TEXTO_AJUDA)

    @patch("app.comandos.status_acesso", return_value="pendente")
    def test_pendente_so_recebe_aviso(self, *_):
        self.assertEqual(processar_mensagem(USUARIO, "/ajuda"), MSG_PENDENTE)

    @patch("app.comandos.acesso.liberar_acesso", return_value=True)
    @patch("app.comandos.status_acesso", return_value="pendente")
    def test_convite_certo_libera(self, _status, liberar, _):
        self.assertIn("liberado", processar_mensagem(USUARIO, "/convite abc123"))
        liberar.assert_called_once_with(USUARIO)

    @patch("app.comandos.acesso.liberar_acesso")
    @patch("app.comandos.status_acesso", return_value="pendente")
    def test_convite_errado_nao_libera(self, _status, liberar, _):
        self.assertIn("inválido", processar_mensagem(USUARIO, "/convite errado"))
        liberar.assert_not_called()

    @patch("app.comandos.acesso.liberar_acesso")
    @patch("app.comandos.status_acesso", return_value="bloqueado")
    def test_bloqueado_nao_usa_convite(self, _status, liberar, _):
        self.assertEqual(processar_mensagem(USUARIO, "/convite abc123"), MSG_INATIVO)
        liberar.assert_not_called()

    @patch("app.comandos.acesso.liberar_acesso", return_value=True)
    def test_admin_libera(self, liberar, _):
        self.assertIn("liberado", processar_mensagem(ADMIN, "/liberar +55 11 98888-7777"))
        liberar.assert_called_once_with(USUARIO)

    @patch("app.comandos.acesso.bloquear_acesso", return_value=True)
    def test_admin_bloqueia(self, bloquear, _):
        self.assertIn("bloqueado", processar_mensagem(ADMIN, f"/bloquear {USUARIO}"))
        bloquear.assert_called_once_with(USUARIO)

    @patch("app.comandos.acesso.liberar_acesso")
    @patch("app.comandos.status_acesso", return_value="ativo")
    def test_nao_admin_nao_libera(self, _status, liberar, _):
        self.assertIn("Não conheço", processar_mensagem(USUARIO, f"/liberar {USUARIO}"))
        liberar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
