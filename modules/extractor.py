"""
Módulo de extração de dados de PDFs compilados de processos requisitórios.

Usa pdfplumber para extração de texto e regex para identificar padrões.
Quando uma página não tem texto extraível (imagem/scan), usa PyMuPDF +
pytesseract (Tesseract OCR) como fallback.

Cada seção do PDF (capa, requisição, NC, certidões etc.) tem sua própria
função auxiliar de extração.

Autor: Sistema SAL/CAF — Cmdo 9º Gpt Log
"""

import re
import io
import sys
from typing import Optional
from datetime import datetime, date, timezone, timedelta

import pdfplumber

# Configurar encoding UTF-8 para stdout/stderr (evita erros com caracteres especiais no Windows)
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

# ── Configuração de fuso horário (Campo Grande-MS: GMT-4) ──────────────
TZ_CAMPO_GRANDE = timezone(timedelta(hours=-4))

def hoje_cg() -> date:
    """Retorna a data de hoje no fuso horário de Campo Grande (GMT-4)."""
    return datetime.now(TZ_CAMPO_GRANDE).date()

def agora_cg() -> datetime:
    """Retorna o datetime atual no fuso horário de Campo Grande (GMT-4)."""
    return datetime.now(TZ_CAMPO_GRANDE)

# ── OCR (opcional — funciona sem, mas não extrai páginas em imagem) ──
try:
    import fitz as _fitz          # PyMuPDF — renderiza página → imagem
    import pytesseract as _tess   # wrapper do Tesseract OCR
    from PIL import Image as _PILImage
    _OCR_DISPONIVEL = True
    print("[OCR] Tesseract + PyMuPDF disponiveis — OK")
except ImportError as _e:
    _OCR_DISPONIVEL = False
    print(f"[OCR] Bibliotecas de OCR não instaladas ({_e}). "
          "Páginas em imagem NÃO serão processadas.")


# ══════════════════════════════════════════════════════════════════════
# CONSTANTES E MAPEAMENTOS
# ══════════════════════════════════════════════════════════════════════

# Mapa de meses abreviados em português → número
MESES_PT = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4,
    "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8,
    "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

# Mapa de meses por extenso → número
MESES_EXTENSO = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Tamanho mínimo de texto para considerar que a página tem conteúdo
_MIN_TEXTO_UTIL = 30

# Padrão de rodapé de peças digitais (não conta como texto útil)
_RODAPE_DIGITAL = re.compile(
    r"^(?:\s*Este documento é peça do processo\s+\d[\d./-]+\s*Pág\s+\d+\s+de\s+\d+\s*)$",
    re.IGNORECASE | re.DOTALL
)

# DPI para renderização OCR (quanto maior, melhor qualidade, mais lento)
_OCR_DPI = 300

# Fator de escala para imagens incorporadas pequenas (melhora OCR)
_OCR_ESCALA_IMG = 3


# ══════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES DE OCR
# ══════════════════════════════════════════════════════════════════════

def _ocr_renderizar_pagina(pdf_path: str, page_idx: int,
                           dpi: int = _OCR_DPI) -> "_PILImage.Image | None":
    """
    Renderiza uma página do PDF como imagem PIL usando PyMuPDF.
    page_idx é 0-based.
    Retorna None se OCR não estiver disponível ou houver erro.
    """
    if not _OCR_DISPONIVEL:
        return None
    try:
        doc = _fitz.open(pdf_path)
        if page_idx >= len(doc):
            doc.close()
            return None
        page = doc[page_idx]
        mat = _fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = _PILImage.open(io.BytesIO(pix.tobytes("png")))
        doc.close()
        return img
    except Exception as e:
        print(f"[OCR] Erro ao renderizar página {page_idx + 1}: {e}")
        return None


def _ocr_extrair_texto(img: "_PILImage.Image", lang: str = "por",
                       psm: int = 3) -> str:
    """
    Executa Tesseract OCR em uma imagem PIL e retorna o texto extraído.
    PSM 3 = auto (melhor para páginas inteiras).
    PSM 6 = bloco uniforme (melhor para tabelas/blocos).
    """
    if not _OCR_DISPONIVEL or img is None:
        return ""
    try:
        config = f"--oem 3 --psm {psm}"
        texto = _tess.image_to_string(img, lang=lang, config=config)
        return texto.strip()
    except Exception as e:
        print(f"[OCR] Erro no Tesseract: {e}")
        return ""


def _ocr_pagina(pdf_path: str, page_idx: int) -> str:
    """
    Renderiza uma página do PDF e executa OCR.
    Retorna o texto extraído ou string vazia.
    """
    img = _ocr_renderizar_pagina(pdf_path, page_idx)
    if img is None:
        return ""
    texto = _ocr_extrair_texto(img, psm=3)
    if texto:
        print(f"[OCR] Página {page_idx + 1}: {len(texto)} caracteres extraídos")
    return texto


def _ocr_imagens_incorporadas(pdf_path: str, page_idx: int,
                              escala: int = _OCR_ESCALA_IMG) -> list[dict]:
    """
    Extrai imagens incorporadas de uma página do PDF, escala e faz OCR.
    Retorna lista de dicts com 'texto', 'largura', 'altura' de cada imagem.
    Útil para tabelas renderizadas como imagem dentro de páginas com texto.
    """
    if not _OCR_DISPONIVEL:
        return []

    resultados = []
    try:
        doc = _fitz.open(pdf_path)
        if page_idx >= len(doc):
            doc.close()
            return []

        page = doc[page_idx]
        imagens = page.get_images()

        for im_info in imagens:
            xref = im_info[0]
            try:
                pix = _fitz.Pixmap(doc, xref)
                # Ignorar imagens muito pequenas (logos, ícones)
                if pix.width < 200 or pix.height < 100:
                    continue

                img = _PILImage.open(io.BytesIO(pix.tobytes("png")))

                # Escalar imagens pequenas para melhorar OCR
                if img.width < 1500:
                    img = img.resize(
                        (img.width * escala, img.height * escala),
                        _PILImage.LANCZOS
                    )

                # Tentar PSM 4 (single column) — melhor para tabelas
                texto_p4 = _ocr_extrair_texto(img, psm=4)
                # Tentar PSM 6 (bloco uniforme) — backup
                texto_p6 = _ocr_extrair_texto(img, psm=6)
                # Preferir PSM 4: produz menos lixo em tabelas.
                # Só usar PSM 6 se PSM 4 for muito curto.
                if len(texto_p4) > len(texto_p6) * 0.5:
                    texto = texto_p4
                else:
                    texto = texto_p6

                if texto and len(texto) > 20:
                    resultados.append({
                        "texto": texto,
                        "largura": pix.width,
                        "altura": pix.height,
                    })
            except Exception as e:
                print(f"[OCR] Erro ao processar imagem xref={xref}: {e}")

        doc.close()
    except Exception as e:
        print(f"[OCR] Erro ao extrair imagens da página {page_idx + 1}: {e}")

    return resultados


# ══════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

def extrair_processo(pdf_path: str) -> dict:
    """
    Recebe o caminho de um PDF compilado e retorna um dicionário
    com todos os dados extraídos, organizados por seção.

    Retorna:
        {
            "identificacao": { nup, tipo, om, setor, objeto, fornecedor, cnpj,
                               tipo_empenho, instrumento, uasg },
            "itens": [ { item, catserv, descricao, und, qtd, nd_si, p_unit, p_total } ],
            "nota_credito": [ { numero, data, ug_emitente, ug_favorecida, nd, ptres,
                                fonte, ugr, pi, esf, valor, prazo_empenho } ],
            "certidoes": { sicaf: {...}, cadin: {...}, tcu: {...}, cnj: {...},
                           ceis: {...}, cnep: {...} },
            "despachos": [ { numero, autor, tipo, texto_resumo } ],
            "metadata": { total_paginas, paginas_com_texto, paginas_ocr }
        }
    """
    resultado = {
        "identificacao": {},
        "itens": [],
        "nota_credito": [],
        "certidoes": {},
        "despachos": [],
        "metadata": {
            "total_paginas": 0,
            "paginas_com_texto": 0,
            "paginas_ocr": 0,
        },
    }

    # Extrair texto e tabelas de todas as páginas (inclui OCR automático)
    paginas = _extrair_paginas(pdf_path)
    resultado["metadata"]["total_paginas"] = len(paginas)

    paginas_com_texto = 0
    paginas_ocr = 0
    for pag in paginas:
        if pag.get("fonte") == "ocr":
            paginas_ocr += 1
            paginas_com_texto += 1  # OCR produziu texto útil
        elif pag["tem_texto"]:
            paginas_com_texto += 1
        else:
            paginas_ocr += 1  # página sem texto e OCR não resolveu
    resultado["metadata"]["paginas_com_texto"] = paginas_com_texto
    resultado["metadata"]["paginas_ocr"] = paginas_ocr

    # Classificar cada página por tipo de peça processual
    paginas_classificadas = _classificar_paginas(paginas)

    # ── Extração da CAPA ──
    texto_capa = _juntar_texto_paginas(paginas_classificadas.get("capa", []))
    if texto_capa:
        resultado["identificacao"] = _extrair_capa(texto_capa)

    # ── Extração da REQUISIÇÃO ──
    texto_requisicao = _juntar_texto_paginas(
        paginas_classificadas.get("requisicao", [])
    )
    if texto_requisicao:
        dados_req = _extrair_requisicao(texto_requisicao)

        # Mesclar dados da requisição com identificação (complementa a capa)
        _mesclar_identificacao(resultado["identificacao"], dados_req)

        # Extrair itens via tabelas estruturadas do pdfplumber
        itens_tabela = _extrair_itens_via_tabelas(
            paginas_classificadas.get("requisicao", []), pdf_path
        )
        resultado["itens"] = (
            itens_tabela if itens_tabela else dados_req.get("itens", [])
        )

        # ── Fallback OCR: itens em imagem incorporada ──
        if not resultado["itens"] and _OCR_DISPONIVEL:
            itens_ocr = _extrair_itens_ocr(
                paginas_classificadas.get("requisicao", []), pdf_path
            )
            if itens_ocr:
                resultado["itens"] = itens_ocr
                print(f"[OCR] {len(itens_ocr)} item(ns) extraído(s) via OCR")

        # ── Fallback OCR: fornecedor/CNPJ em imagem incorporada ──
        ident = resultado["identificacao"]
        if (not ident.get("fornecedor") or not ident.get("cnpj")) and _OCR_DISPONIVEL:
            dados_forn_ocr = _extrair_fornecedor_ocr(
                paginas_classificadas.get("requisicao", []), pdf_path
            )
            if dados_forn_ocr.get("fornecedor") and not ident.get("fornecedor"):
                ident["fornecedor"] = dados_forn_ocr["fornecedor"]
            if dados_forn_ocr.get("cnpj") and not ident.get("cnpj"):
                ident["cnpj"] = dados_forn_ocr["cnpj"]

    # ── Extração da Nota de Crédito ──
    paginas_nc = paginas_classificadas.get("nota_credito", [])
    if paginas_nc:
        resultado["nota_credito"] = _extrair_nota_credito(paginas_nc)
    else:
        print("[NC] Nenhuma página classificada como nota_credito.")

    # ── Complementar NC com dados da requisição (campos que faltam) ──
    _complementar_nc_com_req(resultado["nota_credito"],
                             resultado["identificacao"])

    # ── Complementar NC com dados do espelho OCR (Fonte, ND, PI etc.) ──
    if _OCR_DISPONIVEL and resultado["nota_credito"]:
        _complementar_nc_com_ocr(resultado["nota_credito"],
                                 paginas_classificadas, pdf_path)

    # ── Extração das Certidões (SICAF, CADIN, Consulta Consolidada) ──
    resultado["certidoes"] = _extrair_certidoes(paginas_classificadas)

    # ── Fallback final: fornecedor/CNPJ do SICAF ──
    # Se após extração de texto + OCR ainda faltam, usar dados do SICAF
    _complementar_fornecedor_com_certidoes(
        resultado["identificacao"], resultado["certidoes"]
    )

    # ── Extração do Contrato (se houver) ──
    pags_contrato = paginas_classificadas.get("contrato", [])
    if pags_contrato:
        dados_contrato = _extrair_contrato(pags_contrato)
        if dados_contrato:
            resultado["contrato"] = dados_contrato
            # Validações cruzadas do contrato
            resultado["validacoes_contrato"] = _validar_contrato(
                resultado["identificacao"], dados_contrato,
                resultado["certidoes"]
            )

    # ── Extração dos Despachos (mecânica — preparando para LLM) ──
    pags_despacho = paginas_classificadas.get("despacho", [])
    if pags_despacho:
        resultado["despachos"] = _extrair_despachos(pags_despacho)

    # Tipo de processo inferido
    if not resultado["identificacao"].get("tipo"):
        resultado["identificacao"]["tipo"] = _inferir_tipo_processo(
            resultado["identificacao"], paginas_classificadas
        )

    return resultado


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DE TEXTO DO PDF
# ══════════════════════════════════════════════════════════════════════

def _extrair_paginas(pdf_path: str) -> list[dict]:
    """
    Abre o PDF com pdfplumber e retorna uma lista de dicts com o texto
    de cada página, seu número e se tem texto extraível.

    Para páginas sem texto (imagens/scans), tenta OCR via Tesseract
    se as bibliotecas estiverem disponíveis.
    """
    paginas = []
    paginas_ocr_pendentes = []  # (índice na lista, page_idx 0-based)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text() or ""
                texto = texto.strip()

                # Verificar se o texto é apenas rodapé digital
                # (ex: "Este documento é peça do processo 65297... Pág X de Y")
                apenas_rodape = bool(_RODAPE_DIGITAL.match(texto))
                tem_texto = len(texto) > _MIN_TEXTO_UTIL and not apenas_rodape

                paginas.append({
                    "numero": i + 1,
                    "texto": texto,
                    "tem_texto": tem_texto,
                    "requer_ocr": not tem_texto,
                    "fonte": "pdfplumber",
                })

                # Marcar páginas que precisam de OCR
                if not tem_texto:
                    paginas_ocr_pendentes.append((len(paginas) - 1, i))

    except Exception as e:
        print(f"[ERRO] Falha ao abrir PDF: {e}")
        return paginas

    # ── OCR para páginas sem texto ──
    if paginas_ocr_pendentes and _OCR_DISPONIVEL:
        print(f"[OCR] {len(paginas_ocr_pendentes)} página(s) sem texto — "
              "iniciando OCR...")
        for idx_lista, page_idx in paginas_ocr_pendentes:
            texto_ocr = _ocr_pagina(pdf_path, page_idx)
            if texto_ocr and len(texto_ocr) > _MIN_TEXTO_UTIL:
                paginas[idx_lista]["texto"] = texto_ocr
                paginas[idx_lista]["tem_texto"] = True
                paginas[idx_lista]["fonte"] = "ocr"
                # Manter requer_ocr=True para indicar que veio de OCR

    return paginas


# ══════════════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO DE PÁGINAS
# ══════════════════════════════════════════════════════════════════════

def _classificar_paginas(paginas: list[dict]) -> dict[str, list[dict]]:
    """
    Classifica cada página por tipo de peça processual com base no conteúdo.
    Retorna um dict com chaves: capa, termo_abertura, checklist, requisicao,
    nota_credito, sicaf, cadin, consulta_consolidada, despacho, contrato, edital.

    Uma página pode ser classificada em múltiplas categorias se necessário.
    """
    classificadas = {
        "capa": [],
        "termo_abertura": [],
        "checklist": [],
        "requisicao": [],
        "nota_credito": [],
        "sicaf": [],
        "cadin": [],
        "consulta_consolidada": [],
        "despacho": [],
        "contrato": [],
        "edital": [],
        "nao_classificada": [],
    }

    for pag in paginas:
        texto = pag["texto"].upper()
        classificada = False

        # ── CAPA ──
        if _eh_capa(texto):
            classificadas["capa"].append(pag)
            classificada = True
            continue  # capa é exclusiva

        # ── TERMO DE ABERTURA ──
        if _eh_termo_abertura(texto):
            classificadas["termo_abertura"].append(pag)
            classificada = True
            continue  # termo de abertura é exclusivo

        # ── DESPACHO (testar ANTES de requisição para evitar conflito) ──
        if re.search(r"DESPACHO\s*N[ºO°]", texto) and "APROVO" in texto:
            classificadas["despacho"].append(pag)
            classificada = True
            continue  # despacho com aprovação é exclusivo

        # ── DESPACHO do OD (sem "APROVO" mas com "ENCAMINHO") ──
        if re.search(r"DESPACHO\s*N[ºO°]", texto) and "ENCAMINHO" in texto:
            classificadas["despacho"].append(pag)
            classificada = True
            continue

        # ── CHECK LIST (contrato) ──
        if "CHECK LIST" in texto and "CONTRATO" in texto:
            classificadas["checklist"].append(pag)
            classificada = True
            # NÃO fazer continue — checklist pode ser capa/protocolo geral

        # ── REQUISIÇÃO ──
        eh_req = not classificada and _eh_requisicao(texto)
        if eh_req:
            classificadas["requisicao"].append(pag)
            classificada = True

        # ── NOTA DE CRÉDITO ──
        # Não classificar como NC se já é requisição (req menciona NC no texto)
        if not eh_req and _eh_nota_credito(texto):
            classificadas["nota_credito"].append(pag)
            classificada = True

        # ── SICAF ──
        # Classificar como SICAF apenas o documento real (com "Dados do Fornecedor")
        # e NÃO editais/requisições que mencionam SICAF en passant
        if _eh_sicaf(texto):
            classificadas["sicaf"].append(pag)
            classificada = True

        # ── CADIN ──
        # Classificar apenas o documento real do CADIN ("Créditos Não Quitados")
        if _eh_cadin(texto):
            classificadas["cadin"].append(pag)
            classificada = True

        # ── CONSULTA CONSOLIDADA (TCU/CNJ/CEIS/CNEP) ──
        # Classificar apenas o documento real ("Consulta Consolidada de Pessoa")
        if _eh_consulta_consolidada(texto):
            classificadas["consulta_consolidada"].append(pag)
            classificada = True

        # ── DESPACHO (genérico — para os que não foram pegos acima) ──
        if not classificada and re.search(r"DESPACHO\s*N[ºO°]", texto):
            classificadas["despacho"].append(pag)
            classificada = True

        # ── CONTRATO ──
        if _eh_contrato(texto):
            classificadas["contrato"].append(pag)
            classificada = True

        if not classificada:
            classificadas["nao_classificada"].append(pag)

    return classificadas


def _eh_capa(texto_upper: str) -> bool:
    """Verifica se a página é uma CAPA do processo."""
    indicadores = [
        "PROCESSO NUP" in texto_upper,
        "PROTOCOLO GERAL" in texto_upper,
        "PEÇAS PROCESSUAIS" in texto_upper,
        "CHECK LIST" in texto_upper and "PEÇAS" in texto_upper,
    ]
    return any(indicadores)


def _eh_termo_abertura(texto_upper: str) -> bool:
    """Verifica se a página é um Termo de Abertura."""
    return (
        "TERMO DE ABERTURA" in texto_upper
        or "AUTUO O PRESENTE PROCESSO" in texto_upper
    )


def _eh_requisicao(texto_upper: str) -> bool:
    """Verifica se a página faz parte da Requisição."""
    indicadores = [
        bool(re.search(r"REQ\s*(?:N[ºO°]\s*)?\d", texto_upper)),
        "ORDENADOR DE DESPESAS" in texto_upper,
        "TIPO DE EMPENHO" in texto_upper,
        "AO SR" in texto_upper and "ORDENADOR" in texto_upper,
        # Tabela de itens (páginas de continuação da requisição)
        "MATERIAL" in texto_upper and "ADQUIRIDO" in texto_upper,
        ("P. UNT" in texto_upper or "P.UNT" in texto_upper) and "TOTAL" in texto_upper,
        "FISC ADM" in texto_upper and "REQUISI" in texto_upper,
    ]
    return sum(indicadores) >= 2  # pelo menos 2 indicadores


def _eh_nota_credito(texto_upper: str) -> bool:
    """Verifica se a página contém uma Nota de Crédito."""
    indicadores = [
        "NOTA DE CRÉDITO" in texto_upper or "NOTA DE CREDITO" in texto_upper,
        "UG EMITENTE" in texto_upper,
        "SISTEMA ORIGEM SIAFI" in texto_upper,
        "DEMONSTRA-DIARIO" in texto_upper,
        "DEMONSTRA-CONRAZAO" in texto_upper,
        bool(re.search(r"20\d{2}NC\d{6}", texto_upper)),
    ]
    return any(indicadores)


def _eh_contrato(texto_upper: str) -> bool:
    """
    Verifica se a página pertence ao documento de Contrato.
    Considera termos formais de contrato e também cláusulas contratuais.
    """
    # Indicadores fortes (qualquer um basta)
    if "TERMO DE CONTRATO" in texto_upper:
        return True
    if "CONTRATANTE" in texto_upper and "CONTRATADA" in texto_upper:
        return True

    # Indicadores de cláusula contratual (precisa de 2+)
    indicadores_clausula = [
        bool(re.search(r"CL[ÁA]USULA\s+(?:PRIMEIRA|SEGUNDA|TERCEIRA|QUARTA|QUINTA|"
                        r"SEXTA|S[ÉE]TIMA|OITAVA|NONA|D[ÉE]CIMA)", texto_upper)),
        "CONTRATADA" in texto_upper or "CONTRATANTE" in texto_upper,
        "EXECU" in texto_upper and "CONTRAT" in texto_upper,
        "RESCIS" in texto_upper and "CONTRAT" in texto_upper,
        "VIG" in texto_upper and "CONTRAT" in texto_upper,
        "GARANTIA DE EXECU" in texto_upper,
    ]
    return sum(indicadores_clausula) >= 2


def _eh_sicaf(texto_upper: str) -> bool:
    """
    Verifica se a página é o documento real do SICAF.
    Evita falsos positivos em editais/requisições que mencionam SICAF.
    O documento real contém "Dados do Fornecedor" E "Situação do Fornecedor".
    """
    return (
        "DADOS DO FORNECEDOR" in texto_upper
        and "SITUAÇÃO DO FORNECEDOR" in texto_upper
    ) or (
        "CADASTRAMENTO UNIFICADO DE FORNECEDORES" in texto_upper
        and "DADOS DO FORNECEDOR" in texto_upper
    )


def _eh_cadin(texto_upper: str) -> bool:
    """
    Verifica se a página é o documento real do CADIN.
    Evita falsos positivos em editais/requisições que mencionam CADIN.
    O documento real contém "Créditos Não Quitados" ou "Consulta Contratante"
    junto com "CADIN".
    """
    return (
        "CADIN" in texto_upper
        and (
            "CRÉDITOS NÃO QUITADOS" in texto_upper
            or "CREDITOS NAO QUITADOS" in texto_upper
            or ("CONSULTA CONTRATANTE" in texto_upper)
        )
    )


def _eh_consulta_consolidada(texto_upper: str) -> bool:
    """
    Verifica se a página é o documento real de Consulta Consolidada.
    Evita falsos positivos. O documento real começa com
    "Consulta Consolidada de Pessoa Jurídica" e contém "Resultados da Consulta".
    """
    return (
        "CONSULTA CONSOLIDADA DE PESSOA" in texto_upper
        and "RESULTADO" in texto_upper
    )


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DA CAPA
# ══════════════════════════════════════════════════════════════════════

def _extrair_capa(texto: str) -> dict:
    """
    Extrai dados da capa do processo: NUP, assunto, interessado, órgão
    de origem, classificação, seção e lista de peças processuais.
    """
    dados = {
        "nup": None,
        "assunto": None,
        "interessado": None,
        "orgao_origem": None,
        "classificacao": None,
        "secao": None,
        "pecas_processuais": [],
    }

    # NUP (formato padrão EB: XXXXX.XXXXXX/YYYY-DD)
    nup = re.search(r"(\d{5}\.\d{6}/\d{4}-\d{2})", texto)
    if nup:
        dados["nup"] = nup.group(1)

    # Assunto
    assunto = re.search(r"ASSUNTO:\s*(.+)", texto, re.IGNORECASE)
    if assunto:
        dados["assunto"] = assunto.group(1).strip()

    # Interessado
    interessado = re.search(r"INTERESSADO:\s*(.+)", texto, re.IGNORECASE)
    if interessado:
        dados["interessado"] = interessado.group(1).strip()

    # Órgão de Origem (parar antes de "Data da Criação")
    orgao = re.search(
        r"[ÓO]rg[ãa]o\s+de\s+Origem:\s*(.+?)(?:\s+Data\s+da\s+Cria|$)",
        texto, re.IGNORECASE
    )
    if orgao:
        dados["orgao_origem"] = orgao.group(1).strip()

    # Classificação
    classif = re.search(r"Classifica[çc][ãa]o:\s*(\d{3}\.\d+)", texto, re.IGNORECASE)
    if classif:
        dados["classificacao"] = classif.group(1)

    # Seção
    secao = re.search(r"SE[ÇC][ÃA]O:\s*(.+)", texto, re.IGNORECASE)
    if secao:
        dados["secao"] = secao.group(1).strip()

    # Lista de peças processuais
    dados["pecas_processuais"] = _extrair_pecas_processuais(texto)

    return dados


def _extrair_pecas_processuais(texto: str) -> list[dict]:
    """
    Extrai a lista de peças processuais da capa, identificando
    quais estão ativas, desentranhadas (c) ou com outras marcações.

    Só procura APÓS o texto "PEÇAS PROCESSUAIS" e ANTES de "Legenda".
    """
    pecas = []

    # Isolar a seção de peças processuais
    inicio = re.search(r"PE[ÇC]AS\s+PROCESSUAIS", texto, re.IGNORECASE)
    if not inicio:
        return pecas

    texto_secao = texto[inicio.end():]

    # Limitar até "Legenda" (se existir)
    fim = re.search(r"Legenda", texto_secao, re.IGNORECASE)
    if fim:
        texto_secao = texto_secao[:fim.start()]

    # Procurar linhas no formato: N- nome_peca (marcação)
    padrao = re.compile(
        r"^(\d{1,3})\s*[-–]\s*(.+?)(?:\s*\(([a-d])\))?\s*$",
        re.MULTILINE
    )

    for match in padrao.finditer(texto_secao):
        numero = int(match.group(1))
        nome = match.group(2).strip()
        marcacao = match.group(3)  # a, b, c, d ou None

        # Filtrar falsos positivos (nomes muito curtos ou numéricos)
        if len(nome) < 3 or nome.replace(".", "").replace("/", "").isdigit():
            continue

        status = "ativo"
        if marcacao == "c":
            status = "desentranhado"
        elif marcacao == "a":
            status = "documento_origem"
        elif marcacao == "b":
            status = "nao_imprimivel"
        elif marcacao == "d":
            status = "desmembrado"

        pecas.append({
            "numero": numero,
            "nome": nome,
            "marcacao": marcacao,
            "status": status,
        })

    return pecas


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DA REQUISIÇÃO
# ══════════════════════════════════════════════════════════════════════

def _extrair_requisicao(texto: str) -> dict:
    """
    Extrai dados da Requisição: cabeçalho, dados do instrumento,
    fonte de recursos, dados de contrato (se houver) e tabela de itens.
    """
    dados = {
        # Cabeçalho
        "nr_requisicao": None,
        "setor": None,
        "om": None,
        "nup": None,
        "data": None,
        "destinatario": None,
        "assunto": None,
        "lei_referencia": None,
        "tipo_empenho": None,

        # Fornecedor
        "fornecedor": None,
        "cnpj": None,

        # Instrumento (pregão ou contrato)
        "nr_pregao": None,
        "nr_contrato": None,
        "uasg": None,
        "tipo_participacao": None,

        # Fonte de recursos
        "nc": None,
        "data_nc": None,
        "orgao_emissor_nc": None,
        "nd": None,
        "pi": None,
        "ptres": None,
        "ugr": None,
        "fonte": None,

        # Contrato específico
        "fiscal_contrato": None,
        "ug_gerenciadora": None,

        # Itens
        "itens": [],

        # Máscara pré-montada pelo requisitante (campo 6/7)
        "mascara_requisitante": None,
    }

    # ── Nr Requisição e Setor ──
    # Formato: "Req nº 03-Almox/CIA CCAP/9º B MNT" ou "Req n° 9-Aprv/CCAp"
    req_match = re.search(
        r"Req\.?\s*(?:n[ºo°]\s*)?(\d+)\s*[-–]\s*(.+?)(?:\n|$)",
        texto, re.IGNORECASE
    )
    if req_match:
        dados["nr_requisicao"] = req_match.group(1).strip()
        setor_bruto = req_match.group(2).strip()
        # Pegar só o primeiro segmento do setor (antes da OM)
        # Ex: "Almox/CIA CCAP/9º B MNT" → "Almox"
        # Ex: "Aprv/CCAp/Cmdo 18º B Trnp" → "Aprv"
        # Ex: "9º Gpt Log" → é OM, não setor (ignorar)
        partes_setor = re.split(r"[/]", setor_bruto)
        candidato_setor = partes_setor[0].strip()
        # Verificar se parece ser um nome de OM (número + unidade militar)
        if re.search(r"\d.*(Gpt|B\s|Cia|Esqd|Trnp|Mnt|Sup)", candidato_setor):
            dados["setor"] = None  # é OM, não setor
        else:
            dados["setor"] = candidato_setor

    # ── OM requisitante ──
    # Formatos:
    #   "Do Cmt do 9º B Mnt"          → OM = 9º B Mnt
    #   "Do Sr Cmt do 18 B Trnp"      → OM = 18 B Trnp
    #   "Do Enc Set Mat/Cmdo 9° Gpt Log" → OM = 9º Gpt Log, setor = Set Mat
    om_match = re.search(
        r"Do\s+(?:Sr\s+)?Cmt\s+d[oa]\s+(.+?)(?:\n|$)", texto, re.IGNORECASE
    )
    if om_match:
        dados["om"] = om_match.group(1).strip()
    else:
        # Formato "Do Enc [Setor]/[Cmdo] OM"
        enc_match = re.search(
            r"Do\s+Enc\s+(.+?)(?:\n|$)", texto, re.IGNORECASE
        )
        if enc_match:
            enc_bruto = enc_match.group(1).strip()
            # Separar setor e OM pelo "/" que antecede "Cmdo"
            partes = enc_bruto.split("/")
            if len(partes) >= 2:
                # Setor = parte antes do "/", OM = parte após "Cmdo"
                setor_enc = partes[0].strip()
                om_parte = "/".join(partes[1:]).strip()
                # Remover "Cmdo" do início da OM
                om_parte = re.sub(r"^Cmdo\s+", "", om_parte, flags=re.IGNORECASE)
                dados["om"] = om_parte
                # Guardar setor extraído do "Do Enc" se o setor atual parece OM
                if not dados["setor"] or re.search(r"\d.*(Gpt|B\s|Cia|Esqd)", dados["setor"]):
                    dados["setor"] = setor_enc
            else:
                dados["om"] = enc_bruto

    # ── NUP da Requisição ──
    nup = re.search(r"NUP:\s*(\d{5}\.\d{6}/\d{4}-\d{2})", texto)
    if nup:
        dados["nup"] = nup.group(1)

    # ── Data ──
    data = re.search(
        r"Campo Grande\s*,?\s*(?:MS|–)?\s*,?\s*(.+?)(?:\.|$)",
        texto, re.IGNORECASE
    )
    if data:
        dados["data"] = data.group(1).strip()

    # ── Destinatário ──
    dest = re.search(r"Ao\s+Sr\.?\s+(.+?)(?:\n|$)", texto, re.IGNORECASE)
    if dest:
        dados["destinatario"] = dest.group(1).strip()

    # ── Assunto ──
    assunto = re.search(r"Assunto:\s*(.+?)(?:\n|$)", texto, re.IGNORECASE)
    if assunto:
        dados["assunto"] = assunto.group(1).strip()

    # ── Lei de Referência ──
    lei = re.search(
        r"(?:Rfr|Refer[êe]ncia):\s*(.+?)(?:\n|$)", texto, re.IGNORECASE
    )
    if not lei:
        lei = re.search(
            r"Lei Federal\s+Nr?\s+(.+?)(?:\n|$)", texto, re.IGNORECASE
        )
    if lei:
        dados["lei_referencia"] = lei.group(1).strip()

    # ── Tipo de Empenho ──
    # Primeiro, buscar na declaração formal "Tipo de Empenho: Global"
    empenho = re.search(
        r"Tipo\s+de\s+Empenho\s*:?\s*(Ordin[áa]rio|Global|Estimativo)",
        texto, re.IGNORECASE
    )
    if not empenho:
        # Buscar pelo marcador (X) na lista de tipos
        if re.search(r"\(\s*[xX]\s*\)\s*Ordin[áa]rio", texto):
            empenho_tipo = "Ordinário"
        elif re.search(r"\(\s*[xX]\s*\)\s*Global", texto):
            empenho_tipo = "Global"
        elif re.search(r"\(\s*[xX]\s*\)\s*Estimativo", texto):
            empenho_tipo = "Estimativo"
        else:
            empenho_tipo = None
        if empenho_tipo:
            dados["tipo_empenho"] = empenho_tipo
    else:
        dados["tipo_empenho"] = empenho.group(1).strip().capitalize()

    # ── Fornecedor / Empresa ──
    # Formatos: "Nome da empresa: XXXX", "Empresa: XXXX"
    fornecedor = re.search(
        r"(?:Nome\s+da\s+empresa|Empresa):\s*(.+?)(?:\n|$)",
        texto, re.IGNORECASE
    )
    if fornecedor:
        nome_forn = fornecedor.group(1).strip()
        # Limpar se tiver "– CNPJ:" ou "CNPJ:" no final
        nome_forn = re.sub(r"\s*[–-]\s*CNPJ:.*$", "", nome_forn).strip()
        dados["fornecedor"] = nome_forn

    # ── CNPJ ──
    cnpj = re.search(
        r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto
    )
    if cnpj:
        dados["cnpj"] = cnpj.group(1)

    # ── Número de NC (pode haver múltiplas) ──
    # Eliminar duplicatas preservando a ordem
    ncs_brutas = re.findall(r"(20\d{2}NC\d{6})", texto)
    ncs = list(dict.fromkeys(ncs_brutas))  # remove duplicatas mantendo ordem
    if ncs:
        dados["nc"] = ncs[0]  # NC principal
        if len(ncs) > 1:
            dados["ncs_adicionais"] = ncs[1:]

    # ── Data da NC (adjacente ao número da NC) ──
    if dados["nc"]:
        nc_escapada = re.escape(dados["nc"])
        # Formatos aceitos: "de 05/02/2026", ", de 11/01/26", "de 27 JAN 26"
        data_nc = re.search(
            nc_escapada + r"[\s,]*(?:de\s+)?"
            r"(\d{1,2}/\d{2}/\d{2,4}"      # DD/MM/YYYY ou DD/MM/YY
            r"|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4}"   # DD MMM YY
            r"|\d{1,2}/[A-Za-z]{3}/\d{2,4}"   # DD/MMM/YYYY
            r"|\d{2}[A-Za-z]{3}\d{2,4})",     # DDMMMYY
            texto, re.IGNORECASE
        )
        if data_nc:
            dados["data_nc"] = data_nc.group(1).strip()

    # ── Órgão emissor da NC ──
    # Buscar no contexto de "Fonte de recursos" para evitar falsos positivos
    orgao_nc = re.search(
        r"(?:d[oae]\s+|d[oae]l[ao]\s+)"
        r"(DGO|COEX|COTER|DGP|COE|GDP|Diretoria\s+de\s+Gest[ãa]o\s+Or[çc]ament[áa]ria)",
        texto, re.IGNORECASE
    )
    if orgao_nc:
        orgao = orgao_nc.group(1).strip()
        # Normalizar nome extenso para sigla
        if "Diretoria" in orgao:
            orgao = "DGO"
        dados["orgao_emissor_nc"] = orgao.upper()

    # ── ND (Natureza da Despesa) ──
    nd = re.search(r"ND\s*(3[34]\d{4}|33\.90\.\d{2})", texto)
    if nd:
        dados["nd"] = nd.group(1)

    # ── PI (Plano Interno) ──
    pi = re.search(r"PI\s*([A-Z0-9]{8,15})", texto)
    if pi:
        dados["pi"] = pi.group(1)

    # ── PTRES ──
    ptres = re.search(r"PTRES\s*(\d{4,6})", texto)
    if ptres:
        dados["ptres"] = ptres.group(1)

    # ── UGR ──
    ugr = re.search(r"UGR\s*(\d{6})", texto)
    if ugr:
        dados["ugr"] = ugr.group(1)

    # ── FONTE ──
    fonte = re.search(r"FONTE\s*(\d{10})", texto)
    if fonte:
        dados["fonte"] = fonte.group(1)

    # ── Pregão ──
    pregao = re.search(
        r"(?:Preg[ãa]o|PE)\s*(?:Eletr[ôo]nico\s*)?(?:n[ºo°]\s*)?(\d{3,5}/\d{4})",
        texto, re.IGNORECASE
    )
    if pregao:
        dados["nr_pregao"] = _corrigir_numero_pregao(pregao.group(1))

    # ── Dados adicionais do pregão (UASG gerenciadora, OM, objeto) ──
    dados_pregao = _extrair_dados_pregao(texto)
    if dados_pregao:
        dados["pregao_detalhes"] = dados_pregao

    # ── UASG ──
    uasg = re.search(
        r"(?:UASG|gerenciad[ao]\s+pel[ao])\s*:?\s*(\d{6})",
        texto, re.IGNORECASE
    )
    if uasg:
        dados["uasg"] = uasg.group(1)

    # ── Tipo participação ──
    part = re.search(
        r"\((PART|GER|CAR|participante|gerenciador|carona)\)",
        texto, re.IGNORECASE
    )
    if not part:
        part = re.search(
            r"(participante|gerenciador|carona)",
            texto, re.IGNORECASE
        )
    if part:
        tipo_part = part.group(1).strip().upper()
        mapa_part = {
            "PARTICIPANTE": "PART", "GERENCIADOR": "GER", "CARONA": "CAR"
        }
        dados["tipo_participacao"] = mapa_part.get(tipo_part, tipo_part)

    # ── Contrato ──
    contrato = re.search(
        r"contrato\s*(?:n[ºo°]\s*)?(\d{1,3}/\d{4})",
        texto, re.IGNORECASE
    )
    if contrato:
        dados["nr_contrato"] = contrato.group(1)

    # ── UG gerenciadora (contratos) ──
    ug_ger = re.search(
        r"gerenciad[ao]\s+pel[ao]\s+UG\s*(\d{6})",
        texto, re.IGNORECASE
    )
    if ug_ger:
        dados["ug_gerenciadora"] = ug_ger.group(1)

    # ── Fiscal de contrato ──
    fiscal = re.search(
        r"(?:Gest[ãa]o e )?Fiscaliza[çc][ãa]o\s+de\s+Contrato:\s*(.+?)(?:\n|$)",
        texto, re.IGNORECASE
    )
    if fiscal:
        dados["fiscal_contrato"] = fiscal.group(1).strip()

    # ── Máscara pré-montada (campo 6/7 da requisição) ──
    mascara = _extrair_mascara_requisitante(texto, dados)
    if mascara:
        dados["mascara_requisitante"] = mascara

    return dados


# ══════════════════════════════════════════════════════════════════════
# VALIDAÇÃO E EXTRAÇÃO DE DADOS DO PREGÃO
# ══════════════════════════════════════════════════════════════════════

def _corrigir_numero_pregao(numero: str) -> str:
    """
    Corrige o número do pregão para o formato padrão de 5 dígitos.

    O padrão dos pregões do Exército é NNNNN/YYYY (5 dígitos),
    sempre começando com 90 (ex: 90004/2025, 90014/2024).

    Se o número extraído tiver 3 ou 4 dígitos e parecer incompleto
    (ex: '9014/2024' → '90014/2024', '004/2025' → '90004/2025'),
    insere o prefixo faltante.
    """
    if not numero:
        return numero

    partes = numero.split("/")
    if len(partes) != 2:
        return numero

    nr, ano = partes[0].strip(), partes[1].strip()

    # Se já tem 5 dígitos, retorna como está
    if len(nr) == 5:
        return f"{nr}/{ano}"

    # 4 dígitos começando com 9 → falta o 0 depois do 9
    # Ex: 9014 → 90014, 9006 → 90006
    if len(nr) == 4 and nr.startswith("9"):
        nr_corrigido = f"9{nr[1:].zfill(4)}"
        # Na verdade, o padrão é 90xxx: inserir 0 após o 9
        nr_corrigido = f"90{nr[1:]}"
        print(f"[PREGÃO] Número corrigido: {numero} -> {nr_corrigido}/{ano}")
        return f"{nr_corrigido}/{ano}"

    # 3 dígitos -> provavelmente falta o prefixo 90
    # Ex: 004 -> 90004, 014 -> 90014
    if len(nr) <= 3:
        nr_corrigido = f"90{nr.zfill(3)}"
        print(f"[PREGÃO] Número corrigido: {numero} -> {nr_corrigido}/{ano}")
        return f"{nr_corrigido}/{ano}"

    return numero


def _extrair_dados_pregao(texto: str) -> Optional[dict]:
    """
    Extrai dados detalhados do pregão a partir do texto da requisição.

    Busca padrões como:
    - "Pregão Eletrônico nº 90004/2025 gerenciado pela UASG 160142 – 9º B Sup"
    - "Pregão nº 90006/2024, da UASG 160141, CRO/9"
    - "PE 90004/2025, UASG 160142 (GER)"

    Retorna dict com: uasg_gerenciadora, nome_om_gerenciadora, objeto_pregao.
    Retorna None se não encontrar dados suficientes.
    """
    dados = {}

    # ── Padrão 1: "Pregão ... nº XXXXX/YYYY gerenciado pela UASG NNNNNN – OM"
    m1 = re.search(
        r"Preg[ãa]o\s+(?:Eletr[ôo]nico\s+)?(?:n[ºo°]\s*)?\d{3,5}/\d{4}"
        r"\s+gerenciad[ao]\s+pel[ao]\s+UASG\s+(\d{6})"
        r"\s*[–\-]\s*(.+?)(?:[,.]|\s+o qual|\s+da qual|\n)",
        texto, re.IGNORECASE
    )
    if m1:
        dados["uasg_gerenciadora"] = m1.group(1)
        dados["nome_om_gerenciadora"] = m1.group(2).strip()

    # ── Padrão 2: "Pregão nº XXXXX/YYYY, da UASG NNNNNN, OM"
    if not dados.get("uasg_gerenciadora"):
        m2 = re.search(
            r"Preg[ãa]o\s+(?:Eletr[ôo]nico\s+)?(?:n[ºo°]\s*)?\d{3,5}/\d{4}"
            r",?\s+d[ao]\s+UASG\s+(\d{6})"
            r"[,\s]+([^,\n]+?)(?:,\s+da qual|\s+da qual|\n|$)",
            texto, re.IGNORECASE
        )
        if m2:
            dados["uasg_gerenciadora"] = m2.group(1)
            nome_om = m2.group(2).strip()
            # Limpar: remover "da qual esta UASG" e afins
            nome_om = re.sub(r"\s+d[ao]\s+qual.*", "", nome_om).strip()
            if nome_om and len(nome_om) > 2:
                dados["nome_om_gerenciadora"] = nome_om

    # ── Padrão 3: "PE XXXXX/YYYY, UASG NNNNNN (GER/PART)"
    if not dados.get("uasg_gerenciadora"):
        m3 = re.search(
            r"PE\s+\d{3,5}/\d{4},?\s+UASG\s+(\d{6})",
            texto, re.IGNORECASE
        )
        if m3:
            dados["uasg_gerenciadora"] = m3.group(1)

    # ── Extrair objeto do pregão ──
    # Buscar trecho como: "despesas com a Aquisição de ..."
    # ou "despesas com aquisição de serviço, constante do Pregão"
    obj = re.search(
        r"despesas\s+com\s+(?:a\s+)?([Aa]quisi[çc][ãa]o\s+de\s+.+?)"
        r"(?:\s+para\s+atender|\s+constante|\s+por\s+meio|\s*[,.])",
        texto, re.IGNORECASE | re.DOTALL
    )
    if obj:
        dados["objeto_pregao"] = " ".join(obj.group(1).split())
    else:
        # Fallback: "aprovar as despesas com ..."
        obj2 = re.search(
            r"aprovar\s+as\s+despesas\s+com\s+(.+?)(?:\s+constante|\s+por\s+meio|\s*[,.])",
            texto, re.IGNORECASE | re.DOTALL
        )
        if obj2:
            dados["objeto_pregao"] = " ".join(obj2.group(1).split())

    return dados if dados else None


def _extrair_itens_via_tabelas(paginas_req: list[dict],
                               pdf_path: str) -> list[dict]:
    """
    Extrai itens usando extract_tables() do pdfplumber nas páginas
    da requisição. Mais preciso que regex para tabelas com layout complexo.
    """
    itens = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pag_info in paginas_req:
                idx = pag_info["numero"] - 1  # índice 0-based
                if idx >= len(pdf.pages):
                    continue

                pagina = pdf.pages[idx]
                tabelas = pagina.extract_tables()

                for tabela in tabelas:
                    itens_tabela = _processar_tabela_itens(tabela)
                    itens.extend(itens_tabela)
    except Exception as e:
        print(f"[AVISO] Erro ao extrair tabelas: {e}")

    return itens


def _processar_tabela_itens(tabela: list[list]) -> list[dict]:
    """
    Processa uma tabela extraída pelo pdfplumber e identifica se é
    uma tabela de itens de requisição. Retorna itens encontrados.

    Trata linhas de continuação (onde ITEM é None mas outras colunas
    têm dados complementares como CatMat ou UND).
    """
    if not tabela or len(tabela) < 2:
        return []

    itens = []

    # Identificar o cabeçalho da tabela
    idx_cabecalho = _encontrar_cabecalho_itens(tabela)
    if idx_cabecalho is None:
        return []

    cabecalho = tabela[idx_cabecalho]

    # Mapear colunas por nome
    mapa_colunas = _mapear_colunas(cabecalho)
    if "item" not in mapa_colunas:
        return []

    # Processar linhas de dados (após cabeçalho)
    for i in range(idx_cabecalho + 1, len(tabela)):
        linha = tabela[i]
        if not linha:
            continue

        item_dict = _processar_linha_item(linha, mapa_colunas)
        if item_dict:
            # Buscar dados complementares em linhas de continuação
            for j in range(i + 1, min(i + 3, len(tabela))):
                linha_cont = tabela[j]
                if not linha_cont:
                    continue
                # Linha de continuação: ITEM é None ou vazio
                idx_item = mapa_colunas.get("item", 0)
                if idx_item < len(linha_cont) and linha_cont[idx_item]:
                    val = str(linha_cont[idx_item]).strip()
                    if val and not val.upper().startswith("TOTAL"):
                        break  # próximo item, não continuação

                # Preencher campos vazios com dados da continuação
                _complementar_item(item_dict, linha_cont, mapa_colunas)

            itens.append(item_dict)

    return itens


def _complementar_item(item_dict: dict, linha_cont: list,
                       mapa: dict[str, int]) -> None:
    """
    Complementa dados de um item com valores de uma linha de continuação.
    Só preenche campos que estão None ou vazios.
    """
    campos_mapa = {
        "catserv": "catserv",
        "und": "und",
        "qtd": "qtd",
    }

    for campo_mapa, campo_item in campos_mapa.items():
        if item_dict.get(campo_item):
            continue  # já tem valor

        idx = mapa.get(campo_mapa)
        if idx is not None and idx < len(linha_cont) and linha_cont[idx]:
            valor = str(linha_cont[idx]).replace("\n", " ").strip()
            if valor:
                if campo_item == "qtd":
                    item_dict[campo_item] = _parse_valor_br(valor)
                else:
                    item_dict[campo_item] = valor


def _encontrar_cabecalho_itens(tabela: list[list]) -> Optional[int]:
    """
    Procura a linha de cabeçalho da tabela de itens.
    Identifica por conter palavras-chave como ITEM, QTD, UND, etc.
    """
    for i, linha in enumerate(tabela):
        if not linha:
            continue
        texto_linha = " ".join(
            str(c).upper() for c in linha if c
        )
        # Cabeçalho deve ter ITEM e pelo menos um de QTD/UND/P.UNT/ND
        if "ITEM" in texto_linha or "ÍTEM" in texto_linha or "TEM" in texto_linha:
            if any(kw in texto_linha for kw in [
                "QTD", "UND", "UNT", "TOTAL", "ND", "DESCRI"
            ]):
                return i
    return None


def _mapear_colunas(cabecalho: list) -> dict[str, int]:
    """
    Mapeia as colunas do cabeçalho para posições indexadas.
    Retorna dict com chaves padronizadas.
    Só mapeia a primeira ocorrência de cada tipo para evitar
    que colunas de justificativa sobrescrevam as corretas.
    """
    mapa = {}

    for i, celula in enumerate(cabecalho):
        if not celula:
            continue
        texto = str(celula).upper().replace("\n", " ").strip()

        # Só mapear se ainda não foi mapeado (primeira ocorrência)
        if "item" not in mapa and re.search(r"\bITEM\b|\bÍTEM\b", texto):
            mapa["item"] = i
        elif "catserv" not in mapa and re.search(r"CATMAT|CATSERV|C[ÓO]D", texto):
            mapa["catserv"] = i
        elif "descricao" not in mapa and re.search(r"DESCRI", texto):
            mapa["descricao"] = i
        elif "und" not in mapa and re.search(r"\bUND\b|\bUN\b|UNID", texto):
            mapa["und"] = i
        elif "qtd" not in mapa and re.search(r"\bQTD\b|\bQUANT\b", texto):
            mapa["qtd"] = i
        elif "nd_si" not in mapa and re.search(r"\bND\b.*S\.?I\.?|\bND\s*/\s*S", texto):
            mapa["nd_si"] = i
        elif "p_unit" not in mapa and re.search(r"P[\.\s]*UNT|UNIT[ÁA]RIO|V[\.\s]*UNIT", texto):
            mapa["p_unit"] = i
        elif "p_total" not in mapa and re.search(r"P[\s]*TOTAL|V[\.\s]*TOTAL", texto):
            mapa["p_total"] = i

    return mapa


def _processar_linha_item(linha: list, mapa: dict[str, int]) -> Optional[dict]:
    """
    Processa uma linha de dados da tabela e extrai o item.
    Retorna None se a linha não for um item válido.
    """
    def _celula(chave: str) -> Optional[str]:
        """Obtém o valor de uma célula pelo nome mapeado."""
        idx = mapa.get(chave)
        if idx is not None and idx < len(linha) and linha[idx]:
            return str(linha[idx]).replace("\n", " ").strip()
        return None

    # Verificar se é linha de item (ITEM deve ser número)
    item_str = _celula("item")
    if not item_str:
        return None

    # Verificar se é "TOTAL" ou cabeçalho repetido
    if re.search(r"TOTAL|ITEM|ÍTEM", item_str, re.IGNORECASE):
        return None

    # Extrair número do item
    item_num = re.search(r"(\d+)", item_str)
    if not item_num:
        return None

    # Extrair os demais campos
    descricao = _celula("descricao")
    if not descricao:
        # Tentar campo adjacente ao catserv ou item
        for idx in range(len(linha)):
            if idx != mapa.get("item") and linha[idx]:
                texto = str(linha[idx]).strip()
                if len(texto) > 15:  # descrição geralmente é longa
                    descricao = texto.replace("\n", " ")
                    break

    # ND/SI — pode vir como "39.17" ou "33.90.39/24" etc.
    nd_si_raw = _celula("nd_si")
    nd_si = None
    if nd_si_raw:
        # Limpar quebras de linha e espaços
        nd_si = nd_si_raw.replace(" ", "").replace("\n", "")
        # Se veio como "33.90.39/24", normalizar para "39.24"
        m_nd = re.search(r"(\d{2})\.(\d{2})", nd_si)
        if m_nd:
            nd_si = nd_si  # manter como está

    # Valores monetários
    p_unit_raw = _celula("p_unit")
    p_total_raw = _celula("p_total")

    # Limpar prefixo R$ dos valores
    def _limpar_valor(v):
        if not v:
            return None
        v = re.sub(r"R\$\s*", "", v).strip()
        return _parse_valor_br(v)

    return {
        "item": int(item_num.group(1)),
        "catserv": _celula("catserv"),
        "descricao": descricao,
        "und": _celula("und"),
        "qtd": _parse_valor_br(_celula("qtd")) if _celula("qtd") else None,
        "nd_si": nd_si,
        "p_unit": _limpar_valor(p_unit_raw),
        "p_total": _limpar_valor(p_total_raw),
    }


def _extrair_mascara_requisitante(texto: str, dados_req: dict) -> Optional[str]:
    """
    Tenta extrair a máscara pré-montada pelo requisitante (campo 6/7).

    O campo 6 ou 7 da requisição contém a descrição que o requisitante
    pré-montou para o campo "Descrição" da NE. Geralmente começa após
    "6. Material/Serviço a ser adquirido" ou "7. Descrição" e contém
    OM, REQ, NC, ND, PI, PE/CONTRATO, UASG.

    Nem toda requisição terá esse campo preenchido como máscara —
    retorna None quando não encontra.
    """
    if not dados_req.get("nc"):
        return None

    nc_escapada = re.escape(dados_req["nc"])

    # ── Estratégia 1: Buscar dentro do campo 6 ou 7 especificamente ──
    # Formato: "6. Material/Serviço a ser adquirido/contratado:\n ..."
    # Ou:      "7. Descrição do material..."
    # O bloco vai até o próximo item numerado (8., 9.) ou fim de página
    match_campo = re.search(
        r"[67]\.\s*(?:Material|Descri[çc][ãa]o|Servi[çc]o)[^\n]*\n"
        r"([\s\S]+?)(?=\n\s*(?:\d+\.|\bEste documento|$))",
        texto, re.IGNORECASE
    )
    if match_campo:
        bloco_campo67 = match_campo.group(1).strip()
        # Verificar se o bloco contém NC e dados financeiros (ND + PI/PE)
        if re.search(nc_escapada, bloco_campo67):
            tem_nd = bool(re.search(r"\bND\s", bloco_campo67))
            tem_pi_pe = bool(
                re.search(r"\bPI\s", bloco_campo67)
                or re.search(r"\bPE\s", bloco_campo67)
                or re.search(r"\bCONT(?:RATO)?\s", bloco_campo67, re.IGNORECASE)
            )
            if tem_nd and tem_pi_pe:
                # Limpar: juntar linhas e remover espaços duplos
                mascara = " ".join(bloco_campo67.split())
                return mascara

    # ── Estratégia 2 (fallback): buscar bloco com NC + ND + PE/PI ──
    # Procura qualquer trecho no texto que contenha a NC acompanhada
    # de ND e PI/PE no mesmo parágrafo (até 6 linhas)
    match = re.search(
        r"([^\n]*" + nc_escapada + r"[^\n]*(?:\n[^\n]+){0,6})",
        texto
    )
    if match:
        candidato = match.group(1).strip()
        candidato_joined = " ".join(candidato.split())

        tem_nd = bool(re.search(r"\bND\s", candidato_joined))
        tem_pe_uasg = bool(
            re.search(r"\bPE\s+\d", candidato_joined)
            or re.search(r"\bUASG\s+\d", candidato_joined)
            or re.search(r"\bCONT(?:RATO)?\s", candidato_joined, re.IGNORECASE)
        )

        if tem_nd and tem_pe_uasg:
            return candidato_joined

    return None


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DE ITENS VIA OCR (FALLBACK)
# ══════════════════════════════════════════════════════════════════════

def _extrair_itens_ocr(paginas_req: list[dict],
                       pdf_path: str) -> list[dict]:
    """
    Fallback: quando pdfplumber não extraiu itens (tabela em imagem),
    tenta OCR nas imagens incorporadas das páginas de requisição.

    Estratégia:
    1. Percorre páginas de requisição
    2. Extrai imagens incorporadas (tabelas renderizadas como imagem)
    3. Faz OCR na imagem
    4. Parseia o texto OCR com regex para encontrar itens
    """
    if not _OCR_DISPONIVEL:
        return []

    itens = []
    for pag in paginas_req:
        page_idx = pag["numero"] - 1
        imgs_ocr = _ocr_imagens_incorporadas(pdf_path, page_idx)

        for img_info in imgs_ocr:
            texto = img_info["texto"]
            itens_img = _parsear_itens_ocr(texto)
            itens.extend(itens_img)

    return itens


def _extrair_fornecedor_ocr(paginas_req: list[dict],
                            pdf_path: str) -> dict:
    """
    Extrai fornecedor e CNPJ de imagens incorporadas nas páginas
    da requisição (OCR). Usado quando o pdfplumber não encontra
    esses dados no texto extraível (fornecedor está dentro da tabela
    renderizada como imagem).

    Retorna dict com chaves 'fornecedor' e 'cnpj' (podem ser None).
    """
    dados = {"fornecedor": None, "cnpj": None}

    if not _OCR_DISPONIVEL:
        return dados

    for pag in paginas_req:
        page_idx = pag["numero"] - 1
        imgs_ocr = _ocr_imagens_incorporadas(pdf_path, page_idx)

        for img_info in imgs_ocr:
            texto = img_info["texto"]
            if not texto:
                continue

            # ── CNPJ (formato XX.XXX.XXX/XXXX-XX) ──
            if not dados["cnpj"]:
                m = re.search(
                    r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto
                )
                if m:
                    dados["cnpj"] = m.group(1)

            # ── Fornecedor / Empresa ──
            if not dados["fornecedor"]:
                m = re.search(
                    r"(?:Nome\s+da\s+[Ee]mpresa|[Ee]mpresa)\s*:\s*(.+?)(?:\n|$)",
                    texto
                )
                if m:
                    nome = m.group(1).strip()
                    # Limpar se tiver CNPJ colado no final
                    nome = re.sub(r"\s*[–-]\s*CNPJ:.*$", "", nome).strip()
                    if nome and len(nome) > 3:
                        dados["fornecedor"] = nome

            # Se já encontrou ambos, não precisa continuar
            if dados["fornecedor"] and dados["cnpj"]:
                break

        if dados["fornecedor"] and dados["cnpj"]:
            break

    if dados["fornecedor"] or dados["cnpj"]:
        print(f"[OCR] Fornecedor/CNPJ extraídos da imagem: "
              f"fornecedor={dados['fornecedor']}, cnpj={dados['cnpj']}")

    return dados


def _parsear_itens_ocr(texto_ocr: str) -> list[dict]:
    """
    Parseia texto obtido por OCR de uma tabela de itens de requisição.

    O OCR de tabelas em imagem produz texto desorganizado (colunas misturadas,
    quebras de linha no meio de campos). A estratégia é holística:
    1. Detectar múltiplos itens (por número de item ou múltiplos CatMats)
    2. Para cada item, extrair dados-chave (CatMat, R$, ND, QTD)
    3. Montar o item a partir das peças encontradas
    """
    if not texto_ocr:
        return []

    texto_completo = " ".join(texto_ocr.split())  # normalizar espaços
    linhas = texto_ocr.split("\n")

    # ── ESTRATÉGIA 1: Detectar múltiplos itens por número de item ──
    # Procurar padrões como "00001 -", "00002 -", "228", "235", etc.
    # Padrão 1: número seguido de hífen/traço e letra (ex: "00001 - DESCRIÇÃO")
    itens_numeros = []
    for match in re.finditer(r"\b(\d{3,5})\s*[-–]\s+[A-Z]", texto_ocr, re.MULTILINE):
        item_num = int(match.group(1))
        pos_inicio = match.start()
        linha_idx = texto_ocr[:pos_inicio].count("\n")
        itens_numeros.append({
            "numero": item_num,
            "posicao": pos_inicio,
            "linha": linha_idx,
        })
    
    # Padrão 2: números de item isolados (ex: "228", "235") que aparecem antes de descrições
    # Procurar por números de 3 dígitos que não são CatMat, CNPJ, ou valores monetários
    # e que aparecem em contexto de tabela de itens
    numeros_item_isolados = []
    for match in re.finditer(r"\b(\d{3})\b", texto_ocr):
        num = match.group(1)
        num_int = int(num)
        pos = match.start()
        
        # Verificar contexto: deve estar em contexto de tabela (próximo a palavras-chave)
        contexto_antes = texto_ocr[max(0, pos-50):pos].upper()
        contexto_depois = texto_ocr[pos:min(len(texto_ocr), pos+100)].upper()
        
        # Excluir se é parte de outro campo
        if ("R$" in contexto_antes or 
            "." in contexto_antes[-3:] or  # pode ser parte de valor
            "/" in contexto_depois[:10] or  # pode ser parte de data/CNPJ/ND
            re.match(r"^[3-4]\d{5}$", num)):  # é CatMat
            continue
        
        # Verificar se está em contexto de item (próximo a "ITEM", descrição, ou valores)
        tem_contexto_item = (
            "ITEM" in contexto_antes or
            any(palavra in contexto_depois[:50] for palavra in ["KG", "UN", "UND", "R$", "DESCRI"])
        )
        
        # Aceitar números de item típicos (100-999, mas não muito próximos de outros números)
        if 100 <= num_int <= 999 and tem_contexto_item:
            # Verificar se não é duplicata de um número já encontrado
            if not any(abs(n["numero"] - num_int) < 5 for n in itens_numeros):
                linha_idx = texto_ocr[:pos].count("\n")
                numeros_item_isolados.append({
                    "numero": num_int,
                    "posicao": pos,
                    "linha": linha_idx,
                })
    
    # Combinar ambos os padrões e remover duplicatas
    todos_numeros_item = itens_numeros + numeros_item_isolados
    # Remover duplicatas por número (manter o primeiro encontrado)
    itens_numeros_unicos = []
    numeros_vistos = set()
    for item_info in sorted(todos_numeros_item, key=lambda x: x["posicao"]):
        if item_info["numero"] not in numeros_vistos:
            itens_numeros_unicos.append(item_info)
            numeros_vistos.add(item_info["numero"])
    
    itens_numeros = sorted(itens_numeros_unicos, key=lambda x: x["posicao"])

    # ── ESTRATÉGIA 2: Detectar múltiplos CatMats (cada CatMat = 1 item) ──
    # CatMat pode ser 5 ou 6 dígitos começando com 1, 3 ou 4
    catmats = re.findall(r"\b([1-4]\d{4,5})\b", texto_completo)
    # Remover duplicatas mantendo ordem
    catmats_unicos = []
    for cat in catmats:
        # Validar: deve ter 5 ou 6 dígitos e começar com 1, 3 ou 4
        if len(cat) in [5, 6] and cat[0] in ['1', '3', '4']:
            if cat not in catmats_unicos:
                catmats_unicos.append(cat)

    # ── ESTRATÉGIA 2b: Detectar múltiplas quantidades ou valores (indicam múltiplos itens) ──
    # Procurar padrões de quantidade (ex: "3617 KG", "500 UN", ou números grandes sozinhos)
    # Padrão mais flexível: número seguido de unidade OU número grande isolado
    quantidades_com_unidade = re.findall(r"\b(\d{2,6})\s*(?:KG|UN|UND|L|M2|M3|CX|PCT|LT|HR|SV|MÊS)\b", texto_completo, re.IGNORECASE)
    # Também procurar números grandes que podem ser quantidades (3+ dígitos)
    numeros_grandes = re.findall(r"\b(\d{3,6})\b", texto_completo)
    # Filtrar números que não são CatMat, CNPJ, ou valores monetários
    numeros_grandes_filtrados = [n for n in numeros_grandes 
                                  if not re.match(r"^[3-4]\d{5}$", n)  # não é CatMat
                                  and not re.match(r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$", n)  # não é CNPJ
                                  and len(n) >= 3]
    
    # Procurar múltiplos valores monetários significativos
    valores_monetarios = re.findall(r"R\$\s*([\d.]+,\d{2})", texto_completo)
    valores_float = [_parse_valor_br(v) for v in valores_monetarios if _parse_valor_br(v)]
    
    # Se há 2+ quantidades com unidade OU 2+ números grandes (que podem ser quantidades) OU 3+ valores monetários
    tem_multiplos_sinais = (len(quantidades_com_unidade) >= 2) or (len(numeros_grandes_filtrados) >= 2) or (len(valores_float) >= 3)

    # ── Decidir quantos itens há ──
    num_itens_esperado = max(len(itens_numeros), len(catmats_unicos), 1)
    if tem_multiplos_sinais and len(catmats_unicos) == 1:
        # Se há apenas 1 CatMat mas múltiplos sinais, assumir 2 itens
        num_itens_esperado = max(num_itens_esperado, 2)

    # Se encontrou números de item explícitos, usar esses (prioridade máxima)
    if len(itens_numeros) >= 2:
        # Processar cada item separadamente
        itens = []
        numeros_item_usados = set()  # Evitar duplicatas
        
        for i, item_info in enumerate(itens_numeros):
            item_num = item_info["numero"]
            
            # Pular se já processamos este número de item
            if item_num in numeros_item_usados:
                continue
            
            linha_inicio = item_info["linha"]
            linha_fim = itens_numeros[i + 1]["linha"] if i + 1 < len(itens_numeros) else len(linhas)
            
            # Extrair trecho do texto para este item
            trecho_linhas = linhas[linha_inicio:linha_fim]
            trecho_texto = "\n".join(trecho_linhas)
            trecho_completo = " ".join(trecho_texto.split())

            # Extrair dados deste item específico
            # Tentar encontrar o CatMat mais próximo deste número de item
            catmat_proximo = None
            if catmats_unicos:
                # Procurar CatMat no trecho deste item
                for cat in catmats_unicos:
                    if cat in trecho_completo:
                        catmat_proximo = cat
                        break
                # Se não encontrou no trecho, usar o primeiro disponível
                if not catmat_proximo and len(catmats_unicos) > len(itens):
                    catmat_proximo = catmats_unicos[len(itens)]
            
            item_dict = _extrair_item_ocr_individual(trecho_texto, trecho_completo, item_num, catmat_proximo)
            if item_dict:
                # Garantir que o número do item está correto
                item_dict["item"] = item_num
                itens.append(item_dict)
                numeros_item_usados.add(item_num)
        
        # Remover duplicatas baseadas no número do item (manter o primeiro)
        itens_unicos = []
        numeros_vistos = set()
        for item in itens:
            if item["item"] not in numeros_vistos:
                itens_unicos.append(item)
                numeros_vistos.add(item["item"])
        
        if itens_unicos:
            print(f"[OCR] {len(itens_unicos)} item(ns) extraído(s) via OCR (números de item: {sorted(numeros_vistos)})")
            return itens_unicos

    # ── ESTRATÉGIA 3: Múltiplos CatMats sem números de item explícitos ──
    if len(catmats_unicos) >= 2:
        itens = []
        for i, catmat in enumerate(catmats_unicos):
            # Encontrar posição do CatMat no texto
            pos_cat = texto_completo.find(catmat)
            if pos_cat < 0:
                continue
            
            # Delimitar trecho: do CatMat atual até o próximo (ou fim)
            pos_fim = len(texto_completo)
            if i + 1 < len(catmats_unicos):
                pos_prox = texto_completo.find(catmats_unicos[i + 1], pos_cat + 1)
                if pos_prox > pos_cat:
                    pos_fim = pos_prox
            
            # Converter posições para linhas
            trecho_texto = texto_ocr[pos_cat:pos_fim] if pos_fim < len(texto_ocr) else texto_ocr[pos_cat:]
            trecho_completo = " ".join(trecho_texto.split())

            item_num = i + 1  # numerar sequencialmente
            item_dict = _extrair_item_ocr_individual(trecho_texto, trecho_completo, item_num, catmat)
            if item_dict:
                itens.append(item_dict)
        
        if itens:
            return itens

    # ── ESTRATÉGIA 4: 1 CatMat mas múltiplos sinais (quantidades/valores) ──
    # Dividir o texto em seções baseado em quantidades ou valores monetários
    # SÓ usar esta estratégia se NÃO encontrou números de item explícitos
    if len(catmats_unicos) == 1 and tem_multiplos_sinais and len(itens_numeros) < 2:
        catmat = catmats_unicos[0]
        itens = []
        
        # Encontrar todas as quantidades no texto (com contexto)
        # Padrão mais flexível: número seguido de unidade, mesmo com espaços
        qtd_matches = list(re.finditer(r"\b(\d{2,6})\s*(?:KG|UN|UND|L|M2|M3|CX|PCT|LT|HR|SV|MÊS)\b", texto_ocr, re.IGNORECASE))
        
        # Também procurar por números grandes que podem ser quantidades sem unidade explícita
        # (no OCR, a unidade pode estar em outra linha ou não ser capturada)
        # Mas ser mais restritivo: apenas números realmente grandes (4+ dígitos) e que não sejam
        # parte de outros campos
        numeros_grandes_matches = list(re.finditer(r"\b(\d{4,6})\b", texto_ocr))
        numeros_validos = []
        for match in numeros_grandes_matches:
            num = match.group(1)
            num_int = int(num)
            pos = match.start()
            # Verificar contexto: não é CatMat, não é parte de CNPJ, não é valor monetário
            contexto_antes = texto_ocr[max(0, pos-15):pos].upper()
            contexto_depois = texto_ocr[pos:min(len(texto_ocr), pos+15)].upper()
            
            # Excluir se parece ser parte de outro campo
            if ("R$" in contexto_antes or 
                "." in contexto_antes[-5:] or  # pode ser parte de valor
                "/" in contexto_depois[:5] or   # pode ser parte de data/CNPJ
                re.match(r"^[3-4]\d{5}$", num)):  # é CatMat
                continue
            
            # Aceitar apenas números que fazem sentido como quantidade (não muito grandes)
            # Quantidades típicas: 1-99999
            if 1 <= num_int <= 99999:
                numeros_validos.append(match)
        
        # Combinar quantidades com unidade e números grandes válidos
        todas_quantidades = sorted(qtd_matches + numeros_validos, key=lambda m: m.start())
        # Remover duplicatas próximas (mesmo número em posições muito próximas)
        quantidades_unicas = []
        for match in todas_quantidades:
            if not quantidades_unicas:
                quantidades_unicas.append(match)
            else:
                # Só adicionar se estiver suficientemente distante e for um número diferente
                ultimo_match = quantidades_unicas[-1]
                distancia = match.start() - ultimo_match.start()
                num_atual = match.group(1)
                num_anterior = ultimo_match.group(1)
                
                # Se é o mesmo número muito próximo, ignorar (duplicata)
                if num_atual == num_anterior and distancia < 100:
                    continue
                # Se está muito próximo mas é número diferente, pode ser parte do mesmo item
                if distancia < 30:
                    continue
                quantidades_unicas.append(match)
        
        # Se encontrou 2+ quantidades, dividir o texto por elas
        if len(quantidades_unicas) >= 2:
            # Ordenar por posição no texto
            quantidades_unicas.sort(key=lambda m: m.start())
            
            # Limitar a 2 itens máximo (evitar falsos positivos)
            quantidades_unicas = quantidades_unicas[:2]
            
            for i, qtd_match in enumerate(quantidades_unicas):
                qtd_valor = qtd_match.group(1)
                pos_inicio = qtd_match.start()
                
                # Determinar fim do trecho: início da próxima quantidade ou fim do texto
                if i + 1 < len(quantidades_unicas):
                    pos_fim = quantidades_unicas[i + 1].start()
                else:
                    pos_fim = len(texto_ocr)
                
                # Pegar trecho completo deste item (do início até o próximo)
                # Incluir um pouco antes para pegar descrição que pode estar acima
                contexto_antes = max(0, pos_inicio - 300)
                trecho_texto = texto_ocr[contexto_antes:pos_fim]
                trecho_completo = " ".join(trecho_texto.split())
                
                # Extrair item deste trecho
                item_num = i + 1
                # Usar o CatMat para todos os itens (mesmo CatMat, múltiplos itens)
                item_dict = _extrair_item_ocr_individual(trecho_texto, trecho_completo, item_num, catmat)
                
                if item_dict:
                    # Garantir que a quantidade extraída corresponde à encontrada
                    if not item_dict.get("qtd") or abs(item_dict.get("qtd", 0) - float(qtd_valor)) > 0.1:
                        # Forçar a quantidade encontrada
                        try:
                            item_dict["qtd"] = float(qtd_valor)
                        except:
                            pass
                    
                    # Garantir CatMat
                    if not item_dict.get("catserv") and catmat:
                        item_dict["catserv"] = catmat
                    
                    itens.append(item_dict)
            
            # Se conseguiu extrair exatamente 2 itens válidos, retornar
            if len(itens) == 2:
                print(f"[OCR] {len(itens)} item(ns) extraído(s) via OCR (múltiplos sinais detectados)")
                return itens

    # ── FALLBACK: Processar como item único (lógica original) ──
    item_dict = _extrair_item_ocr_individual(texto_ocr, texto_completo, 1)
    if item_dict:
        return [item_dict]
    
    return []


def _extrair_item_ocr_individual(trecho_texto: str, trecho_completo: str,
                                  item_num: int, catmat_forcado: str = None) -> Optional[dict]:
    """
    Extrai dados de um item individual a partir de um trecho de texto OCR.
    """
    # ── CatMat/CatServ ──
    if catmat_forcado:
        catmat = catmat_forcado
    else:
        # CatMat pode ser 5 ou 6 dígitos começando com 1, 3 ou 4
        catmats = re.findall(r"\b([1-4]\d{4,5})\b", trecho_completo)
        # Filtrar apenas os válidos (5-6 dígitos, começando com 1, 3 ou 4)
        catmats_validos = [c for c in catmats if len(c) in [5, 6] and c[0] in ['1', '3', '4']]
        catmat = catmats_validos[0] if catmats_validos else None

    # ── ND/SI (padrão XX/XX, excluindo CNPJ que tem /XXXX) ──
    nd_match = re.search(r"\b(\d{2})/(\d{2})\b(?!\d)", trecho_completo)
    nd_si = f"{nd_match.group(1)}/{nd_match.group(2)}" if nd_match else None

    # ── Valores monetários (R$ X.XXX,XX ou R$X,XX) ──
    valores = re.findall(r"R\$\s*([\d.]+,\d{2})", trecho_completo)
    valores_float = [_parse_valor_br(v) for v in valores if _parse_valor_br(v)]

    # Identificar unit/total: menor = unitário, maior = total
    p_unit = None
    p_total = None
    if len(valores_float) >= 2:
        valores_float.sort()
        p_unit = valores_float[0]
        p_total = valores_float[-1]
    elif len(valores_float) == 1:
        p_total = valores_float[0]

    # ── TOTAL FORNECEDOR (confirmação do total) ──
    total_forn = re.search(
        r"TOTAL\s+FORNECEDOR\s+(?:R[\$\s]?\s*)?([\d.,]+)", trecho_completo
    )
    if total_forn:
        total_str = total_forn.group(1)
        if total_str.count(",") >= 2:
            partes = total_str.rsplit(",", 1)
            milhar = partes[0].replace(",", ".")
            total_str = milhar + "," + partes[1]
        val = _parse_valor_br(total_str)
        if val:
            p_total = val

    # ── Quantidade ──
    qtd = None
    # Prioridade 1: buscar quantidade perto de UND/KG (mais confiável)
    qtd_vizinha = re.search(
        r"\b(\d{1,4})\s*(?:KG|UN|UND|L|M2|CX|PCT|LT|HR|SV|M)\b",
        trecho_completo, re.IGNORECASE
    )
    if qtd_vizinha:
        num_qtd = int(qtd_vizinha.group(1))
        # Quantidades típicas: 1-9999 (evitar números muito grandes)
        if 1 <= num_qtd <= 9999:
            qtd = float(num_qtd)
    
    # Prioridade 2: buscar entre CatMat e R$ (se não encontrou com unidade)
    if qtd is None and catmat:
        pos_cat = trecho_completo.find(catmat)
        pos_rs = trecho_completo.find("R$", pos_cat)
        if pos_cat >= 0 and pos_rs > pos_cat:
            trecho = trecho_completo[pos_cat + len(catmat):pos_rs]
            # Procurar números pequenos (1-4 dígitos) que não sejam parte de valores grandes
            nums = re.findall(r"\b(\d{1,4})\b", trecho)
            for n in nums:
                n_int = int(n)
                nd_nums = []
                if nd_match:
                    nd_nums = [nd_match.group(1), nd_match.group(2)]
                # Aceitar apenas números razoáveis (1-9999) e que não sejam ND/SI
                if 1 <= n_int <= 9999 and n not in nd_nums:
                    # Verificar se não é parte de um número maior (ex: 30.222)
                    pos_num = trecho.find(n)
                    if pos_num >= 0:
                        contexto_antes = trecho[max(0, pos_num-3):pos_num]
                        contexto_depois = trecho[pos_num+len(n):min(len(trecho), pos_num+len(n)+3)]
                        # Se tem ponto ou vírgula próximo, pode ser parte de número maior
                        if "." not in contexto_antes and "." not in contexto_depois[:1]:
                            qtd = float(n_int)
                            break

    # ── Unidade ──
    und_match = re.search(
        r"\b(KG|UN|UND|L|M|M2|M3|CX|PCT|PAR|JG|GL|LT|HR|SV|MÊS)\b",
        trecho_completo, re.IGNORECASE
    )
    und = und_match.group(1).upper() if und_match else None

    # ── Descrição do produto ──
    descricao = _extrair_descricao_ocr(trecho_texto, catmat)

    if not descricao and not catmat and not p_total:
        return None  # nenhum dado útil encontrado

    return {
        "item": item_num,
        "catserv": catmat,
        "descricao": descricao,
        "und": und,
        "qtd": qtd,
        "nd_si": nd_si,
        "p_unit": p_unit,
        "p_total": p_total,
        "fonte": "ocr",
    }


def _extrair_descricao_ocr(texto_ocr: str, catmat: str = None) -> str:
    """
    Extrai a descrição do produto/serviço de texto OCR de tabela.

    Estratégia:
    1. Encontrar texto do produto na linha do CatMat
    2. Buscar continuações em linhas subsequentes (ex: PETROLEO-GLP)
    3. Juntar tudo e limpar artefatos
    """
    linhas = texto_ocr.split("\n")
    desc_parts = []
    capturando = False

    # Palavras a ignorar (cabeçalhos, campos da tabela, metadados)
    excluir = [
        "TOTAL", "JUSTIFICATIVA", "AQUISIÇÃO", "MOTIVO",
        "QUANTIDADE", "FORNECEDOR", "CNPJ", "NOME DA EMPRESA",
        "APROVISIONAMENT", "CHEFE", "ORDENADOR", "P.UNT", "P TOTAL",
        "SER ADQUIRIDA", "CATMAT", "CATSER", "DESCRIÇÃO DO",
        "SEMESTRAL", "CONFORME", "ORIENTAÇ", "SUFICIENTE",
        "CONTRATADA", "NOTA DE CRÉDITO",
    ]

    for linha in linhas:
        linha = linha.strip()
        if not linha or len(linha) < 3:
            continue

        # ── Linha do CatMat: extrair início da descrição ──
        if catmat and catmat in linha:
            pos = linha.find(catmat) + len(catmat)
            resto = linha[pos:].strip().lstrip("|").strip()
            # Remover quantidade, ND/SI, valores monetários e artefatos
            desc = re.sub(r"\b\d{3,5}\b", " ", resto)
            desc = re.sub(r"\d{2}/\d{2}", " ", desc)
            desc = re.sub(r"R\$\s*[\d.,]+", " ", desc)
            desc = re.sub(r"\|", " ", desc)
            desc = _limpar_descricao_ocr(desc)
            if len(desc) > 3:
                desc_parts.append(desc)
                capturando = True
            continue

        # ── Linhas de continuação (após o CatMat) ──
        if capturando:
            linha_upper = linha.upper()
            # Parar se encontrar TOTAL FORNECEDOR
            if "TOTAL" in linha_upper and "FORNECEDOR" in linha_upper:
                break
            # Pegar primeira palavra CAPS antes de verificar exclusão
            primeira = linha.split()[0] if linha.split() else ""
            # Ignorar linhas onde a PRIMEIRA palavra é de cabeçalho
            if primeira.upper() in excluir:
                continue

            # Extrair palavras em MAIÚSCULAS do início da linha
            # (descrição do produto costuma ser CAPS; justificativa é mista)
            palavras = []
            for palavra in linha.split():
                pal_limpa = re.sub(r"[|]", "", palavra)
                if not pal_limpa:
                    continue
                # Aceitar: palavras CAPS, preposições, e hífens
                if (pal_limpa.isupper()
                        or pal_limpa in ["de", "do", "da", "e", "para", "com"]
                        or re.match(r"^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ-]+$",
                                    pal_limpa)):
                    if not pal_limpa.isdigit():
                        palavras.append(pal_limpa)
                else:
                    break  # encontrou lowercase → parar

            if palavras:
                trecho = " ".join(palavras)
                trecho = _limpar_descricao_ocr(trecho)
                if trecho and len(trecho) > 2:
                    desc_parts.append(trecho)

    if desc_parts:
        descricao = " ".join(desc_parts)
        # Limpeza: remover preposições soltas no final
        descricao = re.sub(r"\s+(?:de|do|da|e|DE|DO|DA|E)\s*$", "", descricao)
        # Limpeza: remover preposição isolada entre partes
        # Ex: "GÁS LIQUEFEITO DE do PETROLEO" → "GÁS LIQUEFEITO DE PETROLEO"
        descricao = re.sub(
            r"\b(DE|DO|DA)\s+(de|do|da)\s+", r"\1 ", descricao
        )
        return descricao.strip()

    return ""


def _limpar_descricao_ocr(descricao: str) -> str:
    """Limpa artefatos de OCR na descrição do item."""
    if not descricao:
        return ""
    # Remover caracteres de controle e pipes (artefatos de tabela)
    descricao = re.sub(r"[|]", " ", descricao)
    # Remover sequências com caracteres especiais de OCR (ª, %, ;, !, <, >)
    descricao = re.sub(r"[\"'\[\]<>]", " ", descricao)
    descricao = re.sub(r"\S*[ªº;%!@#&=]+\S*", " ", descricao)
    # Remover valores monetários residuais
    descricao = re.sub(r"R\$\s*[\d.,]+", " ", descricao)
    descricao = re.sub(r",\d{2}\b", " ", descricao)  # fragmento de decimal
    # Remover números soltos (3+ dígitos sem contexto)
    descricao = re.sub(r"\b\d{3,}\b", " ", descricao)
    # Remover espaços múltiplos
    descricao = re.sub(r"\s+", " ", descricao).strip()
    # Remover lixo no final (caracteres especiais, números)
    descricao = re.sub(r"[\d.,\s]+$", "", descricao).strip()
    # Se ficou muito curto após limpeza, descartar
    if len(descricao) < 3:
        return ""
    return descricao


# ══════════════════════════════════════════════════════════════════════
# COMPLEMENTO NC COM ESPELHO OCR
# ══════════════════════════════════════════════════════════════════════

def _complementar_nc_com_ocr(notas_credito: list[dict],
                             paginas_class: dict,
                             pdf_path: str) -> None:
    """
    Procura páginas não-classificadas ou de NC que vieram de OCR e
    contém dados do 'espelho' da NC (Fonte, ND, UGR, PI, Prazo etc.).
    Complementa as NCs existentes com esses dados.
    """
    if not notas_credito or not _OCR_DISPONIVEL:
        return

    # Coletar texto de páginas OCR que podem ter espelhos
    # (páginas que vieram de OCR e mencionam campos financeiros)
    textos_espelho = []

    # Verificar páginas não classificadas e páginas de NC com fonte OCR
    categorias = ["nao_classificada", "nota_credito"]
    for cat in categorias:
        for pag in paginas_class.get(cat, []):
            if pag.get("fonte") != "ocr":
                continue
            texto = pag["texto"].upper()
            # Verificar se parece um espelho de NC
            indicadores_espelho = [
                "FONTE" in texto and "RECURSO" in texto,
                "NATUREZA DA DESPESA" in texto or "ND " in texto,
                "PLANO INTERNO" in texto or "PI " in texto,
                "UGR" in texto,
            ]
            if sum(indicadores_espelho) >= 2:
                textos_espelho.append(pag["texto"])

    if not textos_espelho:
        return

    texto_espelho = "\n".join(textos_espelho)

    # Extrair campos do espelho (OCR pode ter quebras de linha entre
    # rótulo e valor, então usamos re.DOTALL para pular linhas)
    dados_espelho = {}

    # Fonte de Recursos (10 dígitos, pode estar na linha seguinte ao rótulo)
    # No OCR, rótulos ficam numa linha e valores na outra
    fonte = re.search(
        r"Fonte.{0,80}?(\d{10})", texto_espelho,
        re.IGNORECASE | re.DOTALL
    )
    if fonte:
        dados_espelho["fonte"] = fonte.group(1)

    # Natureza da Despesa (6 dígitos como 339000 ou 339039)
    nd = re.search(
        r"(?:Natureza|ND).{0,60}?(\d{6})", texto_espelho,
        re.IGNORECASE | re.DOTALL
    )
    if nd:
        dados_espelho["nd"] = nd.group(1)

    # UGR (6 dígitos)
    ugr = re.search(
        r"UGR.{0,40}?(\d{6})", texto_espelho,
        re.IGNORECASE | re.DOTALL
    )
    if ugr:
        dados_espelho["ugr"] = ugr.group(1)

    # Plano Interno (código alfanumérico ~10 chars)
    pi = re.search(
        r"(?:Plano\s+Interno|PI).{0,20}?([A-Z0-9]{6,15})",
        texto_espelho, re.IGNORECASE | re.DOTALL
    )
    if pi:
        dados_espelho["pi"] = pi.group(1)

    # Prazo de empenho
    prazo = re.search(
        r"[Pp]razo\s+(?:de\s+)?[Ee]mpenho\s+(\d{1,2}\s*\w{3}\s*\d{2,4})",
        texto_espelho
    )
    if prazo:
        dados_espelho["prazo_empenho"] = prazo.group(1)

    # ESF (1 dígito)
    esf = re.search(r"\bESF\s+(\d)\b", texto_espelho, re.IGNORECASE)
    if esf:
        dados_espelho["esf"] = esf.group(1)

    # PTRES (6 dígitos)
    ptres = re.search(r"\bPTRES\s+(\d{6})\b", texto_espelho, re.IGNORECASE)
    if ptres:
        dados_espelho["ptres"] = ptres.group(1)

    if dados_espelho:
        print(f"[OCR] Espelho NC: complementando com {list(dados_espelho.keys())}")
        # Aplicar a todas as NCs que têm campos vazios
        for nc in notas_credito:
            for campo, valor in dados_espelho.items():
                if not nc.get(campo):
                    nc[campo] = valor


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DA NOTA DE CRÉDITO
# ══════════════════════════════════════════════════════════════════════

def _extrair_nota_credito(paginas_nc: list[dict]) -> list[dict]:
    """
    Extrai dados das páginas de Nota de Crédito.

    Detecta automaticamente o formato:
    - DEMONSTRA-DIARIO (Proc 3 — contratos SIAFI, telas de terminal)
    - Padrão (Proc 2 — texto estruturado com UG EMITENTE, DATA EMISSÃO etc.)
    - Fallback: apenas número NC quando formato não reconhecido

    Retorna lista de dicts com os dados de cada NC encontrada.
    """
    if not paginas_nc:
        return []

    texto = _juntar_texto_paginas(paginas_nc)
    if not texto:
        return []

    texto_upper = texto.upper()

    # ── Detectar DEMONSTRA-DIARIO ou DEMONSTRA-CONRAZAO ──
    eh_dd = (
        "DEMONSTRA-DIARIO" in texto_upper
        or "DEMONSTRA-CONRAZAO" in texto_upper
        or "DOCUMENTO WEB" in texto_upper
        or "UG/GESTAO EMITENTE" in texto_upper
    )

    if eh_dd:
        ncs = _extrair_nc_demonstra_diario(texto)
        if ncs:
            print(f"[NC] DEMONSTRA-DIARIO: {len(ncs)} NC(s) extraída(s)")
            return ncs

    # ── Formato padrão ──
    ncs = _extrair_nc_padrao(texto)
    if ncs:
        print(f"[NC] Formato padrão: {len(ncs)} NC(s) extraída(s)")
        return ncs

    # ── Fallback: extrair pelo menos o número ──
    numeros = list(dict.fromkeys(re.findall(r"(20\d{2}NC\d{6})", texto)))
    if numeros:
        print(f"[NC] Extração parcial (apenas número): {numeros}")
        return [{"numero": n, "formato": "nao_extraido"} for n in numeros]

    print("[NC] Nenhuma NC encontrada nas páginas classificadas.")
    return []


def _extrair_nc_demonstra_diario(texto: str) -> list[dict]:
    """
    Extrai NC no formato SIAFI DEMONSTRA-DIARIO (processos de contrato).

    Estrutura em duas telas:
    - Tela 1: cabeçalho com UG emitente/favorecida, data, nº web (NC), observação
    - Tela 2: linhas de evento com ESF, PTRES, FONTE, ND, UGR, PI e VALOR

    Lógica de saldo:
    - Linhas com mesmos campos E mesmo valor = mesmo saldo, contar UMA vez
    - Linhas com NDs diferentes = posições de saldo independentes
    """
    nc: dict = {
        "numero":          None,
        "formato":         "demonstra_diario",
        "numero_siafi":    None,
        "data_emissao":    None,
        "ug_emitente":     None,
        "nome_emitente":   None,
        "ug_favorecida":   None,
        "nome_favorecida": None,
        "nd":              None,
        "ptres":           None,
        "fonte":           None,
        "ugr":             None,
        "pi":              None,
        "esf":             None,
        "valor_total":     None,
        "saldo":           None,
        "prazo_empenho":   None,
        "dias_restantes":  None,
        "observacao":      None,
        "linhas_evento":   [],
    }

    # ── Número NC (DOCUMENTO WEB) ──
    m = re.search(r"DOCUMENTO\s+WEB\s*:\s*(20\d{2}NC\d{6})", texto, re.IGNORECASE)
    if m:
        nc["numero"] = m.group(1)
    else:
        m = re.search(r"(20\d{2}NC\d{6})", texto)
        if m:
            nc["numero"] = m.group(1)

    if not nc["numero"]:
        return []

    # ── Número interno SIAFI ──
    # DEMONSTRA-DIARIO: "NUMERO : 2026R0000428"
    # DEMONSTRA-CONRAZAO: "NUMERO : 2026RO000273" (com letra O)
    m = re.search(r"NUMERO\s*:\s*(20\d{2}R[O0]?\d+)", texto, re.IGNORECASE)
    if m:
        nc["numero_siafi"] = m.group(1)

    # ── Data de emissão ──
    m = re.search(r"DATA\s+EMISSAO?\s*:\s*(\S+)", texto, re.IGNORECASE)
    if m:
        nc["data_emissao"] = m.group(1).strip()

    # ── UG/GESTÃO Emitente ──
    m = re.search(
        r"UG/GESTAO\s+EMITENTE\s*:\s*(\d{6})\s*/\s*\d+\s*[-–]\s*(.+?)(?:\s*[-–]\s*GESTOR|\n|$)",
        texto, re.IGNORECASE,
    )
    if m:
        nc["ug_emitente"]   = m.group(1).strip()
        nc["nome_emitente"] = m.group(2).strip()
    else:
        m = re.search(r"UG/GESTAO\s+EMITENTE\s*:\s*(\d{6})", texto, re.IGNORECASE)
        if m:
            nc["ug_emitente"] = m.group(1).strip()

    # ── UG/GESTÃO Favorecida ──
    m = re.search(
        r"UG/GESTAO\s+FAVORECIDA\s*:\s*(\d{6})\s*/\s*\d+\s*[-–]\s*(.+?)(?:\n|$)",
        texto, re.IGNORECASE,
    )
    if m:
        nc["ug_favorecida"]   = m.group(1).strip()
        nc["nome_favorecida"] = m.group(2).strip()
    else:
        m = re.search(r"UG/GESTAO\s+FAVORECIDA\s*:\s*(\d{6})", texto, re.IGNORECASE)
        if m:
            nc["ug_favorecida"] = m.group(1).strip()

    # ── Prazo de empenho (na OBSERVACAO) ──
    # Formatos: "EMPENHO ATÉ 30JUN26", "EMPH ATÉ 30 DIAS",
    #           "PRAZO DE EMPENHO 27 FEV 26"
    m = re.search(r"EMPENHO\s+AT[ÉE]\s+(\S+)", texto, re.IGNORECASE)
    if m:
        nc["prazo_empenho"] = m.group(1).strip().rstrip(")")
    if not nc["prazo_empenho"]:
        m = re.search(r"EMPH\s+AT[ÉE]\s+(.+?)[\.\n\r]", texto, re.IGNORECASE)
        if m:
            nc["prazo_empenho"] = m.group(1).strip()
    if not nc["prazo_empenho"]:
        m = re.search(
            r"PRAZO\s+DE\s+EMPENHO\s+(\d{1,2}\s*[A-Za-z]{3}\s*\d{2,4})",
            texto, re.IGNORECASE,
        )
        if m:
            nc["prazo_empenho"] = m.group(1).strip()

    # ── Observação ──
    m = re.search(
        r"OBSERVACAO\s*\n([\s\S]+?)(?:\nLANCADO\s+POR|$)",
        texto, re.IGNORECASE,
    )
    if m:
        nc["observacao"] = " ".join(m.group(1).split())

    # ── Linhas de evento (Tela 2) ──
    linhas_evento = _processar_linhas_evento_dd(texto)
    nc["linhas_evento"] = linhas_evento

    # ── Resolver campos principais a partir das linhas ──
    if linhas_evento:
        # Calcular saldo por ND (deduplicado — linhas iguais contam uma vez)
        saldos_por_nd: dict[str, float] = {}
        for linha in linhas_evento:
            nd = linha.get("nd")
            if nd and nd not in saldos_por_nd:
                saldos_por_nd[nd] = linha.get("valor") or 0.0

        # ND principal = primeira ND específica (≠ 339000) ou a primeira disponível
        nd_principal = None
        for nd in saldos_por_nd:
            if nd != "339000":
                nd_principal = nd
                break
        if not nd_principal:
            nd_principal = next(iter(saldos_por_nd), None)

        # Preencher campos com a linha da ND principal
        linha_principal = next(
            (l for l in linhas_evento if l.get("nd") == nd_principal),
            linhas_evento[0],
        )
        nc["nd"]    = linha_principal.get("nd")
        nc["ptres"] = linha_principal.get("ptres")
        nc["fonte"] = linha_principal.get("fonte")
        nc["ugr"]   = linha_principal.get("ugr")
        nc["pi"]    = linha_principal.get("pi")
        nc["esf"]   = linha_principal.get("esf")
        nc["saldo"] = saldos_por_nd.get(nd_principal, 0.0)

        # Valor total = soma dos saldos de NDs distintas
        nc["valor_total"] = sum(saldos_por_nd.values())

    # ── Calcular dias restantes até o prazo de empenho ──
    if nc["prazo_empenho"]:
        dt = parse_data_flexivel(nc["prazo_empenho"])
        if dt:
            nc["dias_restantes"] = (dt.date() - hoje_cg()).days

    return [nc]


def _processar_linhas_evento_dd(texto: str) -> list[dict]:
    """
    Processa as linhas de evento do DEMONSTRA-DIARIO.

    Formato (duas linhas por evento):
        001 301203                                    2.000,00
                  1  232180 1021000000 339039 167504 E3PCFSCDEGE

    Linha 1 (evento): NNN EEEEEE ... VALOR
    Linha 2 (dados) : (espaços) ESF PTRES FONTE ND UGR PI

    Aplica deduplicação: linhas com todos os campos E valor idênticos
    representam o MESMO saldo (operações contábeis sobre o mesmo recurso).
    """
    linhas_texto = texto.split("\n")
    linhas_evento = []

    # Padrão linha de evento: 3 dígitos + 6 dígitos + espaços + valor no fim
    padrao_evento = re.compile(
        r"^(\d{3})\s+\d{6}.*?([\d]{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*$"
    )
    # Padrão linha de dados: começa com espaços + ESF PTRES FONTE ND UGR PI
    padrao_dados = re.compile(
        r"^\s+(\d)\s+(\d{4,6})\s+(\d{9,10})\s+(3[34]\d{4}|339\d{3})\s+(\d{6})\s+([A-Z0-9]{6,15})\s*$"
    )

    for i, linha in enumerate(linhas_texto):
        m_evt = padrao_evento.match(linha)
        if not m_evt:
            continue

        valor = _parse_valor_br(m_evt.group(2))

        # Procurar linha de dados nas próximas 3 linhas
        for j in range(i + 1, min(i + 4, len(linhas_texto))):
            m_dados = padrao_dados.match(linhas_texto[j])
            if m_dados:
                linhas_evento.append({
                    "esf":   m_dados.group(1),
                    "ptres": m_dados.group(2),
                    "fonte": m_dados.group(3),
                    "nd":    m_dados.group(4),
                    "ugr":   m_dados.group(5),
                    "pi":    m_dados.group(6),
                    "valor": valor,
                })
                break

    # Deduplicar: mesmos campos E mesmo valor → contar uma vez
    vistos: set = set()
    resultado = []
    for linha in linhas_evento:
        chave = (
            linha["nd"], linha["ptres"], linha["fonte"],
            linha["ugr"], linha["pi"], linha["esf"], linha["valor"],
        )
        if chave not in vistos:
            vistos.add(chave)
            resultado.append(linha)

    return resultado


def _extrair_nc_padrao(texto: str) -> list[dict]:
    """
    Extrai NCs no formato padrão do SIAFI (não DEMONSTRA-DIARIO).

    Formato típico:
        Nota de Crédito Nº 2026NC000276 da UG 160073
        NÚMERO          2026NC000276
        UG EMITENTE     160073
        DATA EMISSÃO    12/01/2026
        VALOR TOTAL     R$ 9.000,00
        DESCRIÇÃO       ... Prazo de empenho 27 FEV 26. ...

        DESTINO | 1 | 160136 | 1 | 171460 | 1000000000 | 339000 | 160073 | I3DAFUNADOM | R$ 9.000,00
    """
    ncs = []
    numeros_nc = list(dict.fromkeys(re.findall(r"(20\d{2}NC\d{6})", texto)))

    for nc_num in numeros_nc:
        pos = texto.find(nc_num)
        if pos == -1:
            continue

        # Contexto: 300 chars antes e 3000 depois do número NC
        bloco = texto[max(0, pos - 300): pos + 3000]

        nc: dict = {
            "numero":          nc_num,
            "formato":         "padrao",
            "data_emissao":    None,
            "ug_emitente":     None,
            "nome_emitente":   None,
            "ug_favorecida":   None,
            "nome_favorecida": None,
            "nd":              None,
            "ptres":           None,
            "fonte":           None,
            "ugr":             None,
            "pi":              None,
            "esf":             None,
            "valor_total":     None,
            "saldo":           None,
            "prazo_empenho":   None,
            "dias_restantes":  None,
            "observacao":      None,
            "linhas_evento":   [],
        }

        # UG Emitente
        m = re.search(r"UG\s+EMITENTE\s+(\d{6})", bloco, re.IGNORECASE)
        if m:
            nc["ug_emitente"] = m.group(1)

        # Data emissão
        m = re.search(r"DATA\s+EMISS[ÃA]O\s+(\S+)", bloco, re.IGNORECASE)
        if m:
            nc["data_emissao"] = m.group(1).strip()

        # Valor total
        m = re.search(r"VALOR\s+TOTAL\s+R?\$?\s*([\d.,]+)", bloco, re.IGNORECASE)
        if m:
            nc["valor_total"] = _parse_valor_br(m.group(1))
            nc["saldo"] = nc["valor_total"]

        # Prazo de empenho — múltiplos formatos:
        # "Prazo de empenho 27 FEV 26."
        # "EMPENHO ATÉ 30JUN26"
        # "EMPH ATÉ 30 DIAS"
        m = re.search(r"[Pp]razo\s+de\s+empenho\s+(.+?)[\.\n\r]", bloco)
        if not m:
            m = re.search(r"EMPENHO\s+AT[ÉE]\s+(\S+)", bloco, re.IGNORECASE)
        if not m:
            m = re.search(r"EMPH\s+AT[ÉE]\s+(.+?)[\.\n\r]", bloco, re.IGNORECASE)
        if m:
            nc["prazo_empenho"] = m.group(1).strip()

        # Observação / Descrição
        m = re.search(
            r"DESCRI[ÇC][ÃA]O\s+(.+?)(?=\n[A-Z]{3,}|\Z)",
            bloco, re.IGNORECASE | re.DOTALL,
        )
        if m:
            nc["observacao"] = " ".join(m.group(1).split())

        # ── Linha DESTINO da tabela ──
        # Formato 1 (com pipes): DESTINO | 1 | 160136 | 1 | 171460 | 1000000000 | 339000 | 160073 | I3DAFUNADOM | R$ 9.000,00
        # Formato 2 (com espaços): DESTINO 1 1 160136 1 171397 1000000000 339030 160504 E6SUPLJA3RR R$\n4.000,00
        m = re.search(
            r"DESTINO\s*\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*(\d)\s*\|\s*(\d+)\s*\|"
            r"\s*(\d{9,10})\s*\|\s*(3[34]\d{4}|33\.\d{2}\.\d{2})\s*\|\s*(\d{6})"
            r"\s*\|\s*([A-Z0-9]+)\s*\|\s*R?\$?\s*([\d.,]+)",
            bloco, re.IGNORECASE,
        )
        if not m:
            # Formato com espaços (sem pipes) — valor pode quebrar linha
            m = re.search(
                r"DESTINO\s+\d+\s+\d+\s+(\d{6})\s+(\d)\s+(\d{4,6})\s+"
                r"(\d{9,10})\s+(3[34]\d{4})\s+(\d{6})\s+"
                r"([A-Z0-9]{6,15})\s+R?\$?\s*([\d.,]+)",
                bloco, re.IGNORECASE,
            )
        if m:
            nc["ug_favorecida"] = m.group(1)
            nc["esf"]           = m.group(2)
            nc["ptres"]         = m.group(3)
            nc["fonte"]         = m.group(4)
            nc["nd"]            = m.group(5).replace(".", "")   # 33.90.39 → 339039
            nc["ugr"]           = m.group(6)
            nc["pi"]            = m.group(7)
            val = _parse_valor_br(m.group(8))
            if val and not nc["saldo"]:
                nc["saldo"] = val

        # ── Fallback: campos individuais se tabela não foi encontrada ──
        if not nc["ug_favorecida"]:
            m = re.search(r"UG\s+Favorecida\s*:\s*(\d{6})", bloco, re.IGNORECASE)
            if m:
                nc["ug_favorecida"] = m.group(1)
        if not nc["nd"]:
            m = re.search(r"\bND\s+(3[34]\d{4}|33\.\d{2}\.\d{2})", bloco, re.IGNORECASE)
            if m:
                nc["nd"] = m.group(1).replace(".", "")
        if not nc["ptres"]:
            m = re.search(r"\bPTRES\s+(\d{4,6})", bloco, re.IGNORECASE)
            if m:
                nc["ptres"] = m.group(1)
        if not nc["fonte"]:
            m = re.search(r"\bFONTE\s+(\d{9,10})", bloco, re.IGNORECASE)
            if m:
                nc["fonte"] = m.group(1)
        if not nc["esf"]:
            m = re.search(r"\bESF\s+(\d)", bloco, re.IGNORECASE)
            if m:
                nc["esf"] = m.group(1)
        if not nc["ugr"]:
            m = re.search(r"\bUGR\s+(\d{6})", bloco, re.IGNORECASE)
            if m:
                nc["ugr"] = m.group(1)
        if not nc["pi"]:
            m = re.search(r"\bPI\s+([A-Z0-9]{8,15})", bloco, re.IGNORECASE)
            if m:
                nc["pi"] = m.group(1)

        # Calcular dias restantes
        if nc["prazo_empenho"]:
            dt = parse_data_flexivel(nc["prazo_empenho"])
            if dt:
                nc["dias_restantes"] = (dt.date() - hoje_cg()).days

        ncs.append(nc)

    return ncs


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DE CERTIDÕES
# ══════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DE CONTRATO
# ══════════════════════════════════════════════════════════════════════

def _extrair_contrato(paginas_contrato: list[dict]) -> Optional[dict]:
    """
    Extrai dados das páginas do documento de Contrato.

    Busca:
    - Número do contrato
    - CNPJ contratante e contratada
    - Nome contratante e contratada
    - Objeto do contrato
    - Valor total
    - Vigência (início e fim)
    - Pregão de origem
    - Assinaturas digitais

    Retorna dict com os dados ou None se não houver páginas.
    """
    if not paginas_contrato:
        return None

    texto = "\n\n".join(p["texto"] for p in paginas_contrato)
    texto_upper = texto.upper()

    dados = {
        "nr_contrato_doc": None,
        "uasg_contratante": None,
        "nome_contratante": None,
        "cnpj_contratante": None,
        "contratada": None,
        "cnpj_contratada": None,
        "objeto": None,
        "valor_total": None,
        "vigencia_inicio": None,
        "vigencia_fim": None,
        "pregao_origem": None,
        "tem_assinaturas": False,
        "assinantes": [],
    }

    # ── Número do contrato ──
    # Padrão 1: "CONTRATO DE PRESTAÇÃO DE SERVIÇOS Nº 059/2024"
    m_nr = re.search(
        r"CONTRATO\s+(?:DE\s+\w+\s+(?:DE\s+)?(?:\w+\s+)?)?N[ºo°]?\s*(\d{1,4}/\d{4})",
        texto, re.IGNORECASE
    )
    if m_nr:
        dados["nr_contrato_doc"] = m_nr.group(1)
    else:
        # Padrão 2: "NNN/YYYY, QUE FAZEM ENTRE SI"
        m_nr2 = re.search(r"(\d{1,4}/\d{4})\s*,?\s*QUE\s+FAZEM", texto, re.IGNORECASE)
        if m_nr2:
            dados["nr_contrato_doc"] = m_nr2.group(1)

    # ── CNPJs ──
    cnpjs = re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)

    # ── Contratante (geralmente a OM) ──
    # Buscar "CONTRATANTE" seguido do nome da instituição
    m_contratante = re.search(
        r"(?:CONTRATANTE)[:\s,]+(?:o|a)?\s*"
        r"(?:UNI[ÃA]O,?\s+POR\s+INTERM[ÉE]DIO\s+D[OA]\s+)?"
        r"(.+?)(?:,\s*inscrit|\s*CNPJ|\s*,\s*com\s+sede|\n\n)",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_contratante:
        nome = " ".join(m_contratante.group(1).split())
        # Limpar: remover texto muito longo ou que parece outra cláusula
        if len(nome) < 200:
            dados["nome_contratante"] = nome

    # CNPJ contratante (primeiro CNPJ próximo de CONTRATANTE)
    m_cnpj_contratante = re.search(
        r"CONTRATANTE.{0,300}?CNPJ[:\s]*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_cnpj_contratante:
        dados["cnpj_contratante"] = m_cnpj_contratante.group(1)

    # ── Contratada ──
    # Padrão 1: "CONTRATADA, a empresa NOME LTDA" (preâmbulo do contrato)
    m_contratada = re.search(
        r"(?:CONTRATAD[AO])[:\s,]+(?:a\s+empresa\s+)?"
        r"(.+?)(?:,\s*inscrit|\s*,?\s*CNPJ|\s*,\s*com\s+sede|\n\n)",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_contratada:
        nome = " ".join(m_contratada.group(1).split())
        # Filtrar: não pegar trechos de cláusulas como contratada (remover se genérico)
        if (len(nome) < 200 and len(nome) > 3
                and not re.match(r"(?:ao|a|o|neste|nesta|nos|das)", nome, re.IGNORECASE)):
            dados["contratada"] = nome

    # Padrão 2: "e NOME EMPRESA, ... CONTRATADA" (no preâmbulo, antes de CONTRATADA)
    if not dados.get("contratada"):
        m_contratada2 = re.search(
            r"\be\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ\s&]+(?:LTDA|S/?A|ME|EIRELI|EPP))",
            texto
        )
        if m_contratada2:
            dados["contratada"] = " ".join(m_contratada2.group(1).split())

    # Limpar quebras de linha no nome da contratada
    if dados.get("contratada"):
        dados["contratada"] = " ".join(dados["contratada"].split())

    # CNPJ contratada (CNPJ próximo de CONTRATADA)
    m_cnpj_contratada = re.search(
        r"CONTRATAD[AO].{0,300}?CNPJ[:\s]*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_cnpj_contratada:
        dados["cnpj_contratada"] = m_cnpj_contratada.group(1)
    elif len(cnpjs) >= 2:
        # Se não achou por proximidade, usa o segundo CNPJ como contratada
        # (o primeiro geralmente é da OM contratante)
        dados["cnpj_contratante"] = dados["cnpj_contratante"] or cnpjs[0]
        dados["cnpj_contratada"] = cnpjs[1]

    # ── UASG Contratante ──
    m_uasg = re.search(r"UASG\s*:?\s*(\d{6})", texto, re.IGNORECASE)
    if m_uasg:
        dados["uasg_contratante"] = m_uasg.group(1)

    # ── Objeto do contrato ──
    m_obj = re.search(
        r"(?:CLÁUSULA\s+PRIMEIRA\s*[-–]?\s*OBJETO|1\.\s*CLÁUSULA\s+PRIMEIRA)"
        r".+?(?:1\.1\.?\s*)(.+?)(?:1\.2\.|CL[ÁA]USULA\s+SEGUNDA)",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_obj:
        obj_texto = " ".join(m_obj.group(1).split())
        # Pegar primeira frase relevante (até o primeiro ponto final)
        obj_limpo = re.sub(r"\s*Este\s+Termo\s+de\s+Contrato\s+vincula.*", "", obj_texto)
        if len(obj_limpo) > 300:
            obj_limpo = obj_limpo[:300].rsplit(",", 1)[0]
        dados["objeto"] = obj_limpo.strip()

    # ── Valor total ──
    m_valor = re.search(
        r"(?:valor\s+total|valor\s+global|valor\s+d[ao]\s+contrat)"
        r".{0,50}?R\$\s*([\d.,]+)",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_valor:
        dados["valor_total"] = f"R$ {m_valor.group(1)}"

    # ── Vigência ──
    m_vig = re.search(
        r"(?:prazo\s+de\s+vig[êe]ncia|vig[êe]ncia\s+d[eo])"
        r".+?(\d{1,2}/\d{1,2}/\d{4})"
        r".+?(\d{1,2}/\d{1,2}/\d{4})",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m_vig:
        dados["vigencia_inicio"] = m_vig.group(1)
        dados["vigencia_fim"] = m_vig.group(2)

    # ── Pregão de origem ──
    m_pe = re.search(
        r"(?:PREG[ÃA]O\s+ELETR[ÔO]NICO\s+(?:SRP\s+)?N[ºo°]\s*|PE\s+)"
        r"(\d{3,5}/\d{4})",
        texto, re.IGNORECASE
    )
    if m_pe:
        dados["pregao_origem"] = m_pe.group(1)

    # ── Assinaturas digitais ──
    assinaturas = re.findall(
        r"(?:Assinado\s+digitalmente|Documento\s+assinado\s+digitalmente)",
        texto, re.IGNORECASE
    )
    dados["tem_assinaturas"] = len(assinaturas) >= 2  # pelo menos 2 assinaturas

    # Extrair nomes dos assinantes
    assinantes = re.findall(
        r"(?:Documento\s+)?[Aa]ssinado\s+digitalmente\s*\n\s*(.+?)(?:\n|Data:)",
        texto
    )
    # Fallback: nomes em MAIÚSCULAS após "CONTRATANTE" ou "CONTRATADO" no final
    if not assinantes:
        assinantes = re.findall(
            r"(?:CONTRATANTE|CONTRATAD[AO])\s+(?:Documento\s+assinado\s+digitalmente\s+)?"
            r"([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ\s]+[A-Z])\b",
            texto
        )

    # Limpar nomes de assinantes
    nomes_limpos = []
    for a in assinantes:
        nome = a.strip()
        # Remover artefatos de OCR no início (ex: "w ", "W ")
        nome = re.sub(r"^[wW]\s+", "", nome)
        # Filtrar falsos positivos
        if (len(nome) > 5
                and "assinado" not in nome.lower()
                and "documento" not in nome.lower()
                and "verifique" not in nome.lower()):
            nomes_limpos.append(nome)
    dados["assinantes"] = nomes_limpos

    # Contar dados preenchidos para filtro de qualidade
    campos_chave = ["nr_contrato_doc", "cnpj_contratada", "objeto", "vigencia_inicio"]
    preenchidos = sum(1 for k, v in dados.items()
                      if v and k not in ("assinantes",) and v not in (False, []))
    campos_chave_preenchidos = sum(1 for c in campos_chave if dados.get(c))

    # Se menos de 3 campos preenchidos, provavelmente é falso positivo
    if preenchidos < 3 or campos_chave_preenchidos < 1:
        print(f"[CONTRATO] Apenas {preenchidos} campos extraídos — descartado (falso positivo)")
        return None

    print(f"[CONTRATO] Extraídos {preenchidos} campos do documento de contrato")

    return dados


def _validar_contrato(identificacao: dict, dados_contrato: Optional[dict],
                      certidoes: dict) -> list[dict]:
    """
    Valida dados do contrato cruzando informações de diferentes fontes:
    1. Número do contrato na requisição vs no documento
    2. CNPJ da contratada vs CNPJ do SICAF/fornecedor
    3. Presença de assinaturas
    4. Vigência (se dentro do prazo)

    Retorna lista de validações no formato:
    [{"campo": str, "status": "verde"|"amarelo"|"vermelho", "mensagem": str}]
    """
    validacoes = []

    if not dados_contrato:
        return validacoes

    nr_req = identificacao.get("nr_contrato", "")
    nr_doc = dados_contrato.get("nr_contrato_doc", "")

    # ── 1. Número do contrato ──
    if nr_req and nr_doc:
        # Normalizar para comparação (059/2024 == 59/2024)
        nr_req_norm = nr_req.lstrip("0") or "0"
        nr_doc_norm = nr_doc.lstrip("0") or "0"
        if nr_req_norm == nr_doc_norm:
            validacoes.append({
                "campo": "Nº Contrato",
                "status": "verde",
                "mensagem": f"Número confere: {nr_doc}"
            })
        else:
            validacoes.append({
                "campo": "Nº Contrato",
                "status": "vermelho",
                "mensagem": f"Divergência: requisição={nr_req}, documento={nr_doc}"
            })
    elif nr_req and not nr_doc:
        validacoes.append({
            "campo": "Nº Contrato",
            "status": "amarelo",
            "mensagem": f"Número {nr_req} na requisição, mas não encontrado no documento"
        })

    # ── 2. CNPJ da contratada ──
    cnpj_fornecedor = identificacao.get("cnpj", "")
    cnpj_contratada = dados_contrato.get("cnpj_contratada", "")
    cnpj_sicaf = certidoes.get("sicaf", {}).get("cnpj", "")

    if cnpj_contratada and cnpj_fornecedor:
        if cnpj_contratada == cnpj_fornecedor:
            validacoes.append({
                "campo": "CNPJ Contratada",
                "status": "verde",
                "mensagem": f"CNPJ confere: {cnpj_contratada}"
            })
        else:
            validacoes.append({
                "campo": "CNPJ Contratada",
                "status": "vermelho",
                "mensagem": f"Divergência: contrato={cnpj_contratada}, requisição={cnpj_fornecedor}"
            })

    # CNPJ do contrato vs SICAF
    if cnpj_contratada and cnpj_sicaf and cnpj_contratada != cnpj_sicaf:
        validacoes.append({
            "campo": "CNPJ (Contrato vs SICAF)",
            "status": "vermelho",
            "mensagem": f"Contrato={cnpj_contratada}, SICAF={cnpj_sicaf}"
        })

    # ── 3. Assinaturas ──
    if dados_contrato.get("tem_assinaturas"):
        n_assinantes = len(dados_contrato.get("assinantes", []))
        nomes = ", ".join(dados_contrato["assinantes"][:3])
        validacoes.append({
            "campo": "Assinaturas",
            "status": "verde",
            "mensagem": f"Contrato assinado digitalmente ({n_assinantes} assinantes: {nomes})"
        })
    else:
        validacoes.append({
            "campo": "Assinaturas",
            "status": "amarelo",
            "mensagem": "Assinaturas digitais não detectadas no documento"
        })

    # ── 4. Vigência ──
    vig_fim_str = dados_contrato.get("vigencia_fim")
    if vig_fim_str:
        try:
            vig_fim = datetime.strptime(vig_fim_str, "%d/%m/%Y")
            # Converter para timezone-aware (usar início do dia em Campo Grande)
            vig_fim = vig_fim.replace(tzinfo=TZ_CAMPO_GRANDE)
            hoje = agora_cg()
            if vig_fim < hoje:
                dias_vencido = (hoje - vig_fim).days
                validacoes.append({
                    "campo": "Vigência",
                    "status": "vermelho",
                    "mensagem": f"Contrato vencido desde {vig_fim_str} ({dias_vencido} dias)"
                })
            else:
                dias_restantes = (vig_fim - hoje).days
                status = "verde" if dias_restantes > 30 else "amarelo"
                validacoes.append({
                    "campo": "Vigência",
                    "status": status,
                    "mensagem": f"Vigente até {vig_fim_str} ({dias_restantes} dias restantes)"
                })
        except ValueError:
            validacoes.append({
                "campo": "Vigência",
                "status": "amarelo",
                "mensagem": f"Data de vigência não pôde ser interpretada: {vig_fim_str}"
            })

    return validacoes


# ══════════════════════════════════════════════════════════════════════
# EXTRAÇÃO DE DESPACHOS (mecânica — preparando para LLM)
# ══════════════════════════════════════════════════════════════════════

def _extrair_despachos(paginas_despacho: list[dict]) -> list[dict]:
    """
    Extrai dados básicos de cada despacho encontrado no processo.

    Extração mecânica (sem interpretação semântica).
    O texto completo é preservado para futura análise por LLM.

    Cada despacho retorna:
    - numero_completo: "324-Fisc Adm/CAF/Cmdo 9º Gpt Log"
    - numero: 324 (parte numérica)
    - setor: "Fisc Adm/CAF" ou "SAL/CAF" etc.
    - om: "Cmdo 9º Gpt Log"
    - data: "9 de fevereiro de 2026"
    - assunto: texto do assunto
    - tipo: aprovacao | encaminhamento | informacao | restituicao | outro
    - texto_completo: texto integral (para LLM futura)
    - assinante: "FULANO DE TAL - TC"
    - cargo: "Ordenador de Despesas" etc.
    - assinado_digitalmente: True/False
    - pagina: número da página
    """
    if not paginas_despacho:
        return []

    despachos = []

    for pag in paginas_despacho:
        texto = pag["texto"]
        texto_upper = texto.upper()

        despacho = {
            "numero_completo": None,
            "numero": None,
            "setor": None,
            "om": None,
            "data": None,
            "assunto": None,
            "tipo": "outro",
            "texto_completo": texto,
            "assinante": None,
            "cargo": None,
            "assinado_digitalmente": False,
            "pagina": pag["numero"],
        }

        # ── Número do despacho ──
        # Formato: "Despacho Nº 324-Fisc Adm/CAF/Cmdo 9º Gpt Log"
        m_nr = re.search(
            r"[Dd]espacho\s+N[ºo°\.]\s*(.+?)(?:\n|$)",
            texto
        )
        if m_nr:
            nr_completo = m_nr.group(1).strip()
            despacho["numero_completo"] = nr_completo

            # Parte numérica
            m_num = re.match(r"(\d+)", nr_completo)
            if m_num:
                despacho["numero"] = int(m_num.group(1))

            # Setor e OM (separados por /)
            # Ex: "324-Fisc Adm/CAF/Cmdo 9º Gpt Log"
            m_setor = re.match(r"\d+[-–]\s*(.+)", nr_completo)
            if m_setor:
                partes = m_setor.group(1).split("/")
                if len(partes) >= 2:
                    despacho["setor"] = "/".join(partes[:-1]).strip()
                    despacho["om"] = partes[-1].strip()
                elif len(partes) == 1:
                    despacho["setor"] = partes[0].strip()

        # ── Data ──
        m_data = re.search(
            r"Campo\s+Grande.*?,\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})",
            texto, re.IGNORECASE
        )
        if m_data:
            despacho["data"] = m_data.group(1).strip()

        # ── Assunto ──
        m_assunto = re.search(
            r"Assunto:\s*(.+?)(?:\n\n|\n[A-Z]|\n\d+\.)",
            texto, re.DOTALL
        )
        if m_assunto:
            despacho["assunto"] = " ".join(m_assunto.group(1).split())

        # ── Tipo (classificação mecânica) ──
        if "APROVO" in texto_upper and "ENCAMINHO" in texto_upper:
            despacho["tipo"] = "aprovacao_encaminhamento"
        elif "APROVO" in texto_upper:
            despacho["tipo"] = "aprovacao"
        elif "ENCAMINHO" in texto_upper:
            despacho["tipo"] = "encaminhamento"
        elif "RESTITU" in texto_upper:
            despacho["tipo"] = "restituicao"
        elif "INFORMO" in texto_upper:
            despacho["tipo"] = "informacao"
        elif "REPROVO" in texto_upper:
            despacho["tipo"] = "reprovacao"

        # ── Assinante ──
        # Padrão: "NOME COMPLETO - POSTO\nCargo"
        # Nomes em MAIÚSCULAS seguidos de posto militar
        m_assinante = re.search(
            r"\n([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ\s]+)"
            r"\s*[-–]\s*((?:Cel|TC|Ten[-\s]?Cel|Maj|Cap|1[ºo]\s*Ten|2[ºo]\s*Ten|"
            r"Ten|Sgt|Cb|Sd|ST|S Ten)[^\n]*)",
            texto
        )
        if m_assinante:
            despacho["assinante"] = f"{m_assinante.group(1).strip()} - {m_assinante.group(2).strip()}"

        # Fallback: nome seguido de posto na próxima linha
        if not despacho.get("assinante"):
            m_assinante2 = re.search(
                r"\n([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÜÇ\s]{5,})\n"
                r"((?:Comandante|Ordenador|Chefe|Adjunto|Auxiliar|Gestor)[^\n]+)",
                texto
            )
            if m_assinante2:
                despacho["assinante"] = m_assinante2.group(1).strip()
                despacho["cargo"] = m_assinante2.group(2).strip()

        # ── Cargo (se não foi pego acima) ──
        if not despacho.get("cargo"):
            m_cargo = re.search(
                r"\n((?:Comandante|Ordenador\s+de\s+Despesas|Chefe\s+d[aeo]|"
                r"Adjunto\s+d[aeo]|Auxiliar\s+d[aeo]|Gestor\s+de)[^\n]+)",
                texto, re.IGNORECASE
            )
            if m_cargo:
                despacho["cargo"] = m_cargo.group(1).strip()

        # ── Assinatura digital ──
        despacho["assinado_digitalmente"] = bool(re.search(
            r"(?:assinado?\s+(?:digitalmente|eletronicamente)|"
            r"Document[ao]\s+assinad[ao]\s+eletronicamente)",
            texto, re.IGNORECASE
        ))

        despachos.append(despacho)

    # Ordenar por número (quando disponível) ou por página
    despachos.sort(key=lambda d: (d["numero"] or 0, d["pagina"]))

    n_tipos = {}
    for d in despachos:
        n_tipos[d["tipo"]] = n_tipos.get(d["tipo"], 0) + 1
    tipos_str = ", ".join(f"{v}x {k}" for k, v in n_tipos.items())
    print(f"[DESPACHOS] {len(despachos)} despacho(s) extraído(s) ({tipos_str})")

    return despachos


def _extrair_certidoes(paginas_classificadas: dict) -> dict:
    """
    Extrai dados de todas as certidões do processo:
    SICAF, CADIN e Consulta Consolidada (TCU/CNJ/CEIS/CNEP).

    Retorna dict com chaves: sicaf, cadin, consulta_consolidada.
    """
    certidoes = {
        "sicaf": {},
        "cadin": {},
        "consulta_consolidada": {},
    }

    # ── SICAF ──
    paginas_sicaf = paginas_classificadas.get("sicaf", [])
    if paginas_sicaf:
        texto_sicaf = _juntar_texto_paginas(paginas_sicaf)
        certidoes["sicaf"] = _extrair_sicaf(texto_sicaf)
        print(f"[CERTIDÕES] SICAF extraído — CNPJ: {certidoes['sicaf'].get('cnpj', '?')}")
    else:
        print("[CERTIDÕES] Nenhuma página de SICAF encontrada.")

    # ── CADIN ──
    paginas_cadin = paginas_classificadas.get("cadin", [])
    if paginas_cadin:
        texto_cadin = _juntar_texto_paginas(paginas_cadin)
        certidoes["cadin"] = _extrair_cadin(texto_cadin)
        print(f"[CERTIDÕES] CADIN extraído — Situação: {certidoes['cadin'].get('situacao', '?')}")
    else:
        print("[CERTIDÕES] Nenhuma página de CADIN encontrada.")

    # ── Consulta Consolidada ──
    paginas_cc = paginas_classificadas.get("consulta_consolidada", [])
    if paginas_cc:
        texto_cc = _juntar_texto_paginas(paginas_cc)
        certidoes["consulta_consolidada"] = _extrair_consulta_consolidada(texto_cc)
        print(f"[CERTIDÕES] Consulta Consolidada extraída — {len(certidoes['consulta_consolidada'].get('cadastros', []))} cadastros")
    else:
        print("[CERTIDÕES] Nenhuma página de Consulta Consolidada encontrada.")

    return certidoes


def _extrair_sicaf(texto: str) -> dict:
    """
    Extrai dados do documento SICAF.

    Campos extraídos:
    - cnpj, razao_social, nome_fantasia
    - situacao, data_vencimento_cadastro, porte
    - ocorrencia, impedimento_licitar, ocorrencias_impeditivas_indiretas
    - vinculo_servico_publico
    - validades (dict com cada certidão e sua data de validade)
    - data_emissao
    """
    dados = {
        "cnpj": None,
        "razao_social": None,
        "nome_fantasia": None,
        "situacao": None,
        "data_vencimento_cadastro": None,
        "porte": None,
        "ocorrencia": None,
        "impedimento_licitar": None,
        "ocorrencias_impeditivas_indiretas": None,
        "vinculo_servico_publico": None,
        "validades": {},
        "data_emissao": None,
    }

    # ── CNPJ ──
    m = re.search(r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto)
    if m:
        dados["cnpj"] = m.group(1)

    # ── Razão Social ──
    m = re.search(r"Raz[ãa]o\s+Social:\s*(.+?)(?:\n|Nome Fantasia)", texto, re.DOTALL)
    if m:
        dados["razao_social"] = m.group(1).strip()

    # ── Nome Fantasia ──
    m = re.search(r"Nome\s+Fantasia:\s*(.+?)(?:\n)", texto)
    if m:
        nome = m.group(1).strip()
        # Evitar captura de lixo (ex.: campo vazio seguido do próximo label)
        if nome and "Situação" not in nome and "Fornecedor" not in nome:
            dados["nome_fantasia"] = nome

    # ── Situação do Fornecedor ──
    m = re.search(r"Situa[çc][ãa]o\s+do\s+Fornecedor:\s*(\w+)", texto)
    if m:
        dados["situacao"] = m.group(1).strip()

    # ── Data de Vencimento do Cadastro ──
    m = re.search(r"Vencimento\s+do\s+Cadastro:\s*(\d{2}/\d{2}/\d{4})", texto)
    if m:
        dados["data_vencimento_cadastro"] = m.group(1)

    # ── Porte da Empresa ──
    m = re.search(r"Porte\s+da\s+Empresa:\s*(.+?)(?:\n)", texto)
    if m:
        dados["porte"] = m.group(1).strip()

    # ── Ocorrências e Impedimentos ──
    m = re.search(r"Ocorr[êe]ncia:\s*(.+?)(?:\n)", texto)
    if m:
        dados["ocorrencia"] = m.group(1).strip()

    m = re.search(r"Impedimento\s+de\s+Licitar:\s*(.+?)(?:\n)", texto)
    if m:
        dados["impedimento_licitar"] = m.group(1).strip()

    m = re.search(
        r"Ocorr[êe]ncias\s+Impeditivas\s+[Ii]ndiretas:\s*(.+?)(?:\n)", texto
    )
    if m:
        dados["ocorrencias_impeditivas_indiretas"] = m.group(1).strip()

    m = re.search(
        r'V[ií]nculo\s+com\s+["\u201c]?Servi[çc]o\s+P[úu]blico["\u201d]?:\s*(.+?)(?:\n)',
        texto
    )
    if m:
        dados["vinculo_servico_publico"] = m.group(1).strip()

    # ── Validades individuais ──
    # Formato: "Receita Federal e PGFN Validade: 20/07/2026 Automática"
    # Formato: "FGTS Validade: 19/02/2026 Automática"
    # Formato: "Receita Estadual/Distrital Validade: 19/02/2026"
    # Formato: "Receita Municipal Validade: 06/07/2026"
    # Formato: "Trabalhista (http://...) Validade: 30/05/2026 Automática"

    padroes_validade = [
        (r"Receita\s+Federal.*?Validade:\s*(\d{2}/\d{2}/\d{4})",
         "receita_federal"),
        (r"FGTS\s+Validade:\s*(\d{2}/\d{2}/\d{4})",
         "fgts"),
        (r"Trabalhista.*?Validade:\s*(\d{2}/\d{2}/\d{4})",
         "trabalhista"),
        (r"Receita\s+Estadual.*?Validade:\s*(\d{2}/\d{2}/\d{4})",
         "receita_estadual"),
        (r"Receita\s+Municipal.*?Validade:\s*(\d{2}/\d{2}/\d{4})",
         "receita_municipal"),
    ]

    for padrao, chave in padroes_validade:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            dados["validades"][chave] = m.group(1)

    # ── Qualificação Econômico-Financeira ──
    # Vem após "Qualificação Econômico-Financeira" e tem Validade na linha seguinte
    m = re.search(
        r"Qualifica[çc][ãa]o\s+Econ[ôo]mico.*?Validade:\s*(\d{2}/\d{2}/\d{4})",
        texto, re.IGNORECASE | re.DOTALL
    )
    if m:
        dados["validades"]["qualif_economica"] = m.group(1)

    # ── Data de emissão ──
    m = re.search(r"Emitido\s+em:\s*(\d{2}/\d{2}/\d{4})", texto)
    if m:
        dados["data_emissao"] = m.group(1)

    return dados


def _extrair_cadin(texto: str) -> dict:
    """
    Extrai dados do documento CADIN.

    Campos extraídos:
    - cnpj
    - situacao (REGULAR, IRREGULAR, NADA CONSTA)
    - data_emissao
    """
    dados = {
        "cnpj": None,
        "situacao": None,
        "data_emissao": None,
    }

    # ── CNPJ ──
    m = re.search(r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto)
    if m:
        dados["cnpj"] = m.group(1)

    # ── Situação ──
    # Formato: "Situação para a Esfera Federal: REGULAR"
    m = re.search(
        r"Situa[çc][ãa]o\s+para\s+a\s+Esfera\s+Federal:\s*(\w+)",
        texto, re.IGNORECASE
    )
    if m:
        dados["situacao"] = m.group(1).upper()
    else:
        # Fallback: busca genérica por "Situação"
        m = re.search(
            r"Situa[çc][ãa]o.*?:\s*(REGULAR|IRREGULAR|NADA\s+CONSTA)",
            texto, re.IGNORECASE
        )
        if m:
            dados["situacao"] = m.group(1).upper()

    # ── Data de emissão ──
    m = re.search(r"Emiss[ãa]o\s+em\s+(\d{2}/\d{2}/\d{4})", texto)
    if m:
        dados["data_emissao"] = m.group(1)

    return dados


def _extrair_consulta_consolidada(texto: str) -> dict:
    """
    Extrai dados da Consulta Consolidada de Pessoa Jurídica.
    Inclui resultados de: TCU, CNJ, CEIS, CNEP, CEPIM, CADICON.

    Campos extraídos:
    - cnpj, razao_social
    - data_consulta
    - cadastros: lista de { orgao, cadastro, resultado }
    """
    dados = {
        "cnpj": None,
        "razao_social": None,
        "data_consulta": None,
        "cadastros": [],
    }

    # ── CNPJ ──
    m = re.search(r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto)
    if m:
        dados["cnpj"] = m.group(1)

    # ── Razão Social ──
    m = re.search(r"Raz[ãa]o\s+Social:\s*(.+?)(?:\n)", texto)
    if m:
        dados["razao_social"] = m.group(1).strip()

    # ── Data da consulta ──
    m = re.search(r"Consulta\s+realizada\s+em:\s*(\d{2}/\d{2}/\d{4})", texto)
    if m:
        dados["data_consulta"] = m.group(1)

    # ── Cadastros individuais ──
    # Formato repetido:
    #   Órgão Gestor: TCU
    #   Cadastro: Licitantes Inidôneos
    #   Resultado da consulta: Nada Consta
    # Nota: o nome do cadastro pode ocupar 2+ linhas (ex.: CNJ / CNIA)
    blocos = re.finditer(
        r"[ÓO]rg[ãa]o\s+Gestor:\s*(.+?)\n"
        r"\s*Cadastro:\s*(.+?)\n"
        r"(?:\s*(?!Resultado)(.+?)\n)*"  # linhas extras do nome do cadastro
        r"\s*Resultado\s+da\s+consulta:\s*(.+?)(?:\n|$)",
        texto, re.IGNORECASE
    )

    for bloco in blocos:
        orgao = bloco.group(1).strip()
        cadastro = bloco.group(2).strip()
        resultado = bloco.group(4).strip()  # group(4) após adição do grupo de linhas extras

        # Normalizar nome do cadastro para chave amigável
        nome_curto = _normalizar_nome_cadastro(cadastro, orgao)

        dados["cadastros"].append({
            "orgao": orgao,
            "cadastro": cadastro,
            "nome_curto": nome_curto,
            "resultado": resultado,
        })

    return dados


def _normalizar_nome_cadastro(cadastro: str, orgao: str) -> str:
    """Converte o nome do cadastro para uma chave curta e legível."""
    cadastro_upper = cadastro.upper()

    if "INID" in cadastro_upper and "TCU" in orgao.upper():
        return "TCU — Licitantes Inidôneos"
    if "CNIA" in cadastro_upper or "IMPROBIDADE" in cadastro_upper:
        return "CNJ — Improbidade"
    if "INID" in cadastro_upper and "SUSPENS" in cadastro_upper:
        return "CEIS — Inidôneas/Suspensas"
    if "CNEP" in cadastro_upper or "PUNIDAS" in cadastro_upper:
        return "CNEP — Empresas Punidas"
    if "CEPIM" in cadastro_upper:
        return "CEPIM — Impedidas"
    if "CADICON" in cadastro_upper or "ETCE" in cadastro_upper:
        return "CADICON / eTCE"

    # Fallback: usar nome original
    return cadastro


# ══════════════════════════════════════════════════════════════════════
# MESCLAGEM E INFERÊNCIA
# ══════════════════════════════════════════════════════════════════════

def _complementar_nc_com_req(ncs: list[dict], identificacao: dict) -> None:
    """
    Complementa campos da NC com dados da requisição quando o documento
    NC não contém linhas de evento (ex.: DEMONSTRA-CONRAZAO).

    Também resolve prazo relativo (ex.: "30 DIAS" → data_emissao + 30).
    """
    if not ncs:
        return

    # Mapeamento: campo na NC → campo na identificação
    mapa_campos = {
        "nd":    "nd",
        "ptres": "ptres",
        "fonte": "fonte",
        "ugr":   "ugr",
        "pi":    "pi",
    }

    for nc in ncs:
        # Complementar com dados da req se NC não tem o campo
        for campo_nc, campo_ident in mapa_campos.items():
            if not nc.get(campo_nc):
                valor = identificacao.get(campo_ident)
                if valor:
                    nc[campo_nc] = valor

        # ── Resolver prazo relativo (ex.: "30 DIAS") ──
        prazo = nc.get("prazo_empenho") or ""
        if nc.get("dias_restantes") is None and prazo:
            m = re.match(r"(\d+)\s*DIAS?", prazo, re.IGNORECASE)
            if m and nc.get("data_emissao"):
                # Prazo relativo: data_emissao + N dias
                dt_emissao = parse_data_flexivel(nc["data_emissao"])
                if dt_emissao:
                    from datetime import timedelta
                    dt_prazo = dt_emissao + timedelta(days=int(m.group(1)))
                    nc["prazo_empenho"] = dt_prazo.strftime("%d/%m/%Y")
                    nc["dias_restantes"] = (dt_prazo.date() - hoje_cg()).days

        # ── Calcular saldo via valor_total se saldo não extraído ──
        if nc.get("saldo") is None and nc.get("valor_total") is not None:
            nc["saldo"] = nc["valor_total"]


def _complementar_fornecedor_com_certidoes(identificacao: dict,
                                            certidoes: dict) -> None:
    """
    Fallback final: quando fornecedor e/ou CNPJ não foram extraídos
    do texto nem do OCR da requisição, tenta buscar no SICAF.

    O SICAF contém razão social e CNPJ do fornecedor com alta
    confiabilidade.
    """
    sicaf = certidoes.get("sicaf", {})
    if not sicaf:
        return

    if not identificacao.get("cnpj") and sicaf.get("cnpj"):
        identificacao["cnpj"] = sicaf["cnpj"]
        print(f"[FALLBACK] CNPJ obtido do SICAF: {sicaf['cnpj']}")

    if not identificacao.get("fornecedor") and sicaf.get("razao_social"):
        identificacao["fornecedor"] = sicaf["razao_social"]
        print(f"[FALLBACK] Fornecedor obtido do SICAF: {sicaf['razao_social']}")


def _mesclar_identificacao(identificacao: dict, dados_req: dict) -> None:
    """
    Mescla dados da requisição no dicionário de identificação,
    preenchendo campos que estavam vazios na capa.
    """
    mapa = {
        "nup": "nup",
        "om": "om",
        "setor": "setor",
        "tipo_empenho": "tipo_empenho",
        "fornecedor": "fornecedor",
        "cnpj": "cnpj",
        "assunto": "objeto",  # assunto da requisição vira "objeto"
    }

    for campo_req, campo_id in mapa.items():
        valor = dados_req.get(campo_req)
        if valor and not identificacao.get(campo_id):
            identificacao[campo_id] = valor

    # Nr Requisição + Setor formatado
    if dados_req.get("nr_requisicao"):
        identificacao["nr_requisicao"] = dados_req["nr_requisicao"]

    # Instrumento
    if dados_req.get("nr_contrato"):
        identificacao["instrumento"] = f"Contrato {dados_req['nr_contrato']}"
        identificacao["tipo"] = "Contrato"
    elif dados_req.get("nr_pregao"):
        part = dados_req.get("tipo_participacao", "")
        identificacao["instrumento"] = f"PE {dados_req['nr_pregao']}"
        if part:
            identificacao["instrumento"] += f" ({part})"
        identificacao["tipo"] = "Licitação"

    # UASG
    if dados_req.get("uasg"):
        identificacao["uasg"] = dados_req["uasg"]

    # Dados financeiros
    for campo in ["nc", "data_nc", "orgao_emissor_nc", "nd", "pi",
                   "ptres", "ugr", "fonte", "nr_pregao", "nr_contrato",
                   "tipo_participacao", "fiscal_contrato",
                   "mascara_requisitante", "pregao_detalhes"]:
        if dados_req.get(campo):
            identificacao[campo] = dados_req[campo]


def _inferir_tipo_processo(identificacao: dict,
                           paginas_classificadas: dict) -> Optional[str]:
    """
    Infere o tipo de processo (Licitação, Contrato, Dispensa) com base
    nos dados extraídos e peças classificadas.

    Prioridade: nr_contrato/checklist > nr_pregao > tipo_empenho
    Nota: Pregão SRP pode ter empenho Global (alimentos), então pregão
    prevalece sobre tipo de empenho na inferência.
    """
    # Se tem contrato explícito no instrumento ou peça de contrato/checklist
    if identificacao.get("nr_contrato"):
        return "Contrato"
    if paginas_classificadas.get("checklist"):
        return "Contrato"
    if paginas_classificadas.get("contrato"):
        return "Contrato"

    # Se tem pregão → é licitação (mesmo com empenho Global/SRP)
    if identificacao.get("nr_pregao"):
        return "Licitação"

    # Último recurso: tipo de empenho
    tipo_emp = (identificacao.get("tipo_empenho") or "").lower()
    if tipo_emp in ("global", "estimativo"):
        return "Contrato"
    if tipo_emp == "ordinário":
        return "Licitação"

    return None


# ══════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════

def _juntar_texto_paginas(paginas: list[dict]) -> str:
    """Concatena o texto de múltiplas páginas com separadores."""
    textos = [p["texto"] for p in paginas if p.get("texto")]
    return "\n\n".join(textos)


def _parse_valor_br(texto: str) -> Optional[float]:
    """
    Converte valor monetário no formato brasileiro para float.
    Aceita: '1.999,80', '0,30', '9.000,00', '779,90'
    """
    if not texto:
        return None
    try:
        # Remove pontos de milhar e troca vírgula por ponto
        limpo = texto.strip().replace(".", "").replace(",", ".")
        return float(limpo)
    except (ValueError, AttributeError):
        return None


def parse_data_flexivel(texto: str) -> Optional[datetime]:
    """
    Parser de data flexível que aceita todos os formatos encontrados
    nos processos do EB:

    - DD/MM/YYYY        → 12/01/2026
    - DD/MMM/YYYY       → 11/JAN/2026
    - DD de mês de YYYY → 05 de fevereiro de 2026
    - DDMMMYY           → 18JUN25, 30JUN26
    - DDMmmYY (SIAFI)   → 27Jan26
    - DD MMM YY         → 27 JAN 26
    - DDMMMYYYY         → 18JUN2025
    """
    if not texto:
        return None

    texto = texto.strip()

    # Formato: DD/MM/YYYY
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # Formato: DD/MMM/YYYY (ex: 11/JAN/2026)
    m = re.match(r"(\d{2})/([A-Za-z]{3})/(\d{4})", texto)
    if m:
        mes = MESES_PT.get(m.group(2).upper())
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass

    # Formato: DD de mês de YYYY
    m = re.match(
        r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.IGNORECASE
    )
    if m:
        mes = MESES_EXTENSO.get(m.group(2).lower())
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass

    # Formato: DD MMM YY (ex: 27 JAN 26)
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2})", texto)
    if m:
        mes = MESES_PT.get(m.group(2).upper())
        if mes:
            ano = 2000 + int(m.group(3))
            try:
                return datetime(ano, mes, int(m.group(1)))
            except ValueError:
                pass

    # Formato: DDMmmYY (SIAFI — ex: 27Jan26) ou DDMMMYY (ex: 30JUN26)
    m = re.match(r"(\d{2})([A-Za-z]{3})(\d{2})", texto)
    if m:
        mes = MESES_PT.get(m.group(2).upper())
        if mes:
            ano = 2000 + int(m.group(3))
            try:
                return datetime(ano, mes, int(m.group(1)))
            except ValueError:
                pass

    # Formato: DDMMMYYYY (ex: 18JUN2025)
    m = re.match(r"(\d{2})([A-Za-z]{3})(\d{4})", texto)
    if m:
        mes = MESES_PT.get(m.group(2).upper())
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass

    # Formato: DD/MM/YY
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})", texto)
    if m:
        ano = 2000 + int(m.group(3))
        try:
            return datetime(ano, int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


# ══════════════════════════════════════════════════════════════════════
# FUNÇÃO DE TESTE RÁPIDO
# ══════════════════════════════════════════════════════════════════════

def _imprimir_resultado(resultado: dict, nivel: int = 0) -> None:
    """Imprime o resultado da extração de forma legível (para debug)."""
    indent = "  " * nivel
    for chave, valor in resultado.items():
        if isinstance(valor, dict):
            print(f"{indent}{chave}:")
            _imprimir_resultado(valor, nivel + 1)
        elif isinstance(valor, list):
            print(f"{indent}{chave}: ({len(valor)} itens)")
            for i, item in enumerate(valor):
                if isinstance(item, dict):
                    print(f"{indent}  [{i}]:")
                    _imprimir_resultado(item, nivel + 2)
                else:
                    print(f"{indent}  [{i}]: {item}")
        else:
            print(f"{indent}{chave}: {valor}")


if __name__ == "__main__":
    import sys
    import os

    # Caminho padrão para testes
    diretorio_testes = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "tests"
    )

    # Se recebeu argumento, usa como caminho do PDF
    if len(sys.argv) > 1:
        caminhos = [sys.argv[1]]
    else:
        # Testa todos os PDFs na pasta tests/
        caminhos = [
            os.path.join(diretorio_testes, f)
            for f in os.listdir(diretorio_testes)
            if f.endswith(".pdf")
        ]

    for caminho in caminhos:
        print(f"\n{'='*70}")
        print(f"PROCESSANDO: {os.path.basename(caminho)}")
        print(f"{'='*70}")

        resultado = extrair_processo(caminho)
        _imprimir_resultado(resultado)

