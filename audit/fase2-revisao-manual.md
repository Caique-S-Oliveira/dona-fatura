# Fase 2 — Revisão manual de segurança (Dona Fatura)

Projeto único: Dona Fatura (FastAPI + Supabase + WhatsApp Cloud API + landing estática).
Base: `audit/raw/` (bandit, semgrep, pip-audit) + leitura manual de main, whatsapp, leads, paginas, db, ia,
comandos/{__init__,acesso,privacidade,comprovante,desfazer,pagar,recorrentes,sair_casal,metas}, landing/script.js.
Nenhum arquivo de código foi alterado (correções ficam para a Fase 4).

## Resultado das ferramentas (Fase 1)
- pip-audit: nenhuma vulnerabilidade conhecida. Ressalva: `requirements.txt` não fixa versões (só matplotlib).
- bandit: 10 × B608 (média/baixa confiança) + 1 × B311 (`scripts/dados_teste.py`, dado de teste, irrelevante).
- semgrep: 10 × `avoid-sqlalchemy-text` (os mesmos pontos do B608).
- Revisei cada um dos 10 pontos de SQL montado com f-string: **todos falsos positivos**. Só entram trechos fixos
  no código (`VALIDADE`, `_dono_da_meta`, `filtro`, colunas de whitelist em objetivos/parcelas, nomes de
  tabela/colunas fixos em `sair_casal`, `consulta` em acesso). Valores do usuário sempre vão por parâmetro `:x`.
- `segredos-historico.txt` está **vazio**: não sei se o gitleaks rodou e não achou nada ou se não rodou.
  `arquivos-suspeitos-historico.txt` lista só `.env.example` e `sql/*.sql` (sem `.env` no histórico). Recomendo
  rodar o gitleaks de novo na Fase 5 para confirmar.

## Achados

| # | Sev. | Onde | Achado |
|---|------|------|--------|
| 1 | Alta (a confirmar) | `sql/*.sql` | Só a tabela `leads` tem RLS (`alter_leads.sql:19`). As demais (users, transactions, members…) estão no schema `public` do Supabase sem RLS: se a Data API (PostgREST) estiver ativa, quem tiver a anon key do projeto lê/escreve tudo. Depende da configuração do painel (não verificável aqui). |
| 2 | Média | `acesso.py:44` / `__init__.py:225` | `/convite CÓDIGO` não tem limite de tentativas: um número pendente pode adivinhar `CODIGO_CONVITE` sem bloqueio. Falta rate limit/bloqueio progressivo por número. |
| 3 | Média | `whatsapp.py` | Sem limite de mensagens por usuário: um usuário liberado pode gerar chamadas à IA/downloads sem teto (custo). Texto livre também não tem limite de tamanho antes da IA (só `identificar_comando` corta em 300). |
| 4 | Média | `comprovante.py:61` | Tipo do arquivo vem do `mime_type` declarado pela mensagem, não do conteúdo (magic bytes). Tamanho já é limitado a 5 MB. Impacto baixo (só vai para a IA, não é gravado). |
| 5 | Baixa | `db.py:25` | `DATABASE_URL` sem `sslmode=require` explícito; psycopg usa `prefer`. Confirmar que a URL do pooler do Supabase traz `sslmode=require`. |
| 6 | Baixa | `main.py:16` | `/docs`, `/redoc` e `/openapi.json` públicos em produção (revelam as rotas). |
| 7 | Baixa | `main.py:47` | Token de verificação do webhook comparado com `==` (não constante no tempo); `/cron` usa `hmac.compare_digest`, mas com `str` não-ASCII no header pode levantar `TypeError` (500). |
| 8 | Baixa | `main.py:31-38`, `paginas.py` | Páginas HTML servidas pelo Python sem cabeçalhos de segurança (CSP, X-Content-Type-Options, X-Frame-Options, HSTS). Não há conteúdo dinâmico nelas, então não há XSS hoje. |
| 9 | Baixa | `leads.py:80` | Checagem de `Origin` não impede clientes não-navegador (Origin forjável); a defesa real é limite por IP (em memória, zera a cada reinício/dorme do Render) e a isca. Aceitável para o porte, mas é rate limit fraco. |
| 10 | Baixa | `main.py:52` | Sem limite de tamanho do corpo do webhook (a assinatura só é conferida depois de ler o corpo inteiro). Meta limita no envio; o risco é de quem mandar lixo para a URL pública. |
| 11 | Baixa | `recorrentes.py:95` | `UPDATE recurring_transactions … WHERE id = :id` sem `account_id`. O id vem do estado da conversa gravado pelo servidor, não do usuário, então não é explorável hoje; vale acrescentar `account_id` por defesa em profundidade. |
| 12 | Baixa | `requirements.txt` | Dependências sem versão fixa (build não reproduzível; uma versão nova com problema entra sozinha). |
| 13 | Baixa | `.gitignore` | Só ignora `.env`; variantes (`.env.local`, `.env.*`) e `audit/raw` com saída de scanners não estão cobertas. |

## O que está bom (verificado)
- Webhook: assinatura `X-Hub-Signature-256` com `hmac.compare_digest`, falha fechada se faltar segredo; anti-repetição por id.
- Autorização: porta de entrada (`acesso.avaliar`) antes de comando, IA e download; admin só por `ADMIN_PHONE`;
  botões [Liberar]/[Negar] só valem para o admin; comandos de admin invisíveis para os demais.
- IDOR: consultas de objetivos, parcelas, pagar, desfazer, metas e privacidade filtram por `account_id` (e
  `created_by_user_id` no desfazer); ids de botões/listas são conferidos contra a lista da própria conta
  (`pagar.py:151`). Gastos "meu" filtrados por `scope`/`created_by_user_id`.
- SQL: tudo parametrizado (ver acima). Sem `os.system`, `subprocess`, `shell=True`, `eval`, `pickle`.
- SSRF: nenhuma URL fornecida pelo usuário é requisitada; a URL de mídia vem da resposta da Meta.
- Aleatoriedade: código do casal usa `secrets`; convite compara com `secrets.compare_digest`.
- CORS restrito a `LANDING_ORIGINS`, só POST, sem credenciais. `/cron` protegido por segredo.
- Landing: sem `innerHTML`/`eval`; elementos criados via `el()`; cookies de terceiros só após aceite.
- Logs: sem telefone completo, sem corpo de mensagem, sem tokens (`hide_parameters=True` no engine).
- Segredos: `.env` fora do Git; `.env.example` sem valores.
- Sem senhas/sessões/cookies próprios (autenticação é o número verificado pela Meta), então CSRF e hash de senha não se aplicam.

## Não verificável por código
Configuração do painel do Supabase (RLS, Data API, papel do banco, SSL), variáveis do Render, permissões do
token da Meta, e se o token permanente tem escopo mínimo. Segue para o relatório final.
