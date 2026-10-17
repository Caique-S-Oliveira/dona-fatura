"""Landing page: links internos, nenhum script externo no HTML, formulário/validações e arquivos esperados."""
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

LANDING = Path(__file__).resolve().parent.parent / "landing"
PAGINAS = ["index.html", "privacidade.html", "termos.html"]


class Coletor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for chave in ("href", "src"):
            if chave in a:
                self.refs.append((tag, a[chave]))


def ler(nome):
    return (LANDING / nome).read_text(encoding="utf-8")


class TestLanding(unittest.TestCase):
    def test_arquivos_existem(self):
        for nome in PAGINAS + ["estilo.css", "script.js", "config.js", "conteudo.js", "robots.txt",
                               "sitemap.xml", "favicon.svg", "CHECKLIST_ADS.md"]:
            self.assertTrue((LANDING / nome).exists(), nome)

    def test_links_internos_e_nenhum_recurso_externo(self):
        for pagina in PAGINAS:
            c = Coletor()
            c.feed(ler(pagina))
            for tag, ref in c.refs:
                if ref.startswith("mailto:") or ref == "#":
                    continue
                if tag in ("script", "img"):
                    self.assertFalse(re.match(r"https?://|//", ref), f"{pagina}: recurso externo {ref}")
                arquivo, _, ancora = ref.partition("#")
                if arquivo and not arquivo.startswith("http"):
                    self.assertTrue((LANDING / arquivo).exists(), f"{pagina}: {ref} não existe")

    def test_ancora_do_topo_existe_via_script(self):
        # a âncora #topo é criada pelo script (seção hero)
        self.assertIn('id: "topo"', ler("script.js"))

    def test_google_so_depois_do_consentimento(self):
        js = ler("script.js")
        self.assertEqual(js.count("googletagmanager.com"), 1)
        corpo = js[js.index("function carregarGoogle"):]
        self.assertLess(corpo.index("googletagmanager.com"), corpo.index("fila.splice"))
        self.assertIn("if (googleCarregado || !temIds) return;", js)
        # consentimento começa negado
        self.assertIn('analytics_storage: "denied"', js)
        # carregarGoogle só é chamada após aceitar
        chamadas = [m.start() for m in re.finditer(r"carregarGoogle\(\)", js)]
        self.assertEqual(len(chamadas), 3)  # definição + aceitar + consentimento já salvo

    def test_config_ids_com_formato_valido(self):
        cfg = ler("config.js")  # só IDs públicos; vazio ou no formato certo
        self.assertRegex(cfg, r'GA4_ID:\s*"(G-[A-Z0-9]+)?"')
        self.assertRegex(cfg, r'ADS_ID:\s*"(AW-\d+)?"')
        for segredo in ("SECRET", "TOKEN", "PASSWORD", "sk-"):
            self.assertNotIn(segredo, cfg)

    def test_textos_proibidos_ausentes(self):
        tudo = " ".join(ler(n) for n in PAGINAS + ["conteudo.js"]).lower()
        for proibido in ("fique rico", "garantido", "criptograf", "certificad", "depoimento", "empréstimo"):
            self.assertNotIn(proibido, tudo)

    @unittest.skipUnless(shutil.which("node"), "node não instalado")
    def test_validadores_do_formulario(self):
        codigo = (
            "const v=require(process.argv[1]);"
            "const t=[['(11) 91234-5678','5511912345678'],['5511912345678','5511912345678'],"
            "['11 3123-4567',null],['(01) 91234-5678',null],['',null],['abc',null]];"
            "for(const [e,s] of t){if(v.validarTelefone(e)!==s){console.error('falhou',e);process.exit(1)}}"
            "if(!v.validarNome('Ana')||v.validarNome(' a ')){process.exit(1)}"
        )
        r = subprocess.run(["node", "-e", codigo, str(LANDING / "script.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
