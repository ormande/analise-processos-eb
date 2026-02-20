# ══════════════════════════════════════════════════════════════════════
# modules/nd_lookup.py — Consulta e validação de ND/Subelementos
# ══════════════════════════════════════════════════════════════════════
"""
Carrega a tabela oficial de Natureza da Despesa (ND) do arquivo Excel
e oferece funções de consulta e validação para verificar se a ND/SI
indicada na requisição é compatível com a descrição do item.

A validação é INTERNA — não aparece como seção separada na interface,
mas contribui para o resultado final (ressalva ⚠️ se incompatível).

Formato da ND completa: C.G.MM.EE (ex: 3.3.90.30)
  C  = Categoria Econômica (3=Corrente, 4=Capital)
  G  = Grupo de Natureza (3=Outras Desp. Correntes, 4=Investimentos)
  MM = Modalidade de Aplicação (90=Aplicação Direta)
  EE = Elemento de Despesa (30=Material, 39=Serviço PJ, etc.)

Formato do SI (Subelemento): número de 1-2 dígitos após o elemento.
  Ex: 339030/17 → Elemento 30, SI 17 = Material de Processamento de Dados
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd


# ══════════════════════════════════════════════════════════════════════
# CAMINHO DA PLANILHA
# ══════════════════════════════════════════════════════════════════════

_CAMINHO_XLSX = Path(__file__).resolve().parent.parent / "docs" / "TABELA-NATUREZA-DA-DESPESA-2025.xlsx"


# ══════════════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO POR ELEMENTO (GRUPO SEMÂNTICO)
# ══════════════════════════════════════════════════════════════════════

# Mapeamento elemento → natureza genérica
_NATUREZA_ELEMENTO = {
    30: "material",
    32: "material",     # Material, bem ou serviço p/ distribuição gratuita
    33: "passagem",     # Passagens e locomoção
    35: "servico",      # Serviços de consultoria
    36: "servico_pf",   # Outros Serviços PF
    37: "servico",      # Locação de mão de obra
    39: "servico_pj",   # Outros Serviços PJ
    40: "servico",      # Serviços de TI
    47: "tributo",      # Obrigações tributárias
    51: "permanente",   # Obras e instalações
    52: "permanente",   # Equipamento e material permanente
}

# Palavras-chave que indicam MATERIAL
_KW_MATERIAL = [
    "aquisição", "aquisicao", "aqs", "material", "produto", "fornecimento",
    "calha", "chapa", "parafuso", "prego", "tinta", "papel", "caneta",
    "vidro", "cimento", "areia", "madeira", "tubo", "fio", "cabo",
    "peça", "peca", "componente", "lâmpada", "lampada", "bateria",
    "medicamento", "alimento", "gênero", "genero", "uniforme", "tecido",
    "combustível", "combustivel", "lubrificante", "solvente",
    "filtro", "válvula", "valvula", "rolamento", "anel", "junta",
    "mangueira", "borracha", "plástico", "plastico", "aço", "aco",
    "ferro", "alumínio", "aluminio", "cobre", "inox",
    "impressora", "toner", "cartucho", "pilha",
    "esportivo", "copa", "cozinha", "limpeza", "higiene",
    "galvanizado", "chapa de aço", "calha",
]

# Palavras-chave que indicam SERVIÇO
_KW_SERVICO = [
    "serviço", "servico", "manutenção", "manutencao", "mnt",
    "instalação", "instalacao", "remanejamento", "conserto",
    "reparo", "reparação", "reparacao", "limpeza e conservação",
    "vigilância", "vigilancia", "monitoramento",
    "contrato", "contratação", "contratacao", "prestação", "prestacao",
    "locação", "locacao", "aluguel", "assinatura",
    "consultoria", "assessoria", "treinamento", "capacitação",
    "hospedagem", "transporte", "frete",
    "energia elétrica", "água e esgoto", "telefone", "telecomunicação",
    "software", "licença", "licenca",
    "gráfico", "grafico", "impressão", "impressao",
    "preventiva", "corretiva",
]

# Palavras-chave que indicam EQUIPAMENTO PERMANENTE
_KW_PERMANENTE = [
    "equipamento", "mobiliário", "mobiliario", "veículo", "veiculo",
    "máquina", "maquina", "aparelho", "instrumento",
    "aeronave", "embarcação", "embarcacao",
    "armamento", "armamento",
]


# ══════════════════════════════════════════════════════════════════════
# CARREGAMENTO DA TABELA
# ══════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def _carregar_tabela() -> dict[tuple[int, int], str]:
    """
    Carrega a planilha ND 2025 e retorna um dicionário:
        (elemento, subelemento) → nome da classificação

    Filtra apenas modalidade 90 (Aplicação Direta — caso do Exército).
    Usa cache para carregar uma única vez.
    """
    tabela = {}

    if not _CAMINHO_XLSX.exists():
        print(f"[ND_LOOKUP] Planilha não encontrada: {_CAMINHO_XLSX}")
        return tabela

    try:
        df = pd.read_excel(str(_CAMINHO_XLSX), sheet_name="ND 2025", header=1)
        df.columns = [
            "categoria", "grupo", "modalidade", "elemento",
            "subelemento", "nome", "escrituracao", "ente",
            "inclusao", "exclusao", "alteracao", "col12",
        ]

        # Filtrar modalidade 90 (Aplicação Direta)
        df90 = df[df["modalidade"] == 90].copy()

        for _, row in df90.iterrows():
            elem = int(row["elemento"]) if pd.notna(row["elemento"]) else 0
            subelem = int(row["subelemento"]) if pd.notna(row["subelemento"]) else 0
            nome = str(row["nome"]).strip() if pd.notna(row["nome"]) else ""

            if nome:
                tabela[(elem, subelem)] = nome

        print(f"[ND_LOOKUP] Tabela carregada: {len(tabela)} registros (modalidade 90)")

    except Exception as e:
        print(f"[ND_LOOKUP] Erro ao carregar planilha: {e}")

    return tabela


@lru_cache(maxsize=1)
def _carregar_elementos() -> dict[int, str]:
    """Carrega apenas a aba 'Elemento de Despesa' para consultas rápidas."""
    elementos = {}

    if not _CAMINHO_XLSX.exists():
        return elementos

    try:
        df = pd.read_excel(str(_CAMINHO_XLSX), sheet_name="Elemento de Despesa")
        for _, row in df.iterrows():
            codigo = int(row.iloc[0]) if pd.notna(row.iloc[0]) else 0
            nome = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
            if nome:
                elementos[codigo] = nome
    except Exception as e:
        print(f"[ND_LOOKUP] Erro ao carregar elementos: {e}")

    return elementos


# ══════════════════════════════════════════════════════════════════════
# PARSE DA ND/SI
# ══════════════════════════════════════════════════════════════════════

def parse_nd_si(nd_si: str | None) -> tuple[int | None, int | None]:
    """
    Extrai (elemento, subelemento) a partir do campo ND/SI da requisição.

    Formatos aceitos:
        "39.17"       → (39, 17)
        "33.90.39/24" → (39, 24)
        "33.90.30"    → (30, None)
        "339030"      → (30, None)
        "30/17"       → (30, 17)

    Retorna (None, None) se não conseguir parsear.
    """
    if not nd_si:
        return None, None

    nd_si = nd_si.strip()

    # Formato com barra: "33.90.39/24" ou "30/17"
    if "/" in nd_si:
        partes = nd_si.split("/")
        si = int(partes[-1]) if partes[-1].strip().isdigit() else None
        nd_parte = partes[0].strip()

        # Pegar o último grupo de 2 dígitos antes da barra como elemento
        numeros = re.findall(r"\d+", nd_parte)
        if numeros:
            elem = int(numeros[-1])
            # Se for maior que 99, provavelmente é ND completa (339039)
            if elem > 99:
                elem = elem % 100  # 339039 → 39
            return elem, si

    # Formato com ponto: "39.17" ou "33.90.30"
    if "." in nd_si:
        partes = nd_si.split(".")
        if len(partes) == 2:
            # "39.17" → elemento=39, SI=17
            try:
                elem = int(partes[0])
                si = int(partes[1])
                if elem <= 99 and si <= 99:
                    return elem, si
            except ValueError:
                pass

        if len(partes) >= 3:
            # "33.90.30" → elemento=30, sem SI
            try:
                elem = int(partes[-1])
                return elem, None
            except ValueError:
                pass

    # Formato compacto: "339030"
    if nd_si.isdigit() and len(nd_si) == 6:
        elem = int(nd_si[-2:])
        return elem, None

    return None, None


def parse_nd_completa(nd: str | None) -> int | None:
    """
    Extrai o elemento de despesa da ND completa.

    Formatos: "339030", "33.90.30", "339000"
    Retorna o elemento (30, 39, etc.) ou None.
    """
    if not nd:
        return None

    nd = nd.strip().replace(".", "")

    if nd.isdigit() and len(nd) == 6:
        return int(nd[-2:])

    return None


# ══════════════════════════════════════════════════════════════════════
# CONSULTA
# ══════════════════════════════════════════════════════════════════════

def consultar(elemento: int, subelemento: int = 0) -> str | None:
    """
    Consulta o nome da classificação para um (elemento, subelemento).
    Tenta primeiro com SI específico, depois com SI=0 (genérico).

    Retorna None se não encontrar.
    """
    tabela = _carregar_tabela()

    # Busca exata
    nome = tabela.get((elemento, subelemento))
    if nome:
        return nome

    # Fallback: subelemento genérico (0)
    if subelemento != 0:
        return tabela.get((elemento, 0))

    return None


def nome_elemento(elemento: int) -> str | None:
    """Retorna o nome genérico do elemento de despesa (sem subelemento)."""
    elementos = _carregar_elementos()
    return elementos.get(elemento)


def natureza_elemento(elemento: int) -> str:
    """
    Retorna a natureza genérica do elemento:
    'material', 'servico_pj', 'servico_pf', 'passagem', 'permanente', 'outro'
    """
    return _NATUREZA_ELEMENTO.get(elemento, "outro")


# ══════════════════════════════════════════════════════════════════════
# VALIDAÇÃO: ND/SI × DESCRIÇÃO DO ITEM
# ══════════════════════════════════════════════════════════════════════

def _detectar_natureza_descricao(descricao: str) -> str | None:
    """
    Analisa a descrição do item e tenta inferir sua natureza:
    'material', 'servico' ou None (inconclusivo).
    """
    if not descricao:
        return None

    desc_lower = descricao.lower()

    pontos_material = sum(1 for kw in _KW_MATERIAL if kw in desc_lower)
    pontos_servico  = sum(1 for kw in _KW_SERVICO  if kw in desc_lower)
    pontos_perm     = sum(1 for kw in _KW_PERMANENTE if kw in desc_lower)

    # Se tem pontos dos dois lados e a diferença é pequena → inconclusivo
    total = pontos_material + pontos_servico + pontos_perm
    if total == 0:
        return None

    if pontos_material > pontos_servico and pontos_material > pontos_perm:
        return "material"
    if pontos_servico > pontos_material and pontos_servico > pontos_perm:
        return "servico"
    if pontos_perm > pontos_material and pontos_perm > pontos_servico:
        return "permanente"

    return None  # empate → inconclusivo


def validar_item(
    nd_si: str | None,
    descricao: str | None,
    nd_processo: str | None = None,
) -> dict | None:
    """
    Valida a compatibilidade entre ND/SI e a descrição de um item.

    Parâmetros:
        nd_si:        campo ND/SI da tabela de itens (ex: "39.17", "33.90.39/24")
        descricao:    texto descritivo do item
        nd_processo:  ND geral do processo (ex: "339030") — usada como fallback

    Retorna dict com:
        compativel:  True/False
        mensagem:    texto descritivo do achado
        nd_nome:     nome da classificação ND/SI consultada
        elem:        código do elemento
        si:          código do subelemento
    Ou None se não for possível validar.
    """
    # Tentar parse do ND/SI do item
    elem, si = parse_nd_si(nd_si)

    # Se não conseguiu do item, tentar da ND do processo
    if elem is None and nd_processo:
        elem = parse_nd_completa(nd_processo)
        si = None

    if elem is None:
        return None  # sem dados para validar

    # Consultar nome na tabela
    nd_nome = consultar(elem, si or 0)
    elem_nome = nome_elemento(elem) or f"Elemento {elem}"

    # Classificar natureza do elemento (ND)
    nat_nd = natureza_elemento(elem)

    # Classificar natureza da descrição
    nat_desc = _detectar_natureza_descricao(descricao or "")

    if nat_desc is None:
        # Inconclusivo — não penalizar
        return {
            "compativel": True,
            "mensagem": f"ND {elem} ({elem_nome}) — verificação inconclusiva",
            "nd_nome": nd_nome,
            "elem": elem,
            "si": si,
        }

    # Verificar compatibilidade
    compativel = True
    mensagem = ""

    # Material na ND × Serviço na descrição (ou vice-versa)
    if nat_nd == "material" and nat_desc == "servico":
        compativel = False
        mensagem = (
            f"ND indica MATERIAL ({elem_nome}), "
            f"mas descrição sugere SERVIÇO"
        )
    elif nat_nd in ("servico_pj", "servico_pf", "servico") and nat_desc == "material":
        compativel = False
        mensagem = (
            f"ND indica SERVIÇO ({elem_nome}), "
            f"mas descrição sugere MATERIAL"
        )
    elif nat_nd == "permanente" and nat_desc in ("material", "servico"):
        # Material permanente × consumo ou serviço
        if nat_desc == "servico":
            compativel = False
            mensagem = (
                f"ND indica EQUIPAMENTO PERMANENTE ({elem_nome}), "
                f"mas descrição sugere SERVIÇO"
            )
    elif nat_nd == "material" and nat_desc == "permanente":
        compativel = False
        mensagem = (
            f"ND indica MATERIAL DE CONSUMO ({elem_nome}), "
            f"mas descrição sugere EQUIPAMENTO PERMANENTE"
        )

    if compativel:
        # SI específico
        si_info = ""
        if si is not None and nd_nome:
            si_info = f", SI {si:02d} ({nd_nome})"
        mensagem = f"ND {elem} ({elem_nome}){si_info} — compatível"

    return {
        "compativel": compativel,
        "mensagem": mensagem,
        "nd_nome": nd_nome,
        "elem": elem,
        "si": si,
    }

