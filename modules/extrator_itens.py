"""
Módulo independente para extração de itens da tabela de requisição de processos requisitórios.

Extrai:
- Dados do fornecedor (nome, CNPJ)
- Todos os itens da tabela de materiais/serviços
- Valor total da tabela
- Campo observação (máscara do requisitante)

Este módulo extrai SOMENTE tabelas de texto nativo (pdfplumber).
Tabelas em formato de imagem (OCR) serão tratadas pelo extrator_itens_ocr.py separado.

Este módulo é 100% independente e não importa nada do extractor.py existente.
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import pdfplumber
except ImportError:
    print("[ITENS] ERRO: pdfplumber não está instalado. Execute: pip install pdfplumber")
    sys.exit(1)


# ── Funções Auxiliares ──────────────────────────────────────────────────────

def _normalizar_nd_si(raw: str) -> Optional[str]:
    """
    Normaliza o campo ND/SI para formato padrão.
    
    Aceita múltiplos formatos:
    - "33.90.30.34" → "30.34"
    - "33.90.39/17" → "39.17"
    - "30.24" → "30.24" (assume prefixo 3390)
    - "30/04" → "30.04"
    - "4490.52.08" → "52.08"
    
    Args:
        raw: String bruta do campo ND/SI
        
    Returns:
        String normalizada (ex: "30.34", "39.17") ou None se não conseguir parsear
    """
    if not raw:
        return None
    
    # Limpar: remover espaços, \n, \r, \t
    texto = re.sub(r"[\s\n\r\t]+", "", str(raw).strip())
    
    if not texto:
        return None
    
    # Padrão 1: "33.90.30.34" (completo com 4 partes)
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})\.(\d{2})$", texto)
    if match:
        elem = match.group(3)
        si = match.group(4)
        return f"{elem}.{si}"
    
    # Padrão 2: "33.90.39/17" ou "33.90.39.17" (completo com / ou .)
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})[/.](\d{2})$", texto)
    if match:
        elem = match.group(3)
        si = match.group(4)
        return f"{elem}.{si}"
    
    # Padrão 3: "4490.52.08" (Classe IV completo)
    match = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})$", texto)
    if match:
        elem = match.group(2)
        si = match.group(3)
        return f"{elem}.{si}"
    
    # Padrão 4: "30.24" ou "39.17" ou "33.01" (só elem.SI, assume prefixo 3390)
    match = re.match(r"^(\d{2})\.(\d{2})$", texto)
    if match:
        # Retornar como está (já está no formato normalizado)
        return texto
    
    # Padrão 5: "30/04" (elem/SI com /)
    match = re.match(r"^(\d{2})[/](\d{2})$", texto)
    if match:
        elem = match.group(1)
        si = match.group(2)
        return f"{elem}.{si}"
    
    # Se nenhum padrão bater, retornar texto limpo
    return texto if texto else None


def _parse_valor_br(texto: str) -> Optional[float]:
    """
    Converte valor monetário do formato brasileiro para float.
    
    Formato brasileiro: ponto = milhar, vírgula = decimal
    Exemplos: "R$ 9.984,00" → 9984.0, "38,9948" → 38.9948, "0,30" → 0.3
    
    Args:
        texto: String com valor monetário (pode ter "R$", espaços, \n)
        
    Returns:
        Float com o valor ou None se não conseguir parsear
    """
    if not texto:
        return None
    
    # Remover "R$", espaços, \n, \r, \t
    texto_limpo = re.sub(r"R\$\s*", "", str(texto), flags=re.IGNORECASE)
    texto_limpo = re.sub(r"[\s\n\r\t]+", "", texto_limpo)
    
    if not texto_limpo:
        return None
    
    # Remover pontos de milhar (só se houver vírgula depois)
    if "," in texto_limpo:
        # Tem vírgula = tem decimal, então pontos são milhar
        texto_limpo = texto_limpo.replace(".", "")
        # Trocar vírgula por ponto decimal
        texto_limpo = texto_limpo.replace(",", ".")
    else:
        # Sem vírgula: verificar se tem ponto
        if "." in texto_limpo:
            # Se tem exatamente 3 dígitos após o ponto → pode ser milhar
            partes = texto_limpo.split(".")
            if len(partes) == 2 and len(partes[1]) == 3:
                # É milhar: "6.666" → 6666
                texto_limpo = texto_limpo.replace(".", "")
            # Caso contrário, tratar como decimal (improvável mas possível)
    
    try:
        return float(texto_limpo)
    except ValueError:
        return None


def _parse_qtd_br(texto: str) -> Optional[float]:
    """
    Converte quantidade do formato brasileiro para float.
    
    Regra especial: "6.666" (sem vírgula, 3 dígitos após ponto) → 6666 (milhar)
    "3.899,98" (com vírgula) → 3899.98 (decimal)
    
    Args:
        texto: String com quantidade
        
    Returns:
        Float com a quantidade ou None se não conseguir parsear
    """
    if not texto:
        return None
    
    # Limpar espaços, \n
    texto_limpo = re.sub(r"[\s\n\r\t]+", "", str(texto).strip())
    
    if not texto_limpo:
        return None
    
    # Se tem vírgula → formato decimal brasileiro
    if "," in texto_limpo:
        # Remover pontos de milhar
        texto_limpo = texto_limpo.replace(".", "")
        # Trocar vírgula por ponto decimal
        texto_limpo = texto_limpo.replace(",", ".")
    else:
        # Sem vírgula: verificar se tem ponto
        if "." in texto_limpo:
            partes = texto_limpo.split(".")
            if len(partes) == 2 and len(partes[1]) == 3:
                # É milhar: "6.666" → 6666
                texto_limpo = texto_limpo.replace(".", "")
            # Caso contrário, tratar como decimal
    
    try:
        return float(texto_limpo)
    except ValueError:
        return None


def _extrair_fornecedor(texto_paginas: str) -> Dict[str, Optional[str]]:
    """
    Extrai nome e CNPJ do fornecedor do texto das páginas.
    
    Tenta múltiplos formatos:
    1. "Nome da Empresa: ... CNPJ: ..."
    2. "Empresa: ... CNPJ: ..."
    3. "CNPJ - Nome" (CNPJ antes do nome)
    4. "Nome – CNPJ: ..." (na mesma linha)
    5. Sem rótulo, só CNPJ e nome próximos
    
    Args:
        texto_paginas: Texto completo de todas as páginas
        
    Returns:
        Dict com {"fornecedor": str|None, "cnpj": str|None}
    """
    resultado = {"fornecedor": None, "cnpj": None}
    
    # Buscar CNPJ (formato: XX.XXX.XXX/XXXX-XX)
    padrao_cnpj = r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"
    match_cnpj = re.search(padrao_cnpj, texto_paginas)
    
    if not match_cnpj:
        return resultado
    
    cnpj = match_cnpj.group(0)
    resultado["cnpj"] = cnpj
    
    # Buscar contexto ao redor do CNPJ (50 caracteres antes e depois)
    inicio = max(0, match_cnpj.start() - 200)
    fim = min(len(texto_paginas), match_cnpj.end() + 200)
    contexto = texto_paginas[inicio:fim]
    
    # Formato 1: "Nome da Empresa: ... CNPJ: ..."
    match = re.search(r"Nome\s+da\s+Empresa\s*:\s*(.+?)(?:\s+CNPJ\s*:|$)", contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        # Remover CNPJ se estiver no nome
        nome = re.sub(padrao_cnpj, "", nome).strip()
        resultado["fornecedor"] = nome
        return resultado
    
    # Formato 2: "Empresa: ... CNPJ: ..."
    match = re.search(r"Empresa\s*:\s*(.+?)(?:\s+CNPJ\s*:|$)", contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        nome = re.sub(padrao_cnpj, "", nome).strip()
        resultado["fornecedor"] = nome
        return resultado
    
    # Formato 3: "CNPJ - Nome" ou "CNPJ – Nome"
    match = re.search(rf"({padrao_cnpj})\s*[-–]\s*(.+?)(?:\n|$|DO:|AO:)", contexto, re.IGNORECASE)
    if match:
        nome = match.group(2).strip()
        resultado["fornecedor"] = nome
        return resultado
    
    # Formato 4: "Nome – CNPJ: ..." ou "Nome - CNPJ: ..." (na mesma linha)
    match = re.search(r"(.+?)\s*[-–]\s*CNPJ\s*:\s*" + padrao_cnpj, contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        # Remover rótulos comuns
        nome = re.sub(r"^(Nome\s+da\s+Empresa|Empresa)\s*:\s*", "", nome, flags=re.IGNORECASE)
        resultado["fornecedor"] = nome
        return resultado
    
    # Formato 5: Buscar linha que contém CNPJ e tentar extrair nome da mesma linha
    linhas = contexto.split("\n")
    for linha in linhas:
        if cnpj in linha:
            # Remover CNPJ da linha
            nome = re.sub(padrao_cnpj, "", linha).strip()
            # Remover rótulos
            nome = re.sub(r"^(Nome\s+da\s+Empresa|Empresa|CNPJ|CPF\s*/\s*CNPJ)\s*:?\s*", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r"[-–]\s*$", "", nome).strip()
            # Remover texto comum que não é nome
            nome = re.sub(r",\s*destinada.*$", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r",\s*CNPJ.*$", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r"DUNS.*$", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r"Situação.*$", "", nome, flags=re.IGNORECASE)
            nome = nome.strip()
            if nome and len(nome) > 3 and not nome.startswith(","):  # Nome deve ter pelo menos 3 caracteres e não começar com vírgula
                resultado["fornecedor"] = nome
                return resultado
    
    # Formato 6: Buscar "da empresa" antes do CNPJ
    match = re.search(r"da\s+empresa\s+([^,]+?)(?:,\s*CNPJ|$)", contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        if nome and len(nome) > 3:
            resultado["fornecedor"] = nome
            return resultado
    
    return resultado


def _mapear_colunas(cabecalho: List[str]) -> Optional[Dict[str, int]]:
    """
    Mapeia as colunas da tabela para campos padronizados.
    
    Identifica: item, catserv, descricao, und, qtd, nd_si, p_unit, p_total
    Ignora colunas com "JUSTIFICATIVA" ou "MOTIVO".
    
    Args:
        cabecalho: Lista de strings (primeira linha da tabela)
        
    Returns:
        Dict mapeando nome_campo -> indice_coluna, ou None se não reconhecer
    """
    mapa = {}
    colunas_ignorar = []
    
    # Normalizar cada célula do cabeçalho
    for i, celula in enumerate(cabecalho):
        if not celula:
            continue
        
        # Normalizar: remover \n, espaços extras, converter para maiúsculas
        normalizado = re.sub(r"\s+", " ", str(celula).replace("\n", " ").strip().upper())
        
        # Verificar se é coluna a ignorar
        if "JUSTIFICATIVA" in normalizado or "MOTIVO" in normalizado:
            colunas_ignorar.append(i)
            continue
        
        # Mapear por keywords
        if ("ITEM" in normalizado or "ÍTEM" in normalizado) and "item" not in mapa:
            mapa["item"] = i
        elif ("CAT" in normalizado or "CATMAT" in normalizado or "CATSERV" in normalizado) and "catserv" not in mapa:
            mapa["catserv"] = i
        elif "DESCRI" in normalizado and "descricao" not in mapa:
            mapa["descricao"] = i
        elif ("UND" in normalizado or "FORN" in normalizado) and "und" not in mapa:
            mapa["und"] = i
        elif ("QTD" in normalizado or "QUANTIDADE" in normalizado) and "qtd" not in mapa:
            mapa["qtd"] = i
        elif ("ND" in normalizado or "S.I." in normalizado or "SI" in normalizado) and "nd_si" not in mapa:
            # Não confundir com "UND"
            if "UND" not in normalizado:
                mapa["nd_si"] = i
        elif ("UNT" in normalizado or "UNIT" in normalizado) and "p_unit" not in mapa:
            mapa["p_unit"] = i
        elif ("TOTAL" in normalizado or "GLOBAL" in normalizado) and "p_total" not in mapa:
            mapa["p_total"] = i
    
    # Se encontrou colunas com "R$", mapear como P_UNIT e P_TOTAL
    colunas_r = []
    for i, celula in enumerate(cabecalho):
        if celula and "R$" in str(celula).upper():
            colunas_r.append(i)
    
    if len(colunas_r) == 2:
        if "p_unit" not in mapa:
            mapa["p_unit"] = colunas_r[0]
        if "p_total" not in mapa:
            mapa["p_total"] = colunas_r[1]
    elif len(colunas_r) == 1:
        if "p_total" not in mapa:
            mapa["p_total"] = colunas_r[0]
    
    # Verificar se mapeou pelo menos item e descrição (mínimo necessário)
    if "item" in mapa and "descricao" in mapa:
        return mapa
    
    return None


def _detectar_tabela_sem_cabecalho(tabela: List[List[str]], mapa_anterior: Dict[str, int]) -> bool:
    """
    Verifica se uma tabela sem cabeçalho é continuação da tabela anterior.
    
    Args:
        tabela: Lista de linhas (cada linha é lista de células)
        mapa_anterior: Mapa de colunas da tabela anterior
        
    Returns:
        True se parece ser continuação, False caso contrário
    """
    if not tabela or len(tabela) == 0:
        return False
    
    if "item" not in mapa_anterior:
        return False
    
    # Verificar primeira linha de dados
    primeira_linha = tabela[0]
    if len(primeira_linha) <= mapa_anterior["item"]:
        return False
    
    # Verificar se primeira coluna (ou coluna ITEM) tem número
    col_item = mapa_anterior["item"]
    if col_item < len(primeira_linha):
        valor_item = str(primeira_linha[col_item]).strip()
        # Deve ser número de 1-3 dígitos
        if re.match(r"^\d{1,3}$", valor_item):
            return True
    
    # Verificar se tem valor monetário em alguma coluna
    for linha in tabela[:3]:  # Verificar até 3 primeiras linhas
        for celula in linha:
            if celula and ("R$" in str(celula) or re.search(r"\d+[,.]\d{2}", str(celula))):
                return True
    
    return False


def _extrair_observacao(texto: str) -> Optional[str]:
    """
    Extrai o campo observação (máscara do requisitante) do texto.
    
    Formato: Obs: "texto da máscara"
    
    Args:
        texto: Texto completo das páginas
        
    Returns:
        String com a observação ou None se não encontrar
    """
    padrao = r"[Oo]bs\s*:\s*[\"'](.+?)[\"']"
    match = re.search(padrao, texto, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    
    return None


def _verificar_ancoras_requisicao(texto_pagina: str, texto_anterior: str = "") -> bool:
    """
    Verifica se a página contém âncoras que indicam que é da requisição.
    
    Args:
        texto_pagina: Texto da página atual
        texto_anterior: Texto das páginas anteriores (para contexto)
        
    Returns:
        True se tem âncoras da requisição, False caso contrário
    """
    texto_completo = texto_anterior + "\n" + texto_pagina
    
    # Anti-âncoras (indicam que NÃO é da requisição)
    anti_ancoras = [
        r"EDITAL",
        r"TERMO\s+DE\s+REFER[ÊE]NCIA",
        r"ATA\s+DE\s+REGISTRO\s+DE\s+PRE[ÇC]OS",
        r"PREG[ÃA]O\s+ELETR[ÔO]NICO\s+N[°º]",
        r"PREGOEIRO",
        r"EQUIPE\s+DE\s+APOIO",
    ]
    
    # Verificar anti-âncoras primeiro
    contador_anti = 0
    for padrao in anti_ancoras:
        if re.search(padrao, texto_completo, re.IGNORECASE):
            contador_anti += 1
    
    # Se tem 2+ anti-âncoras, não é da requisição
    if contador_anti >= 2:
        return False
    
    # Se não tem anti-âncoras, assumir que pode ser da requisição
    # (será validado pelo mapeamento de colunas)
    return True


def extrair_itens(pdf_path: str) -> Dict[str, Any]:
    """
    Extrai itens da tabela de requisição de um PDF de processo requisitório.
    
    Localiza a tabela da requisição (não de outros documentos), extrai fornecedor,
    todos os itens, total e observação.
    
    Args:
        pdf_path: Caminho para o arquivo PDF
        
    Returns:
        Dict com os dados extraídos:
        {
            "fornecedor": str | None,
            "cnpj": str | None,
            "itens": List[Dict],
            "total": float | None,
            "total_calculado": float | None,
            "observacao": str | None,
            "paginas_processadas": List[int],
            "debug": str
        }
    """
    resultado = {
        "fornecedor": None,
        "cnpj": None,
        "itens": [],
        "total": None,
        "total_calculado": None,
        "observacao": None,
        "paginas_processadas": [],
        "debug": "",
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                resultado["debug"] = "PDF vazio ou sem páginas"
                return resultado
            
            # Coletar texto de todas as páginas para extrair fornecedor
            textos_paginas = []
            for pagina in pdf.pages:
                texto = pagina.extract_text()
                textos_paginas.append(texto or "")
            
            texto_completo = "\n".join(textos_paginas)
            
            # Extrair fornecedor e CNPJ
            fornecedor_info = _extrair_fornecedor(texto_completo)
            resultado["fornecedor"] = fornecedor_info.get("fornecedor")
            resultado["cnpj"] = fornecedor_info.get("cnpj")
            
            # Extrair observação
            resultado["observacao"] = _extrair_observacao(texto_completo)
            
            # Buscar tabela da requisição
            mapa_colunas = None
            texto_anterior = ""
            itens_encontrados = []
            total_encontrado = None
            paginas_processadas = []
            linha_cabecalho = 0  # Inicializar
            
            for num_pagina, pagina in enumerate(pdf.pages):
                texto_pagina = textos_paginas[num_pagina]
                
                # Extrair tabelas da página
                tabelas = pagina.extract_tables()
                
                if not tabelas:
                    texto_anterior += "\n" + texto_pagina
                    continue
                
                # Verificar se página tem anti-âncoras (não é da requisição)
                if not _verificar_ancoras_requisicao(texto_pagina, texto_anterior):
                    texto_anterior += "\n" + texto_pagina
                    continue
                
                for tabela in tabelas:
                    if not tabela or len(tabela) < 2:
                        continue
                    
                    # Tentar mapear colunas do cabeçalho
                    # Pode estar na primeira linha ou em uma linha posterior (se primeira linha é fornecedor)
                    if mapa_colunas is None:
                        # Tentar primeira linha
                        mapa = _mapear_colunas(tabela[0])
                        # Se não encontrou, tentar segunda linha
                        if not mapa and len(tabela) > 1:
                            mapa = _mapear_colunas(tabela[1])
                            linha_cabecalho = 1
                        else:
                            linha_cabecalho = 0
                        
                        if mapa:
                            mapa_colunas = mapa
                            paginas_processadas.append(num_pagina + 1)  # +1 porque páginas começam em 1
                        else:
                            continue
                    else:
                        # Verificar se é continuação
                        if not _detectar_tabela_sem_cabecalho(tabela, mapa_colunas):
                            continue
                        if num_pagina + 1 not in paginas_processadas:
                            paginas_processadas.append(num_pagina + 1)
                    
                    # Processar linhas de dados
                    # Pular linha do fornecedor (se existe) e cabeçalho
                    inicio_dados = linha_cabecalho + 1
                    item_atual = None  # Para juntar linhas de continuação
                    
                    for linha in tabela[inicio_dados:]:  # Pular fornecedor e cabeçalho
                        if not linha or len(linha) == 0:
                            continue
                        
                        # Verificar se é linha TOTAL
                        linha_texto = " ".join(str(c) for c in linha if c).upper()
                        if "TOTAL" in linha_texto:
                            # Extrair total
                            if mapa_colunas and "p_total" in mapa_colunas:
                                col_total = mapa_colunas["p_total"]
                                if col_total < len(linha) and linha[col_total]:
                                    total_encontrado = _parse_valor_br(str(linha[col_total]))
                            # Se não encontrou na coluna mapeada, tentar última coluna numérica
                            if total_encontrado is None:
                                for celula in reversed(linha):
                                    if celula:
                                        valor = _parse_valor_br(str(celula))
                                        if valor is not None and valor > 0:
                                            total_encontrado = valor
                                            break
                            item_atual = None  # Resetar item atual
                            continue
                        
                        # Verificar se é linha de dados (tem número na coluna ITEM)
                        if mapa_colunas and "item" in mapa_colunas:
                            col_item = mapa_colunas["item"]
                            tem_item_valido = False
                            
                            if col_item < len(linha) and linha[col_item]:
                                valor_item = str(linha[col_item]).strip()
                                if re.match(r"^\d{1,3}$", valor_item):
                                    tem_item_valido = True
                            
                            # Se não tem item válido, pode ser continuação de descrição
                            if not tem_item_valido:
                                # Verificar se é continuação: primeira coluna vazia E tem texto na descrição
                                if mapa_colunas and "descricao" in mapa_colunas:
                                    col_desc = mapa_colunas["descricao"]
                                    if (not linha[0] or str(linha[0]).strip() == "") and col_desc < len(linha) and linha[col_desc]:
                                        # É continuação → juntar ao item anterior
                                        if item_atual and "descricao" in item_atual:
                                            texto_continuacao = str(linha[col_desc]).strip()
                                            if texto_continuacao:
                                                texto_continuacao = re.sub(r"\s+", " ", texto_continuacao.replace("\n", " ")).strip()
                                                item_atual["descricao"] += " " + texto_continuacao
                                        continue
                                # Caso contrário, pular linha
                                continue
                        else:
                            continue
                        
                        # Extrair dados do item
                        item = {}
                        
                        # Item (número)
                        if "item" in mapa_colunas:
                            col = mapa_colunas["item"]
                            if col < len(linha) and linha[col]:
                                try:
                                    item["item"] = int(str(linha[col]).strip())
                                except ValueError:
                                    continue
                        
                        # CatServ
                        if "catserv" in mapa_colunas:
                            col = mapa_colunas["catserv"]
                            if col < len(linha) and linha[col]:
                                item["catserv"] = str(linha[col]).strip()
                            else:
                                item["catserv"] = None
                        else:
                            item["catserv"] = None
                        
                        # Descrição
                        if "descricao" in mapa_colunas:
                            col = mapa_colunas["descricao"]
                            if col < len(linha) and linha[col]:
                                desc = str(linha[col])
                                # Normalizar: substituir \n por espaço, colapsar espaços
                                desc = re.sub(r"\s+", " ", desc.replace("\n", " ")).strip()
                                item["descricao"] = desc
                            else:
                                item["descricao"] = ""
                        else:
                            item["descricao"] = ""
                        
                        # UND
                        if "und" in mapa_colunas:
                            col = mapa_colunas["und"]
                            if col < len(linha) and linha[col]:
                                item["und"] = str(linha[col]).strip()
                            else:
                                item["und"] = None
                        else:
                            item["und"] = None
                        
                        # QTD
                        if "qtd" in mapa_colunas:
                            col = mapa_colunas["qtd"]
                            if col < len(linha) and linha[col]:
                                item["qtd"] = _parse_qtd_br(str(linha[col]))
                            else:
                                item["qtd"] = None
                        else:
                            item["qtd"] = None
                        
                        # ND/SI
                        if "nd_si" in mapa_colunas:
                            col = mapa_colunas["nd_si"]
                            if col < len(linha) and linha[col]:
                                item["nd_si"] = _normalizar_nd_si(str(linha[col]))
                            else:
                                item["nd_si"] = None
                        else:
                            item["nd_si"] = None
                        
                        # P_UNIT
                        if "p_unit" in mapa_colunas:
                            col = mapa_colunas["p_unit"]
                            if col < len(linha) and linha[col]:
                                item["p_unit"] = _parse_valor_br(str(linha[col]))
                            else:
                                item["p_unit"] = None
                        else:
                            item["p_unit"] = None
                        
                        # P_TOTAL
                        if "p_total" in mapa_colunas:
                            col = mapa_colunas["p_total"]
                            if col < len(linha) and linha[col]:
                                item["p_total"] = _parse_valor_br(str(linha[col]))
                            else:
                                item["p_total"] = None
                        else:
                            item["p_total"] = None
                        
                        # Só adicionar se tem pelo menos item e descrição
                        if "item" in item and item.get("descricao"):
                            itens_encontrados.append(item)
                            item_atual = item  # Guardar para possível continuação
                
                texto_anterior += "\n" + texto_pagina
            
            # Calcular total dos itens
            total_calculado = sum(item.get("p_total", 0) or 0 for item in itens_encontrados)
            
            resultado["itens"] = itens_encontrados
            resultado["total"] = total_encontrado
            resultado["total_calculado"] = total_calculado if total_calculado > 0 else None
            resultado["paginas_processadas"] = paginas_processadas
            
            if not itens_encontrados:
                resultado["debug"] = "Nenhuma tabela de itens encontrada"
            else:
                resultado["debug"] = f"Encontrados {len(itens_encontrados)} itens em {len(paginas_processadas)} página(s)"
            
    except Exception as e:
        resultado["debug"] = f"Erro ao processar PDF: {str(e)}"
        print(f"[ITENS] ERRO ao processar {pdf_path}: {e}")
        import traceback
        traceback.print_exc()
    
    return resultado


# ── Testes Unitários ────────────────────────────────────────────────────────

def _testar_normalizar_nd_si():
    """
    Testa a função _normalizar_nd_si com todos os formatos conhecidos.
    """
    casos_teste = [
        ("33.90.30.34", "30.34"),
        ("33.90.39/17", "39.17"),
        ("33.90.39.17", "39.17"),
        ("30.24", "30.24"),
        ("30/04", "30.04"),
        ("39.17", "39.17"),
        ("33.01", "33.01"),
        ("4490.52.08", "52.08"),
        ("33.9\n0.39/\n24", "39.24"),  # Com quebras de linha
    ]
    
    print("[ITENS] Executando testes unitários de _normalizar_nd_si...")
    print("-" * 70)
    
    passou = 0
    falhou = 0
    
    for entrada, esperado in casos_teste:
        resultado = _normalizar_nd_si(entrada)
        if resultado == esperado:
            print(f"✅ {entrada} → {resultado}")
            passou += 1
        else:
            print(f"❌ {entrada} → {resultado} (esperado: {esperado})")
            falhou += 1
    
    print("-" * 70)
    print(f"Resultado: {passou} passou, {falhou} falhou")
    
    if falhou > 0:
        print("[ITENS] ⚠️  Alguns testes falharam.")
        return False
    
    print("[ITENS] ✅ Todos os testes passaram!")
    return True


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # Executar testes unitários primeiro
    print("[ITENS] Iniciando testes...\n")
    testes_ok = _testar_normalizar_nd_si()
    print()
    
    if not testes_ok:
        print("[ITENS] ⚠️  Testes unitários falharam. Continuando mesmo assim...\n")
    
    # Processar PDFs
    if len(sys.argv) > 1:
        # Processar arquivo específico
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists():
            print(f"[ITENS] ERRO: Arquivo não encontrado: {pdf_path}")
            sys.exit(1)
        
        pdfs = [pdf_path]
    else:
        # Processar todos os PDFs em tests/
        tests_dir = Path(__file__).parent.parent / "tests"
        pdfs = list(tests_dir.glob("*.pdf"))
        
        if not pdfs:
            print(f"[ITENS] ERRO: Nenhum PDF encontrado em {tests_dir}")
            sys.exit(1)
        
        print(f"[ITENS] Encontrados {len(pdfs)} PDF(s) em tests/\n")
    
    # Processar cada PDF
    resultados = []
    processos_com_itens = 0
    
    for pdf_path in sorted(pdfs):
        print("═" * 70)
        print(f"    ITENS: {pdf_path.name}")
        print("═" * 70)
        
        resultado = extrair_itens(str(pdf_path))
        
        if resultado.get("debug") and "ERRO" in resultado["debug"].upper():
            print(f"ERRO: {resultado['debug']}")
        else:
            # Fornecedor
            fornecedor = resultado.get("fornecedor") or "—"
            cnpj = resultado.get("cnpj") or "—"
            print(f"Fornecedor: {fornecedor}")
            print(f"CNPJ:       {cnpj}")
            print("-" * 70)
            
            # Itens
            itens = resultado.get("itens", [])
            if itens:
                processos_com_itens += 1
                
                # Cabeçalho da tabela
                print("Item | CatServ | Descrição (40 chars)         | UND   | QTD   | ND/SI | P.Unit    | P.Total")
                print("-" * 70)
                
                # Linhas de itens
                for item in itens:
                    item_num = str(item.get("item", ""))
                    catserv = str(item.get("catserv", ""))[:10]
                    desc = (item.get("descricao", "")[:40] + ".." if len(item.get("descricao", "")) > 40 else item.get("descricao", ""))
                    und = str(item.get("und", ""))[:5]
                    qtd = f"{item.get('qtd', 0):.2f}" if item.get("qtd") else ""
                    nd_si = str(item.get("nd_si", ""))[:6]
                    p_unit = f"R$ {item.get('p_unit', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if item.get("p_unit") else ""
                    p_total = f"R$ {item.get('p_total', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if item.get("p_total") else ""
                    
                    print(f"{item_num:4} | {catserv:7} | {desc:40} | {und:5} | {qtd:5} | {nd_si:6} | {p_unit:10} | {p_total}")
                
                print("-" * 70)
                
                # Total
                total = resultado.get("total")
                total_calc = resultado.get("total_calculado")
                
                if total:
                    total_fmt = f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    print(f"TOTAL extraído:   {total_fmt}")
                else:
                    print("TOTAL extraído:   —")
                
                if total_calc:
                    total_calc_fmt = f"R$ {total_calc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if total and abs(total - total_calc) < 0.01:
                        print(f"TOTAL calculado:  {total_calc_fmt}  ✅")
                    else:
                        print(f"TOTAL calculado:  {total_calc_fmt}")
                else:
                    print("TOTAL calculado:  —")
                
                # Observação
                obs = resultado.get("observacao")
                if obs:
                    print(f"Obs: {obs[:80]}..." if len(obs) > 80 else f"Obs: {obs}")
                else:
                    print("Obs: (não encontrada)")
                
                # Páginas
                paginas = resultado.get("paginas_processadas", [])
                print(f"Páginas: {paginas}")
            else:
                print("Nenhum item encontrado")
                print(f"Debug: {resultado.get('debug', '—')}")
        
        print("═" * 70)
        print()
    
    # Resumo final
    print("═" * 70)
    print(f"RESUMO: {processos_com_itens}/{len(pdfs)} processos com itens extraídos")
    print("═" * 70)

