import hmac
import json
import logging
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.alertas import executar_alertas
from app.leads import instalar as instalar_leads
from app.retencao import limpar_dados_tecnicos
from app.paginas import EXCLUSAO, PRIVACIDADE
from app.whatsapp import handle_incoming, verify_signature

logging.basicConfig(level=logging.INFO)  # sem isso o log dos alertas (INFO) não aparece

MAX_CORPO_WEBHOOK = 1024 * 1024  # 1 MB: bem acima do que a Meta envia

# Sem /docs, /redoc e /openapi.json públicos: não mostram as rotas a quem não precisa.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def cabecalhos_de_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    resposta.headers["Strict-Transport-Security"] = "max-age=31536000"
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    )
    return resposta


def _iguais(a: str, b: str) -> bool:
    """Comparação em tempo constante, que também aceita texto não-ASCII sem dar erro."""
    return hmac.compare_digest(a.encode(), b.encode())


instalar_leads(app)  # POST /lead (lista de espera da landing page) + CORS


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/saude", methods=["GET", "HEAD"])
async def saude() -> dict[str, str]:
    """Usada pelo Render e pelo cron-job.org para manter o serviço acordado."""
    return {"status": "ok"}


@app.get("/privacidade", response_class=HTMLResponse)
def pagina_privacidade() -> str:
    return PRIVACIDADE


@app.get("/exclusao-de-dados", response_class=HTMLResponse)
def pagina_exclusao() -> str:
    return EXCLUSAO

@app.get("/webhook")
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and verify_token and token and _iguais(token, verify_token):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="Token de verificação inválido")


@app.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
    if int(request.headers.get("content-length") or 0) > MAX_CORPO_WEBHOOK:
        raise HTTPException(status_code=413, detail="Corpo grande demais")
    body = await request.body()
    if len(body) > MAX_CORPO_WEBHOOK:
        raise HTTPException(status_code=413, detail="Corpo grande demais")
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Assinatura inválida")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    background_tasks.add_task(handle_incoming, payload)
    return {"status": "ok"}


@app.api_route("/cron", methods=["GET", "POST"])
def cron(
    request: Request,
    background_tasks: BackgroundTasks,
    forcar: bool = False,
) -> dict[str, str]:
    """Chamada pelo cron-job.org com o cabeçalho X-Cron-Secret. Responde na hora e envia os
    alertas em segundo plano. `forcar=1` ignora a regra das 10h (para testar)."""
    segredo = os.getenv("CRON_SECRET")
    enviado = request.headers.get("X-Cron-Secret", "")
    if not segredo or not _iguais(enviado, segredo):
        raise HTTPException(status_code=403, detail="Segredo inválido")
    background_tasks.add_task(executar_alertas, forcar)
    background_tasks.add_task(limpar_dados_tecnicos)  # retenção: apaga dados técnicos vencidos
    return {"status": "ok"}
