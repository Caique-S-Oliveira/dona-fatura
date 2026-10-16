import unittest

from app.comandos import responder
from app.comandos.ajuda import TEXTO_AJUDA


class TestRoteador(unittest.TestCase):
    def test_ajuda(self):
        self.assertEqual(responder("/ajuda"), TEXTO_AJUDA)

    def test_ajuda_maiuscula_e_espacos(self):
        self.assertEqual(responder("  /AJUDA  "), TEXTO_AJUDA)

    def test_comando_nao_implementado(self):
        self.assertEqual(responder("/resumo"), "Ainda estou aprendendo isso.")

    def test_comando_com_acento(self):
        self.assertEqual(responder("/previsão"), "Ainda estou aprendendo isso.")

    def test_comando_desconhecido(self):
        self.assertIn("Não conheço", responder("/xyz"))

    def test_frase_livre(self):
        self.assertIn("/ajuda", responder("gastei 45 no mercado"))


if __name__ == "__main__":
    unittest.main()
