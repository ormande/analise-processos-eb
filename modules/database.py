"""
Schema do banco de dados SQLite.
Cria as tabelas na primeira execução.

Inclui funções para salvar, listar e carregar análises realizadas
(histórico completo do sistema).
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = "data/analise_processos.db"


def init_database():
    """Cria o banco e as tabelas se não existirem."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tabela de Naturezas da Despesa e Subelementos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nd_subelementos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria_economica TEXT,
            grupo_despesa TEXT,
            modalidade TEXT,
            elemento TEXT,
            subelemento TEXT,
            codigo_completo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabela de UASGs conhecidas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uasgs (
            codigo TEXT PRIMARY KEY,
            nome_om TEXT NOT NULL,
            primeiro_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ultimo_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # UASGs iniciais (mais usadas pelo 9º Gpt Log)
    uasgs_iniciais = [
        ("160136", "9º Gpt Log"),
        ("160141", "CRO/9"),
        ("160142", "9º B Sup"),
        ("160143", "H Mil A CG"),
        ("160078", "CMCG"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO uasgs (codigo, nome_om) VALUES (?, ?)",
        uasgs_iniciais,
    )

    # ── Tabela principal de análises realizadas ──────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nup TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resultado TEXT NOT NULL,
            om_requisitante TEXT,
            fornecedor TEXT,
            cnpj TEXT,
            valor_total REAL,
            tipo_processo TEXT,
            instrumento TEXT,
            mascara_ne TEXT,
            despacho TEXT,
            dados_completos TEXT,
            observacoes TEXT
        )
    """)

    # ── Tabela de pregões (banco orgânico) ──────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pregoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            uasg_gerenciadora TEXT,
            nome_om_gerenciadora TEXT,
            objeto TEXT,
            fornecedores TEXT DEFAULT '[]',
            itens TEXT DEFAULT '[]',
            processos_vinculados TEXT DEFAULT '[]',
            primeiro_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ultimo_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Tabela de contratos (banco orgânico) ─────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contratos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            uasg_contratante TEXT,
            nome_contratante TEXT,
            cnpj_contratante TEXT,
            contratada TEXT,
            cnpj_contratada TEXT,
            objeto TEXT,
            valor_total TEXT,
            vigencia_inicio TEXT,
            vigencia_fim TEXT,
            pregao_origem TEXT,
            tem_assinaturas INTEGER DEFAULT 0,
            processos_vinculados TEXT DEFAULT '[]',
            primeiro_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ultimo_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migração: adicionar colunas novas se tabela já existia
    _migrar_tabela_analises(cursor)

    conn.commit()
    conn.close()


def _migrar_tabela_analises(cursor: sqlite3.Cursor) -> None:
    """
    Adiciona colunas novas à tabela analises se ainda não existem.
    Permite evolução do schema sem perder dados antigos.
    """
    colunas_existentes = set()
    try:
        cursor.execute("PRAGMA table_info(analises)")
        for row in cursor.fetchall():
            colunas_existentes.add(row[1])  # nome da coluna
    except Exception:
        return

    novas_colunas = {
        "tipo_processo":  "TEXT",
        "instrumento":    "TEXT",
        "dados_completos": "TEXT",
    }
    for col, tipo in novas_colunas.items():
        if col not in colunas_existentes:
            try:
                cursor.execute(f"ALTER TABLE analises ADD COLUMN {col} {tipo}")
                print(f"[DB] Coluna '{col}' adicionada à tabela analises")
            except Exception:
                pass  # Coluna já existe ou outro erro


def get_connection():
    """Retorna conexão com o banco."""
    return sqlite3.connect(DB_PATH)


# ══════════════════════════════════════════════════════════════════════
# UASGs
# ══════════════════════════════════════════════════════════════════════

def registrar_uasg(codigo: str, nome_om: str) -> None:
    """Registra UASG nova ou atualiza último uso."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO uasgs (codigo, nome_om)
           VALUES (?, ?)
           ON CONFLICT(codigo) DO UPDATE SET ultimo_uso = CURRENT_TIMESTAMP""",
        (codigo, nome_om),
    )
    conn.commit()
    conn.close()


def listar_uasgs() -> list[tuple]:
    """Retorna todas as UASGs cadastradas."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo, nome_om FROM uasgs ORDER BY codigo")
    resultado = cursor.fetchall()
    conn.close()
    return resultado


# ══════════════════════════════════════════════════════════════════════
# HISTÓRICO DE ANÁLISES
# ══════════════════════════════════════════════════════════════════════

def salvar_analise(
    nup: str,
    resultado_tipo: str,
    identificacao: dict,
    itens: list[dict],
    nota_credito: list[dict],
    certidoes: list[dict],
    validacoes_req: dict,
    validacoes_nc: list | dict,
    resultado_validacao: dict,
    mascara_ne: Optional[str] = None,
    despacho: Optional[str] = None,
    divergencias_mascara: Optional[list[dict]] = None,
    observacoes: Optional[str] = None,
) -> int:
    """
    Salva uma análise completa no banco de dados.

    Armazena:
    - Campos principais em colunas individuais (para consulta rápida)
    - Todos os dados detalhados em JSON (campo dados_completos)

    Retorna o ID da análise salva.
    """
    # Calcular valor total dos itens
    valor_total = 0.0
    for item in itens:
        try:
            vt = item.get("valor_total") or item.get("total") or 0
            if isinstance(vt, str):
                vt = vt.replace("R$", "").replace(".", "").replace(",", ".").strip()
            valor_total += float(vt)
        except (ValueError, TypeError):
            pass

    # Montar JSON completo com todos os dados
    dados_completos = {
        "identificacao": identificacao,
        "itens": itens,
        "nota_credito": nota_credito,
        "certidoes": certidoes,
        "validacoes_req": validacoes_req,
        "validacoes_nc": validacoes_nc,
        "resultado": resultado_validacao,
        "divergencias_mascara": divergencias_mascara or [],
    }

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO analises
           (nup, resultado, om_requisitante, fornecedor, cnpj,
            valor_total, tipo_processo, instrumento,
            mascara_ne, despacho, dados_completos, observacoes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            nup,
            resultado_tipo,
            identificacao.get("om", ""),
            identificacao.get("fornecedor", ""),
            identificacao.get("cnpj", ""),
            valor_total if valor_total > 0 else None,
            identificacao.get("tipo", ""),
            identificacao.get("instrumento", ""),
            mascara_ne,
            despacho,
            json.dumps(dados_completos, ensure_ascii=False, default=str),
            observacoes,
        ),
    )
    analise_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Registrar UASG se encontrada
    uasg = identificacao.get("uasg")
    om = identificacao.get("om", "")
    if uasg:
        registrar_uasg(uasg, om)

    print(f"[DB] Análise salva — ID {analise_id}, NUP {nup}")
    return analise_id


def listar_analises(limite: int = 50) -> list[dict]:
    """
    Retorna as últimas análises realizadas (sem dados_completos).

    Cada item retornado tem:
        id, nup, data_analise, resultado, om_requisitante,
        fornecedor, cnpj, valor_total, tipo_processo, instrumento.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, nup, data_analise, resultado, om_requisitante,
                  fornecedor, cnpj, valor_total, tipo_processo, instrumento
           FROM analises
           ORDER BY data_analise DESC
           LIMIT ?""",
        (limite,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def carregar_analise(analise_id: int) -> Optional[dict]:
    """
    Carrega uma análise completa pelo ID.

    Retorna dict com todos os campos + dados_completos desserializado.
    Retorna None se não encontrar.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, nup, data_analise, resultado, om_requisitante,
                  fornecedor, cnpj, valor_total, tipo_processo, instrumento,
                  mascara_ne, despacho, dados_completos, observacoes
           FROM analises
           WHERE id = ?""",
        (analise_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    analise = dict(row)

    # Desserializar JSON dos dados completos
    dados_json = analise.get("dados_completos")
    if dados_json:
        try:
            analise["dados_completos"] = json.loads(dados_json)
        except (json.JSONDecodeError, TypeError):
            analise["dados_completos"] = {}

    return analise


def excluir_analise(analise_id: int) -> bool:
    """
    Exclui uma análise pelo ID.
    Retorna True se excluiu, False se não encontrou.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analises WHERE id = ?", (analise_id,))
    excluiu = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return excluiu


def contar_analises() -> int:
    """Retorna o total de análises no banco."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM analises")
    total = cursor.fetchone()[0]
    conn.close()
    return total


# ══════════════════════════════════════════════════════════════════════
# BASE DE PREGÕES (banco orgânico)
# ══════════════════════════════════════════════════════════════════════

def registrar_pregao(
    numero: str,
    uasg_gerenciadora: Optional[str] = None,
    nome_om_gerenciadora: Optional[str] = None,
    objeto: Optional[str] = None,
    fornecedor: Optional[dict] = None,
    itens: Optional[list[dict]] = None,
    nup: Optional[str] = None,
) -> int:
    """
    Registra ou atualiza um pregão no banco de dados.

    Se o pregão já existe (mesmo número), faz MERGE:
    - Adiciona fornecedor à lista (sem duplicar CNPJ)
    - Adiciona itens à lista (sem duplicar descrição)
    - Adiciona NUP aos processos vinculados (sem duplicar)
    - Atualiza objeto/OM se estiverem vazios

    Retorna o ID do pregão (novo ou existente).
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Verificar se já existe
    cursor.execute("SELECT * FROM pregoes WHERE numero = ?", (numero,))
    existente = cursor.fetchone()

    if existente:
        existente = dict(existente)
        pregao_id = existente["id"]

        # ── Merge de fornecedores ──
        fornecedores_atuais = _json_load(existente.get("fornecedores", "[]"))
        if fornecedor and fornecedor.get("cnpj"):
            cnpjs_existentes = {f.get("cnpj") for f in fornecedores_atuais}
            if fornecedor["cnpj"] not in cnpjs_existentes:
                fornecedores_atuais.append(fornecedor)

        # ── Merge de itens ──
        itens_atuais = _json_load(existente.get("itens", "[]"))
        if itens:
            descricoes_existentes = {
                i.get("descricao", "").strip().upper()
                for i in itens_atuais
            }
            for item in itens:
                desc_norm = (item.get("descricao") or "").strip().upper()
                if desc_norm and desc_norm not in descricoes_existentes:
                    itens_atuais.append(item)
                    descricoes_existentes.add(desc_norm)

        # ── Merge de processos vinculados ──
        processos = _json_load(existente.get("processos_vinculados", "[]"))
        if nup and nup not in processos:
            processos.append(nup)

        # ── Atualizar campos que estavam vazios ──
        novo_objeto = existente.get("objeto") or objeto
        nova_om = existente.get("nome_om_gerenciadora") or nome_om_gerenciadora
        nova_uasg = existente.get("uasg_gerenciadora") or uasg_gerenciadora

        cursor.execute(
            """UPDATE pregoes
               SET uasg_gerenciadora = ?,
                   nome_om_gerenciadora = ?,
                   objeto = ?,
                   fornecedores = ?,
                   itens = ?,
                   processos_vinculados = ?,
                   ultimo_uso = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                nova_uasg,
                nova_om,
                novo_objeto,
                json.dumps(fornecedores_atuais, ensure_ascii=False),
                json.dumps(itens_atuais, ensure_ascii=False, default=str),
                json.dumps(processos, ensure_ascii=False),
                pregao_id,
            ),
        )
        print(f"[DB] Pregão {numero} atualizado (ID {pregao_id})")
    else:
        # ── Novo pregão ──
        fornecedores_lista = [fornecedor] if fornecedor and fornecedor.get("cnpj") else []
        itens_lista = itens or []
        processos_lista = [nup] if nup else []

        cursor.execute(
            """INSERT INTO pregoes
               (numero, uasg_gerenciadora, nome_om_gerenciadora, objeto,
                fornecedores, itens, processos_vinculados)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                numero,
                uasg_gerenciadora,
                nome_om_gerenciadora,
                objeto,
                json.dumps(fornecedores_lista, ensure_ascii=False),
                json.dumps(itens_lista, ensure_ascii=False, default=str),
                json.dumps(processos_lista, ensure_ascii=False),
            ),
        )
        pregao_id = cursor.lastrowid
        print(f"[DB] Pregão {numero} registrado (ID {pregao_id})")

    conn.commit()
    conn.close()
    return pregao_id


def listar_pregoes(limite: int = 50) -> list[dict]:
    """
    Retorna os pregões cadastrados, ordenados pelo último uso.
    Desserializa os campos JSON automaticamente.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, numero, uasg_gerenciadora, nome_om_gerenciadora,
                  objeto, fornecedores, itens, processos_vinculados,
                  primeiro_uso, ultimo_uso
           FROM pregoes
           ORDER BY ultimo_uso DESC
           LIMIT ?""",
        (limite,),
    )
    rows = cursor.fetchall()
    conn.close()

    resultado = []
    for r in rows:
        d = dict(r)
        d["fornecedores"] = _json_load(d.get("fornecedores", "[]"))
        d["itens"] = _json_load(d.get("itens", "[]"))
        d["processos_vinculados"] = _json_load(d.get("processos_vinculados", "[]"))
        resultado.append(d)

    return resultado


def buscar_pregao(numero: str) -> Optional[dict]:
    """
    Busca um pregão pelo número exato (ex: '90004/2025').
    Retorna dict com dados desserializados ou None.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pregoes WHERE numero = ?", (numero,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    d = dict(row)
    d["fornecedores"] = _json_load(d.get("fornecedores", "[]"))
    d["itens"] = _json_load(d.get("itens", "[]"))
    d["processos_vinculados"] = _json_load(d.get("processos_vinculados", "[]"))
    return d


def contar_pregoes() -> int:
    """Retorna o total de pregões no banco."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM pregoes")
    total = cursor.fetchone()[0]
    conn.close()
    return total


def _json_load(valor: str) -> list | dict:
    """Carrega JSON de forma segura, retornando [] em caso de erro."""
    if not valor:
        return []
    try:
        return json.loads(valor)
    except (json.JSONDecodeError, TypeError):
        return []


# ══════════════════════════════════════════════════════════════════════
# BASE DE CONTRATOS (banco orgânico)
# ══════════════════════════════════════════════════════════════════════

def _normalizar_numero_contrato(numero: str) -> str:
    """
    Normaliza o número do contrato para comparação e armazenamento.
    '59/2024' e '059/2024' viram '059/2024' (3 dígitos + / + 4 dígitos).
    """
    if not numero:
        return numero
    partes = numero.split("/")
    if len(partes) != 2:
        return numero
    nr, ano = partes[0].strip(), partes[1].strip()
    return f"{nr.zfill(3)}/{ano}"


def registrar_contrato(
    numero: str,
    uasg_contratante: Optional[str] = None,
    nome_contratante: Optional[str] = None,
    cnpj_contratante: Optional[str] = None,
    contratada: Optional[str] = None,
    cnpj_contratada: Optional[str] = None,
    objeto: Optional[str] = None,
    valor_total: Optional[str] = None,
    vigencia_inicio: Optional[str] = None,
    vigencia_fim: Optional[str] = None,
    pregao_origem: Optional[str] = None,
    tem_assinaturas: bool = False,
    nup: Optional[str] = None,
) -> int:
    """
    Registra ou atualiza um contrato no banco de dados.

    Se o contrato já existe (mesmo número normalizado), faz MERGE:
    - Adiciona NUP aos processos vinculados (sem duplicar)
    - Atualiza campos que estavam vazios

    Retorna o ID do contrato (novo ou existente).
    """
    numero_norm = _normalizar_numero_contrato(numero)
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Verificar se já existe
    cursor.execute("SELECT * FROM contratos WHERE numero = ?", (numero_norm,))
    existente = cursor.fetchone()

    if existente:
        existente = dict(existente)
        contrato_id = existente["id"]

        # ── Merge de processos vinculados ──
        processos = _json_load(existente.get("processos_vinculados", "[]"))
        if nup and nup not in processos:
            processos.append(nup)

        # ── Atualizar campos que estavam vazios ──
        cursor.execute(
            """UPDATE contratos
               SET uasg_contratante = COALESCE(NULLIF(uasg_contratante, ''), ?),
                   nome_contratante = COALESCE(NULLIF(nome_contratante, ''), ?),
                   cnpj_contratante = COALESCE(NULLIF(cnpj_contratante, ''), ?),
                   contratada = COALESCE(NULLIF(contratada, ''), ?),
                   cnpj_contratada = COALESCE(NULLIF(cnpj_contratada, ''), ?),
                   objeto = COALESCE(NULLIF(objeto, ''), ?),
                   valor_total = COALESCE(NULLIF(valor_total, ''), ?),
                   vigencia_inicio = COALESCE(NULLIF(vigencia_inicio, ''), ?),
                   vigencia_fim = COALESCE(NULLIF(vigencia_fim, ''), ?),
                   pregao_origem = COALESCE(NULLIF(pregao_origem, ''), ?),
                   tem_assinaturas = MAX(tem_assinaturas, ?),
                   processos_vinculados = ?,
                   ultimo_uso = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                uasg_contratante, nome_contratante, cnpj_contratante,
                contratada, cnpj_contratada, objeto, valor_total,
                vigencia_inicio, vigencia_fim, pregao_origem,
                1 if tem_assinaturas else 0,
                json.dumps(processos, ensure_ascii=False),
                contrato_id,
            ),
        )
        print(f"[DB] Contrato {numero_norm} atualizado (ID {contrato_id})")
    else:
        # ── Novo contrato ──
        processos_lista = [nup] if nup else []

        cursor.execute(
            """INSERT INTO contratos
               (numero, uasg_contratante, nome_contratante, cnpj_contratante,
                contratada, cnpj_contratada, objeto, valor_total,
                vigencia_inicio, vigencia_fim, pregao_origem,
                tem_assinaturas, processos_vinculados)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                numero_norm, uasg_contratante, nome_contratante,
                cnpj_contratante, contratada, cnpj_contratada,
                objeto, valor_total, vigencia_inicio, vigencia_fim,
                pregao_origem, 1 if tem_assinaturas else 0,
                json.dumps(processos_lista, ensure_ascii=False),
            ),
        )
        contrato_id = cursor.lastrowid
        print(f"[DB] Contrato {numero_norm} registrado (ID {contrato_id})")

    conn.commit()
    conn.close()
    return contrato_id


def listar_contratos(limite: int = 50) -> list[dict]:
    """
    Retorna os contratos cadastrados, ordenados pelo último uso.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT *
           FROM contratos
           ORDER BY ultimo_uso DESC
           LIMIT ?""",
        (limite,),
    )
    rows = cursor.fetchall()
    conn.close()

    resultado = []
    for r in rows:
        d = dict(r)
        d["processos_vinculados"] = _json_load(d.get("processos_vinculados", "[]"))
        resultado.append(d)
    return resultado


def buscar_contrato(numero: str) -> Optional[dict]:
    """
    Busca um contrato pelo número (normaliza automaticamente).
    Retorna dict ou None.
    """
    numero_norm = _normalizar_numero_contrato(numero)
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM contratos WHERE numero = ?", (numero_norm,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    d = dict(row)
    d["processos_vinculados"] = _json_load(d.get("processos_vinculados", "[]"))
    return d


def contar_contratos() -> int:
    """Retorna o total de contratos no banco."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM contratos")
    total = cursor.fetchone()[0]
    conn.close()
    return total
