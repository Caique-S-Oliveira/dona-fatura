-- Controle de acesso (complemento da Etapa 4). Rodar uma vez no SQL Editor do Supabase.
-- Os usuários que já existem ficam 'ativo'; os novos passam a entrar como 'pendente'.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS access_status TEXT NOT NULL DEFAULT 'ativo'
        CHECK (access_status IN ('pendente', 'ativo', 'bloqueado')),
    ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ;

ALTER TABLE users ALTER COLUMN access_status SET DEFAULT 'pendente';
