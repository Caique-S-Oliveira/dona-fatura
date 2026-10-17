// Dona Fatura — landing page. JavaScript puro, sem bibliotecas.
// Carregado depois de config.js e conteudo.js. Serve a index.html e às páginas legais.
(function () {
  "use strict";

  // ---------- Validação (funções puras; mesmas regras do POST /lead) ----------

  function validarNome(valor) {
    return String(valor || "").replace(/\s+/g, " ").trim().length >= 2;
  }

  // Celular com DDD, com ou sem 55. Devolve só dígitos com 55, ou null.
  function validarTelefone(valor) {
    var d = String(valor || "").replace(/\D/g, "");
    if (d.length === 13 && d.indexOf("55") === 0) d = d.slice(2);
    return /^[1-9][1-9]9\d{8}$/.test(d) ? "55" + d : null;
  }

  function formatarTelefone(valor) {
    var d = String(valor || "").replace(/\D/g, "").slice(0, 11);
    if (d.length <= 2) return d;
    if (d.length <= 7) return "(" + d.slice(0, 2) + ") " + d.slice(2);
    return "(" + d.slice(0, 2) + ") " + d.slice(2, 7) + "-" + d.slice(7);
  }

  if (typeof document === "undefined") {
    if (typeof module !== "undefined") module.exports = { validarNome: validarNome, validarTelefone: validarTelefone };
    return;
  }

  // ---------- Configuração e utilidades ----------

  var C = window.CONFIG || {};
  var T = window.CONTEUDO || {};
  var LOCAL = ["localhost", "127.0.0.1", ""].indexOf(location.hostname) !== -1;
  var PARAMS = new URLSearchParams(location.search);
  var CHAVES_ORIGEM = ["gclid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];

  // Só no seu computador: ?modo=lancamento simula o outro modo sem mexer no config.js.
  var modo = C.MODO === "lancamento" ? "lancamento" : "piloto";
  if (LOCAL && (PARAMS.get("modo") === "piloto" || PARAMS.get("modo") === "lancamento")) modo = PARAMS.get("modo");

  var temIds = !!(C.GA4_ID || C.ADS_ID);

  function el(tag, props, filhos) {
    var n = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === "texto") n.textContent = props[k];
      else if (k === "classe") n.className = props[k];
      else n.setAttribute(k, props[k]);
    });
    (filhos || []).forEach(function (f) {
      if (f) n.appendChild(typeof f === "string" ? document.createTextNode(f) : f);
    });
    return n;
  }

  function guardar(storage, chave, valor) {
    try { storage.setItem(chave, valor); } catch (e) { /* storage bloqueado: segue sem */ }
  }
  function ler(storage, chave) {
    try { return storage.getItem(chave); } catch (e) { return null; }
  }

  // ---------- Origem do visitante (gclid, UTM, variação) ----------

  var origem = (function () {
    var salvo = {};
    try { salvo = JSON.parse(ler(sessionStorage, "df_origem") || "{}") || {}; } catch (e) { salvo = {}; }
    CHAVES_ORIGEM.forEach(function (k) {
      var v = PARAMS.get(k);
      if (v) salvo[k] = v.slice(0, 200);
    });
    var pedida = PARAMS.get("v");
    if (pedida && T.variacoes && T.variacoes[pedida]) salvo.variante = pedida;
    guardar(sessionStorage, "df_origem", JSON.stringify(salvo));
    return salvo;
  })();

  var variante = origem.variante || "padrao";

  // ---------- Consentimento (Consent Mode v2) e medição ----------

  // Stub do gtag: só enfileira em dataLayer, não baixa nada. Tudo negado até o visitante aceitar.
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "denied", wait_for_update: 500
  });

  var consentimento = ler(localStorage, "df_consent"); // "granted" | "denied" | null
  var googleCarregado = false;
  var fila = []; // eventos antes da resposta ao banner; descartados se recusar

  function enviarAoGoogle(e) {
    gtag("event", e.nome, e.params);
    var rotulo = e.nome === "lead_submit" ? C.ADS_LABEL_LEAD : e.nome === "whatsapp_click" ? C.ADS_LABEL_WHATSAPP : "";
    if (rotulo && C.ADS_ID) gtag("event", "conversion", { send_to: C.ADS_ID + "/" + rotulo });
  }

  function carregarGoogle() {
    if (googleCarregado || !temIds) return;
    googleCarregado = true;
    gtag("consent", "update", {
      ad_storage: "granted", ad_user_data: "granted", ad_personalization: "granted", analytics_storage: "granted"
    });
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(C.GA4_ID || C.ADS_ID);
    document.head.appendChild(s);
    gtag("js", new Date());
    if (C.GA4_ID) gtag("config", C.GA4_ID);
    if (C.ADS_ID) gtag("config", C.ADS_ID);
    fila.splice(0).forEach(enviarAoGoogle);
  }

  // Ponto único de medição. Eventos: page_view, cta_click, form_start, lead_submit,
  // whatsapp_click, faq_open, scroll_75.
  function track(nome, params) {
    var e = { nome: nome, params: Object.assign({ modo: modo, variante: variante }, params || {}) };
    if (LOCAL && window.console) console.log("[track]", e.nome, e.params);
    if (!temIds || consentimento === "denied") return;
    if (consentimento === "granted") {
      if (googleCarregado) enviarAoGoogle(e); else fila.push(e);
    } else {
      fila.push(e);
    }
  }

  function responderConsentimento(valor) {
    consentimento = valor;
    guardar(localStorage, "df_consent", valor);
    var banner = document.getElementById("cookies");
    if (banner) banner.remove();
    if (valor === "granted") carregarGoogle(); else fila.length = 0;
  }

  function mostrarBanner() {
    if (document.getElementById("cookies")) return;
    var tc = T.cookies || {};
    var recusar = el("button", { type: "button", classe: "btn btn-sec", texto: tc.recusar });
    var aceitar = el("button", { type: "button", classe: "btn btn-primario", texto: tc.aceitar });
    recusar.addEventListener("click", function () { responderConsentimento("denied"); });
    aceitar.addEventListener("click", function () { responderConsentimento("granted"); });
    var banner = el("div", { id: "cookies", classe: "cookies", role: "region", "aria-label": "Cookies" }, [
      el("p", { texto: tc.texto }),
      el("div", { classe: "cookies-botoes" }, [recusar, aceitar])
    ]);
    document.body.appendChild(banner);
  }

  // ---------- Formulário da lista de espera ----------

  var dialogo = null;

  function endpointLead() {
    return C.ENDPOINT_LEAD || (LOCAL ? C.ENDPOINT_LEAD_LOCAL : "");
  }

  function emailLink() {
    return el("a", { href: "mailto:" + C.EMAIL, texto: C.EMAIL });
  }

  function postarLead(url, dados, tentativa) {
    var ctrl = new AbortController();
    var limite = setTimeout(function () { ctrl.abort(); }, 75000); // Render grátis pode levar ~1 min para acordar
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
      signal: ctrl.signal
    }).then(function (r) {
      clearTimeout(limite);
      return r.json().catch(function () { return {}; }).then(function (corpo) {
        return { ok: r.ok, status: r.status, detalhe: corpo.detail };
      });
    }).catch(function (erro) {
      clearTimeout(limite);
      if (tentativa < 1 && erro.name !== "AbortError") {
        return new Promise(function (ok) { setTimeout(ok, 3000); }).then(function () {
          return postarLead(url, dados, tentativa + 1);
        });
      }
      return { ok: false, status: 0 };
    });
  }

  function montarFormulario() {
    var tf = T.formulario || {};
    var campoNome = el("input", { id: "f-nome", name: "nome", type: "text", autocomplete: "name", maxlength: "80", required: "" });
    var campoTel = el("input", {
      id: "f-whatsapp", name: "whatsapp", type: "tel", inputmode: "numeric", autocomplete: "tel",
      placeholder: tf.whatsappExemplo, maxlength: "16", required: ""
    });
    // Campo-isca: invisível para pessoas; robôs costumam preencher.
    var isca = el("input", { id: "f-site", name: "site", type: "text", tabindex: "-1", autocomplete: "off" });
    var caixa = el("input", { id: "f-consent", name: "consentimento", type: "checkbox" });
    var erroNome = el("p", { classe: "erro", id: "e-nome" });
    var erroTel = el("p", { classe: "erro", id: "e-whatsapp" });
    var erroCons = el("p", { classe: "erro", id: "e-consent" });
    var status = el("p", { classe: "status", role: "status", "aria-live": "polite" });
    var enviar = el("button", { type: "submit", classe: "btn btn-primario", texto: tf.enviar });
    var fechar = el("button", { type: "button", classe: "fechar", "aria-label": tf.fechar, texto: "×" });

    var form = el("form", { novalidate: "", autocomplete: "on" }, [
      el("label", { for: "f-nome", texto: tf.nome }), campoNome, erroNome,
      el("label", { for: "f-whatsapp", texto: tf.whatsapp }), campoTel, erroTel,
      el("div", { classe: "isca", "aria-hidden": "true" }, [el("label", { for: "f-site", texto: "Não preencha" }), isca]),
      el("label", { classe: "consent", for: "f-consent" }, [caixa, el("span", { texto: tf.consentimento })]),
      erroCons, enviar, status
    ]);
    var corpo = el("div", { classe: "dialogo-corpo" }, [
      fechar, el("h2", { texto: tf.titulo }), el("p", { texto: tf.intro }), form
    ]);
    var d = el("dialog", { classe: "dialogo", "aria-label": tf.titulo }, [corpo]);
    document.body.appendChild(d);

    var iniciou = false;
    form.addEventListener("input", function () {
      if (!iniciou) { iniciou = true; track("form_start"); }
    });
    campoTel.addEventListener("input", function () { campoTel.value = formatarTelefone(campoTel.value); });
    fechar.addEventListener("click", function () { fecharDialogo(); });
    d.addEventListener("click", function (ev) { if (ev.target === d) fecharDialogo(); });

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      erroNome.textContent = erroTel.textContent = erroCons.textContent = status.textContent = "";
      var telefone = validarTelefone(campoTel.value);
      var valido = true;
      if (!validarNome(campoNome.value)) { erroNome.textContent = tf.erroNome; valido = false; }
      if (!telefone) { erroTel.textContent = tf.erroWhatsapp; valido = false; }
      if (!caixa.checked) { erroCons.textContent = tf.erroConsentimento; valido = false; }
      if (!valido) return;

      var url = endpointLead();
      if (!url) {
        status.textContent = tf.erroSemEndpoint + " ";
        status.appendChild(emailLink());
        return;
      }
      enviar.disabled = true;
      status.textContent = tf.enviando;
      var aviso = setTimeout(function () { status.textContent = tf.acordando; }, 4000);

      var dados = {
        nome: campoNome.value.trim(), telefone: telefone, consentimento: true, site: isca.value,
        variante: variante, pagina: location.pathname
      };
      CHAVES_ORIGEM.forEach(function (k) { if (origem[k]) dados[k] = origem[k]; });

      postarLead(url, dados, 0).then(function (r) {
        clearTimeout(aviso);
        enviar.disabled = false;
        if (r.ok) {
          track("lead_submit");
          form.replaceWith(el("p", { classe: "sucesso", role: "status", texto: tf.sucesso }));
        } else if (r.status === 400 && r.detalhe) {
          status.textContent = String(r.detalhe);
        } else {
          status.textContent = tf.erroEnvio + " ";
          status.appendChild(emailLink());
        }
      });
    });
    return d;
  }

  function fecharDialogo() {
    if (!dialogo) return;
    if (dialogo.close) dialogo.close(); else dialogo.removeAttribute("open");
  }

  function abrirFormulario(local) {
    track("cta_click", { local: local, tipo: "lista" });
    if (!dialogo) dialogo = montarFormulario();
    if (dialogo.showModal) dialogo.showModal(); else dialogo.setAttribute("open", "");
  }

  // ---------- Botões principais ----------

  function linkWhatsapp() {
    var numero = String(C.WHATSAPP_BOT || "").replace(/\D/g, "");
    if (!numero) return "";
    return "https://wa.me/" + numero + "?text=" + encodeURIComponent(C.MENSAGEM_WHATSAPP || "");
  }

  function montarCta(container, local) {
    var tb = T.botoes || {};
    var wa = modo === "lancamento" ? linkWhatsapp() : "";
    if (modo === "lancamento" && !wa && window.console) console.warn("MODO lancamento sem WHATSAPP_BOT: usando a lista de espera.");
    container.textContent = "";
    function botaoLista(primario) {
      var b = el("button", { type: "button", classe: "btn " + (primario ? "btn-primario" : "btn-sec"), texto: tb.entrarLista });
      b.addEventListener("click", function () { abrirFormulario(local); });
      return b;
    }
    if (wa) {
      var a = el("a", { classe: "btn btn-primario", href: wa, rel: "noopener", texto: tb.comecarWhatsapp });
      a.addEventListener("click", function () {
        track("cta_click", { local: local, tipo: "whatsapp" });
        track("whatsapp_click", { local: local });
      });
      container.appendChild(a);
      if (C.LISTA_ESPERA_NO_LANCAMENTO) container.appendChild(botaoLista(false));
    } else {
      container.appendChild(botaoLista(true));
    }
  }

  // ---------- Seções da página ----------

  function secao(id, titulo, classe) {
    var h = el("h2", { texto: titulo });
    var s = el("section", { id: id, classe: "secao " + (classe || "") }, [el("div", { classe: "wrap" }, [h])]);
    return s;
  }
  function wrapDe(s) { return s.firstChild; }

  function montarHero() {
    var v = (T.variacoes && T.variacoes[variante]) || T.variacoes.padrao;
    var cta = el("div", { classe: "cta" });
    montarCta(cta, "topo");
    return el("section", { classe: "hero", id: "topo" }, [el("div", { classe: "wrap" }, [
      el("p", { classe: "selo", texto: T.selo }),
      el("h1", { texto: v.titulo }),
      el("p", { classe: "sub", texto: v.subtitulo }),
      cta,
      el("p", { classe: "aviso", texto: T.avisoPiloto })
    ])]);
  }

  function montarPassos() {
    var s = secao("como-funciona", T.passos.titulo);
    var lista = el("ol", { classe: "passos" });
    T.passos.itens.forEach(function (p) {
      lista.appendChild(el("li", {}, [el("h3", { texto: p.titulo }), el("p", { texto: p.texto })]));
    });
    wrapDe(s).appendChild(lista);
    return s;
  }

  function montarExemplo() {
    var s = secao("exemplo", T.exemplo.titulo, "alt");
    var chat = el("div", { classe: "chat", role: "img", "aria-label": T.exemplo.rotulo });
    T.exemplo.mensagens.forEach(function (m) {
      var bolha = el("div", { classe: "bolha " + (m.de === "voce" ? "voce" : "bot") }, [el("p", { texto: m.texto })]);
      if (m.botoes) {
        var linha = el("div", { classe: "bolha-botoes" });
        m.botoes.forEach(function (b) { linha.appendChild(el("span", { texto: b })); });
        bolha.appendChild(linha);
      }
      chat.appendChild(bolha);
    });
    wrapDe(s).appendChild(el("figure", { classe: "exemplo" }, [chat, el("figcaption", { texto: T.exemplo.rotulo })]));
    return s;
  }

  function montarBeneficios() {
    var s = secao("beneficios", T.beneficios.titulo);
    var grade = el("ul", { classe: "cartoes" });
    T.beneficios.itens.forEach(function (b) {
      var titulo = el("h3", { texto: b.titulo });
      if (b.emBreve) titulo.appendChild(el("span", { classe: "etiqueta", texto: T.beneficios.emBreve }));
      grade.appendChild(el("li", { classe: b.emBreve ? "em-breve" : "" }, [titulo, el("p", { texto: b.texto })]));
    });
    wrapDe(s).appendChild(grade);
    return s;
  }

  function montarPrivacidade() {
    var s = secao("privacidade", T.privacidade.titulo, "destaque");
    var grade = el("ul", { classe: "cartoes" });
    T.privacidade.itens.forEach(function (b) {
      grade.appendChild(el("li", {}, [el("h3", { texto: b.titulo }), el("p", { texto: b.texto })]));
    });
    wrapDe(s).appendChild(grade);
    wrapDe(s).appendChild(el("p", { classe: "mais" }, [el("a", { href: "privacidade.html", texto: T.privacidade.link })]));
    return s;
  }

  function montarPrecos() {
    var s = secao("precos", T.precos.titulo);
    var grade = el("ul", { classe: "cartoes" });
    T.precos.planos.forEach(function (p) {
      var detalhes = el("ul", { classe: "detalhes" });
      p.detalhes.forEach(function (d) { detalhes.appendChild(el("li", { texto: d })); });
      grade.appendChild(el("li", {}, [el("h3", { texto: p.nome }), el("p", { classe: "preco", texto: p.preco }), detalhes]));
    });
    wrapDe(s).appendChild(grade);
    wrapDe(s).appendChild(el("p", { classe: "nota", texto: T.precos.nota }));
    return s;
  }

  function montarFaq() {
    var s = secao("faq", T.faq.titulo, "alt");
    T.faq.itens.forEach(function (item, i) {
      var resposta = typeof item.resposta === "string" ? item.resposta : (item.resposta[modo] || item.resposta.piloto);
      var d = el("details", {}, [el("summary", { texto: item.pergunta }), el("p", { texto: resposta })]);
      d.addEventListener("toggle", function () {
        if (d.open) track("faq_open", { pergunta: i + 1 });
      });
      wrapDe(s).appendChild(d);
    });
    return s;
  }

  function montarCtaFinal() {
    var cta = el("div", { classe: "cta" });
    montarCta(cta, "final");
    return el("section", { classe: "secao final" }, [el("div", { classe: "wrap" }, [
      el("h2", { texto: T.ctaFinal.titulo }), el("p", { texto: T.ctaFinal.texto }), cta,
      el("p", { classe: "aviso", texto: T.avisoPiloto })
    ])]);
  }

  function montarRodape() {
    var r = document.getElementById("rodape");
    if (!r) return;
    var tr = T.rodape || {};
    var links = el("p", { classe: "rodape-links" }, [
      el("a", { href: "privacidade.html", texto: tr.privacidade }), " · ",
      el("a", { href: "termos.html", texto: tr.termos }), " · ",
      el("span", {}, [tr.contato + ": ", el("a", { href: "mailto:" + C.EMAIL, texto: C.EMAIL })])
    ]);
    var filhos = [links, el("p", { classe: "nota", texto: tr.nota })];
    if (temIds) {
      var pref = el("button", { type: "button", classe: "link", texto: T.cookies.preferencias });
      pref.addEventListener("click", mostrarBanner);
      filhos.push(el("p", {}, [pref]));
    }
    r.appendChild(el("div", { classe: "wrap" }, filhos));
  }

  // ---------- SEO dinâmico (só quando há domínio) ----------

  function ajustarSeo() {
    if (!C.DOMINIO) return;
    var url = C.DOMINIO + "/";
    var canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) canonical.setAttribute("href", url);
    var og = document.querySelector('meta[property="og:url"]');
    if (og) og.setAttribute("content", url);
    var ld = document.createElement("script");
    ld.type = "application/ld+json";
    ld.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        { "@type": "WebSite", name: T.marca, url: url, inLanguage: "pt-BR" },
        { "@type": "Organization", name: T.marca, url: url, email: C.EMAIL }
      ]
    });
    document.head.appendChild(ld);
  }

  function ligarLinkDoApp() {
    var a = document.getElementById("link-politica-bot");
    if (a && C.URL_APP) { a.href = C.URL_APP + "/privacidade"; a.hidden = false; }
    document.querySelectorAll("[data-email]").forEach(function (n) {
      n.href = "mailto:" + C.EMAIL;
      n.textContent = C.EMAIL;
    });
  }

  // ---------- Início ----------

  function observarRolagem() {
    var disparado = false;
    window.addEventListener("scroll", function () {
      if (disparado) return;
      var total = document.documentElement.scrollHeight;
      if ((window.scrollY + window.innerHeight) / total >= 0.75) {
        disparado = true;
        track("scroll_75");
      }
    }, { passive: true });
  }

  function iniciar() {
    var app = document.getElementById("app");
    if (app && document.body.getAttribute("data-pagina") === "home") {
      app.textContent = "";
      app.appendChild(montarHero());
      app.appendChild(montarPassos());
      app.appendChild(montarExemplo());
      app.appendChild(montarBeneficios());
      app.appendChild(montarPrivacidade());
      if (C.MOSTRAR_PRECOS) app.appendChild(montarPrecos());
      app.appendChild(montarFaq());
      app.appendChild(montarCtaFinal());
      ajustarSeo();
      observarRolagem();
    }
    montarRodape();
    ligarLinkDoApp();
    if (temIds) {
      if (consentimento === "granted") carregarGoogle();
      else if (consentimento === null) mostrarBanner();
    }
    track("page_view", { pagina: location.pathname });
  }

  window.DF = { track: track, validarTelefone: validarTelefone, validarNome: validarNome };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
