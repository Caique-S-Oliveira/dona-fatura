-- Controle de acesso com aprovação do administrador. Rodar uma vez no SQL Editor do Supabase.
-- Status continuam em access_status: 'pendente', 'ativo' (= liberado) e 'bloqueado' (= negado).
-- Quem já existia fica como está (os que já usavam continuam 'ativo').
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS cadastro_completo BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS profile_name TEXT,
    ADD COLUMN IF NOT EXISTS pending_reply_sent BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS admin_notified BOOLEAN NOT NULL DEFAULT FALSE;

-- Quem já terminou o /inicio (o nome é gravado no fim dele) fica com o cadastro completo.
UPDATE users SET cadastro_completo = TRUE WHERE display_name IS NOT NULL;
