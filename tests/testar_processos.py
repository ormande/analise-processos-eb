"""
Script de teste de regressão para validação de extração de processos.

Compara resultados extraídos contra valores esperados e gera relatório.
Uso: python tests/testar_processos.py
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import extractor

# ── Configuração ──────────────────────────────────────────────────────
TESTS_DIR = Path(__file__).parent
REPORT_DIR = TESTS_DIR / "relatorios"
REPORT_DIR.mkdir(exist_ok=True)

# ── Cores ANSI para terminal ──────────────────────────────────────────
class Cores:
    """Códigos ANSI para cores no terminal."""
    VERDE = "\033[92m"
    AMARELO = "\033[93m"
    VERMELHO = "\033[91m"
    AZUL = "\033[94m"
    RESET = "\033[0m"
    NEGRITO = "\033[1m"

# ── Valores Esperados ──────────────────────────────────────────────────
ESPERADO: Dict[str, Dict[str, Any]] = {
    "Processo-65297_001529_2026-55.pdf": {
        "nup": "65297.001529/2026-55",
        "min_itens": 3,
        "tem_nc": True,
        "tem_sicaf": True,
        "uasg_esperada": "160512",
    },
    "Processo-65345_000389_2026-85.pdf": {
        "nup": "65345.000389/2026-85",
        "min_itens": 1,
        "tem_nc": True,
        "tem_sicaf": True,
        "uasg_esperada": "160141",
    },
    "Processo-65345_000547_2026-05.pdf": {
        "nup": "65345.000547/2026-05",
        "min_itens": 2,  # ANTES: 0 itens, APÓS correção: deve ter 2+
        "tem_nc": True,
        "tem_sicaf": True,
    },
    "Processo-65345_000556_2026-98.pdf": {
        "nup": "65345.000556/2026-98",
        "min_itens": 1,  # ANTES: 0, APÓS correção: deve ter itens
        "tem_nc": True,
        "tem_sicaf": True,
    },
}


def processar_pdf(caminho_pdf: Path) -> Dict[str, Any]:
    """Processa um PDF e retorna os dados extraídos."""
    print(f"\n{Cores.AZUL}{'='*70}{Cores.RESET}")
    print(f"{Cores.NEGRITO}Processando: {caminho_pdf.name}{Cores.RESET}")
    print(f"{Cores.AZUL}{'='*70}{Cores.RESET}")
    
    try:
        resultado = extractor.extrair_processo(str(caminho_pdf))
        
        # Extrair dados relevantes
        ident = resultado.get("identificacao", {})
        itens = resultado.get("itens", [])
        ncs = resultado.get("nota_credito", [])
        certidoes = resultado.get("certidoes", {})
        
        resumo = {
            "arquivo": caminho_pdf.name,
            "sucesso": True,
            "timestamp": datetime.now().isoformat(),
            "identificacao": {
                "nup": ident.get("nup"),
                "uasg": ident.get("uasg"),
                "nr_requisicao": ident.get("nr_requisicao"),
            },
            "itens": {
                "total": len(itens),
                "detalhes": [
                    {
                        "item": item.get("item"),
                        "descricao": (item.get("descricao", "")[:50] + "..." 
                                     if len(item.get("descricao", "")) > 50 
                                     else item.get("descricao", "")),
                        "qtd": item.get("qtd"),
                        "nd_si": item.get("nd_si"),
                    }
                    for item in itens[:5]  # Limitar a 5 itens para resumo
                ],
            },
            "nota_credito": {
                "tem_nc": bool(ncs),
                "num_ncs": len(ncs),
            },
            "certidoes": {
                "tem_sicaf": bool(certidoes.get("sicaf")),
                "tem_cadin": bool(certidoes.get("cadin")),
                "tem_consolidada": bool(certidoes.get("consulta_consolidada")),
            },
        }
        
        return resumo
        
    except Exception as e:
        print(f"{Cores.VERMELHO}ERRO ao processar {caminho_pdf.name}: {e}{Cores.RESET}")
        import traceback
        traceback.print_exc()
        return {
            "arquivo": caminho_pdf.name,
            "sucesso": False,
            "erro": str(e),
            "timestamp": datetime.now().isoformat(),
        }


def validar_resultado(extraido: Dict[str, Any], esperado: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Valida resultado extraído contra valores esperados.
    Retorna lista de falhas (vazia se tudo OK).
    """
    falhas = []
    
    if not extraido.get("sucesso"):
        falhas.append({
            "campo": "processamento",
            "mensagem": f"Falha ao processar: {extraido.get('erro', 'Erro desconhecido')}",
            "severidade": "erro",
        })
        return falhas
    
    ident = extraido.get("identificacao", {})
    itens = extraido.get("itens", {})
    nc = extraido.get("nota_credito", {})
    certidoes = extraido.get("certidoes", {})
    
    # Validar NUP
    nup_esperado = esperado.get("nup")
    nup_extraido = ident.get("nup")
    if nup_esperado and nup_extraido != nup_esperado:
        falhas.append({
            "campo": "nup",
            "mensagem": f"NUP esperado: {nup_esperado}, extraído: {nup_extraido}",
            "esperado": nup_esperado,
            "extraido": nup_extraido,
            "severidade": "alta",
        })
    
    # Validar número mínimo de itens
    min_itens = esperado.get("min_itens")
    num_itens = itens.get("total", 0)
    if min_itens is not None and num_itens < min_itens:
        falhas.append({
            "campo": "itens",
            "mensagem": f"Itens extraídos: {num_itens} (esperado ≥{min_itens})",
            "esperado": f">={min_itens}",
            "extraido": num_itens,
            "severidade": "alta",
        })
    
    # Validar presença de NC
    tem_nc_esperado = esperado.get("tem_nc")
    tem_nc_extraido = nc.get("tem_nc", False)
    if tem_nc_esperado is not None and tem_nc_extraido != tem_nc_esperado:
        falhas.append({
            "campo": "nota_credito",
            "mensagem": f"NC esperada: {tem_nc_esperado}, extraída: {tem_nc_extraido}",
            "esperado": tem_nc_esperado,
            "extraido": tem_nc_extraido,
            "severidade": "media",
        })
    
    # Validar presença de SICAF
    tem_sicaf_esperado = esperado.get("tem_sicaf")
    tem_sicaf_extraido = certidoes.get("tem_sicaf", False)
    if tem_sicaf_esperado is not None and tem_sicaf_extraido != tem_sicaf_esperado:
        falhas.append({
            "campo": "sicaf",
            "mensagem": f"SICAF esperada: {tem_sicaf_esperado}, extraída: {tem_sicaf_extraido}",
            "esperado": tem_sicaf_esperado,
            "extraido": tem_sicaf_extraido,
            "severidade": "media",
        })
    
    # Validar UASG (se especificada)
    uasg_esperada = esperado.get("uasg_esperada")
    uasg_extraida = ident.get("uasg")
    if uasg_esperada and uasg_extraida != uasg_esperada:
        falhas.append({
            "campo": "uasg",
            "mensagem": f"UASG esperada: {uasg_esperada}, extraída: {uasg_extraida}",
            "esperado": uasg_esperada,
            "extraido": uasg_extraida,
            "severidade": "media",
        })
    
    return falhas


def imprimir_resultado_teste(arquivo: str, extraido: Dict[str, Any], 
                             falhas: List[Dict[str, Any]], esperado: Dict[str, Any]):
    """Imprime resultado do teste formatado com cores."""
    print(f"\n{Cores.NEGRITO}Arquivo: {arquivo}{Cores.RESET}")
    
    if not extraido.get("sucesso"):
        print(f"{Cores.VERMELHO}❌ FALHA: {extraido.get('erro', 'Erro desconhecido')}{Cores.RESET}")
        return
    
    ident = extraido.get("identificacao", {})
    itens = extraido.get("itens", {})
    nc = extraido.get("nota_credito", {})
    certidoes = extraido.get("certidoes", {})
    
    # Dados extraídos
    print(f"  NUP: {ident.get('nup', '—')}")
    print(f"  UASG: {ident.get('uasg', '—')}")
    print(f"  Itens: {itens.get('total', 0)}")
    print(f"  NC: {'✅' if nc.get('tem_nc') else '❌'} ({nc.get('num_ncs', 0)} NCs)")
    print(f"  SICAF: {'✅' if certidoes.get('tem_sicaf') else '❌'}")
    
    # Validações
    if falhas:
        print(f"\n{Cores.VERMELHO}❌ FALHAS ENCONTRADAS:{Cores.RESET}")
        for falha in falhas:
            severidade_emoji = {
                "erro": "🔴",
                "alta": "🔴",
                "media": "⚠️",
            }.get(falha.get("severidade", "media"), "⚠️")
            print(f"  {severidade_emoji} {falha['campo']}: {falha['mensagem']}")
    else:
        print(f"\n{Cores.VERDE}✅ TODOS OS TESTES PASSARAM{Cores.RESET}")


def gerar_relatorio_json(resultados: List[Dict[str, Any]], 
                        validacoes: Dict[str, List[Dict[str, Any]]]) -> str:
    """Gera relatório JSON com timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    relatorio_path = REPORT_DIR / f"regressao_{timestamp}.json"
    
    relatorio = {
        "timestamp": datetime.now().isoformat(),
        "total_processos": len(resultados),
        "processos_ok": sum(1 for r in resultados 
                          if r.get("sucesso") and not validacoes.get(r["arquivo"])),
        "processos_com_falhas": sum(1 for r in resultados 
                                   if not r.get("sucesso") or validacoes.get(r["arquivo"])),
        "resultados": [
            {
                **resultado,
                "validacoes": {
                    "passou": not validacoes.get(resultado["arquivo"], []),
                    "falhas": validacoes.get(resultado["arquivo"], []),
                }
            }
            for resultado in resultados
        ],
    }
    
    with open(relatorio_path, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    
    return str(relatorio_path)


def main():
    """Função principal."""
    # Forçar UTF-8 no Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    print(f"{Cores.NEGRITO}{'='*70}{Cores.RESET}")
    print(f"{Cores.NEGRITO}TESTE DE REGRESSÃO - EXTRAÇÃO DE PROCESSOS{Cores.RESET}")
    print(f"{Cores.NEGRITO}{'='*70}{Cores.RESET}")
    print(f"Diretório de testes: {TESTS_DIR}")
    print(f"Diretório de relatórios: {REPORT_DIR}\n")
    
    # Encontrar PDFs esperados
    pdfs_esperados = list(ESPERADO.keys())
    pdfs_encontrados = []
    
    for nome_arquivo in pdfs_esperados:
        caminho = TESTS_DIR / nome_arquivo
        if caminho.exists():
            pdfs_encontrados.append(caminho)
        else:
            print(f"{Cores.AMARELO}⚠️  Arquivo não encontrado: {nome_arquivo}{Cores.RESET}")
    
    if not pdfs_encontrados:
        print(f"{Cores.VERMELHO}ERRO: Nenhum PDF de teste encontrado!{Cores.RESET}")
        sys.exit(1)
    
    print(f"Encontrados {len(pdfs_encontrados)}/{len(pdfs_esperados)} arquivo(s) PDF:\n")
    for pdf in pdfs_encontrados:
        print(f"  - {pdf.name}")
    
    # Processar cada PDF
    resultados = []
    validacoes = {}
    
    for pdf in sorted(pdfs_encontrados):
        resultado = processar_pdf(pdf)
        resultados.append(resultado)
        
        # Validar contra esperado
        esperado = ESPERADO.get(pdf.name, {})
        if esperado:
            falhas = validar_resultado(resultado, esperado)
            if falhas:
                validacoes[pdf.name] = falhas
            imprimir_resultado_teste(pdf.name, resultado, falhas, esperado)
        else:
            print(f"{Cores.AMARELO}⚠️  Sem valores esperados definidos para {pdf.name}{Cores.RESET}")
    
    # Gerar relatório JSON
    relatorio_path = gerar_relatorio_json(resultados, validacoes)
    
    # Resumo final
    processos_ok = sum(1 for r in resultados 
                      if r.get("sucesso") and not validacoes.get(r["arquivo"]))
    processos_com_falhas = len(resultados) - processos_ok
    
    print(f"\n{Cores.NEGRITO}{'='*70}{Cores.RESET}")
    print(f"{Cores.NEGRITO}RESULTADO DOS TESTES{Cores.RESET}")
    print(f"{Cores.NEGRITO}{'='*70}{Cores.RESET}")
    
    if processos_com_falhas == 0:
        print(f"{Cores.VERDE}✅ {processos_ok}/{len(resultados)} processos OK{Cores.RESET}")
    else:
        print(f"{Cores.VERDE}✅ {processos_ok}/{len(resultados)} processos OK{Cores.RESET}")
        print(f"{Cores.VERMELHO}❌ {processos_com_falhas} processo(s) com falhas:{Cores.RESET}")
        for resultado in resultados:
            arquivo = resultado["arquivo"]
            if not resultado.get("sucesso"):
                print(f"  {arquivo}: {resultado.get('erro', 'Erro desconhecido')}")
            elif validacoes.get(arquivo):
                falhas = validacoes[arquivo]
                for falha in falhas:
                    print(f"  {arquivo}: {falha['campo']} - {falha['mensagem']}")
    
    print(f"\nRelatório JSON salvo: {relatorio_path}")
    
    # Exit code: 0 se todos passaram, 1 se algum falhou
    sys.exit(0 if processos_com_falhas == 0 else 1)


if __name__ == "__main__":
    main()
