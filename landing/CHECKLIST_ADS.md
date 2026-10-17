# Checklist antes de rodar anúncio (Google Ads)

## Produto e WhatsApp
- [ ] Número definitivo do bot e verificação da empresa na Meta (o número de teste só aceita 5 destinatários).
- [ ] Modelos (templates) aprovados, se os alertas forem ativados (`MODELOS_ATIVOS=1`).
- [ ] Decidir se o acesso continua com liberação manual do admin; se sim, manter `LISTA_ESPERA_NO_LANCAMENTO: true`.

## Domínio e hospedagem
- [ ] Comprar domínio próprio e apontar para o Cloudflare Pages (HTTPS automático).
- [ ] Trocar `SEU-DOMINIO.com.br` em `index.html` (canonical e og:url), `robots.txt` e `sitemap.xml`.
- [ ] Preencher `DOMINIO` no `config.js`.
- [ ] Em `index.html`, `privacidade.html` e `termos.html`: trocar `noindex, nofollow` por `index, follow` (as legais podem ficar noindex).
- [ ] No Render, definir `LANDING_ORIGINS` com o domínio da LP (ex.: `https://donafatura.com.br`) e preencher `ENDPOINT_LEAD` no `config.js`.
- [ ] Rodar `sql/alter_leads.sql` no Supabase.
- [ ] Criar uma imagem de compartilhamento (`og.webp`, 1200x630) e acrescentar `og:image` no `index.html`.

## Medição
- [ ] Criar a propriedade GA4 e preencher `GA4_ID`.
- [ ] Criar a conta do Google Ads, preencher `ADS_ID` e criar as conversões `lead_submit` e `whatsapp_click`; copiar os rótulos para `ADS_LABEL_LEAD` e `ADS_LABEL_WHATSAPP`.
- [ ] Testar com o banner de cookies: sem aceitar, nenhum script do Google carrega; ao aceitar, os eventos chegam no GA4 (DebugView).
- [ ] Marcar `lead_submit` como evento principal (conversão) no GA4.
- [ ] Anúncios com `?v=` e UTMs (ex.: `?v=controle&utm_source=google&utm_medium=cpc&utm_campaign=...`). O `gclid` é capturado sozinho.

## Políticas do Google Ads
- [ ] Ler as políticas de produtos e serviços financeiros e a de dados pessoais sensíveis; conferir se o anúncio e a página se enquadram (sem promessa de ganho, sem empréstimo/investimento, com aviso de que não é consultoria).
- [ ] Verificar se será exigida verificação do anunciante ou declaração de serviços financeiros para o Brasil.
- [ ] Conferir se a página cumpre as regras de transparência (quem somos, contato, privacidade acessível).

## Textos legais e privacidade
- [ ] Revisar `privacidade.html` e `termos.html` com um profissional (retirar o aviso de rascunho depois).
- [ ] Conferir na documentação do Supabase e do Render antes de afirmar criptografia ou certificações (hoje a página não afirma nada disso).
- [ ] Definir o prazo de retenção da lista de espera.
- [ ] Definir preços (se for cobrar), preencher `conteudo.js > precos` e ligar `MOSTRAR_PRECOS`.
- [ ] Revisar os textos em `conteudo.js`: só citar recursos que existem; tirar “em breve” do que ficar pronto.
