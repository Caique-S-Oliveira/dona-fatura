"""Limites simples em memória (zeram quando o Render reinicia): freio contra abuso e custo."""
import threading
import time

_trava = threading.Lock()
_registros: dict[str, list[float]] = {}


def excedeu(chave: str, maximo: int, janela_segundos: int) -> bool:
    """Registra uma tentativa e devolve True se passou de `maximo` dentro da janela."""
    agora = time.monotonic()
    with _trava:
        recentes = [t for t in _registros.get(chave, []) if agora - t < janela_segundos]
        recentes.append(agora)
        _registros[chave] = recentes
        if len(_registros) > 5000:  # evita crescer sem fim
            for k in [k for k, v in _registros.items() if not v or agora - v[-1] >= janela_segundos]:
                del _registros[k]
        return len(recentes) > maximo


def limpar() -> None:
    with _trava:
        _registros.clear()
