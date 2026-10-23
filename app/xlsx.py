"""Gera uma planilha .xlsx simples (várias abas) só com a biblioteca padrão do Python."""
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape


def _coluna(indice: int) -> str:
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _celula(coluna: int, linha: int, valor, negrito: bool) -> str:
    ref = f"{_coluna(coluna)}{linha}"
    estilo = ' s="1"' if negrito else ""
    if valor is None or valor == "":
        return f'<c r="{ref}"{estilo}/>'
    if isinstance(valor, bool):
        valor = "Sim" if valor else "Não"
    elif isinstance(valor, (int, float, Decimal)):
        return f'<c r="{ref}"{estilo}><v>{valor}</v></c>'
    elif isinstance(valor, datetime):
        valor = valor.strftime("%d/%m/%Y %H:%M")
    elif isinstance(valor, date):
        valor = valor.strftime("%d/%m/%Y")
    # Texto que começaria como fórmula vira texto puro (evita injeção de fórmula no Excel).
    texto = str(valor)
    if texto[:1] in ("=", "+", "-", "@"):
        texto = "'" + texto
    texto = "".join(c for c in texto if c >= " " or c in "\n\t")
    return f'<c r="{ref}"{estilo} t="inlineStr"><is><t xml:space="preserve">{escape(texto)}</t></is></c>'


def _aba(cabecalho: list[str], linhas: list[list]) -> str:
    corpo = []
    for n, linha in enumerate([cabecalho, *linhas], start=1):
        celulas = "".join(_celula(i, n, v, n == 1) for i, v in enumerate(linha))
        corpo.append(f'<row r="{n}">{celulas}</row>')
    largura = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{max(14, min(40, len(t) + 4))}" customWidth="1"/>'
        for i, t in enumerate(cabecalho)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{largura}</cols><sheetData>{''.join(corpo)}</sheetData></worksheet>"
    )


def montar(abas: list[tuple[str, list[str], list[list]]]) -> bytes:
    """abas: [(nome, cabeçalho, linhas)] -> bytes do .xlsx."""
    nomes = [nome[:31] for nome, _, _ in abas]
    ct = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(abas) + 1)
    )
    folhas = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(nomes, 1))
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(abas) + 1)
    )
    estilos_id = len(abas) + 1
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{ct}</Types>")
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
        z.writestr("xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{folhas}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}"
            f'<Relationship Id="rId{estilos_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>")
        z.writestr("xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            "</styleSheet>")
        for i, (_, cabecalho, linhas) in enumerate(abas, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _aba(cabecalho, linhas))
    return saida.getvalue()
