"""
Módulo independente para extração de itens da tabela de requisição usando OCR.

Este módulo é o FALLBACK quando extrator_itens.py retorna 0 itens porque a tabela
está em formato de IMAGEM (não texto nativo).

Usa abordagem de 3 fases:
1. VISÃO: Detecção de grade com OpenCV
2. LEITURA: OCR célula a célula com Tesseract
3. LÓGICA: Mapeamento de colunas e normalização (mesma lógica do extrator_itens.py)

Este módulo é 100% independente e não importa nada de outros módulos do projeto.
"""

import re
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# Imports opcionais (graceful degradation se não instalados)
try:
    import cv2
    import numpy as np
except ImportError:
    print("[OCR] AVISO: OpenCV/numpy não está instalado. Execute: pip install opencv-python numpy")
    cv2 = None
    np = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("[OCR] AVISO: pytesseract/PIL não está instalado. Execute: pip install pytesseract pillow")
    pytesseract = None
    Image = None

try:
    import fitz  # PyMuPDF
except ImportError:
    print("[OCR] AVISO: PyMuPDF não está instalado. Execute: pip install PyMuPDF")
    fitz = None

try:
    import pdfplumber
except ImportError:
    print("[OCR] AVISO: pdfplumber não está instalado. Execute: pip install pdfplumber")
    pdfplumber = None


# ── Correções de OCR Comuns ────────────────────────────────────────────────────

CORRECOES_OCR = {
    "ÍTEM": "ITEM",       # acento incorreto
    "l": "1",             # L minúsculo → 1 (em contexto numérico)
    "O": "0",             # O maiúsculo → 0 (em contexto numérico)
    "S": "5",             # S → 5 (em contexto numérico)
    "R5": "R$",           # 5 confundido com $
    "RS": "R$",           # S confundido com $
    "R ": "R$ ",          # R sem cifrão
}


# ── Funções de Normalização (cópias do extrator_itens.py) ─────────────────────

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


def _corrigir_ocr(texto: str, contexto: str = "texto") -> str:
    """
    Aplica correções de OCR comuns.
    
    Args:
        texto: Texto bruto do OCR
        contexto: "numero" (corrige l→1, O→0), "texto" (não corrige), "valor" (corrige S→$)
        
    Returns:
        Texto corrigido
    """
    if not texto:
        return ""
    
    # Correções universais
    texto = texto.replace("ÍTEM", "ITEM")
    
    # Correções por contexto
    if contexto == "numero":
        # Em contexto numérico: l→1, O→0, S→5
        texto = re.sub(r"\bl\b", "1", texto)  # l isolado → 1
        texto = re.sub(r"\bO\b", "0", texto)  # O isolado → 0
        texto = re.sub(r"\bS\b", "5", texto)  # S isolado → 5
    elif contexto == "valor":
        # Em contexto de valor: R5→R$, RS→R$
        texto = texto.replace("R5", "R$")
        texto = texto.replace("RS", "R$")
        texto = texto.replace("R ", "R$ ")
    
    return texto


# ── FASE 1: VISÃO — Detecção de Grade ──────────────────────────────────────────

def _localizar_regiao_tabela(pdf_path: str, page_num: int, img: np.ndarray, dpi: int = 300, debug: bool = False) -> Tuple[int, int]:
    """
    Localiza a região da tabela de itens na página usando âncoras textuais.
    
    Busca o texto "Material" + "adquirido/contratado" para encontrar o topo da tabela.
    Usa PyMuPDF para extrair texto com posições e converte coordenadas PDF → pixels.
    
    Args:
        pdf_path: Caminho do PDF
        page_num: Número da página (0-indexed)
        img: Imagem renderizada (para obter dimensões)
        dpi: DPI usado na renderização (padrão 300)
        debug: Se True, imprime informações de debug
        
    Returns:
        Tuple (y_topo, y_fundo) em pixels da imagem.
        Se não encontrar âncora, retorna fallback (35% da altura, 95% da altura).
    """
    if fitz is None:
        altura_img = img.shape[0]
        y_topo_fallback = int(altura_img * 0.35)
        y_fundo_fallback = int(altura_img * 0.95)
        if debug:
            print(f"[OCR-DEBUG] PyMuPDF não disponível, usando fallback: Y={y_topo_fallback}-{y_fundo_fallback}")
        return (y_topo_fallback, y_fundo_fallback)
    
    try:
        altura_img, largura_img = img.shape[:2]
        
        # Abrir PDF e extrair texto com posições
        doc = fitz.open(pdf_path)
        if page_num >= len(doc):
            doc.close()
            altura_img = img.shape[0]
            return (int(altura_img * 0.35), int(altura_img * 0.95))
        
        page = doc[page_num]
        
        # Extrair texto com posições (formato dict)
        texto_dict = page.get_text("dict")
        doc.close()
        
        # Fator de conversão: coordenadas PDF (pontos) → pixels
        # PDF usa pontos (1 ponto = 1/72 polegada)
        # Imagem renderizada: 1 pixel = 1/DPI polegada
        fator_conversao = dpi / 72.0
        
        # Buscar âncora: "Material" + ("adquirido" ou "contratado")
        padrao_ancora = re.compile(r"[Mm]aterial.*?(?:adquirido|contratado)", re.IGNORECASE)
        y_topo = None
        texto_ancora_encontrado = None
        
        # Percorrer blocos de texto
        if "blocks" in texto_dict:
            for block in texto_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        if "spans" in line:
                            texto_linha = " ".join(span.get("text", "") for span in line["spans"])
                            
                            # Verificar se contém a âncora
                            if padrao_ancora.search(texto_linha):
                                # Obter coordenada Y do bloco (bbox)
                                bbox = line.get("bbox", [0, 0, 0, 0])
                                y_pdf = bbox[3]  # y1 (coordenada inferior do texto no PDF)
                                
                                # Converter para pixels
                                # PDF: origem no canto inferior esquerdo (Y cresce para cima)
                                # Imagem: origem no canto superior esquerdo (Y cresce para baixo)
                                # Converter: y_imagem = altura_pdf - y_pdf
                                altura_pagina_pdf = page.rect.height
                                y_pdf_invertido = altura_pagina_pdf - y_pdf
                                
                                # Converter pontos PDF para pixels da imagem
                                # A imagem foi renderizada com DPI, então altura_img = altura_pdf * (dpi/72)
                                y_topo = int(y_pdf_invertido * fator_conversao) + 30  # +30 pixels de margem
                                texto_ancora_encontrado = texto_linha.strip()
                                break
                
                if y_topo is not None:
                    break
        
        # Se não encontrou âncora, usar fallback
        if y_topo is None:
            y_topo_fallback = int(altura_img * 0.35)
            y_fundo_fallback = int(altura_img * 0.95)
            if debug:
                print(f"[OCR-DEBUG] Âncora não encontrada, usando fallback: Y={y_topo_fallback}-{y_fundo_fallback}")
            return (y_topo_fallback, y_fundo_fallback)
        
        if debug:
            print(f"[OCR-DEBUG] Âncora encontrada: '{texto_ancora_encontrado}' em Y={y_topo}px")
        
        # Buscar âncora de fim (próximo texto abaixo)
        # Procurar por: "Obs:", "18º", assinatura, ou usar 95% da altura
        padroes_fim = [
            re.compile(r"Obs\s*:", re.IGNORECASE),
            re.compile(r"18[°º]\s*B\s*Trnp", re.IGNORECASE),
            re.compile(r"Assinatura", re.IGNORECASE),
        ]
        
        y_fundo = None
        
        if "blocks" in texto_dict:
            for block in texto_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        if "spans" in line:
                            texto_linha = " ".join(span.get("text", "") for span in line["spans"])
                            
                            # Verificar se contém padrão de fim
                            for padrao in padroes_fim:
                                if padrao.search(texto_linha):
                                    bbox = line.get("bbox", [0, 0, 0, 0])
                                    y_pdf = bbox[1]  # y0 (coordenada superior do texto)
                                    
                                    # Converter para pixels
                                    y_pdf_invertido = altura_pagina_pdf - y_pdf
                                    y_fundo = int(y_pdf_invertido * fator_conversao)
                                    
                                    if y_fundo > y_topo:  # Deve estar abaixo da âncora
                                        if debug:
                                            print(f"[OCR-DEBUG] Âncora de fim encontrada: '{texto_linha.strip()}' em Y={y_fundo}px")
                                        break
                            
                            if y_fundo is not None:
                                break
                
                if y_fundo is not None:
                    break
        
        # Se não encontrou âncora de fim, usar 95% da altura
        if y_fundo is None or y_fundo <= y_topo:
            y_fundo = int(altura_img * 0.95)
            if debug:
                print(f"[OCR-DEBUG] Âncora de fim não encontrada, usando 95% da altura: Y={y_fundo}px")
        
        # Garantir limites válidos
        y_topo = max(0, min(y_topo, altura_img - 100))
        y_fundo = max(y_topo + 100, min(y_fundo, altura_img))
        
        if debug:
            print(f"[OCR-DEBUG] Região da tabela: Y={y_topo}-{y_fundo}px (altura={y_fundo-y_topo}px)")
        
        return (y_topo, y_fundo)
    
    except Exception as e:
        print(f"[OCR] ERRO ao localizar região da tabela: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        
        # Fallback em caso de erro
        altura_img = img.shape[0]
        return (int(altura_img * 0.35), int(altura_img * 0.95))


def _renderizar_pagina(pdf_path: str, page_num: int, dpi: int = 300) -> Optional[np.ndarray]:
    """
    Renderiza página do PDF como imagem em alta resolução.
    
    Args:
        pdf_path: Caminho do PDF
        page_num: Número da página (0-indexed)
        dpi: Resolução (padrão 300)
        
    Returns:
        Numpy array (imagem BGR) ou None se erro
    """
    if fitz is None:
        return None
    
    try:
        doc = fitz.open(pdf_path)
        if page_num >= len(doc):
            doc.close()
            return None
        
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        
        # Converter para numpy array
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        # Se é RGBA, converter para BGR
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 1:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        doc.close()
        return img
    except Exception as e:
        print(f"[OCR] ERRO ao renderizar página {page_num}: {e}")
        return None


def _detectar_grade(img: np.ndarray, debug: bool = False, debug_dir: Optional[Path] = None, page_num: int = 0) -> List[List[Tuple[int, int, int, int]]]:
    """
    Detecta células da tabela na imagem usando OpenCV.
    
    Implementa Fase 1 completa: binarização, kernels, contornos, ordenação.
    
    Args:
        img: Imagem BGR (numpy array)
        debug: Se True, imprime informações detalhadas e salva imagens de debug
        debug_dir: Diretório para salvar imagens de debug
        page_num: Número da página (para nomear arquivos de debug)
        
    Returns:
        Lista de linhas, cada linha é lista de (x, y, w, h) das células
        Lista vazia se não encontrar grade
    """
    if cv2 is None or np is None:
        return []
    
    try:
        altura, largura = img.shape[:2]
        area_maxima = int(altura * largura * 0.5)  # 50% da imagem (corrigido)
        
        if debug:
            print(f"[OCR-DEBUG] FASE 1 (VISÃO): Dimensões da imagem: {largura}x{altura}")
        
        # Converter para escala de cinza
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Aplicar filtro de mediana para reduzir ruído
        gray = cv2.medianBlur(gray, 3)
        
        # Binarização invertida com Otsu (corrigido)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Salvar imagem binarizada se debug
        if debug and debug_dir:
            cv2.imwrite(str(debug_dir / f"debug_binary_p{page_num+1}.png"), binary)
        
        # Tamanho dos kernels com limites (corrigido)
        kernel_h_size = max(40, min(largura // 30, 100))
        kernel_v_size = max(40, min(altura // 30, 100))
        
        if debug:
            print(f"[OCR-DEBUG] Kernel horizontal: {kernel_h_size}, vertical: {kernel_v_size}")
        
        # Isolar linhas horizontais
        kernel_h = np.ones((1, kernel_h_size), np.uint8)
        horizontal = cv2.erode(binary, kernel_h, iterations=1)
        horizontal = cv2.dilate(horizontal, kernel_h, iterations=1)
        
        # Salvar linhas horizontais se debug
        if debug and debug_dir:
            cv2.imwrite(str(debug_dir / f"debug_horizontal_p{page_num+1}.png"), horizontal)
        
        # Isolar linhas verticais
        kernel_v = np.ones((kernel_v_size, 1), np.uint8)
        vertical = cv2.erode(binary, kernel_v, iterations=1)
        vertical = cv2.dilate(vertical, kernel_v, iterations=1)
        
        # Salvar linhas verticais se debug
        if debug and debug_dir:
            cv2.imwrite(str(debug_dir / f"debug_vertical_p{page_num+1}.png"), vertical)
        
        # Fusão: grade completa
        grade = cv2.add(horizontal, vertical)
        
        # Salvar grade fusionada se debug
        if debug and debug_dir:
            cv2.imwrite(str(debug_dir / f"debug_grade_p{page_num+1}.png"), grade)
        
        # Encontrar contornos (células)
        contornos, _ = cv2.findContours(grade, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        if debug:
            print(f"[OCR-DEBUG] Contornos encontrados antes do filtro: {len(contornos)}")
        
        # Extrair bounding boxes das células
        celulas = []
        for c in contornos:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            
            # Filtrar: área mínima 1000 pixels², máxima 50% da imagem, aspect ratio válido (corrigido)
            if w > 20 and h > 15 and area > 1000 and area < area_maxima:
                celulas.append((x, y, w, h))
        
        if debug:
            print(f"[OCR-DEBUG] Células após filtro: {len(celulas)}")
        
        if not celulas:
            # FALLBACK 1: Tentar com threshold adaptativo
            if debug:
                print(f"[OCR-DEBUG] Nenhuma célula encontrada, tentando threshold adaptativo...")
            
            binary_adapt = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY_INV, 15, 10
            )
            
            # Tentar novamente com kernels menores (metade)
            kernel_h_size_fallback = max(20, kernel_h_size // 2)
            kernel_v_size_fallback = max(20, kernel_v_size // 2)
            
            kernel_h_fallback = np.ones((1, kernel_h_size_fallback), np.uint8)
            horizontal_fallback = cv2.erode(binary_adapt, kernel_h_fallback, iterations=1)
            horizontal_fallback = cv2.dilate(horizontal_fallback, kernel_h_fallback, iterations=1)
            
            kernel_v_fallback = np.ones((kernel_v_size_fallback, 1), np.uint8)
            vertical_fallback = cv2.erode(binary_adapt, kernel_v_fallback, iterations=1)
            vertical_fallback = cv2.dilate(vertical_fallback, kernel_v_fallback, iterations=1)
            
            grade_fallback = cv2.add(horizontal_fallback, vertical_fallback)
            contornos_fallback, _ = cv2.findContours(grade_fallback, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            if debug:
                print(f"[OCR-DEBUG] Contornos com threshold adaptativo: {len(contornos_fallback)}")
            
            celulas_fallback = []
            for c in contornos_fallback:
                x, y, w, h = cv2.boundingRect(c)
                area = w * h
                if w > 20 and h > 15 and area > 1000 and area < area_maxima:
                    celulas_fallback.append((x, y, w, h))
            
            if celulas_fallback:
                if debug:
                    print(f"[OCR-DEBUG] Células encontradas com fallback: {len(celulas_fallback)}")
                celulas = celulas_fallback
            else:
                if debug:
                    print(f"[OCR-DEBUG] FALLBACK também falhou, retornando lista vazia")
                return []
        
        # Calcular tolerância proporcionalmente (corrigido)
        altura_media = sum(h for _, _, _, h in celulas) / len(celulas)
        tolerancia_y = max(15, int(altura_media // 3))
        
        if debug:
            print(f"[OCR-DEBUG] Altura média das células: {altura_media:.1f}, tolerância Y: {tolerancia_y}")
        
        # Ordenar células em grade
        linhas_ordenadas = _ordenar_celulas_em_grade(celulas, tolerancia_y=tolerancia_y)
        
        if debug:
            print(f"[OCR-DEBUG] Linhas na grade ordenada: {len(linhas_ordenadas)}")
            
            # Salvar imagem com contornos desenhados se debug
            if debug_dir:
                img_contornos = img.copy()
                for linha in linhas_ordenadas:
                    for x, y, w, h in linha:
                        cv2.rectangle(img_contornos, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.imwrite(str(debug_dir / f"debug_contornos_p{page_num+1}.png"), img_contornos)
        
        return linhas_ordenadas
    
    except Exception as e:
        print(f"[OCR] ERRO na detecção de grade: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return []


def _ordenar_celulas_em_grade(celulas: List[Tuple[int, int, int, int]], tolerancia_y: int = 15) -> List[List[Tuple[int, int, int, int]]]:
    """
    Ordena células: primeiro por linha (Y), depois por coluna (X).
    
    Args:
        celulas: Lista de (x, y, w, h)
        tolerancia_y: Pixels de diferença para considerar mesma linha
        
    Returns:
        Lista de linhas, cada linha é lista de células ordenadas por X
    """
    if not celulas:
        return []
    
    # Ordenar por Y primeiro
    celulas_ordenadas = sorted(celulas, key=lambda c: c[1])
    
    # Agrupar por linhas (Y similar)
    linhas = []
    linha_atual = [celulas_ordenadas[0]]
    
    for celula in celulas_ordenadas[1:]:
        y_atual = linha_atual[0][1]
        y_nova = celula[1]
        
        if abs(y_nova - y_atual) <= tolerancia_y:
            linha_atual.append(celula)
        else:
            # Finalizar linha atual (ordenar por X)
            linhas.append(sorted(linha_atual, key=lambda c: c[0]))
            linha_atual = [celula]
    
    # Adicionar última linha
    linhas.append(sorted(linha_atual, key=lambda c: c[0]))
    
    return linhas


# ── FASE 2: LEITURA — OCR Célula a Célula ─────────────────────────────────────

def _ocr_celula(img: np.ndarray, bbox: Tuple[int, int, int, int], tipo: str = "texto") -> str:
    """
    Extrai texto de uma célula usando Tesseract OCR.
    
    Args:
        img: Imagem original (BGR)
        bbox: (x, y, w, h) da célula
        tipo: "numero", "texto", "valor" (afeta configuração do Tesseract)
        
    Returns:
        Texto extraído (limpo)
    """
    if pytesseract is None or Image is None:
        return ""
    
    try:
        x, y, w, h = bbox
        
        # Recortar célula da imagem original
        celula_img = img[y:y+h, x:x+w]
        
        if celula_img.size == 0:
            return ""
        
        # Converter para escala de cinza
        if len(celula_img.shape) == 3:
            celula_gray = cv2.cvtColor(celula_img, cv2.COLOR_BGR2GRAY)
        else:
            celula_gray = celula_img
        
        # Binarização Otsu (melhor para OCR)
        _, celula_bin = cv2.threshold(celula_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Converter para PIL Image
        pil_img = Image.fromarray(celula_bin)
        
        # Configuração do Tesseract por tipo
        if tipo == "numero":
            # Números: linha única, whitelist de dígitos
            config = '--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789.,/'
        elif tipo == "valor":
            # Valores monetários: linha única, whitelist incluindo R$
            config = '--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789.,/R$ '
        else:
            # Texto: bloco de texto
            config = '--psm 6 --oem 3'
        
        # Fallback de lang (corrigido)
        try:
            langs = pytesseract.get_languages()
            lang = 'por' if 'por' in langs else 'eng'
        except:
            lang = 'eng'
        
        # OCR
        texto = pytesseract.image_to_string(pil_img, lang=lang, config=config).strip()
        
        # Aplicar correções de OCR
        texto = _corrigir_ocr(texto, contexto=tipo)
        
        return texto
    
    except Exception as e:
        print(f"[OCR] ERRO no OCR da célula: {e}")
        return ""


# ── FASE 3: LÓGICA — Mapeamento e Normalização ────────────────────────────────

def _mapear_colunas_ocr(cabecalho: List[str], grade_texto: Optional[List[List[str]]] = None) -> Optional[Dict[str, int]]:
    """
    Mapeia colunas do cabeçalho para campos padronizados.
    
    Mesma lógica do extrator_itens.py, com tolerância a erros de OCR e fallback por posição.
    
    Args:
        cabecalho: Lista de strings (primeira linha da tabela)
        grade_texto: Grade completa de texto (para fallback por posição)
        
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
        
        # Aplicar correções de OCR no cabeçalho
        normalizado = _corrigir_ocr(normalizado, contexto="texto")
        
        # Verificar se é coluna a ignorar
        if "JUSTIFICATIVA" in normalizado or "MOTIVO" in normalizado:
            colunas_ignorar.append(i)
            continue
        
        # Mapear por keywords (tolerante a erros de OCR) - flexibilizado
        if ("ITEM" in normalizado or "ÍTEM" in normalizado) and "item" not in mapa:
            mapa["item"] = i
        elif ("CAT" in normalizado or "CATMAT" in normalizado or "CATSERV" in normalizado) and "catserv" not in mapa:
            mapa["catserv"] = i
        elif "DESCRI" in normalizado and "descricao" not in mapa:
            mapa["descricao"] = i
        elif ("UND" in normalizado or "FORN" in normalizado or "FORN" in normalizado) and "und" not in mapa:
            mapa["und"] = i
        elif ("QTD" in normalizado or "QUANTIDADE" in normalizado or "QUANT" in normalizado) and "qtd" not in mapa:
            mapa["qtd"] = i
        elif ("ND" in normalizado or "S.I." in normalizado or "SI" in normalizado or "S I" in normalizado) and "nd_si" not in mapa:
            # Não confundir com "UND"
            if "UND" not in normalizado:
                mapa["nd_si"] = i
        elif ("UNT" in normalizado or "UNIT" in normalizado or ("VALOR" in normalizado and "UNT" in normalizado)) and "p_unit" not in mapa:
            mapa["p_unit"] = i
        elif (("TOTAL" in normalizado or "GLOBAL" in normalizado) or ("VALOR" in normalizado and ("TOTAL" in normalizado or "GLOBAL" in normalizado))) and "p_total" not in mapa:
            mapa["p_total"] = i
    
    # Se encontrou colunas com "R$", mapear como P_UNIT e P_TOTAL
    colunas_r = []
    for i, celula in enumerate(cabecalho):
        if celula:
            celula_upper = str(celula).upper()
            if "R$" in celula_upper or "R5" in celula_upper or "RS" in celula_upper:
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
    
    # FALLBACK: Mapeamento por posição (se não reconheceu pelo menos 4 colunas)
    if len(mapa) < 4 and grade_texto and len(grade_texto) > 1:
        return _mapear_colunas_por_posicao(cabecalho, grade_texto)
    
    return None


def _mapear_colunas_por_posicao(cabecalho: List[str], grade_texto: List[List[str]]) -> Optional[Dict[str, int]]:
    """
    Mapeia colunas por posição quando o mapeamento por keywords falha.
    
    Args:
        cabecalho: Lista de strings do cabeçalho
        grade_texto: Grade completa (para analisar dados)
        
    Returns:
        Dict mapeando nome_campo -> indice_coluna, ou None se não conseguir
    """
    if len(grade_texto) < 2:
        return None
    
    mapa = {}
    num_colunas = len(cabecalho)
    
    # Analisar primeira linha de dados para identificar tipos
    primeira_linha = grade_texto[1] if len(grade_texto) > 1 else []
    
    # Coluna 0 ou 1 → item (a que tiver números pequenos 1-999)
    for i in range(min(2, num_colunas)):
        if i < len(primeira_linha):
            valor = str(primeira_linha[i]).strip()
            if re.match(r"^\d{1,3}$", valor):
                mapa["item"] = i
                break
    
    # Coluna com números de 3-6 dígitos → catserv
    for i in range(num_colunas):
        if i < len(primeira_linha):
            valor = str(primeira_linha[i]).strip()
            if re.match(r"^\d{3,6}$", valor):
                mapa["catserv"] = i
                break
    
    # Coluna mais larga (texto longo) → descricao
    larguras = [len(str(c)) for c in cabecalho]
    if larguras:
        idx_desc = larguras.index(max(larguras))
        mapa["descricao"] = idx_desc
    
    # Coluna com "UND", "und", "Sv", "KG" → und
    for i, celula in enumerate(cabecalho):
        if celula:
            celula_upper = str(celula).upper()
            if any(x in celula_upper for x in ["UND", "SV", "KG", "FORN"]):
                mapa["und"] = i
                break
    
    # Penúltima coluna numérica → p_unit
    # Última coluna numérica → p_total
    colunas_numericas = []
    for i in range(num_colunas):
        if i < len(primeira_linha):
            valor = str(primeira_linha[i]).strip()
            if re.search(r"[\d,\.]", valor) and ("R$" in valor or re.search(r"\d+[,\.]\d{2}", valor)):
                colunas_numericas.append(i)
    
    if len(colunas_numericas) >= 2:
        mapa["p_unit"] = colunas_numericas[-2]
        mapa["p_total"] = colunas_numericas[-1]
    elif len(colunas_numericas) == 1:
        mapa["p_total"] = colunas_numericas[0]
    
    # Verificar se mapeou pelo menos item e descrição
    if "item" in mapa and "descricao" in mapa:
        return mapa
    
    return None


def _extrair_fornecedor_ocr(texto_paginas: str) -> Dict[str, Optional[str]]:
    """
    Extrai nome e CNPJ do fornecedor do texto (mesma lógica do extrator_itens.py).
    
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
    
    # Buscar contexto ao redor do CNPJ (200 caracteres antes e depois)
    inicio = max(0, match_cnpj.start() - 200)
    fim = min(len(texto_paginas), match_cnpj.end() + 200)
    contexto = texto_paginas[inicio:fim]
    
    # Formato 1: "Nome da Empresa: ... CNPJ: ..."
    match = re.search(r"Nome\s+da\s+Empresa\s*:\s*(.+?)(?:\s+CNPJ\s*:|$)", contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
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
    
    # Formato 4: "Nome – CNPJ: ..."
    match = re.search(r"(.+?)\s*[-–]\s*CNPJ\s*:\s*" + padrao_cnpj, contexto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        nome = re.sub(r"^(Nome\s+da\s+Empresa|Empresa)\s*:\s*", "", nome, flags=re.IGNORECASE)
        resultado["fornecedor"] = nome
        return resultado
    
    # Formato 5: Buscar linha que contém CNPJ
    linhas = contexto.split("\n")
    for linha in linhas:
        if cnpj in linha:
            nome = re.sub(padrao_cnpj, "", linha).strip()
            nome = re.sub(r"^(Nome\s+da\s+Empresa|Empresa|CNPJ|CPF\s*/\s*CNPJ)\s*:?\s*", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r"[-–]\s*$", "", nome).strip()
            nome = re.sub(r",\s*destinada.*$", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r",\s*CNPJ.*$", "", nome, flags=re.IGNORECASE)
            nome = nome.strip()
            if nome and len(nome) > 3 and not nome.startswith(","):
                resultado["fornecedor"] = nome
                return resultado
    
    return resultado


def _pagina_eh_imagem(page, texto: str) -> bool:
    """
    Verifica se a página tem tabela em formato de imagem.
    
    Args:
        page: Objeto página do pdfplumber
        texto: Texto extraído da página
        
    Returns:
        True se parece ser imagem, False caso contrário
    """
    # Se tem pouco texto (<50 caracteres) → provavelmente é imagem
    if len(texto.strip()) < 50:
        return True
    
    # Verificar se tem imagens grandes na página
    if hasattr(page, 'images') and page.images:
        altura_pagina = page.height
        largura_pagina = page.width
        area_pagina = altura_pagina * largura_pagina
        
        for img in page.images:
            # Calcular área da imagem
            if 'width' in img and 'height' in img:
                area_img = img['width'] * img['height']
                # Se imagem ocupa >50% da página → é imagem
                if area_img > area_pagina * 0.5:
                    return True
    
    return False


# ── Função Principal ───────────────────────────────────────────────────────────

def extrair_itens_ocr(pdf_path: str, debug: bool = False) -> Dict[str, Any]:
    """
    Extrai itens da tabela de requisição usando OCR (quando tabela está em imagem).
    
    Implementa as 3 fases: Visão (OpenCV), Leitura (Tesseract), Lógica (mapeamento).
    
    Args:
        pdf_path: Caminho para o arquivo PDF
        
    Returns:
        Dict com os dados extraídos (formato idêntico ao extrator_itens.py):
        {
            "fornecedor": str | None,
            "cnpj": str | None,
            "itens": List[Dict],
            "total": float | None,
            "total_calculado": float | None,
            "observacao": str | None,
            "paginas_processadas": List[int],
            "metodo": "ocr",
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
        "metodo": "ocr",
        "debug": "",
    }
    
    # Verificar dependências
    if cv2 is None or np is None:
        resultado["debug"] = "OpenCV/numpy não instalado"
        return resultado
    
    if pytesseract is None or Image is None:
        resultado["debug"] = "pytesseract/PIL não instalado"
        return resultado
    
    if fitz is None:
        resultado["debug"] = "PyMuPDF não instalado"
        return resultado
    
    if pdfplumber is None:
        resultado["debug"] = "pdfplumber não instalado"
        return resultado
    
    try:
        # Abrir PDF com pdfplumber para detectar páginas de imagem
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                resultado["debug"] = "PDF vazio ou sem páginas"
                return resultado
            
            # Coletar texto de todas as páginas (para fornecedor)
            textos_paginas = []
            paginas_imagem = []
            
            for num_pagina, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text() or ""
                textos_paginas.append(texto)
                
                # Detectar se é página de imagem
                if _pagina_eh_imagem(pagina, texto):
                    paginas_imagem.append(num_pagina)
            
            texto_completo = "\n".join(textos_paginas)
            
            # Extrair fornecedor e CNPJ do texto
            fornecedor_info = _extrair_fornecedor_ocr(texto_completo)
            resultado["fornecedor"] = fornecedor_info.get("fornecedor")
            resultado["cnpj"] = fornecedor_info.get("cnpj")
            
            # Se não encontrou páginas de imagem, retornar vazio
            if not paginas_imagem:
                resultado["debug"] = "Nenhuma página de imagem detectada"
                return resultado
            
            print(f"[OCR] Páginas de imagem detectadas: {[p+1 for p in paginas_imagem]}")
            
            # Criar diretório de debug se necessário
            debug_dir = None
            if debug:
                debug_dir = Path(__file__).parent.parent / "tests" / "debug_ocr"
                debug_dir.mkdir(parents=True, exist_ok=True)
                print(f"[OCR-DEBUG] Modo debug ativado. Imagens salvas em: {debug_dir}")
            
            # Processar cada página de imagem
            mapa_colunas = None
            itens_encontrados = []
            total_encontrado = None
            paginas_processadas = []
            linha_cabecalho = 0
            
            for num_pagina in paginas_imagem:
                try:
                    if debug:
                        print(f"\n[OCR-DEBUG] === Processando página {num_pagina+1} ===")
                    
                    # Renderizar página como imagem
                    img = _renderizar_pagina(pdf_path, num_pagina, dpi=300)
                    if img is None:
                        if debug:
                            print(f"[OCR-DEBUG] ERRO: Não foi possível renderizar página {num_pagina+1}")
                        continue
                    
                    # LOCALIZAR REGIÃO DA TABELA usando âncoras textuais
                    y_topo, y_fundo = _localizar_regiao_tabela(pdf_path, num_pagina, img, dpi=300, debug=debug)
                    
                    # Recortar imagem para a região da tabela
                    img_recortada = img[y_topo:y_fundo, :]
                    
                    if debug:
                        print(f"[OCR-DEBUG] Imagem recortada: {img_recortada.shape[1]}x{img_recortada.shape[0]} pixels")
                        
                        # Salvar imagens de debug da região
                        if debug_dir:
                            # Imagem original com retângulo marcando a região
                            img_regiao = img.copy()
                            cv2.rectangle(img_regiao, (0, y_topo), (img.shape[1], y_fundo), (0, 0, 255), 3)
                            cv2.imwrite(str(debug_dir / f"debug_regiao_p{num_pagina+1}.png"), img_regiao)
                            
                            # Imagem recortada (região da tabela)
                            cv2.imwrite(str(debug_dir / f"debug_recorte_p{num_pagina+1}.png"), img_recortada)
                    
                    # FASE 1: Detectar grade na imagem RECORTADA
                    linhas_celulas = _detectar_grade(img_recortada, debug=debug, debug_dir=debug_dir, page_num=num_pagina)
                    
                    if not linhas_celulas:
                        # Fallback: tentar OCR na região recortada inteira (sem segmentação)
                        print(f"[OCR] Grade não detectada na página {num_pagina+1}, tentando OCR na região recortada...")
                        if debug:
                            print(f"[OCR-DEBUG] FASE 1 FALHOU: Nenhuma célula detectada, aplicando OCR completo na região")
                        
                        # Aplicar OCR com --psm 6 na região recortada inteira
                        if pytesseract and Image:
                            try:
                                gray_recorte = cv2.cvtColor(img_recortada, cv2.COLOR_BGR2GRAY)
                                _, bin_recorte = cv2.threshold(gray_recorte, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                                pil_recorte = Image.fromarray(bin_recorte)
                                
                                try:
                                    langs = pytesseract.get_languages()
                                    lang = 'por' if 'por' in langs else 'eng'
                                except:
                                    lang = 'eng'
                                
                                texto_completo = pytesseract.image_to_string(pil_recorte, lang=lang, config='--psm 6 --oem 3')
                                
                                if debug:
                                    print(f"[OCR-DEBUG] Texto extraído (primeiros 500 chars): {texto_completo[:500]}")
                                
                                # Tentar processar texto com regex (similar ao extrator_itens.py)
                                # Por enquanto, apenas logar e continuar
                                if debug:
                                    print(f"[OCR-DEBUG] OCR completo não implementado ainda, pulando página")
                            except Exception as e:
                                if debug:
                                    print(f"[OCR-DEBUG] ERRO no OCR completo: {e}")
                        
                        continue
                    
                    # FASE 2: OCR célula a célula (usar img_recortada e coordenadas relativas)
                    if debug:
                        print(f"[OCR-DEBUG] FASE 2 (LEITURA): Iniciando OCR célula a célula...")
                    
                    grade_texto = []
                    for idx_linha, linha_celulas in enumerate(linhas_celulas):
                        linha_texto = []
                        for bbox in linha_celulas:
                            # Usar img_recortada e coordenadas relativas (bbox já está relativo à região recortada)
                            texto_celula = _ocr_celula(img_recortada, bbox, tipo="texto")
                            linha_texto.append(texto_celula)
                        grade_texto.append(linha_texto)
                        
                        # Debug: imprimir primeira e segunda linha
                        if debug and idx_linha < 2:
                            print(f"[OCR-DEBUG] Linha {idx_linha}: {linha_texto}")
                    
                    if not grade_texto or len(grade_texto) < 2:
                        if debug:
                            print(f"[OCR-DEBUG] FASE 2 FALHOU: Grade de texto vazia ou muito pequena")
                        continue
                    
                    # FASE 3: Mapear colunas e processar dados
                    if debug:
                        print(f"[OCR-DEBUG] FASE 3 (LÓGICA): Mapeando colunas...")
                    
                    # Identificar linha de cabeçalho
                    if mapa_colunas is None:
                        # Tentar primeira linha
                        mapa = _mapear_colunas_ocr(grade_texto[0], grade_texto=grade_texto)
                        if not mapa and len(grade_texto) > 1:
                            # Tentar segunda linha
                            mapa = _mapear_colunas_ocr(grade_texto[1], grade_texto=grade_texto)
                            linha_cabecalho = 1
                        else:
                            linha_cabecalho = 0
                        
                        if mapa:
                            mapa_colunas = mapa
                            paginas_processadas.append(num_pagina + 1)
                            print(f"[OCR] Cabeçalho encontrado na página {num_pagina+1}")
                            if debug:
                                print(f"[OCR-DEBUG] Mapeamento de colunas: {mapa}")
                        else:
                            if debug:
                                print(f"[OCR-DEBUG] FASE 3 FALHOU: Não foi possível mapear colunas")
                            continue
                    else:
                        # Verificar se é continuação (primeira linha tem número na coluna ITEM)
                        if len(grade_texto) > 0 and "item" in mapa_colunas:
                            col_item = mapa_colunas["item"]
                            if col_item < len(grade_texto[0]):
                                valor_item = str(grade_texto[0][col_item]).strip()
                                if re.match(r"^\d{1,3}$", valor_item):
                                    # É continuação
                                    paginas_processadas.append(num_pagina + 1)
                                    linha_cabecalho = -1  # Sem cabeçalho
                                else:
                                    continue
                            else:
                                continue
                        else:
                            continue
                    
                    # Processar linhas de dados
                    inicio_dados = linha_cabecalho + 1 if linha_cabecalho >= 0 else 0
                    item_atual = None
                    
                    for linha in grade_texto[inicio_dados:]:
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
                            # Se não encontrou, tentar última coluna numérica
                            if total_encontrado is None:
                                for celula in reversed(linha):
                                    if celula:
                                        valor = _parse_valor_br(str(celula))
                                        if valor is not None and valor > 0:
                                            total_encontrado = valor
                                            break
                            item_atual = None
                            continue
                        
                        # Verificar se é linha de dados (tem número na coluna ITEM)
                        if mapa_colunas and "item" in mapa_colunas:
                            col_item = mapa_colunas["item"]
                            tem_item_valido = False
                            
                            if col_item < len(linha) and linha[col_item]:
                                valor_item = str(linha[col_item]).strip()
                                # Aplicar correções de OCR
                                valor_item = _corrigir_ocr(valor_item, contexto="numero")
                                if re.match(r"^\d{1,3}$", valor_item):
                                    tem_item_valido = True
                            
                            # Se não tem item válido, pode ser continuação de descrição
                            if not tem_item_valido:
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
                                    texto_item = _corrigir_ocr(str(linha[col]), contexto="numero")
                                    item["item"] = int(texto_item.strip())
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
                                texto_qtd = _corrigir_ocr(str(linha[col]), contexto="numero")
                                item["qtd"] = _parse_qtd_br(texto_qtd)
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
                                texto_valor = _corrigir_ocr(str(linha[col]), contexto="valor")
                                item["p_unit"] = _parse_valor_br(texto_valor)
                            else:
                                item["p_unit"] = None
                        else:
                            item["p_unit"] = None
                        
                        # P_TOTAL
                        if "p_total" in mapa_colunas:
                            col = mapa_colunas["p_total"]
                            if col < len(linha) and linha[col]:
                                texto_valor = _corrigir_ocr(str(linha[col]), contexto="valor")
                                item["p_total"] = _parse_valor_br(texto_valor)
                            else:
                                item["p_total"] = None
                        else:
                            item["p_total"] = None
                        
                        # Só adicionar se tem pelo menos item e descrição
                        if "item" in item and item.get("descricao"):
                            itens_encontrados.append(item)
                            item_atual = item
                            if debug:
                                print(f"[OCR-DEBUG] Item {item.get('item')} adicionado: {item.get('descricao', '')[:40]}...")
                    
                    if debug:
                        print(f"[OCR-DEBUG] Total de itens parseados na página {num_pagina+1}: {len([i for i in itens_encontrados if i.get('item')])}")
                
                except Exception as e:
                    print(f"[OCR] ERRO ao processar página {num_pagina+1}: {e}")
                    if debug:
                        import traceback
                        traceback.print_exc()
                    continue
            
            # Calcular total dos itens
            total_calculado = sum(item.get("p_total", 0) or 0 for item in itens_encontrados)
            
            resultado["itens"] = itens_encontrados
            resultado["total"] = total_encontrado
            resultado["total_calculado"] = total_calculado if total_calculado > 0 else None
            resultado["paginas_processadas"] = paginas_processadas
            
            if not itens_encontrados:
                resultado["debug"] = "Nenhuma tabela de itens encontrada (OCR)"
            else:
                resultado["debug"] = f"Encontrados {len(itens_encontrados)} itens em {len(paginas_processadas)} página(s) (OCR)"
            
            if debug:
                print(f"\n[OCR-DEBUG] === RESUMO FINAL ===")
                print(f"[OCR-DEBUG] Itens encontrados: {len(itens_encontrados)}")
                print(f"[OCR-DEBUG] Total extraído: {total_encontrado}")
                print(f"[OCR-DEBUG] Total calculado: {total_calculado}")
    
    except Exception as e:
        resultado["debug"] = f"Erro ao processar PDF: {str(e)}"
        print(f"[OCR] ERRO ao processar {pdf_path}: {e}")
        import traceback
        traceback.print_exc()
    
    return resultado


# ── Testes Unitários ───────────────────────────────────────────────────────────

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
    
    print("[OCR] Executando testes unitários de _normalizar_nd_si...")
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
        print("[OCR] ⚠️  Alguns testes falharam.")
        return False
    
    print("[OCR] ✅ Todos os testes passaram!")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # Executar testes unitários primeiro
    print("[OCR] Iniciando testes...\n")
    testes_ok = _testar_normalizar_nd_si()
    print()
    
    if not testes_ok:
        print("[OCR] ⚠️  Testes unitários falharam. Continuando mesmo assim...\n")
    
    # Processar PDFs
    if len(sys.argv) > 1:
        # Processar arquivo específico
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists():
            print(f"[OCR] ERRO: Arquivo não encontrado: {pdf_path}")
            sys.exit(1)
        
        pdfs = [pdf_path]
    else:
        # Processar todos os PDFs em tests/
        tests_dir = Path(__file__).parent.parent / "tests"
        pdfs = list(tests_dir.glob("*.pdf"))
        
        if not pdfs:
            print(f"[OCR] ERRO: Nenhum PDF encontrado em {tests_dir}")
            sys.exit(1)
        
        print(f"[OCR] Encontrados {len(pdfs)} PDF(s) em tests/\n")
    
    # Processar cada PDF
    resultados = []
    processos_com_itens = 0
    total_paginas_imagem = 0
    
    for pdf_path in sorted(pdfs):
        print("═" * 70)
        print(f"    ITENS (OCR): {pdf_path.name}")
        print("═" * 70)
        
        resultado = extrair_itens_ocr(str(pdf_path), debug=True)
        
        if resultado.get("debug") and "ERRO" in resultado["debug"].upper():
            print(f"ERRO: {resultado['debug']}")
        else:
            # Páginas de imagem
            paginas_img = resultado.get("paginas_processadas", [])
            if paginas_img:
                print(f"Páginas de imagem detectadas: {paginas_img}")
                total_paginas_imagem += len(paginas_img)
            
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
                
                # Método
                print(f"Método: OCR (OpenCV + Tesseract)")
            else:
                print("Nenhum item encontrado")
                print(f"Debug: {resultado.get('debug', '—')}")
        
        print("═" * 70)
        print()
    
    # Resumo final
    print("═" * 70)
    print(f"OCR processou {processos_com_itens}/{len(pdfs)} processos ({total_paginas_imagem} páginas de imagem detectadas)")
    print("═" * 70)

