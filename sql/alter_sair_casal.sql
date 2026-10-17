-- Etapa 16: /sair_casal. Avisos que esperam o parceiro falar com o bot
-- (o WhatsApp só deixa mandar texto livre até 24h depois da última mensagem dele).
CREATE TABLE IF NOT EXISTS pending_notices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pending_notices_user_idx ON pending_notices (user_id);
