"""
Script de teste para processar todos os PDFs em tests/ e gerar relatório.

Compara resultados esperados vs extraídos e identifica problemas comuns.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import extractor

# ── Configuração ──────────────────────────────────────────────────────
TESTS_DIR = Path(__file__).parent
REPORT_DIR = TESTS_DIR / "relatorios"
REPORT_DIR.mkdir(exist_ok=True)

# Resultados esperados (manualmente documentados após análise)
# Formato: {nome_arquivo: {campo: valor_esperado}}
RESULTADOS_ESPERADOS = {
    "Processo-64136_000430_2026-16.pdf": {
        "num_itens": 2,  # Tem 2 itens na tabela
        "tem_nc": True,
        "tem_certidoes": True,
    },
    "Processo-65297_001232_2026-90.pdf": {
        "num_itens": 1,
        "tem_nc": True,
        "tem_certidoes": True,
    },
    "Processo-65345_000389_2026-85.pdf": {
        "num_itens": 1,
        "tem_nc": True,
        "tem_certidoes": True,
    },
}


def processar_pdf(caminho_pdf: Path) -> dict:
    """Processa um PDF e retorna os dados extraídos."""
    print(f"\n{'='*70}")
    print(f"Processando: {caminho_pdf.name}")
    print(f"{'='*70}")
    
    try:
        resultado = extractor.extrair_processo(str(caminho_pdf))
        
        # Resumo dos dados extraídos
        resumo = {
            "arquivo": caminho_pdf.name,
            "sucesso": True,
            "timestamp": datetime.now().isoformat(),
            "identificacao": {
                "nup": resultado.get("identificacao", {}).get("nup"),
                "uasg": resultado.get("identificacao", {}).get("uasg"),
                "nr_requisicao": resultado.get("identificacao", {}).get("nr_requisicao"),
            },
            "itens": {
                "total": len(resultado.get("itens", [])),
                "detalhes": [
                    {
                        "item": item.get("item"),
                        "descricao": item.get("descricao", "")[:50] + "..." if item.get("descricao") else None,
                        "qtd": item.get("qtd"),
                        "nd_si": item.get("nd_si"),
                    }
                    for item in resultado.get("itens", [])
                ],
            },
            "nota_credito": {
                "tem_nc": bool(resultado.get("nota_credito")),
                "num_ncs": len(resultado.get("nota_credito", [])),
            },
            "certidoes": {
                "tem_sicaf": bool(resultado.get("certidoes", {}).get("sicaf")),
                "tem_cadin": bool(resultado.get("certidoes", {}).get("cadin")),
                "tem_consolidada": bool(resultado.get("certidoes", {}).get("consulta_consolidada")),
            },
            "contrato": {
                "tem_contrato": bool(resultado.get("contrato")),
            },
        }
        
        return resumo
        
    except Exception as e:
        print(f"ERRO ao processar {caminho_pdf.name}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "arquivo": caminho_pdf.name,
            "sucesso": False,
            "erro": str(e),
            "timestamp": datetime.now().isoformat(),
        }


def comparar_resultados(extraido: dict, esperado: dict) -> dict:
    """Compara resultados extraídos com esperados."""
    problemas = []
    
    if not extraido.get("sucesso"):
        problemas.append({
            "severidade": "erro",
            "campo": "processamento",
            "mensagem": f"Falha ao processar: {extraido.get('erro', 'Erro desconhecido')}",
        })
        return problemas
    
    # Comparar número de itens
    num_itens_esperado = esperado.get("num_itens")
    num_itens_extraido = extraido.get("itens", {}).get("total", 0)
    
    if num_itens_esperado and num_itens_extraido != num_itens_esperado:
        problemas.append({
            "severidade": "alta",
            "campo": "itens",
            "mensagem": f"Esperado {num_itens_esperado} item(ns), extraído {num_itens_extraido}",
            "esperado": num_itens_esperado,
            "extraido": num_itens_extraido,
        })
    
    # Comparar presença de NC
    tem_nc_esperado = esperado.get("tem_nc")
    tem_nc_extraido = extraido.get("nota_credito", {}).get("tem_nc", False)
    
    if tem_nc_esperado is not None and tem_nc_esperado != tem_nc_extraido:
        problemas.append({
            "severidade": "media",
            "campo": "nota_credito",
            "mensagem": f"NC esperada: {tem_nc_esperado}, extraída: {tem_nc_extraido}",
        })
    
    # Comparar presença de certidões
    tem_cert_esperado = esperado.get("tem_certidoes")
    tem_cert_extraido = (
        extraido.get("certidoes", {}).get("tem_sicaf", False) or
        extraido.get("certidoes", {}).get("tem_cadin", False) or
        extraido.get("certidoes", {}).get("tem_consolidada", False)
    )
    
    if tem_cert_esperado is not None and tem_cert_esperado != tem_cert_extraido:
        problemas.append({
            "severidade": "media",
            "campo": "certidoes",
            "mensagem": f"Certidões esperadas: {tem_cert_esperado}, extraídas: {tem_cert_extraido}",
        })
    
    return problemas


def gerar_relatorio(resultados: list[dict]) -> str:
    """Gera relatório em formato texto."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    relatorio_path = REPORT_DIR / f"relatorio_testes_{timestamp}.txt"
    
    with open(relatorio_path, "w", encoding="utf-8") as f:
        f.write("="*70 + "\n")
        f.write("RELATÓRIO DE TESTES - EXTRAÇÃO DE PROCESSOS\n")
        f.write("="*70 + "\n")
        f.write(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Total de processos testados: {len(resultados)}\n\n")
        
        total_problemas = 0
        processos_com_problema = 0
        
        for res in resultados:
            f.write("\n" + "-"*70 + "\n")
            f.write(f"Arquivo: {res['arquivo']}\n")
            f.write("-"*70 + "\n")
            
            if not res.get("sucesso"):
                f.write(f"[ERRO] {res.get('erro', 'Erro desconhecido')}\n")
                processos_com_problema += 1
                total_problemas += 1
                continue
            
            # Dados extraídos
            f.write(f"[OK] Processado com sucesso\n\n")
            f.write(f"Identificação:\n")
            f.write(f"  - NUP: {res.get('identificacao', {}).get('nup', '—')}\n")
            f.write(f"  - UASG: {res.get('identificacao', {}).get('uasg', '—')}\n")
            f.write(f"  - Req: {res.get('identificacao', {}).get('nr_requisicao', '—')}\n")
            
            f.write(f"\nItens: {res.get('itens', {}).get('total', 0)}\n")
            for item in res.get('itens', {}).get('detalhes', []):
                f.write(f"  - Item {item.get('item')}: {item.get('descricao', '—')}\n")
                f.write(f"    Qtd: {item.get('qtd')}, ND/SI: {item.get('nd_si', '—')}\n")
            
            f.write(f"\nNota de Credito: {'[OK]' if res.get('nota_credito', {}).get('tem_nc') else '[FALTA]'}\n")
            if res.get('nota_credito', {}).get('tem_nc'):
                f.write(f"  - Numero de NCs: {res.get('nota_credito', {}).get('num_ncs', 0)}\n")
            
            f.write(f"\nCertidoes:\n")
            f.write(f"  - SICAF: {'[OK]' if res.get('certidoes', {}).get('tem_sicaf') else '[FALTA]'}\n")
            f.write(f"  - CADIN: {'[OK]' if res.get('certidoes', {}).get('tem_cadin') else '[FALTA]'}\n")
            f.write(f"  - Consolidada: {'[OK]' if res.get('certidoes', {}).get('tem_consolidada') else '[FALTA]'}\n")
            
            f.write(f"\nContrato: {'[OK]' if res.get('contrato', {}).get('tem_contrato') else '[FALTA]'}\n")
            
            # Comparar com esperado
            esperado = RESULTADOS_ESPERADOS.get(res['arquivo'], {})
            if esperado:
                problemas = comparar_resultados(res, esperado)
                if problemas:
                    processos_com_problema += 1
                    total_problemas += len(problemas)
                    f.write(f"\n⚠️ PROBLEMAS ENCONTRADOS:\n")
                    for prob in problemas:
                        f.write(f"  [{prob['severidade'].upper()}] {prob['campo']}: {prob['mensagem']}\n")
                else:
                    f.write(f"\n[OK] Todos os resultados estao conforme o esperado!\n")
        
        # Resumo final
        f.write("\n" + "="*70 + "\n")
        f.write("RESUMO FINAL\n")
        f.write("="*70 + "\n")
        f.write(f"Total de processos: {len(resultados)}\n")
        f.write(f"Processos com problemas: {processos_com_problema}\n")
        f.write(f"Total de problemas: {total_problemas}\n")
        f.write(f"Taxa de sucesso: {((len(resultados) - processos_com_problema) / len(resultados) * 100):.1f}%\n")
    
    return str(relatorio_path)


def main():
    """Função principal."""
    import sys
    import io
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    print("Iniciando testes de extracao de processos...")
    print(f"Diretorio de testes: {TESTS_DIR}")
    print(f"Diretorio de relatorios: {REPORT_DIR}\n")
    
    # Encontrar todos os PDFs
    pdfs = list(TESTS_DIR.glob("*.pdf"))
    
    if not pdfs:
        print("ERRO: Nenhum PDF encontrado em tests/")
        return
    
    print(f"Encontrados {len(pdfs)} arquivo(s) PDF:\n")
    for pdf in pdfs:
        print(f"  - {pdf.name}")
    
    # Processar cada PDF
    resultados = []
    for pdf in sorted(pdfs):
        resultado = processar_pdf(pdf)
        resultados.append(resultado)
    
    # Gerar relatório
    print("\n" + "="*70)
    print("Gerando relatorio...")
    print("="*70)
    
    relatorio_path = gerar_relatorio(resultados)
    
    print(f"\nRelatorio gerado: {relatorio_path}")
    print(f"\nResumo:")
    print(f"  - Processos testados: {len(resultados)}")
    sucessos = sum(1 for r in resultados if r.get("sucesso"))
    print(f"  - Sucessos: {sucessos}")
    print(f"  - Falhas: {len(resultados) - sucessos}")
    
    # Salvar JSON também
    json_path = REPORT_DIR / f"resultados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"  - JSON salvo: {json_path}")


if __name__ == "__main__":
    main()

