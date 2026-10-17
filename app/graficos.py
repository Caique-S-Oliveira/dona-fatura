"""Gráficos em PNG (matplotlib). Só os números vêm de fora: aqui nada é calculado."""
import io
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")  # sem janela: só gera a imagem
import matplotlib.pyplot as plt  # noqa: E402

from app.comandos.formato import formatar_reais  # noqa: E402

COR_DEVERIA = "#8a8f98"
COR_ESTA = "#2563eb"
COR_PROJECAO = "#d9480f"


def _reais_curto(valor: float, _posicao=None) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def grafico_previsao(
    acumulado: list[Decimal],
    dias_no_mes: int,
    saidas_previstas: Decimal,
    limite_mensal: Decimal | None,
    titulo: str,
) -> bytes:
    """Deveria estar (meta ao ritmo certo) x está (gasto até hoje) x projeção do fim do mês."""
    hoje = len(acumulado)
    esta = [float(v) for v in acumulado]
    fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
    ax.plot(range(1, hoje + 1), esta, color=COR_ESTA, linewidth=2, label="Está")
    ax.plot([hoje, dias_no_mes], [esta[-1], float(saidas_previstas)],
            color=COR_PROJECAO, linewidth=2, linestyle="--", label="Projeção do fim do mês")
    ax.plot(hoje, esta[-1], "o", color=COR_ESTA, markersize=8, markeredgecolor="white", markeredgewidth=2)
    ax.annotate(formatar_reais(saidas_previstas), (dias_no_mes, float(saidas_previstas)),
                textcoords="offset points", xytext=(-6, -14), ha="right", color="#333333", fontsize=9)
    if limite_mensal:
        ritmo = [float(limite_mensal) * d / dias_no_mes for d in range(1, dias_no_mes + 1)]
        ax.plot(range(1, dias_no_mes + 1), ritmo, color=COR_DEVERIA, linewidth=2,
                linestyle=":", label="Deveria estar (metas)")
    ax.set_title(titulo, loc="left", fontsize=11)
    ax.set_xlim(1, dias_no_mes)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Dia do mês", fontsize=9)
    ax.yaxis.set_major_formatter(_reais_curto)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()
