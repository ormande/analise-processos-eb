"""
Módulo independente para extração de dados da capa (página 1) de processos requisitórios.

Extrai apenas 3 campos:
- NUP (Número Único de Protocolo)
- Número da Requisição
- OM Requisitante (Organização Militar)

Este módulo é 100% independente e não importa nada do extractor.py existente.
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import pdfplumber
except ImportError:
    print("[CAPA] ERRO: pdfplumber não está instalado. Execute: pip install pdfplumber")
    sys.exit(1)


# ── Constantes ──────────────────────────────────────────────────────────────

# Mapeamento de variações de nomes de OM para nomes oficiais
OM_CONHECIDAS: Dict[str, str] = {
    # 9º Grupamento Logístico
    "9 GRUPAMENTO LOGISTICO": "9º Grupamento Logístico",
    "9º GRUPAMENTO LOGISTICO": "9º Grupamento Logístico",
    "9 GRUPAMENTO LOGÍSTICO": "9º Grupamento Logístico",
    "9º GRUPAMENTO LOGÍSTICO": "9º Grupamento Logístico",
    "9 GPT LOG": "9º Grupamento Logístico",
    "9º GPT LOG": "9º Grupamento Logístico",
    "9 GPT LOGISTICO": "9º Grupamento Logístico",
    "9º GPT LOGISTICO": "9º Grupamento Logístico",
    "9 GPT LOGÍSTICO": "9º Grupamento Logístico",
    "9º GPT LOGÍSTICO": "9º Grupamento Logístico",
    "9 GRUP LOG": "9º Grupamento Logístico",
    "9º GRUP LOG": "9º Grupamento Logístico",
    "CMDO 9 GPT LOG": "9º Grupamento Logístico",
    "CMDO 9º GPT LOG": "9º Grupamento Logístico",
    
    # 9º Batalhão de Manutenção
    "9 BATALHAO DE MANUTENCAO": "9º Batalhão de Manutenção",
    "9º BATALHAO DE MANUTENCAO": "9º Batalhão de Manutenção",
    "9 BATALHÃO DE MANUTENÇÃO": "9º Batalhão de Manutenção",
    "9º BATALHÃO DE MANUTENÇÃO": "9º Batalhão de Manutenção",
    "9 B MNT": "9º Batalhão de Manutenção",
    "9º B MNT": "9º Batalhão de Manutenção",
    "9 B MNT": "9º Batalhão de Manutenção",
    "9º B MNT": "9º Batalhão de Manutenção",
    "9 BATALHAO MANUTENCAO": "9º Batalhão de Manutenção",
    "9º BATALHAO MANUTENCAO": "9º Batalhão de Manutenção",
    
    # 9º Batalhão de Saúde
    "9 BATALHAO DE SAUDE": "9º Batalhão de Saúde",
    "9º BATALHAO DE SAUDE": "9º Batalhão de Saúde",
    "9 BATALHÃO DE SAÚDE": "9º Batalhão de Saúde",
    "9º BATALHÃO DE SAÚDE": "9º Batalhão de Saúde",
    "9 B SAU": "9º Batalhão de Saúde",
    "9º B SAU": "9º Batalhão de Saúde",
    "9 B SAUDE": "9º Batalhão de Saúde",
    "9º B SAUDE": "9º Batalhão de Saúde",
    "9 BATALHAO SAUDE": "9º Batalhão de Saúde",
    "9º BATALHAO SAUDE": "9º Batalhão de Saúde",
    
    # 9º Batalhão de Suprimento
    "9 BATALHAO DE SUPRIMENTO": "9º Batalhão de Suprimento",
    "9º BATALHAO DE SUPRIMENTO": "9º Batalhão de Suprimento",
    "9 BATALHÃO DE SUPRIMENTO": "9º Batalhão de Suprimento",
    "9º BATALHÃO DE SUPRIMENTO": "9º Batalhão de Suprimento",
    "9 B SUP": "9º Batalhão de Suprimento",
    "9º B SUP": "9º Batalhão de Suprimento",
    "9 B SUPRIMENTO": "9º Batalhão de Suprimento",
    "9º B SUPRIMENTO": "9º Batalhão de Suprimento",
    "9 BATALHAO SUPRIMENTO": "9º Batalhão de Suprimento",
    "9º BATALHAO SUPRIMENTO": "9º Batalhão de Suprimento",
    
    # 18º Batalhão de Transporte
    "18 BATALHAO DE TRANSPORTE": "18º Batalhão de Transporte",
    "18º BATALHAO DE TRANSPORTE": "18º Batalhão de Transporte",
    "18 BATALHÃO DE TRANSPORTE": "18º Batalhão de Transporte",
    "18º BATALHÃO DE TRANSPORTE": "18º Batalhão de Transporte",
    "18 B TRNP": "18º Batalhão de Transporte",
    "18º B TRNP": "18º Batalhão de Transporte",
    "18 B TRANSPORTE": "18º Batalhão de Transporte",
    "18º B TRANSPORTE": "18º Batalhão de Transporte",
    "18 BATALHAO TRANSPORTE": "18º Batalhão de Transporte",
    "18º BATALHAO TRANSPORTE": "18º Batalhão de Transporte",
}


# ── Funções de Extração ─────────────────────────────────────────────────────

def _extrair_nup(texto: str) -> Optional[str]:
    """
    Extrai o NUP (Número Único de Protocolo) do texto.
    
    Formato esperado: XXXXX.XXXXXX/XXXX-XX
    Exemplos: 65297.001529/2026-55, 65345.000389/2026-85
    
    Args:
        texto: Texto completo da página 1 (capa)
        
    Returns:
        String com o NUP encontrado ou None se não encontrar
    """
    padrao = r"\d{5}\.\d{6}/\d{4}-\d{2}"
    match = re.search(padrao, texto)
    return match.group(0) if match else None


def _extrair_nr_requisicao(texto: str) -> Dict[str, Any]:
    """
    Extrai o número da requisição do campo ASSUNTO.
    
    Captura variações como:
    - "Requisição 21/2026" → "21/2026"
    - "Req n° S002/2026" → "S002/2026"
    - "Req 03" → "03"
    
    Args:
        texto: Texto completo da página 1 (capa)
        
    Returns:
        Dict com:
        - "nr_requisicao_raw": número bruto extraído (ex: "21/2026", "M012/2026", "03")
        - "nr_requisicao_fmt": formato para exibição (ex: "Requisição Nº 21/2026")
        - "tem_letra": bool indicando se tem prefixo de letra (M, S, R, etc.)
        - "ano": string com o ano (ex: "2026") ou None
    """
    # Regex para capturar todas as variações
    # Usa múltiplos padrões para maior robustez e flexibilidade com encoding
    padroes = [
        # Padrão 1: Requisição (com variações de ç/c) seguido de espaço e número
        r"Requisi[çc][aã]o\s+(?:n[°ºr.]?\s*)?([A-Z]?\d{1,4}(?:[/-]\d{4})?)(?:[-]|\s|$)",
        # Padrão 2: Req seguido de espaço e número
        r"Req\s+(?:n[°ºr.]?\s*)?([A-Z]?\d{1,4}(?:[/-]\d{4})?)(?:[-]|\s|$)",
        # Padrão 3: Requisição/Req seguido diretamente de número (sem espaço)
        r"Requisi[çc][aã]o(?:n[°ºr.]?\s*)?([A-Z]?\d{1,4}(?:[/-]\d{4})?)(?:[-]|\s|$)",
        # Padrão 4: Req seguido diretamente de número (sem espaço)
        r"Req(?:n[°ºr.]?\s*)?([A-Z]?\d{1,4}(?:[/-]\d{4})?)(?:[-]|\s|$)",
    ]
    
    match = None
    for padrao in padroes:
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            break
    
    if not match:
        return {
            "nr_requisicao_raw": None,
            "nr_requisicao_fmt": None,
            "tem_letra": False,
            "ano": None,
        }
    
    nr_raw = match.group(1)
    
    # Verificar se tem letra no início
    tem_letra = bool(re.match(r"^[A-Z]", nr_raw))
    
    # Extrair ano se presente
    ano_match = re.search(r"[/-](\d{4})$", nr_raw)
    ano = ano_match.group(1) if ano_match else None
    
    # Formatar para exibição
    if tem_letra:
        nr_fmt = f"Req Nº {nr_raw}"
    else:
        nr_fmt = f"Requisição Nº {nr_raw}"
    
    return {
        "nr_requisicao_raw": nr_raw,
        "nr_requisicao_fmt": nr_fmt,
        "tem_letra": tem_letra,
        "ano": ano,
    }


def _extrair_om(texto: str) -> Dict[str, Any]:
    """
    Extrai a OM Requisitante do campo "Órgão de Origem:".
    
    Normaliza o nome comparando com a lista de OMs conhecidas.
    
    Args:
        texto: Texto completo da página 1 (capa)
        
    Returns:
        Dict com:
        - "om_raw": texto bruto extraído
        - "om_oficial": nome oficial normalizado (ou o raw se não reconhecida)
    """
    # Buscar após "Órgão de Origem:" ou "Orgao de Origem:"
    padrao = r"[OÓ]rg[aã]o\s+de\s+[Oo]rigem\s*:\s*(.+?)(?:\n|Data|$)"
    
    match = re.search(padrao, texto, re.IGNORECASE)
    
    if not match:
        return {
            "om_raw": None,
            "om_oficial": None,
        }
    
    om_raw = match.group(1).strip()
    
    # Normalizar: remover espaços extras, converter para maiúsculas
    om_normalizada = re.sub(r"\s+", " ", om_raw).upper()
    
    # Buscar na lista de OMs conhecidas
    om_oficial = OM_CONHECIDAS.get(om_normalizada, om_raw)
    
    return {
        "om_raw": om_raw,
        "om_oficial": om_oficial,
    }


def extrair_capa(pdf_path: str) -> Dict[str, Any]:
    """
    Extrai os 3 campos da capa (página 1) de um PDF de processo requisitório.
    
    Campos extraídos:
    - NUP (Número Único de Protocolo)
    - Número da Requisição
    - OM Requisitante
    
    Args:
        pdf_path: Caminho para o arquivo PDF
        
    Returns:
        Dict com os campos extraídos:
        {
            "nup": str ou None,
            "nr_requisicao": {
                "nr_requisicao_raw": str ou None,
                "nr_requisicao_fmt": str ou None,
                "tem_letra": bool,
                "ano": str ou None,
            },
            "om": {
                "om_raw": str ou None,
                "om_oficial": str ou None,
            },
            "erro": str ou None (se houver erro)
        }
    """
    resultado = {
        "nup": None,
        "nr_requisicao": {
            "nr_requisicao_raw": None,
            "nr_requisicao_fmt": None,
            "tem_letra": False,
            "ano": None,
        },
        "om": {
            "om_raw": None,
            "om_oficial": None,
        },
        "erro": None,
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                resultado["erro"] = "PDF vazio ou sem páginas"
                return resultado
            
            # Extrair texto da página 1 (índice 0)
            pagina = pdf.pages[0]
            texto = pagina.extract_text()
            
            if not texto:
                resultado["erro"] = "Não foi possível extrair texto da página 1"
                return resultado
            
            # Extrair os 3 campos
            resultado["nup"] = _extrair_nup(texto)
            resultado["nr_requisicao"] = _extrair_nr_requisicao(texto)
            resultado["om"] = _extrair_om(texto)
            
    except Exception as e:
        resultado["erro"] = f"Erro ao processar PDF: {str(e)}"
        print(f"[CAPA] ERRO ao processar {pdf_path}: {e}")
    
    return resultado


# ── Testes Unitários ────────────────────────────────────────────────────────

def _testar_extrair_nr_requisicao():
    """
    Testa a função _extrair_nr_requisicao com casos de teste conhecidos.
    """
    casos_teste = [
        {
            "texto": "ASSUNTO: Requisição 21/2026- Almox Cmdo (Aquisição de material hidraúlico)",
            "nr_raw_esperado": "21/2026",
            "nr_fmt_esperado": "Requisição Nº 21/2026",
        },
        {
            "texto": "ASSUNTO: Requisição N°10/2026 - Almox",
            "nr_raw_esperado": "10/2026",
            "nr_fmt_esperado": "Requisição Nº 10/2026",
        },
        {
            "texto": "ASSUNTO: Requisição 01/2026",
            "nr_raw_esperado": "01/2026",
            "nr_fmt_esperado": "Requisição Nº 01/2026",
        },
        {
            "texto": "ASSUNTO: Req n° S002/2026 – Pel Sup",
            "nr_raw_esperado": "S002/2026",
            "nr_fmt_esperado": "Req Nº S002/2026",
        },
        {
            "texto": "ASSUNTO: Req n° M012/2026 – Pel Sup",
            "nr_raw_esperado": "M012/2026",
            "nr_fmt_esperado": "Req Nº M012/2026",
        },
        {
            "texto": "ASSUNTO: Req 03",
            "nr_raw_esperado": "03",
            "nr_fmt_esperado": "Requisição Nº 03",
        },
        {
            "texto": "ASSUNTO: Req 01",
            "nr_raw_esperado": "01",
            "nr_fmt_esperado": "Requisição Nº 01",
        },
        {
            "texto": "ASSUNTO: Requisição 19/2026",
            "nr_raw_esperado": "19/2026",
            "nr_fmt_esperado": "Requisição Nº 19/2026",
        },
        {
            "texto": "ASSUNTO: Requisição 09/2026",
            "nr_raw_esperado": "09/2026",
            "nr_fmt_esperado": "Requisição Nº 09/2026",
        },
        {
            "texto": "ASSUNTO: Requisição 02/2026",
            "nr_raw_esperado": "02/2026",
            "nr_fmt_esperado": "Requisição Nº 02/2026",
        },
    ]
    
    print("[CAPA] Executando testes unitários de _extrair_nr_requisicao...")
    print("-" * 70)
    
    passou = 0
    falhou = 0
    
    for i, caso in enumerate(casos_teste, 1):
        resultado = _extrair_nr_requisicao(caso["texto"])
        nr_raw = resultado["nr_requisicao_raw"]
        nr_fmt = resultado["nr_requisicao_fmt"]
        
        raw_ok = nr_raw == caso["nr_raw_esperado"]
        fmt_ok = nr_fmt == caso["nr_fmt_esperado"]
        
        if raw_ok and fmt_ok:
            print(f"✅ Teste {i}: PASSOU")
            passou += 1
        else:
            print(f"❌ Teste {i}: FALHOU")
            print(f"   Texto: {caso['texto']}")
            print(f"   Esperado raw: {caso['nr_raw_esperado']}, obtido: {nr_raw}")
            print(f"   Esperado fmt: {caso['nr_fmt_esperado']}, obtido: {nr_fmt}")
            falhou += 1
    
    print("-" * 70)
    print(f"Resultado: {passou} passou, {falhou} falhou")
    
    if falhou > 0:
        print("[CAPA] ⚠️  Alguns testes falharam. Verifique os padrões regex.")
        return False
    
    print("[CAPA] ✅ Todos os testes passaram!")
    return True


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # Executar testes unitários primeiro
    print("[CAPA] Iniciando testes...\n")
    testes_ok = _testar_extrair_nr_requisicao()
    print()
    
    if not testes_ok:
        print("[CAPA] ⚠️  Testes unitários falharam. Continuando mesmo assim...\n")
    
    # Processar PDFs
    if len(sys.argv) > 1:
        # Processar arquivo específico
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists():
            print(f"[CAPA] ERRO: Arquivo não encontrado: {pdf_path}")
            sys.exit(1)
        
        pdfs = [pdf_path]
    else:
        # Processar todos os PDFs em tests/
        tests_dir = Path(__file__).parent.parent / "tests"
        pdfs = list(tests_dir.glob("*.pdf"))
        
        if not pdfs:
            print(f"[CAPA] ERRO: Nenhum PDF encontrado em {tests_dir}")
            sys.exit(1)
        
        print(f"[CAPA] Encontrados {len(pdfs)} PDF(s) em tests/\n")
    
    # Processar cada PDF
    resultados = []
    completos = 0
    
    for pdf_path in sorted(pdfs):
        print("═" * 70)
        print(f"    CAPA: {pdf_path.name}")
        print("═" * 70)
        
        resultado = extrair_capa(str(pdf_path))
        
        if resultado.get("erro"):
            print(f"ERRO: {resultado['erro']}")
        else:
            # NUP
            nup = resultado.get("nup") or "—"
            print(f"NUP:        {nup}")
            
            # Requisição
            nr_info = resultado.get("nr_requisicao", {})
            nr_fmt = nr_info.get("nr_requisicao_fmt") or "—"
            print(f"Requisição: {nr_fmt}")
            
            # OM
            om_info = resultado.get("om", {})
            om_oficial = om_info.get("om_oficial") or "—"
            print(f"OM:         {om_oficial}")
            
            # Verificar se extração está completa
            tem_nup = resultado.get("nup") is not None
            tem_nr = nr_info.get("nr_requisicao_raw") is not None
            tem_om = om_info.get("om_oficial") is not None
            
            if tem_nup and tem_nr and tem_om:
                completos += 1
            
            resultados.append({
                "arquivo": pdf_path.name,
                "completo": tem_nup and tem_nr and tem_om,
            })
        
        print("-" * 70)
        print()
    
    # Resumo final
    print("═" * 70)
    print(f"RESUMO: {completos}/{len(pdfs)} processos com extração completa")
    print("═" * 70)

