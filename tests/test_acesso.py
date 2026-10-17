"""Controle de acesso: número novo fica pendente, o admin libera ou nega, e só quem foi liberado usa o bot.

Roda SQL de verdade num SQLite em memória (como o test_casal) e troca só o envio ao WhatsApp,
a IA e o download de mídia por gravadores, para provar o que NÃO foi chamado.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from app import whatsapp
from app.comandos import acesso, processar_mensagem
from app.comandos.acesso import MSG_ANTES_DO_INICIO, MSG_LIBERADO, MSG_PENDENTE, so_digitos
from app.comandos.ajuda import TEXTO_AJUDA, TEXTO_ADMIN, TEXTO_INICIAR
from tests.test_casal import BancoDeTeste

ADMIN = "5511900000000"
USUARIO = "5511988887777"
OUTRO = "5511977776666"


def texto(telefone, corpo, n=[0]):
    n[0] += 1
    return {"id": f"wamid.{n[0]}", "from": telefone, "type": "text", "text": {"body": corpo}}


def botao(telefone, id_botao, titulo, n=[1000]):
    n[0] += 1
    return {"id": f"wamid.{n[0]}", "from": telefone, "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": id_botao, "title": titulo}}}


def foto(telefone, n=[2000]):
    n[0] += 1
    return {"id": f"wamid.{n[0]}", "from": telefone, "type": "image",
            "image": {"id": "media1", "mime_type": "image/png"}}


def payload(mensagem, nome=None):
    valor = {"messages": [mensagem]}
    if nome:
        valor["contacts"] = [{"wa_id": mensagem["from"], "profile": {"name": nome}}]
    return {"entry": [{"changes": [{"field": "messages", "value": valor}]}]}


class BaseAcesso(BancoDeTeste):
    def setUp(self):
        super().setUp()
        ambiente = patch.dict(os.environ, {"ADMIN_PHONE": "+55 (11) 90000-0000", "ADMIN_NUMERO": "",
                                           "CODIGO_CONVITE": "abc123"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.envios = []  # (destino, tipo, conteúdo) de tudo que o bot mandou
        self.janela_fechada = set()  # números para os quais o envio falha (janela de 24h)
        self.ia = MagicMock()
        self.baixar = MagicMock()
        for alvo, falso in [
            ("app.whatsapp._post_message", self._enviar),
            ("app.whatsapp.register_message", lambda *a: True),
            ("app.whatsapp.alertas.abrir_fila", lambda: None),
            ("app.whatsapp.alertas.enviar_alertas_de_gasto", lambda: None),
            ("app.ia.chamar_ia", self.ia),
            ("app.ia.pedir_json", self.ia),
            ("app.whatsapp.download_media", self.baixar),
        ]:
            patcher = patch(alvo, falso)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _enviar(self, carga):
        if carga["to"] in self.janela_fechada:
            raise RuntimeError("janela fechada")
        self.envios.append((carga["to"], carga["type"], carga))
        return "wamid.saida"

    def receber(self, mensagem, nome=None):
        whatsapp.handle_incoming(payload(mensagem, nome))

    def para(self, destino):
        return [c for d, _, c in self.envios if d == destino]

    def textos(self, destino):
        saida = []
        for carga in self.para(destino):
            if carga["type"] == "text":
                saida.append(carga["text"]["body"])
            elif carga["type"] == "interactive":
                saida.append(carga["interactive"]["body"]["text"])
        return saida

    def status(self, telefone):
        return self.sql("SELECT access_status FROM users WHERE phone_number = :t", t=telefone).scalar()

    def contas(self, telefone):
        return self.sql("SELECT count(*) FROM members m JOIN users u ON u.id = m.user_id"
                        " WHERE u.phone_number = :t", t=telefone).scalar()

    def liberar_pelo_admin(self, telefone):
        self.receber(botao(ADMIN, f"acesso:liberar:{telefone}", "Liberar"))


class TestNumeroDesconhecido(BaseAcesso):
    def test_a_nao_recebe_comando_nem_aciona_ia_ou_download(self):
        self.receber(texto(USUARIO, "/gasto 45 mercado"), nome="Maria")
        self.receber(texto(USUARIO, "gastei 45 no mercado"))
        self.receber(foto(USUARIO))
        self.assertEqual(self.textos(USUARIO), [MSG_PENDENTE])  # nenhuma resposta de comando
        self.ia.assert_not_called()
        self.baixar.assert_not_called()
        self.assertEqual(self.status(USUARIO), "pendente")
        self.assertEqual(self.contas(USUARIO), 0)  # sem conta financeira
        self.assertEqual(self.sql("SELECT count(*) FROM transactions").scalar(), 0)

    def test_b_responde_so_uma_vez_e_avisa_o_admin_so_uma_vez(self):
        for corpo in ("oi", "/ajuda", "/inicio", "oi de novo"):
            self.receber(texto(USUARIO, corpo), nome="Maria")
        self.assertEqual(self.textos(USUARIO), [MSG_PENDENTE])
        pedidos = self.para(ADMIN)
        self.assertEqual(len(pedidos), 1)
        corpo = pedidos[0]["interactive"]
        self.assertIn(f"Pedido de acesso: +{USUARIO} (Maria)", corpo["body"]["text"])
        botoes = corpo["action"]["buttons"]
        self.assertEqual([b["reply"]["title"] for b in botoes], ["Liberar", "Negar"])
        self.assertEqual(botoes[0]["reply"]["id"], f"acesso:liberar:{USUARIO}")

    def test_pedido_que_nao_chegou_vai_na_proxima_mensagem_do_admin(self):
        self.janela_fechada.add(ADMIN)
        self.receber(texto(USUARIO, "oi"))
        self.assertEqual(self.para(ADMIN), [])
        self.assertEqual(self.sql("SELECT admin_notified FROM users").scalar(), 0)  # continua pendente
        self.janela_fechada.clear()
        self.receber(texto(ADMIN, "oi"))  # o admin mandou algo: a janela reabriu
        mensagens = self.textos(ADMIN)
        self.assertIn("Você tem 1 pedido pendente.", mensagens[0])
        self.assertIn(f"+{USUARIO}", mensagens[1])
        self.receber(texto(ADMIN, "oi"))
        pedidos = [t for t in self.textos(ADMIN) if t.startswith("Pedido de acesso")]
        self.assertEqual(len(pedidos), 1)  # não repete o pedido


class TestLiberar(BaseAcesso):
    def test_c_botao_liberar_muda_status_e_usuario_passa_a_usar_comandos(self):
        self.receber(texto(USUARIO, "oi"))
        self.liberar_pelo_admin(USUARIO)
        self.assertEqual(self.status(USUARIO), "ativo")
        self.assertIn("liberado", self.textos(ADMIN)[-1])
        self.assertEqual(self.textos(USUARIO)[-1], MSG_LIBERADO)
        self.receber(texto(USUARIO, "/inicio"))
        self.assertIn("como você quer ser chamado", self.textos(USUARIO)[-1])
        self.assertEqual(self.contas(USUARIO), 1)  # a conta nasce só agora

    def test_janela_fechada_do_usuario_nao_desfaz_a_liberacao(self):
        self.receber(texto(USUARIO, "oi"))
        self.janela_fechada.add(USUARIO)
        self.liberar_pelo_admin(USUARIO)
        self.assertEqual(self.status(USUARIO), "ativo")
        self.assertIn("liberado", self.textos(ADMIN)[-1])
        self.janela_fechada.clear()
        self.receber(texto(USUARIO, "/ajuda"))
        self.assertIn("/inicio", self.textos(USUARIO)[-1])

    def test_botao_de_quem_nao_e_admin_e_ignorado(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(botao(OUTRO, f"acesso:liberar:{USUARIO}", "Liberar"))
        self.assertEqual(self.status(USUARIO), "pendente")
        self.assertEqual(self.textos(OUTRO), [])

    def test_antes_do_inicio_so_inicio_e_ajuda(self):
        self.receber(texto(USUARIO, "oi"))
        self.liberar_pelo_admin(USUARIO)
        for corpo in ("/gasto 45 mercado", "/resumo", "gastei 45 no mercado", "bom dia"):
            self.receber(texto(USUARIO, corpo))
            self.assertEqual(self.textos(USUARIO)[-1].split("\n")[-1], MSG_ANTES_DO_INICIO)
        self.ia.assert_not_called()
        self.receber(foto(USUARIO))
        self.assertEqual(self.textos(USUARIO)[-1].split("\n")[-1], MSG_ANTES_DO_INICIO)
        self.baixar.assert_not_called()

    def test_convite_continua_funcionando(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(texto(USUARIO, "/convite abc123"))
        self.assertEqual(self.status(USUARIO), "ativo")


class TestNegado(BaseAcesso):
    def test_d_negado_e_ignorado_em_silencio(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(botao(ADMIN, f"acesso:negar:{USUARIO}", "Negar"))
        self.assertEqual(self.status(USUARIO), "bloqueado")
        antes = len(self.envios)
        self.receber(texto(USUARIO, "/gasto 45 mercado"))
        self.receber(foto(USUARIO))
        self.assertEqual(len(self.envios), antes)  # nem uma mensagem
        self.ia.assert_not_called()
        self.baixar.assert_not_called()

    def test_usuario_negado_nao_e_avisado(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(botao(ADMIN, f"acesso:negar:{USUARIO}", "Negar"))
        self.assertEqual(self.textos(USUARIO), [MSG_PENDENTE])


class TestAjuda(BaseAcesso):
    def liberado(self, telefone, completo):
        self.receber(texto(telefone, "oi"))
        self.liberar_pelo_admin(telefone)
        if completo:
            self.sql("UPDATE users SET cadastro_completo = 1 WHERE phone_number = :t", t=telefone)

    def test_e_ajuda_muda_conforme_o_cadastro(self):
        self.liberado(USUARIO, completo=False)
        self.receber(texto(USUARIO, "/ajuda"))
        sem_cadastro = self.textos(USUARIO)[-1]
        self.assertTrue(sem_cadastro.endswith(TEXTO_INICIAR))  # a 1ª resposta traz as boas-vindas antes
        self.assertNotIn("/gasto", sem_cadastro)
        self.assertIn("Mande /inicio para configurar seu nome, renda e metas. Leva uns 2 minutos.", sem_cadastro)
        self.sql("UPDATE users SET cadastro_completo = 1 WHERE phone_number = :t", t=USUARIO)
        self.receber(texto(USUARIO, "/ajuda"))
        self.assertEqual(self.textos(USUARIO)[-1], TEXTO_AJUDA)

    def test_ajuda_so_lista_comandos_que_existem(self):
        from app.comandos import COMANDOS_CONHECIDOS, COMANDOS_COM_USUARIO, COMANDOS
        for linha in TEXTO_AJUDA.splitlines():
            if linha.startswith("/"):
                nome = linha[1:].split()[0]
                self.assertIn(nome, COMANDOS_CONHECIDOS)
                self.assertTrue(nome in COMANDOS_COM_USUARIO or nome in COMANDOS, nome)
        self.assertNotIn("/grupo", TEXTO_AJUDA)

    def test_admin_ve_secao_de_administracao_e_usuario_comum_nao(self):
        self.liberado(USUARIO, completo=True)
        self.receber(texto(USUARIO, "/ajuda"))
        self.assertNotIn("Administração", self.textos(USUARIO)[-1])
        self.receber(texto(ADMIN, "/ajuda"))
        self.assertTrue(self.textos(ADMIN)[-1].endswith(TEXTO_ADMIN))
        self.assertIn(TEXTO_INICIAR, self.textos(ADMIN)[-1])  # o admin também ainda não fez o /inicio


class TestComandosDoAdmin(BaseAcesso):
    def ativo(self, telefone):
        self.receber(texto(telefone, "oi"))
        self.liberar_pelo_admin(telefone)
        self.sql("UPDATE users SET cadastro_completo = 1 WHERE phone_number = :t", t=telefone)

    def test_f_comandos_de_admin_nao_funcionam_para_outros(self):
        self.receber(texto(OUTRO, "oi"))  # fica pendente
        self.ativo(USUARIO)
        for comando in ("/usuarios", "/pendentes", f"/liberar {OUTRO}", f"/negar {OUTRO}", f"/bloquear {OUTRO}"):
            self.receber(texto(USUARIO, comando))
            self.assertIn("Não conheço", self.textos(USUARIO)[-1], comando)
        self.assertEqual(self.status(OUTRO), "pendente")
        # e quem não é liberado nem sequer é respondido
        antes = len(self.envios)
        self.receber(texto(OUTRO, f"/liberar {OUTRO}"))
        self.assertEqual(len(self.envios), antes)
        self.assertEqual(self.status(OUTRO), "pendente")

    def test_admin_libera_nega_e_lista(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(texto(OUTRO, "oi"))
        self.receber(texto(ADMIN, f"/liberar +{USUARIO}"))
        self.assertIn("liberado", self.textos(ADMIN)[-1])
        self.assertEqual(self.status(USUARIO), "ativo")
        self.receber(texto(ADMIN, f"/negar {OUTRO}"))
        self.assertEqual(self.status(OUTRO), "bloqueado")
        self.receber(texto(ADMIN, "/usuarios"))
        lista = self.textos(ADMIN)[-1]
        self.assertIn(f"+{USUARIO} - liberado", lista)
        self.assertIn(f"+{OUTRO} - negado", lista)

    def test_pendentes_lista_com_botoes(self):
        self.receber(texto(USUARIO, "oi"))
        self.receber(texto(ADMIN, "/pendentes"))
        interativos = [c for c in self.para(ADMIN) if c["type"] == "interactive"]
        self.assertEqual(len(interativos), 2)  # o aviso de quando chegou + a lista
        self.assertIn("1 pedido pendente", self.textos(ADMIN)[-1])

    def test_admin_sem_pedidos(self):
        self.receber(texto(ADMIN, "/pendentes"))
        self.assertEqual(self.textos(ADMIN)[-1], "Nenhum pedido pendente.")


class TestLogs(unittest.TestCase):
    def test_mascarar_mostra_so_4_ultimos_digitos(self):
        self.assertEqual(acesso.mascarar("+55 (11) 98888-7777"), "***7777")
        self.assertNotIn("98888", acesso.mascarar(USUARIO))

    def test_so_digitos(self):
        self.assertEqual(so_digitos("+55 (11) 98888-7777"), USUARIO)


if __name__ == "__main__":
    unittest.main()
