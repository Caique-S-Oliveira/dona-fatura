"""POST /lead: validação, isca anti-robô, origem (CORS), limite por IP e gravação (SQLite em memória)."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, text

from app import leads

ORIGEM = {"Origin": "http://localhost:8080"}
VALIDO = {"nome": "Maria Souza", "telefone": "(11) 91234-5678", "consentimento": True, "site": ""}


class TestLeads(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.motor.begin() as c:
            c.execute(text(
                "CREATE TABLE leads (id TEXT PRIMARY KEY, nome TEXT NOT NULL, telefone TEXT NOT NULL UNIQUE, "
                "consentimento_em TEXT NOT NULL, variante TEXT, gclid TEXT, utm_source TEXT, utm_medium TEXT, "
                "utm_campaign TEXT, utm_term TEXT, utm_content TEXT, pagina TEXT, criado_em TEXT NOT NULL)"
            ))
        patcher = patch("app.leads.get_engine", lambda: self.motor)
        patcher.start()
        self.addCleanup(patcher.stop)
        leads._tentativas.clear()
        app = FastAPI()
        leads.instalar(app)
        self.cliente = TestClient(app)

    def linhas(self):
        with self.motor.connect() as c:
            return c.execute(text("SELECT nome, telefone, utm_source, gclid, variante FROM leads")).all()

    def post(self, **mudancas):
        return self.cliente.post("/lead", json={**VALIDO, **mudancas}, headers=ORIGEM)

    def test_grava_e_normaliza_telefone(self):
        r = self.post(utm_source="google", gclid="abc", variante="controle")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.linhas(), [("Maria Souza", "5511912345678", "google", "abc", "controle")])

    def test_repetido_responde_ok_sem_duplicar(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post(telefone="5511912345678").status_code, 200)
        self.assertEqual(len(self.linhas()), 1)

    def test_telefone_invalido(self):
        for ruim in ["123", "(11) 3123-4567", "(01) 91234-5678", "abc"]:
            self.assertEqual(self.post(telefone=ruim).status_code, 400, ruim)
        self.assertEqual(self.linhas(), [])

    def test_nome_e_consentimento_obrigatorios(self):
        self.assertEqual(self.post(nome=" ").status_code, 400)
        self.assertEqual(self.post(consentimento=False).status_code, 400)

    def test_isca_preenchida_nao_grava(self):
        self.assertEqual(self.post(site="http://spam").status_code, 200)
        self.assertEqual(self.linhas(), [])

    def test_origem_nao_permitida(self):
        r = self.cliente.post("/lead", json=VALIDO, headers={"Origin": "https://outro.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.cliente.post("/lead", json=VALIDO).status_code, 403)

    def test_cors_so_para_origem_da_landing(self):
        r = self.cliente.options("/lead", headers={**ORIGEM, "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://localhost:8080")
        r = self.cliente.options("/lead", headers={"Origin": "https://outro.com", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_limite_por_ip(self):
        for _ in range(leads.MAX_TENTATIVAS):
            self.post(telefone="123")
        self.assertEqual(self.post().status_code, 429)


if __name__ == "__main__":
    unittest.main()
