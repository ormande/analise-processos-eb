"""
Módulo independente para extração de dados da requisição de processos requisitórios.

Extrai 3 campos das páginas da requisição:
- Tipo de Empenho (Global, Ordinário ou Estimativo)
- Instrumento (Pregão Eletrônico, Contrato ou Dispensa)
- UASG (código + nome da OM)

Este módulo é 100% independente e não importa nada do extractor.py existente.
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import pdfplumber
except ImportError:
    print("[REQUISIÇÃO] ERRO: pdfplumber não está instalado. Execute: pip install pdfplumber")
    sys.exit(1)


# ── Constantes ──────────────────────────────────────────────────────────────

# Mapeamento de códigos UASG para nomes oficiais
UASG_CONHECIDAS: Dict[str, str] = {
    "160136": "9º Grupamento Logístico",
    "160141": "CRO/9",
    "160142": "9º Batalhão de Suprimento",
    "160143": "Hospital Militar de Área de Campo Grande",
    "160078": "Colégio Militar de Campo Grande",
    "160255": "1º Batalhão de Polícia do Exército",
    "160512": "20º Regimento de Cavalaria Blindado",
    "160502": "Departamento de Engenharia e Construção",
    "160504": "Comando Militar do Oeste",
}


# ── Funções de Extração ─────────────────────────────────────────────────────

def _extrair_tipo_empenho(texto: str) -> Optional[str]:
    """
    Extrai o tipo de empenho do texto da requisição.
    
    Tenta duas fontes:
    - FONTE A: Campo do cabeçalho "Tipo de Empenho: ..."
    - FONTE B: Checkbox marcado na seção 4 "(x) Global/Ordinário/Estimativo"
    
    Args:
        texto: Texto completo das páginas da requisição
        
    Returns:
        String com o tipo normalizado ("Global", "Ordinário", "Estimativo") ou None
    """
    # FONTE A: Campo do cabeçalho
    padrao_a = r"[Tt]ipo\s+de\s+[Ee]mpenho\s*:\s*(Global|Ordin[aá]rio|Estimativo)"
    match_a = re.search(padrao_a, texto, re.IGNORECASE)
    
    if match_a:
        tipo = match_a.group(1)
        # Normalizar: primeira letra maiúscula
        return tipo.capitalize() if tipo.lower() == "global" else tipo.title()
    
    # FONTE B: Checkbox marcado (x), (X) ou (✓)
    padrao_b = r"\([\s]*[xX✓][\s]*\)\s*(Global|Ordin[aá]rio|Estimativo)"
    match_b = re.search(padrao_b, texto, re.IGNORECASE)
    
    if match_b:
        tipo = match_b.group(1)
        # Normalizar: primeira letra maiúscula
        return tipo.capitalize() if tipo.lower() == "global" else tipo.title()
    
    return None


def _extrair_instrumento(texto: str) -> Dict[str, Optional[str]]:
    """
    Extrai o instrumento de contratação (Pregão, Contrato ou Dispensa).
    
    Busca no texto da seção 1 da requisição. Se múltiplos instrumentos
    forem encontrados, aplica regra de prioridade baseada em "por meio de/do".
    
    Args:
        texto: Texto completo das páginas da requisição
        
    Returns:
        Dict com:
        - "tipo": "pregao", "contrato", "dispensa" ou None
        - "numero": número do instrumento (ex: "90004/2025", "126/2022") ou None
        - "fmt": formato para exibição (ex: "PE 90004/2025", "Contrato 126/2022") ou None
    """
    resultado = {
        "tipo": None,
        "numero": None,
        "fmt": None,
    }
    
    # Buscar pregão eletrônico
    # Padrão: "Pregão Eletrônico", "Pregão" ou "PE" seguido de número
    padrao_pregao = r"(?:Preg[aã]o\s+Eletr[oô]nico|Preg[aã]o|PE)\s*(?:n[°ºr.]?\s*)?\s*(\d{4,5}\s*/\s*\d{4})"
    match_pregao = re.search(padrao_pregao, texto, re.IGNORECASE)
    
    # Buscar contrato
    # Padrão: "contrato" seguido de número (priorizar contrato original, não aditivo)
    padrao_contrato = r"[Cc]ontrato\s*(?:n[°ºr.]?\s*)?\s*(\d{1,4}\s*/\s*\d{4})"
    match_contrato = re.search(padrao_contrato, texto, re.IGNORECASE)
    
    # Buscar dispensa
    # Padrão: "Dispensa" (com ou sem "de Licitação") seguido de número
    padrao_dispensa = r"[Dd]ispensa(?:\s+de\s+[Ll]icita[çc][aã]o)?\s*(?:n[°ºr.]?\s*)?\s*(\d{1,4}\s*/\s*\d{4})"
    match_dispensa = re.search(padrao_dispensa, texto, re.IGNORECASE)
    
    # Se múltiplos encontrados, aplicar regra de prioridade
    # Buscar contexto "por meio de/do" para determinar o principal
    contexto_por_meio = re.search(
        r"por\s+meio\s+(?:de|do)\s+(?:o\s+)?(?:Preg[aã]o\s+Eletr[oô]nico|Preg[aã]o|PE|[Cc]ontrato)",
        texto,
        re.IGNORECASE
    )
    
    if contexto_por_meio:
        contexto_texto = contexto_por_meio.group(0).lower()
        if "preg" in contexto_texto or "pe" in contexto_texto:
            # Priorizar pregão se mencionado em "por meio de"
            if match_pregao:
                numero = re.sub(r"\s+", "", match_pregao.group(1))
                resultado["tipo"] = "pregao"
                resultado["numero"] = numero
                resultado["fmt"] = f"PE {numero}"
                return resultado
        elif "contrato" in contexto_texto:
            # Priorizar contrato se mencionado em "por meio de"
            if match_contrato:
                numero = re.sub(r"\s+", "", match_contrato.group(1))
                resultado["tipo"] = "contrato"
                resultado["numero"] = numero
                resultado["fmt"] = f"Contrato {numero}"
                return resultado
    
    # Se não há contexto "por meio de", usar ordem de prioridade:
    # 1. Pregão (mais comum)
    # 2. Contrato
    # 3. Dispensa
    
    if match_pregao:
        numero = re.sub(r"\s+", "", match_pregao.group(1))
        resultado["tipo"] = "pregao"
        resultado["numero"] = numero
        resultado["fmt"] = f"PE {numero}"
        return resultado
    
    if match_contrato:
        numero = re.sub(r"\s+", "", match_contrato.group(1))
        resultado["tipo"] = "contrato"
        resultado["numero"] = numero
        resultado["fmt"] = f"Contrato {numero}"
        return resultado
    
    if match_dispensa:
        numero = re.sub(r"\s+", "", match_dispensa.group(1))
        resultado["tipo"] = "dispensa"
        resultado["numero"] = numero
        resultado["fmt"] = f"Dispensa {numero}"
        return resultado
    
    return resultado


def _extrair_uasg(texto: str) -> Dict[str, Optional[str]]:
    """
    Extrai a UASG (código + nome da OM) do texto da requisição.
    
    Busca padrões:
    - "UASG XXXXXX" ou "UG XXXXXX" seguido de nome
    - Fallback: número de 6 dígitos começando com 16 seguido de separador + nome
    
    Normaliza o nome usando UASG_CONHECIDAS. Se código não está no dicionário,
    usa o nome extraído do PDF com title case.
    
    Args:
        texto: Texto completo das páginas da requisição
        
    Returns:
        Dict com:
        - "codigo": código UASG (ex: "160136") ou None
        - "nome": nome da OM (ex: "9º Grupamento Logístico") ou None
        - "fmt": formato para exibição (ex: "160136 — 9º Grupamento Logístico") ou None
    """
    resultado = {
        "codigo": None,
        "nome": None,
        "fmt": None,
    }
    
    # Padrão 1: "UASG XXXXXX" ou "UG XXXXXX" seguido de separador + nome
    padrao_1 = r"(?:UASG|UG)\s*:?\s*(\d{6})\s*[-–,]\s*(.+?)(?:\.|,|\n|$)"
    match_1 = re.search(padrao_1, texto, re.IGNORECASE)
    
    if match_1:
        codigo = match_1.group(1)
        nome_raw = match_1.group(2).strip()
        
        # Normalizar nome
        nome_oficial = UASG_CONHECIDAS.get(codigo)
        if nome_oficial:
            nome = nome_oficial
        else:
            # Usar nome extraído com title case
            nome = nome_raw.title()
        
        resultado["codigo"] = codigo
        resultado["nome"] = nome
        resultado["fmt"] = f"{codigo} — {nome}"
        return resultado
    
    # Padrão 2: Fallback - número de 6 dígitos começando com 16 seguido de separador + nome
    # (sem prefixo UASG/UG)
    padrao_2 = r"(\d{6})\s*[-–,]\s*(.+?)(?:\.|,|\n|$)"
    match_2 = re.search(padrao_2, texto)
    
    if match_2:
        codigo = match_2.group(1)
        # Verificar se começa com 16 (códigos UASG do Exército)
        if codigo.startswith("16"):
            nome_raw = match_2.group(2).strip()
            
            # Normalizar nome
            nome_oficial = UASG_CONHECIDAS.get(codigo)
            if nome_oficial:
                nome = nome_oficial
            else:
                # Usar nome extraído com title case
                nome = nome_raw.title()
            
            resultado["codigo"] = codigo
            resultado["nome"] = nome
            resultado["fmt"] = f"{codigo} — {nome}"
            return resultado
    
    return resultado


def extrair_requisicao(pdf_path: str) -> Dict[str, Any]:
    """
    Extrai os 3 campos da requisição de um PDF de processo requisitório.
    
    Campos extraídos:
    - Tipo de Empenho (Global, Ordinário ou Estimativo)
    - Instrumento (Pregão Eletrônico, Contrato ou Dispensa)
    - UASG (código + nome da OM)
    
    Lê TODAS as páginas do PDF, mas prioriza páginas 1-5 (índices 0-4)
    onde os dados geralmente estão.
    
    Args:
        pdf_path: Caminho para o arquivo PDF
        
    Returns:
        Dict com os campos extraídos:
        {
            "tipo_empenho": str ou None,
            "instrumento": {
                "tipo": str ou None,
                "numero": str ou None,
                "fmt": str ou None,
            },
            "uasg": {
                "codigo": str ou None,
                "nome": str ou None,
                "fmt": str ou None,
            },
            "erro": str ou None (se houver erro)
        }
    """
    resultado = {
        "tipo_empenho": None,
        "instrumento": {
            "tipo": None,
            "numero": None,
            "fmt": None,
        },
        "uasg": {
            "codigo": None,
            "nome": None,
            "fmt": None,
        },
        "erro": None,
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                resultado["erro"] = "PDF vazio ou sem páginas"
                return resultado
            
            # Priorizar páginas 1-5 (índices 0-4), mas ler todas se necessário
            textos_prioritarios = []
            textos_completos = []
            
            for i, pagina in enumerate(pdf.pages):
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    textos_completos.append(texto_pagina)
                    if i < 5:  # Páginas 0-4 (páginas 1-5)
                        textos_prioritarios.append(texto_pagina)
            
            # Juntar textos prioritários primeiro
            texto_prioritario = "\n".join(textos_prioritarios)
            texto_completo = "\n".join(textos_completos)
            
            # Tentar extrair dos textos prioritários primeiro
            # Se não encontrar, tentar no texto completo
            
            # Extrair tipo de empenho
            tipo_empenho = _extrair_tipo_empenho(texto_prioritario)
            if not tipo_empenho:
                tipo_empenho = _extrair_tipo_empenho(texto_completo)
            resultado["tipo_empenho"] = tipo_empenho
            
            # Extrair instrumento
            instrumento = _extrair_instrumento(texto_prioritario)
            if not instrumento["tipo"]:
                instrumento = _extrair_instrumento(texto_completo)
            resultado["instrumento"] = instrumento
            
            # Extrair UASG
            uasg = _extrair_uasg(texto_prioritario)
            if not uasg["codigo"]:
                uasg = _extrair_uasg(texto_completo)
            resultado["uasg"] = uasg
            
    except Exception as e:
        resultado["erro"] = f"Erro ao processar PDF: {str(e)}"
        print(f"[REQUISIÇÃO] ERRO ao processar {pdf_path}: {e}")
    
    return resultado


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # Processar PDFs
    if len(sys.argv) > 1:
        # Processar arquivo específico
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists():
            print(f"[REQUISIÇÃO] ERRO: Arquivo não encontrado: {pdf_path}")
            sys.exit(1)
        
        pdfs = [pdf_path]
    else:
        # Processar todos os PDFs em tests/
        tests_dir = Path(__file__).parent.parent / "tests"
        pdfs = list(tests_dir.glob("*.pdf"))
        
        if not pdfs:
            print(f"[REQUISIÇÃO] ERRO: Nenhum PDF encontrado em {tests_dir}")
            sys.exit(1)
        
        print(f"[REQUISIÇÃO] Encontrados {len(pdfs)} PDF(s) em tests/\n")
    
    # Processar cada PDF
    resultados = []
    completos = 0
    
    for pdf_path in sorted(pdfs):
        print("═" * 70)
        print(f"    REQUISIÇÃO: {pdf_path.name}")
        print("═" * 70)
        
        resultado = extrair_requisicao(str(pdf_path))
        
        if resultado.get("erro"):
            print(f"ERRO: {resultado['erro']}")
        else:
            # Tipo de Empenho
            tipo_empenho = resultado.get("tipo_empenho") or "—"
            print(f"Tipo Empenho: {tipo_empenho}")
            
            # Instrumento
            instrumento = resultado.get("instrumento", {})
            instrumento_fmt = instrumento.get("fmt") or "—"
            print(f"Instrumento:  {instrumento_fmt}")
            
            # UASG
            uasg = resultado.get("uasg", {})
            uasg_fmt = uasg.get("fmt") or "—"
            print(f"UASG:         {uasg_fmt}")
            
            # Verificar se extração está completa (3/3 campos)
            tem_tipo = resultado.get("tipo_empenho") is not None
            tem_instrumento = instrumento.get("tipo") is not None
            tem_uasg = uasg.get("codigo") is not None
            
            if tem_tipo and tem_instrumento and tem_uasg:
                completos += 1
            
            resultados.append({
                "arquivo": pdf_path.name,
                "completo": tem_tipo and tem_instrumento and tem_uasg,
            })
        
        print("-" * 70)
        print()
    
    # Resumo final
    print("═" * 70)
    print(f"RESUMO: {completos}/{len(pdfs)} processos com extração completa (3/3 campos)")
    print("═" * 70)

