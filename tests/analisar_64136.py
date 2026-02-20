"""
Script para analisar especificamente o processo 64136 e entender
por que só extrai 1 item quando há 2 na tabela.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import extractor
import pdfplumber

pdf_path = "tests/Processo-64136_000430_2026-16.pdf"

print("="*70)
print("ANALISE DO PROCESSO 64136")
print("="*70)

# Extrair dados
res = extractor.extrair_processo(pdf_path)

print(f"\nItens extraidos: {len(res.get('itens', []))}")
for i, item in enumerate(res.get('itens', []), 1):
    print(f"\n  Item {i}:")
    print(f"    Numero: {item.get('item')}")
    print(f"    Descricao: {item.get('descricao', '')[:80]}...")
    print(f"    Qtd: {item.get('qtd')}")
    print(f"    ND/SI: {item.get('nd_si')}")

# Verificar o que o OCR está capturando
print("\n" + "="*70)
print("TEXTO OCR DAS IMAGENS INCORPORADAS")
print("="*70)

paginas = extractor._extrair_paginas(pdf_path)
paginas_req = [p for p in paginas if extractor._eh_requisicao(p.get("texto", "").upper())]

print(f"\nPaginas de requisicao encontradas: {[p['numero'] for p in paginas_req]}")

# Verificar imagens OCR
for pag in paginas_req:
    page_idx = pag["numero"] - 1
    imgs_ocr = extractor._ocr_imagens_incorporadas(pdf_path, page_idx)
    
    print(f"\n--- Pagina {pag['numero']} ---")
    print(f"Imagens incorporadas encontradas: {len(imgs_ocr)}")
    
    for i, img_info in enumerate(imgs_ocr):
        texto_ocr = img_info.get("texto", "")
        print(f"\n  Imagem {i + 1} (tamanho: {len(texto_ocr)} chars):")
        print(f"  Texto OCR (primeiros 1000 chars):")
        print(f"  {texto_ocr[:1000]}")
        
        # Tentar parsear
        itens_ocr = extractor._parsear_itens_ocr(texto_ocr)
        print(f"  Itens extraidos desta imagem: {len(itens_ocr)}")
        for item in itens_ocr:
            print(f"    - Item {item.get('item')}: {item.get('descricao', '')[:60]}...")

# Analisar tabelas em TODAS as páginas (não só requisição)
print("\n" + "="*70)
print("ANALISANDO TABELAS EM TODAS AS PAGINAS")
print("="*70)

# Extrair tabelas de cada página (incluindo não-requisição para debug)
with pdfplumber.open(pdf_path) as pdf:
    # Verificar páginas próximas à requisição também
    paginas_para_verificar = set()
    for pag_info in paginas_req:
        paginas_para_verificar.add(pag_info["numero"])
        # Adicionar páginas adjacentes
        if pag_info["numero"] > 1:
            paginas_para_verificar.add(pag_info["numero"] - 1)
        if pag_info["numero"] < len(pdf.pages):
            paginas_para_verificar.add(pag_info["numero"] + 1)
    
    for num_pag in sorted(paginas_para_verificar):
        if num_pag < 1 or num_pag > len(pdf.pages):
            continue
        
        idx = num_pag - 1
        pagina = pdf.pages[idx]
        texto_pag = pagina.extract_text() or ""
        
        # Verificar se tem palavras-chave de tabela de itens
        tem_item = "item" in texto_pag.lower() or "qtd" in texto_pag.lower()
        
        tabelas = pagina.extract_tables()
        
        if tabelas or tem_item:
            print(f"\n--- Pagina {num_pag} ---")
            print(f"Texto tem 'item' ou 'qtd': {tem_item}")
            print(f"Tabelas encontradas (pdfplumber): {len(tabelas)}")
            
            if texto_pag:
                # Procurar por padrões de item na página
                import re
                itens_texto = re.findall(r'(?i)item\s*[:\s]*(\d+)', texto_pag)
                if itens_texto:
                    print(f"  Numeros de item encontrados no texto: {itens_texto}")
            
            for t_idx, tabela in enumerate(tabelas):
                print(f"\n  Tabela {t_idx + 1} ({len(tabela)} linhas):")
                
                # Mostrar primeiras 15 linhas
                for i, linha in enumerate(tabela[:15]):
                    print(f"    Linha {i}: {linha}")
                
                # Tentar processar
                itens_tabela = extractor._processar_tabela_itens(tabela)
                print(f"    Itens extraidos desta tabela: {len(itens_tabela)}")
                for item in itens_tabela:
                    print(f"      - Item {item.get('item')}: {item.get('descricao', '')[:50]}...")
            
            # Se não encontrou tabelas mas tem texto com "item", mostrar texto
            if not tabelas and tem_item:
                print(f"\n  Texto da pagina (primeiros 500 chars):")
                print(f"  {texto_pag[:500]}...")

