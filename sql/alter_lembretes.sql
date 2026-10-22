-- Etapa 14 (complemento): lembrete de inatividade por modelo.
-- Rode no SQL Editor do Supabase.

-- O usuário pode desligar os lembretes (botão "Parar lembretes") e religar com /lembretes.
ALTER TABLE users ADD COLUMN IF NOT EXISTS lembretes_ativos BOOLEAN NOT NULL DEFAULT TRUE;

-- Um registro por usuário por dia em que ele era candidato a lembrete: enviado, pulado ou erro,
-- sempre com o motivo. "erro" (a API recusou o modelo) impede nova tentativa no mesmo dia.
CREATE TABLE IF NOT EXISTS reminder_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    day DATE NOT NULL,
    stage_days INTEGER,
    result TEXT NOT NULL CHECK (result IN ('enviado', 'pulado', 'erro')),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, day)
);
