# Plano de resposta a incidentes de segurança (LGPD, art. 48)

Rascunho operacional. Os prazos e o enquadramento legal precisam de revisão jurídica.

## 1. Detectar
- Alertas ou e-mails do Render, Supabase, Meta e Anthropic.
- Aviso de um usuário (e-mail donafatura.app@gmail.com ou WhatsApp).
- Sinais no log do Render: muitas respostas 403 em /webhook ou /cron, erros em sequência, mensagens
  "Limite de mensagens por minuto excedido".

## 2. Conter (primeiras horas)
1. Se um segredo vazou, trocar na hora (exige decisão do responsável): token do WhatsApp, WHATSAPP_APP_SECRET,
   DATABASE_URL (senha do banco no Supabase), ANTHROPIC_API_KEY, CRON_SECRET, CODIGO_CONVITE.
2. Atualizar as variáveis no Render e reiniciar o serviço.
3. Se for um usuário abusando, bloquear com /negar NÚMERO.

## 3. Registrar
Anotar em um arquivo privado (fora do Git): data e hora, o que aconteceu, quais dados e quantos titulares
foram afetados, causa provável, medidas tomadas. Não colocar telefone completo nem segredos.

## 4. Avaliar e comunicar
- Há risco ou dano relevante aos titulares? Se sim, comunicar à ANPD e aos titulares afetados.
- A ANPD indica prazo curto (a Res. CD/ANPD nº 15/2024 fala em 3 dias úteis). **Confirmar com assessoria jurídica.**
- A comunicação deve dizer: natureza dos dados, titulares envolvidos, medidas de proteção, riscos, o que foi
  feito e contato (donafatura.app@gmail.com).
- Aos usuários: pelo WhatsApp (dentro da janela de 24h) e por e-mail quando houver.

## 5. Corrigir e aprender
Corrigir a causa, acrescentar teste, atualizar a auditoria e este plano.
