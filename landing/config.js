// Configuração da landing page. É o único arquivo que você precisa mexer para trocar de fase.
// Nada aqui é segredo: IDs do Google e o número do bot são públicos.
window.CONFIG = {
  // "piloto" = lista de espera | "lancamento" = botão leva ao WhatsApp do bot
  MODO: "piloto",

  // Número do bot, só dígitos com 55 e DDD (ex.: "5511987654321"). Usado no modo "lancamento".
  WHATSAPP_BOT: "5511927506874",
  MENSAGEM_WHATSAPP: "Oi, quero começar",
  // No lançamento o bot ainda exige liberação do admin: mantém a lista de espera como alternativa.
  LISTA_ESPERA_NO_LANCAMENTO: true,

  // Bloco de preços (conteudo.js > precos). Deixe false durante o piloto.
  MOSTRAR_PRECOS: false,

  // Medição. Vazio = nenhum script do Google é carregado.
  GA4_ID: "",                  // ex.: "G-XXXXXXXXXX"
  ADS_ID: "",                  // ex.: "AW-123456789"
  ADS_LABEL_LEAD: "",          // rótulo da conversão "lead_submit" (Google Ads)
  ADS_LABEL_WHATSAPP: "",      // rótulo da conversão "whatsapp_click"

  // Endereço do POST /lead. Vazio = usa ENDPOINT_LEAD_LOCAL quando a página roda no seu computador.
  ENDPOINT_LEAD: "https://dona-fatura.onrender.com/lead",           // ex.: "https://SEU-APP.onrender.com/lead"
  ENDPOINT_LEAD_LOCAL: "http://127.0.0.1:8000/lead",

  EMAIL: "donafatura.app@gmail.com",
  DOMINIO: "",                 // ex.: "https://donafatura.com.br" (sem barra no final)
  URL_APP: ""                  // endereço do Render, só para linkar a política do bot (ex.: "https://SEU-APP.onrender.com")
};
