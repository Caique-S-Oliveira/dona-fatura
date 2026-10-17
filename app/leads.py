"""Lista de espera da landing page: POST /lead grava na tabela `leads`."""
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)
router = APIRouter()

ORIGENS_PADRAO = "http://localhost:8080,http://127.0.0.1:8080"
MAX_TENTATIVAS = 10  # por IP, por hora (conta também os envios inválidos)
JANELA_S = 3600
_tentativas: dict[str, deque[float]] = defaultdict(deque)


class LeadIn(BaseModel):
    nome: str = Field(max_length=80)
    telefone: str = Field(max_length=30)
    consentimento: bool = False
    site: str = Field("", max_length=200)  # campo-isca: gente não preenche
    variante: str | None = Field(None, max_length=40)
    gclid: str | None = Field(None, max_length=200)
    utm_source: str | None = Field(None, max_length=200)
    utm_medium: str | None = Field(None, max_length=200)
    utm_campaign: str | None = Field(None, max_length=200)
    utm_term: str | None = Field(None, max_length=200)
    utm_content: str | None = Field(None, max_length=200)
    pagina: str | None = Field(None, max_length=300)


def origens_permitidas() -> list[str]:
    bruto = os.getenv("LANDING_ORIGINS") or ORIGENS_PADRAO
    return [o.strip().rstrip("/") for o in bruto.split(",") if o.strip()]


def normalizar_telefone(valor: str) -> str | None:
    """Celular brasileiro com DDD (com ou sem 55). Devolve só dígitos com 55, ou None."""
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) == 13 and digitos.startswith("55"):
        digitos = digitos[2:]
    if re.fullmatch(r"[1-9][1-9]9\d{8}", digitos):
        return "55" + digitos
    return None


def _excedeu_limite(ip: str) -> bool:
    agora = time.monotonic()
    fila = _tentativas[ip]
    while fila and agora - fila[0] > JANELA_S:
        fila.popleft()
    if len(fila) >= MAX_TENTATIVAS:
        return True
    fila.append(agora)
    if len(_tentativas) > 5000:  # evita crescer sem limite
        for chave in [k for k, v in _tentativas.items() if not v or agora - v[-1] > JANELA_S]:
            del _tentativas[chave]
    return False


def _ip(request: Request) -> str:
    # No Render o último item de X-Forwarded-For é o que o próprio proxy colocou (o anterior pode ser forjado).
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado:
        return encaminhado.split(",")[-1].strip()
    return request.client.host if request.client else "desconhecido"


@router.post("/lead")
def cadastrar_lead(lead: LeadIn, request: Request) -> dict[str, str]:
    origem = (request.headers.get("origin") or "").rstrip("/")
    if origem not in origens_permitidas():
        raise HTTPException(status_code=403, detail="Origem não permitida")
    if _excedeu_limite(_ip(request)):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente de novo mais tarde.")
    if lead.site.strip():  # robô preencheu a isca: finge que deu certo e não grava
        return {"status": "ok"}

    nome = " ".join(lead.nome.split())
    telefone = normalizar_telefone(lead.telefone)
    if len(nome) < 2:
        raise HTTPException(status_code=400, detail="Informe seu nome.")
    if telefone is None:
        raise HTTPException(status_code=400, detail="Informe um WhatsApp com DDD, ex.: (11) 91234-5678.")
    if not lead.consentimento:
        raise HTTPException(status_code=400, detail="É preciso aceitar o contato para entrar na lista.")

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO leads (id, nome, telefone, consentimento_em, variante, gclid, utm_source, "
                "utm_medium, utm_campaign, utm_term, utm_content, pagina, criado_em) "
                "VALUES (:id, :nome, :telefone, :agora, :variante, :gclid, :utm_source, :utm_medium, "
                ":utm_campaign, :utm_term, :utm_content, :pagina, :agora) "
                "ON CONFLICT (telefone) DO NOTHING"  # repetido: responde ok sem revelar que já existia
            ),
            {
                "id": str(uuid.uuid4()),
                "nome": nome,
                "telefone": telefone,
                "agora": datetime.now(timezone.utc),
                "variante": lead.variante,
                "gclid": lead.gclid,
                "utm_source": lead.utm_source,
                "utm_medium": lead.utm_medium,
                "utm_campaign": lead.utm_campaign,
                "utm_term": lead.utm_term,
                "utm_content": lead.utm_content,
                "pagina": lead.pagina,
            },
        )
    logger.info("Novo cadastro na lista de espera")
    return {"status": "ok"}


def instalar(app: FastAPI) -> None:
    """Liga a rota /lead e o CORS (só para os domínios da landing page, em LANDING_ORIGINS)."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origens_permitidas(),
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
