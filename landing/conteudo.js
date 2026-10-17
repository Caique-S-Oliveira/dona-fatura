// Todos os textos da página. Edite aqui; o HTML não precisa mudar.
// Variações de título: abra a página com ?v=controle (ou previsao, casal) para testar anúncios.
window.CONTEUDO = {
  marca: "Dona Fatura",
  selo: "Piloto fechado · gratuito durante o piloto",

  variacoes: {
    padrao: {
      titulo: "Assistente de finanças no WhatsApp: registra seus gastos, compara com suas metas e prevê como o mês termina",
      subtitulo: "Mande o gasto por texto ou foto do comprovante. A Dona Fatura anota, confere com suas metas e diz, sem rodeio, o que ajustar."
    },
    controle: {
      titulo: "Controle seus gastos pelo WhatsApp: a Dona Fatura anota, compara com suas metas e prevê o fim do mês",
      subtitulo: "Sem planilha e sem app novo. Você escreve “gastei 45 no mercado” e ela cuida do resto."
    },
    previsao: {
      titulo: "Saiba como seu mês termina antes que ele termine: previsão e metas no WhatsApp",
      subtitulo: "A Dona Fatura soma o que você já gastou, o que ainda vai vencer e diz quanto segurar por semana."
    },
    casal: {
      titulo: "Finanças do casal no WhatsApp: gastos juntos, metas em comum e privacidade para o que é de cada um",
      subtitulo: "Os dois registram na mesma conta. Gastos marcados como “meu” ficam só com quem registrou."
    }
  },

  botoes: {
    entrarLista: "Entrar na lista de espera",
    comecarWhatsapp: "Começar no WhatsApp"
  },

  avisoPiloto: "A Dona Fatura está em piloto. É uma ferramenta de organização: não é consultoria financeira e não substitui um profissional.",

  passos: {
    titulo: "Como funciona",
    itens: [
      { titulo: "Mande o gasto", texto: "Escreva “gastei 45 no mercado” ou envie a foto do comprovante." },
      { titulo: "Confirme", texto: "Ela sugere a categoria e você toca em Sim ou Corrigir. Nada é salvo sem a sua confirmação." },
      { titulo: "Veja o diagnóstico", texto: "Compare com as metas, veja a previsão do fim do mês e o que ajustar por semana." }
    ]
  },

  exemplo: {
    titulo: "Veja uma conversa",
    rotulo: "Exemplo ilustrativo, com dados inventados.",
    mensagens: [
      { de: "voce", texto: "gastei 45,90 no mercado" },
      { de: "bot", texto: "Mercado · R$ 45,90 · hoje. Registro?", botoes: ["Sim", "Corrigir"] },
      { de: "voce", texto: "Sim" },
      { de: "bot", texto: "Anotado. Mercado: R$ 412,30 de R$ 600,00 no mês." },
      { de: "voce", texto: "/previsao" },
      { de: "bot", texto: "No ritmo atual você fecha o mês com R$ 240,00 sobrando. Restaurante já passou da meta: segure R$ 35,00 por semana." }
    ]
  },

  beneficios: {
    titulo: "O que ela faz",
    itens: [
      { titulo: "Registro por texto ou comprovante", texto: "Frases simples, comandos curtos ou foto/PDF do comprovante. Você confere antes de salvar." },
      { titulo: "Metas em R$", texto: "Defina quanto quer gastar por tipo: fixo, variável, assinatura, investimento e reserva de emergência." },
      { titulo: "Previsão do mês", texto: "Entradas, saídas, contas que ainda vencem e seu ritmo de gastos, com gráfico." },
      { titulo: "Diagnóstico direto", texto: "Mostra só o que está fora do plano e quanto ajustar por semana." },
      { titulo: "Casal", texto: "Dois números, uma conta. Metas conjuntas e individuais; gasto “meu” fica privado." },
      { titulo: "Objetivos e parcelas", texto: "Quanto falta para sua meta de poupança e quanto guardar por mês. Parcelas entram na previsão." },
      { titulo: "Resumo semanal automático", texto: "Aviso com o resumo da semana e o andamento das metas.", emBreve: true },
      { titulo: "Conversa em grupo do WhatsApp", texto: "O casal registrando e consultando tudo no mesmo grupo.", emBreve: true }
    ],
    emBreve: "em breve"
  },

  privacidade: {
    titulo: "Privacidade, sem enrolação",
    itens: [
      { titulo: "O que fica guardado", texto: "Valor, data, favorecido e categoria de cada registro, além do seu nome, renda e metas." },
      { titulo: "Fotos e PDFs", texto: "São lidos e descartados em seguida. O arquivo não fica guardado." },
      { titulo: "Você apaga quando quiser", texto: "Mande /apagar_meus_dados e confirme. Seus registros, metas e renda são removidos." },
      { titulo: "Quem tem acesso", texto: "Quem administra o banco de dados tem acesso técnico aos dados. Hoje é só o responsável pelo projeto, que não consulta os seus a menos que você peça ajuda." },
      { titulo: "Por onde os dados passam", texto: "As mensagens trafegam pelo WhatsApp (Meta). A IA da Anthropic lê fotos, PDFs e frases livres só para interpretá-los. Os dados ficam no Supabase e no Render. Não vendemos nem repassamos seus dados." },
      { titulo: "No casal", texto: "O parceiro vê o total dos gastos “meu”, nunca o detalhe." }
    ],
    link: "Ler a política de privacidade completa"
  },

  precos: {
    titulo: "Preço",
    planos: [
      { nome: "Piloto", preco: "Gratuito", detalhes: ["Acesso liberado aos poucos", "Todos os recursos disponíveis hoje"] }
    ],
    nota: "Valores do lançamento ainda não definidos. Avisaremos antes de qualquer cobrança."
  },

  faq: {
    titulo: "Perguntas frequentes",
    itens: [
      { pergunta: "Quanto custa?", resposta: "É gratuito durante o piloto. O preço do lançamento ainda não foi definido e você será avisado antes de qualquer cobrança." },
      {
        pergunta: "Como eu entro?",
        resposta: {
          piloto: "Deixe seu nome e WhatsApp na lista de espera. Estamos liberando o acesso aos poucos, de forma manual, e avisamos por WhatsApp quando chegar a sua vez.",
          lancamento: "Toque em “Começar no WhatsApp” e mande a primeira mensagem. Durante o piloto, o acesso é liberado manualmente; se ainda não for a sua vez, entre na lista de espera."
        }
      },
      { pergunta: "Preciso mandar holerite?", resposta: "Não. Funciona só com texto: informe sua renda com /entrada VALOR. O holerite é opcional." },
      { pergunta: "Meus dados estão seguros?", resposta: "Guardamos o mínimo (valor, data, favorecido e categoria), descartamos fotos e PDFs e você pode apagar tudo quando quiser. O banco é protegido por senha, mas quem o administra tem acesso técnico aos dados, e nenhum sistema é livre de risco. Os detalhes estão na seção de privacidade." },
      { pergunta: "Ela acessa minha conta do banco?", resposta: "Não. Você informa os gastos por texto ou comprovante. Nunca pedimos senha, cartão ou acesso ao banco." },
      { pergunta: "Precisa instalar algum aplicativo?", resposta: "Não. Tudo acontece numa conversa de WhatsApp." },
      { pergunta: "Funciona para casal?", resposta: "Sim. Os dois números usam a mesma conta, com metas conjuntas e individuais. Gastos marcados como “meu” ficam privados." },
      { pergunta: "É consultoria financeira?", resposta: "Não. A Dona Fatura organiza e mostra seus números. Ela não recomenda investimentos nem substitui um profissional." }
    ]
  },

  ctaFinal: { titulo: "Quer testar?", texto: "O piloto é gratuito e o acesso é liberado aos poucos." },

  formulario: {
    titulo: "Entrar na lista de espera",
    intro: "Avisamos por WhatsApp quando o seu acesso for liberado.",
    nome: "Seu nome",
    whatsapp: "Seu WhatsApp com DDD",
    whatsappExemplo: "(11) 91234-5678",
    consentimento: "Aceito que a Dona Fatura me chame no WhatsApp para avisar sobre o acesso. Posso pedir a exclusão dos meus dados a qualquer momento.",
    enviar: "Entrar na lista",
    enviando: "Enviando…",
    acordando: "Acordando o servidor, pode levar até 1 minuto…",
    fechar: "Fechar",
    sucesso: "Pronto! Você está na lista. Avisamos por WhatsApp quando liberarmos o seu acesso.",
    erroNome: "Informe seu nome.",
    erroWhatsapp: "Informe um celular com DDD, ex.: (11) 91234-5678.",
    erroConsentimento: "Marque o consentimento para entrar na lista.",
    erroEnvio: "Não conseguimos enviar agora. Tente de novo em instantes ou escreva para",
    erroSemEndpoint: "O cadastro ainda não está ativo. Escreva para"
  },

  cookies: {
    texto: "Usamos cookies de medição (Google Analytics e Google Ads) para saber quais anúncios funcionam. Eles só são ativados se você aceitar.",
    aceitar: "Aceitar",
    recusar: "Recusar",
    preferencias: "Preferências de cookies"
  },

  rodape: {
    contato: "Contato",
    privacidade: "Privacidade",
    termos: "Termos de uso",
    nota: "Projeto em piloto. Não é consultoria financeira."
  },

  semScript: "Esta página precisa de JavaScript para exibir o conteúdo. Para falar com a gente, escreva para"
};
