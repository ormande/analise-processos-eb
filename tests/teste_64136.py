"""Teste rápido do processo 64136"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import extractor

res = extractor.extrair_processo('tests/Processo-64136_000430_2026-16.pdf')
print(f'Itens extraidos: {len(res.get("itens", []))}')
for i, item in enumerate(res.get('itens', []), 1):
    print(f'  Item {item.get("item")}: qtd={item.get("qtd")}, desc={item.get("descricao", "")[:60]}...')

