-- Landing page: lista de espera (POST /lead). Cole no SQL Editor do Supabase.
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome TEXT NOT NULL,
    telefone TEXT NOT NULL UNIQUE,          -- só dígitos, com 55 (ex.: 5511987654321)
    consentimento_em TIMESTAMPTZ NOT NULL,  -- quando a pessoa marcou o consentimento
    variante TEXT,                          -- ?v= do anúncio (título testado)
    gclid TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_term TEXT,
    utm_content TEXT,
    pagina TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sem políticas = a API pública do Supabase não enxerga a tabela; o bot (conexão direta) continua gravando.
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
