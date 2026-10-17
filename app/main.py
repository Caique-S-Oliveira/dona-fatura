import hmac
import json
import logging
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.alertas import executar_alertas
from app.whatsapp import handle_incoming, verify_signature

logging.basicConfig(level=logging.INFO)  # sem isso o log dos alertas (INFO) não aparece

app = FastAPI()


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/webhook")
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and verify_token and token == verify_token:
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="Token de verificação inválido")


@app.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
    body = await request.body()
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
    if not segredo or not hmac.compare_digest(enviado, segredo):
        raise HTTPException(status_code=403, detail="Segredo inválido")
    background_tasks.add_task(executar_alertas, forcar)
    return {"status": "ok"}
