"""Páginas públicas exigidas pela Meta: política de privacidade e exclusão de dados."""

EMAIL = "donafatura.app@gmail.com"
RESPONSAVEL = "Caique Santos de Oliveira"

_ESTILO = (
    "body{font-family:Arial,sans-serif;max-width:680px;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5;color:#222}h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:1.6rem}"
)


def _pagina(titulo: str, corpo: str) -> str:
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{titulo} — Dona Fatura</title><style>{_ESTILO}</style></head>"
        f"<body><h1>{titulo}</h1>{corpo}</body></html>"
    )


PRIVACIDADE = _pagina(
    "Política de Privacidade",
    f"""
<p>A Dona Fatura é uma assistente financeira no WhatsApp, de uso pessoal e de amigos,
mantida por {RESPONSAVEL}. Contato: <a href="mailto:{EMAIL}">{EMAIL}</a>.</p>

<h2>O que guardamos</h2>
<p>Seu número de WhatsApp, seu nome, sua renda, suas metas e os registros que você confirma
(valor, data, favorecido e categoria). Se você usar o modo casal, os dados da conta
compartilhada ficam visíveis ao parceiro, exceto os gastos marcados como "meu", dos quais ele vê
apenas o total.</p>

<h2>Fotos e PDFs</h2>
<p>Comprovantes e holerites enviados são lidos por inteligência artificial e depois descartados.
Guardamos apenas valor, data, favorecido e categoria.</p>

<h2>Com quem os dados passam</h2>
<ul>
<li>Meta (WhatsApp Cloud API): entrega das mensagens.</li>
<li>Anthropic (IA): recebe a imagem, o PDF ou a frase apenas para interpretá-los.</li>
<li>Supabase (banco de dados) e Render (hospedagem): onde os dados ficam armazenados.</li>
</ul>
<p>Não vendemos nem compartilhamos seus dados com terceiros para publicidade.</p>

<h2>Quem tem acesso</h2>
<p>Pelo WhatsApp, só você (e seu parceiro, no modo casal). Porém, quem administra o banco de
dados e o bot consegue ver os dados armazenados. Não prometemos criptografia além da oferecida
pelos serviços acima.</p>

<h2>Seus direitos</h2>
<p>Você pode apagar seus dados a qualquer momento com o comando /apagar_meus_dados, ou pedir
por e-mail. Veja <a href="/exclusao-de-dados">como excluir seus dados</a>.</p>
""",
)

EXCLUSAO = _pagina(
    "Exclusão de Dados",
    f"""
<p>Você pode apagar seus dados da Dona Fatura de duas formas.</p>

<h2>1. Pelo WhatsApp</h2>
<p>Envie <b>/apagar_meus_dados</b> para a Dona Fatura e confirme no botão "Apagar tudo". Isso
apaga seus registros, metas, categorias, renda e nome. Fica apenas seu número e a liberação de
acesso, para você poder voltar quando quiser.</p>

<h2>2. Por e-mail (inclusive o número)</h2>
<p>Para remover também o seu número do sistema, escreva para
<a href="mailto:{EMAIL}">{EMAIL}</a> a partir de uma conta que possamos associar a você, informando
o número de WhatsApp usado. Responderemos e concluiremos a exclusão em até 30 dias.</p>

<p>Mais detalhes na <a href="/privacidade">Política de Privacidade</a>.</p>
""",
)
