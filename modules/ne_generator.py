# ══════════════════════════════════════════════════════════════════════
# modules/ne_generator.py — Gerador de máscara da Nota de Empenho (NE)
# ══════════════════════════════════════════════════════════════════════
"""
Gera o texto descritivo para o campo "Descrição" da Nota de Empenho,
seguindo o padrão do NOVO_MODELO_CAMPO_DESCRICAO_NE do 9º Gpt Log.

REGRA FUNDAMENTAL:
- Só incluir campos que existem na NC. Se não tem PTRES, não incluir.
- A máscara só é gerada para aprovação (com ou sem ressalva).
- Se houver múltiplas NCs, gerar uma máscara para cada uma.

Templates por tipo:
  LICITAÇÃO  → [Sigla OM], REQ [Nr]-[Setor], [Objeto], [NC] de [data],
               [de/do] [Órgão], ND [código][, FONTE][, PTRES][, UGR],
               PI [código], PE [Nr/Ano], UASG [código] ([PART/GER/CAR]).

  CONTRATO   → [Sigla OM], REQ [Nr]-[Setor], [Objeto], [NC] de [data],
               [de/do] [Órgão], ND [código][, PTRES][, UGR],
               PI [código], CONT [Nr/Ano], UASG [código] ([GER]).

  DISPENSA   → [Sigla OM], DISP [Nr/Ano], [Objeto], [NC] de [data],
               ND [código], PI [código], DISP [Nr/Ano],
               UASG [código] ([GER/PART]).
"""

from __future__ import annotations
import re


# ══════════════════════════════════════════════════════════════════════
# MAPA DE SIGLAS DE OM
# ══════════════════════════════════════════════════════════════════════

_SIGLAS_OM = {
    # Chaves em UPPER para lookup case-insensitive
    "9º GPT LOG":              "9º GPT LOG",
    "9 GPT LOG":               "9º GPT LOG",
    "CMDO 9º GPT LOG":         "9º GPT LOG",
    "CMDO 9 GPT LOG":          "9º GPT LOG",
    "COMANDO DO 9º GPT LOG":   "9º GPT LOG",
    "9º GRUPO DE LOGÍSTICA":   "9º GPT LOG",
    "9º B SUP":                "9º B SUP",
    "9 B SUP":                 "9º B SUP",
    "9º BATALHÃO DE SUPRIMENTO": "9º B SUP",
    "H MIL A CG":              "H MIL A CG",
    "HOSPITAL MILITAR":        "H MIL A CG",
    "CRO/9":                   "CRO/9",
    "CRO 9":                   "CRO/9",
    "18º B TRNP":              "18º B TRNP",
    "18 B TRNP":               "18º B TRNP",
    "CIA CMDO":                "CIA CMDO",
    "CIA CMDO/9º GPT LOG":     "CIA CMDO/9º GPT LOG",
    "9º B MNT":                "9º B MNT",
    "9 B MNT":                 "9º B MNT",
    "CMCG":                    "CMCG",
}


def _abreviar_om(om_completa: str | None) -> str:
    """
    Converte nome completo da OM em sigla abreviada MAIÚSCULA.
    Se não encontrar no mapa, retorna o nome original em UPPER.
    """
    if not om_completa:
        return "—"

    om_upper = om_completa.strip().upper()

    # Busca direta no mapa
    for chave, sigla in _SIGLAS_OM.items():
        if chave.upper() in om_upper or om_upper in chave.upper():
            return sigla

    # Fallback: retorna em UPPER, limitando a 20 chars
    return om_upper[:20]


# ══════════════════════════════════════════════════════════════════════
# PREPARAÇÃO DO ÓRGÃO EMISSOR (de/do)
# ══════════════════════════════════════════════════════════════════════

_SIGLAS_ORGAO = {
    "COMANDO DE OPERAÇÕES TERRESTRES":      "COTER",
    "COTER":                                 "COTER",
    "DIRETORIA DE GESTÃO DE PESSOAL":       "DGP",
    "DIRETORIA DE GESTAO DE PESSOAL":       "DGP",
    "DGP":                                   "DGP",
    "COMANDO DE ENGENHARIA E CONSTRUÇÕES":  "COE",
    "COE":                                   "COE",
    "DIRETORIA DE GESTÃO ORÇAMENTÁRIA":     "DGO",
    "DIRETORIA DE GESTAO ORCAMENTARIA":     "DGO",
    "DGO":                                   "DGO",
    "DEPARTAMENTO DE ENGENHARIA E CONSTRUÇÃO": "DEC",
    "DEC":                                   "DEC",
    "DIRETORIA DE SAÚDE":                   "D SAÚ",
    "D SAÚ":                                 "D SAÚ",
    "DIRETORIA DE FORMAÇÃO E APERFEIÇOAMENTO": "DFA",
    "DFA":                                   "DFA",
    "ESTADO-MAIOR DO EXÉRCITO":             "EME",
    "EME":                                   "EME",
    "DEPARTAMENTO-GERAL DO PESSOAL":        "DGP",
}


def _abreviar_orgao(orgao: str | None) -> str:
    """Converte nome completo de órgão em sigla, se possível."""
    if not orgao:
        return ""

    orgao_upper = orgao.strip().upper()
    orgao_upper = re.sub(r"^(DO|DA|DE)\s+", "", orgao_upper)

    for chave, sigla in _SIGLAS_ORGAO.items():
        if chave.upper() in orgao_upper or orgao_upper in chave.upper():
            return sigla

    # Se não encontrou, retorna o nome original (limitado)
    return orgao_upper[:15]


def _preposicao_orgao(orgao: str | None) -> str:
    """
    Retorna 'do [ORGAO]' ou 'da [ORGAO]' conforme a sigla.
    Padrão observado nos modelos:
    - 'do COTER', 'do COE', 'do DGP'
    - 'da DGP' (feminino) — na prática, 'do' é mais comum
    """
    if not orgao:
        return ""

    sigla = _abreviar_orgao(orgao)
    return f"do {sigla}"


# ══════════════════════════════════════════════════════════════════════
# GERAÇÃO DA MÁSCARA
# ══════════════════════════════════════════════════════════════════════

def gerar_mascara(res: dict) -> str | None:
    """
    Gera a(s) máscara(s) da NE a partir dos dados extraídos.

    Parâmetros:
        res: dicionário completo retornado por extrair_processo()

    Retorna:
        String com a(s) máscara(s), separadas por \\n\\n se múltiplas NCs.
        None se não for possível gerar (sem NC ou dados insuficientes).
    """
    ident = res.get("identificacao", {})
    ncs = res.get("nota_credito", [])

    if not ncs:
        return None

    tipo_processo = (ident.get("tipo") or "").upper()

    mascaras = []
    for nc in ncs:
        mascara = _gerar_mascara_nc(ident, nc, tipo_processo)
        if mascara:
            mascaras.append(mascara)

    return "\n\n".join(mascaras) if mascaras else None


def _gerar_mascara_nc(ident: dict, nc: dict, tipo_processo: str) -> str:
    """Gera a máscara para uma NC individual."""

    # ── Campos base ──
    om = _abreviar_om(ident.get("om"))
    nr_req = ident.get("nr_requisicao", "")
    setor = ident.get("setor", "")
    objeto = _resumir_objeto(ident.get("objeto") or ident.get("assunto") or "")

    # ── Dados da NC ──
    numero_nc = nc.get("numero") or ""
    data_nc = nc.get("data_emissao") or ""
    orgao_emissor = nc.get("nome_emitente") or ident.get("orgao_emissor_nc") or ""
    nd = nc.get("nd") or ident.get("nd") or ""
    pi = nc.get("pi") or ident.get("pi") or ""
    ptres = nc.get("ptres") or ""
    ugr = nc.get("ugr") or ""
    fonte = nc.get("fonte") or ""
    esf = nc.get("esf") or ""

    # ── Instrumento ──
    nr_pregao = ident.get("nr_pregao") or ""
    nr_contrato = ident.get("nr_contrato") or ""
    uasg = ident.get("uasg") or ""
    tipo_part = ident.get("tipo_participacao") or "GER"

    # ══════════════════════════════════════════════════════════════════
    # Montar a máscara conforme tipo do processo
    # ══════════════════════════════════════════════════════════════════
    partes = []

    if "CONTRATO" in tipo_processo:
        partes = _montar_contrato(
            om, nr_req, setor, objeto, numero_nc, data_nc,
            orgao_emissor, nd, ptres, ugr, pi, nr_contrato, uasg
        )
    elif "DISPENSA" in tipo_processo:
        partes = _montar_dispensa(
            om, objeto, numero_nc, data_nc,
            nd, pi, nr_pregao, uasg, tipo_part
        )
    else:
        # Licitação (padrão)
        partes = _montar_licitacao(
            om, nr_req, setor, objeto, numero_nc, data_nc,
            orgao_emissor, nd, fonte, ptres, ugr, pi,
            nr_pregao, uasg, tipo_part
        )

    return " ".join(partes)


# ── Templates por tipo ───────────────────────────────────────────────

def _montar_licitacao(
    om, nr_req, setor, objeto, nc, data_nc,
    orgao, nd, fonte, ptres, ugr, pi,
    nr_pregao, uasg, tipo_part
) -> list[str]:
    """Monta partes da máscara para processos de LICITAÇÃO."""
    partes = []

    # Sigla OM
    partes.append(f"{om},")

    # REQ Nr-Setor (se houver)
    if nr_req and setor:
        partes.append(f"REQ {nr_req}-{setor.upper()},")
    elif nr_req:
        partes.append(f"REQ {nr_req},")

    # Objeto resumido
    if objeto:
        partes.append(f"{objeto},")

    # NC de data
    if nc:
        nc_str = nc
        if data_nc:
            nc_str += f", de {data_nc},"
        else:
            nc_str += ","
        partes.append(nc_str)

    # Órgão emissor
    if orgao:
        prep = _preposicao_orgao(orgao)
        partes.append(f"{prep},")

    # ND (obrigatório)
    if nd:
        partes.append(f"ND {nd}")

    # FONTE (condicional — só se presente na NC)
    if fonte:
        partes.append(f"FONTE {fonte}")

    # PTRES (condicional)
    if ptres:
        partes.append(f"PTRES {ptres}")

    # UGR (condicional)
    if ugr:
        partes.append(f"UGR {ugr}")

    # PI
    if pi:
        partes.append(f"PI {pi},")

    # PE Nr/Ano
    if nr_pregao:
        partes.append(f"PE {nr_pregao},")

    # UASG (tipo_part)
    if uasg:
        partes.append(f"UASG {uasg} ({tipo_part}).")
    else:
        # Fechar sem UASG
        if partes and partes[-1].endswith(","):
            partes[-1] = partes[-1][:-1] + "."

    return partes


def _montar_contrato(
    om, nr_req, setor, objeto, nc, data_nc,
    orgao, nd, ptres, ugr, pi, nr_contrato, uasg
) -> list[str]:
    """Monta partes da máscara para processos de CONTRATO."""
    partes = []

    partes.append(f"{om},")

    if nr_req and setor:
        partes.append(f"REQ {nr_req}-{setor.upper()},")
    elif nr_req:
        partes.append(f"REQ {nr_req},")

    if objeto:
        partes.append(f"{objeto},")

    if nc:
        nc_str = nc
        if data_nc:
            nc_str += f", de {data_nc},"
        else:
            nc_str += ","
        partes.append(nc_str)

    if orgao:
        prep = _preposicao_orgao(orgao)
        partes.append(f"{prep},")

    if nd:
        partes.append(f"ND {nd},")

    if ptres:
        partes.append(f"PTRES {ptres},")

    if ugr:
        partes.append(f"UGR {ugr}")

    if pi:
        partes.append(f"PI {pi},")

    if nr_contrato:
        partes.append(f"CONT {nr_contrato},")

    if uasg:
        partes.append(f"UASG {uasg} (GER).")
    else:
        if partes and partes[-1].endswith(","):
            partes[-1] = partes[-1][:-1] + "."

    return partes


def _montar_dispensa(
    om, objeto, nc, data_nc,
    nd, pi, nr_disp, uasg, tipo_part
) -> list[str]:
    """Monta partes da máscara para processos de DISPENSA."""
    partes = []

    partes.append(f"{om},")

    if nr_disp:
        partes.append(f"DISP {nr_disp},")

    if objeto:
        partes.append(f"{objeto},")

    if nc:
        nc_str = nc
        if data_nc:
            nc_str += f", de {data_nc},"
        else:
            nc_str += ","
        partes.append(nc_str)

    if nd:
        partes.append(f"ND {nd},")

    if pi:
        partes.append(f"PI {pi},")

    if nr_disp:
        partes.append(f"DISP {nr_disp},")

    if uasg:
        partes.append(f"UASG {uasg} ({tipo_part}).")
    else:
        if partes and partes[-1].endswith(","):
            partes[-1] = partes[-1][:-1] + "."

    return partes


# ══════════════════════════════════════════════════════════════════════
# COMPARAÇÃO DE MÁSCARAS (SISTEMA vs REQUISITANTE)
# ══════════════════════════════════════════════════════════════════════

def comparar_mascaras(mascara_sistema: str | None,
                      mascara_requisitante: str | None) -> list[dict]:
    """
    Compara a máscara gerada pelo sistema com a máscara pré-montada
    pelo requisitante (campo 6/7 da requisição).

    Retorna lista de divergências encontradas. Cada divergência é um dict:
        { campo, sistema, requisitante, severidade }

    Regras:
    - A máscara do sistema PREVALECE (é a oficial).
    - Divergências são apenas informativas para o analista.
    - Se uma das máscaras não existir, retorna lista vazia (sem comparação).
    - Campos comparados: NC, ND, PI, PE/CONT, UASG, FONTE, PTRES, UGR.
    """
    if not mascara_sistema or not mascara_requisitante:
        return []

    # Tokenizar ambas as máscaras
    campos_sistema = _tokenizar_mascara(mascara_sistema)
    campos_req = _tokenizar_mascara(mascara_requisitante)

    divergencias = []

    # Campos a comparar (chave interna, nome legível)
    campos_comparar = [
        ("nc",    "NC"),
        ("nd",    "ND"),
        ("pi",    "PI"),
        ("pe",    "PE (Pregão)"),
        ("cont",  "Contrato"),
        ("uasg",  "UASG"),
        ("fonte", "FONTE"),
        ("ptres", "PTRES"),
        ("ugr",   "UGR"),
    ]

    for chave, nome in campos_comparar:
        val_sis = campos_sistema.get(chave)
        val_req = campos_req.get(chave)

        # Só comparar se ambos existem
        if not val_sis or not val_req:
            continue

        # Normalizar para comparação (sem espaços, pontos, hífens)
        norm_sis = _normalizar_valor(val_sis)
        norm_req = _normalizar_valor(val_req)

        if norm_sis != norm_req:
            # ND genérica (339000) na req vs específica no sistema → esperado
            if chave == "nd" and norm_req == "339000":
                continue  # NC genérica é normal, não é divergência

            divergencias.append({
                "campo":        nome,
                "sistema":      val_sis,
                "requisitante": val_req,
                "severidade":   "info",
            })

    # Verificar NCs adicionais na máscara do requisitante que não estão
    # na máscara do sistema (ex: requisitante listou 5 NCs, sistema usou 1)
    ncs_sistema = set(_extrair_todos_nc(mascara_sistema))
    ncs_req = set(_extrair_todos_nc(mascara_requisitante))
    ncs_extras_req = ncs_req - ncs_sistema
    if ncs_extras_req:
        divergencias.append({
            "campo":        "NCs adicionais",
            "sistema":      "—",
            "requisitante": ", ".join(sorted(ncs_extras_req)),
            "severidade":   "info",
        })

    return divergencias


def _tokenizar_mascara(mascara: str) -> dict[str, str]:
    """
    Extrai campos-chave de uma máscara (texto livre) usando regex.
    Retorna dict com chaves: nc, nd, pi, pe, cont, uasg, fonte, ptres, ugr.
    """
    campos = {}

    # NC (primeiro número)
    m = re.search(r"(20\d{2}NC\d{6})", mascara)
    if m:
        campos["nc"] = m.group(1)

    # ND (6 dígitos começando com 33 ou 34)
    m = re.search(r"\bND\s+(3[34]\d{4}|33\.90\.\d{2})", mascara)
    if m:
        campos["nd"] = m.group(1).replace(".", "")

    # PI (código alfanumérico 6-15 chars)
    m = re.search(r"\bPI\s+([A-Z0-9]{6,15})", mascara, re.IGNORECASE)
    if m:
        campos["pi"] = m.group(1)

    # PE (pregão: NNN/YYYY ou NNNNN/YYYY)
    m = re.search(r"\bPE\s+(\d{3,5}/\d{4})", mascara)
    if m:
        campos["pe"] = m.group(1)

    # Contrato
    m = re.search(r"\bCONT(?:RATO)?\s+(\d{1,3}/\d{4})", mascara, re.IGNORECASE)
    if m:
        campos["cont"] = m.group(1)

    # UASG (6 dígitos)
    m = re.search(r"\bUASG\s+(\d{6})", mascara)
    if m:
        campos["uasg"] = m.group(1)

    # FONTE (10 dígitos)
    m = re.search(r"\bFONTE\s+(\d{10})", mascara)
    if m:
        campos["fonte"] = m.group(1)

    # PTRES (4-6 dígitos)
    m = re.search(r"\bPTRES\s+(\d{4,6})", mascara)
    if m:
        campos["ptres"] = m.group(1)

    # UGR (6 dígitos)
    m = re.search(r"\bUGR\s+(\d{6})", mascara)
    if m:
        campos["ugr"] = m.group(1)

    return campos


def _normalizar_valor(valor: str) -> str:
    """Remove espaços, pontos e hífens para comparação."""
    return valor.strip().replace(".", "").replace("-", "").replace(" ", "").upper()


def _extrair_todos_nc(texto: str) -> list[str]:
    """Extrai todos os números de NC de um texto."""
    return re.findall(r"(20\d{2}NC\d{6})", texto)


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════

def _resumir_objeto(objeto: str) -> str:
    """
    Resume o objeto do processo em poucas palavras para a máscara.
    Exemplos do modelo real:
      "Aquisição de Material Esportivo" → "AQS DE MATERIAL ESPORTIVO"
      "Serviço de Manutenção"           → "SV DE MANUTENÇÃO"
      "Contrato de Serviço"             → "CONT DE SERVIÇO"
    """
    if not objeto:
        return ""

    # Remover textos entre parênteses (ex: "(SFPC)")
    texto = re.sub(r"\(.*?\)", "", objeto).strip()

    # Abreviações comuns
    abreviacoes = {
        r"\bAQUISI[ÇC][ÃA]O\b": "AQS",
        r"\bSERVI[ÇC]O[S]?\b":  "SV",
        r"\bMANUTEN[ÇC][ÃA]O\b": "MNT",
        r"\bMATERIAL\b":         "MAT",
        r"\bCONTRATO\b":         "CONT",
        r"\bGÊNEROS?\b":         "GEN",
        r"\bALIMENT[ÍI]CIOS?\b": "ALIMENTICIOS",
        r"\bSA[ÚU]DE\b":         "SAÚ",
        r"\bLIMPEZA\b":          "LIMP",
        r"\bELETR[ÔO]NIC[OA]?\b": "ELET",
        r"\bEXPEDIENTE\b":       "EXPED",
        r"\bGR[ÁA]FICOS?\b":     "GRAFICOS",
        r"\bESPORTIVO[S]?\b":    "ESPORTIVO",
        r"\bPRESTAÇÃO\b":       "PREST",
    }

    texto_upper = texto.upper()
    for padrao, abrev in abreviacoes.items():
        texto_upper = re.sub(padrao, abrev, texto_upper, flags=re.IGNORECASE)

    # Limitar tamanho
    palavras = texto_upper.split()
    if len(palavras) > 6:
        texto_upper = " ".join(palavras[:6])

    return texto_upper

