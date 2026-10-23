"""Correções da auditoria de segurança/LGPD (Fase 4)."""
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import limites, retencao, whatsapp
from app.comandos import acesso
from app.main import app

TELEFONE = "5511988887777"


class TestLimites(unittest.TestCase):
    def setUp(self):
        limites.limpar()

    def test_passou_do_maximo_na_janela(self):
        resultados = [limites.excedeu("a", 3, 60) for _ in range(5)]
        self.assertEqual(resultados, [False, False, False, True, True])

    def test_chaves_diferentes_nao_se_misturam(self):
        for _ in range(5):
            limites.excedeu("a", 3, 60)
        self.assertFalse(limites.excedeu("b", 3, 60))

    @patch.dict(os.environ, {"CODIGO_CONVITE": "segredo"})
    def test_convite_bloqueia_apos_varias_tentativas(self):
        for _ in range(acesso.MAX_TENTATIVAS_CONVITE):
            self.assertEqual(acesso.comando_convite(TELEFONE, "errado"), "Código inválido. Confira e tente de novo.")
        self.assertIn("Muitas tentativas", acesso.comando_convite(TELEFONE, "errado"))
        # nem o código certo passa enquanto estiver bloqueado
        with patch("app.comandos.acesso.liberar_acesso") as liberar:
            self.assertIn("Muitas tentativas", acesso.comando_convite(TELEFONE, "segredo"))
        liberar.assert_not_called()

    def test_mensagens_demais_por_minuto_sao_ignoradas(self):
        payload = {"entry": [{"changes": [{"field": "messages", "value": {"messages": [
            {"id": f"wamid.{i}", "from": TELEFONE, "type": "text", "text": {"body": "oi"}}
            for i in range(whatsapp.MAX_MENSAGENS_POR_MINUTO + 5)
        ]}}]}]}
        with patch("app.whatsapp.register_message", return_value=True), \
                patch("app.whatsapp.acesso.avaliar") as avaliar:
            avaliar.return_value = MagicMock(liberado=False, resposta=None, novo_pedido=False)
            whatsapp.handle_incoming(payload)
        self.assertEqual(avaliar.call_count, whatsapp.MAX_MENSAGENS_POR_MINUTO)


class TestRetencao(unittest.TestCase):
    def test_roda_todas_as_limpezas_e_so_em_dados_tecnicos(self):
        conexao = MagicMock()
        conexao.execute.return_value.rowcount = 2
        motor = MagicMock()
        motor.begin.return_value.__enter__.return_value = conexao
        with patch("app.retencao.get_engine", return_value=motor):
            resultado = retencao.limpar_dados_tecnicos()
        self.assertEqual(len(resultado), len(retencao._LIMPEZAS))
        sqls = " ".join(str(c.args[0]) for c in conexao.execute.call_args_list)
        for tabela in ("transactions", "goals", "leads", "members"):
            self.assertNotIn(f"FROM {tabela} ", sqls)

    def test_falha_numa_limpeza_nao_para_as_outras(self):
        motor = MagicMock()
        motor.begin.side_effect = [RuntimeError("banco fora")] + [MagicMock()] * 10
        with patch("app.retencao.get_engine", return_value=motor):
            resultado = retencao.limpar_dados_tecnicos()
        self.assertEqual(len(resultado), len(retencao._LIMPEZAS) - 1)


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app)

    def test_docs_desligados(self):
        for rota in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.cliente.get(rota).status_code, 404)

    def test_cabecalhos_de_seguranca(self):
        resposta = self.cliente.get("/privacidade")
        self.assertEqual(resposta.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resposta.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", resposta.headers["Content-Security-Policy"])

    @patch.dict(os.environ, {"CRON_SECRET": "segredo"})
    def test_cron_com_cabecalho_nao_ascii_da_403_e_nao_500(self):
        resposta = self.cliente.get("/cron", headers={"X-Cron-Secret": "ação".encode("utf-8")})
        self.assertEqual(resposta.status_code, 403)

    @patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "tok"})
    def test_verificacao_do_webhook(self):
        ok = self.cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"})
        self.assertEqual(ok.text, "42")
        ruim = self.cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "açã", "hub.challenge": "42"})
        self.assertEqual(ruim.status_code, 403)

    def test_webhook_com_corpo_gigante_e_recusado(self):
        resposta = self.cliente.post("/webhook", content=b"x" * (1024 * 1024 + 1))
        self.assertEqual(resposta.status_code, 413)


class TestBanco(unittest.TestCase):
    def test_exige_tls_fora_do_banco_local(self):
        from app import db
        db.get_engine.cache_clear()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@db.exemplo.com:5432/x"}), \
                patch("app.db.create_engine") as criar:
            db.get_engine()
        self.assertEqual(criar.call_args.kwargs["connect_args"], {"sslmode": "require"})
        db.get_engine.cache_clear()


if __name__ == "__main__":
    unittest.main()
