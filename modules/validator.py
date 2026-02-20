# ══════════════════════════════════════════════════════════════════════
# modules/validator.py — Validações cruzadas e consolidação do resultado
# ══════════════════════════════════════════════════════════════════════
"""
Módulo responsável por:
1. Validação cruzada de CNPJ entre peças (Requisição × SICAF × CADIN × Consulta)
2. Validação cruzada de Razão Social
3. Consolidação de TODAS as validações (req, NC, certidões) em um resultado final
4. Determinação automática do tipo de decisão (aprovação / ressalva / reprovação)

Regras de severidade (conforme ESPECIFICACAO_LOGICA_NEGOCIO_v2.md):
  🟢 conforme  — verificado e aprovado
  ⚠️ ressalva  — sinalização, analista decide
  🔴 bloqueio  — provável reprovação, analista investiga
"""

from __future__ import annotations

from modules import nd_lookup


# ══════════════════════════════════════════════════════════════════════
# VALIDAÇÃO CRUZADA DE CNPJ
# ══════════════════════════════════════════════════════════════════════

def _normalizar_cnpj(cnpj: str | None) -> str | None:
    """Remove formatação do CNPJ para comparação. Ex: 12.345.678/0001-90 → 12345678000190"""
    if not cnpj:
        return None
    return cnpj.replace(".", "").replace("/", "").replace("-", "").strip()


def _validar_cnpj_cruzado(res: dict) -> list[dict]:
    """
    Compara o CNPJ do fornecedor (requisição) com os CNPJs encontrados
    nas certidões (SICAF, CADIN, Consulta Consolidada).

    Regras:
    - CNPJ igual em todas as peças → 🟢 conforme
    - CNPJ divergente em qualquer peça → 🔴 bloqueio
    - Peça sem CNPJ extraído → ignorar (não penalizar)
    """
    ident = res.get("identificacao", {})
    certidoes_raw = res.get("certidoes", {})

    cnpj_req = ident.get("cnpj")
    cnpj_req_norm = _normalizar_cnpj(cnpj_req)

    # Coletar CNPJs de cada peça
    pecas_cnpj = {}

    sicaf = certidoes_raw.get("sicaf", {})
    if sicaf.get("cnpj"):
        pecas_cnpj["SICAF"] = sicaf["cnpj"]

    cadin = certidoes_raw.get("cadin", {})
    if cadin.get("cnpj"):
        pecas_cnpj["CADIN"] = cadin["cnpj"]

    consulta = certidoes_raw.get("consulta_consolidada", {})
    if consulta.get("cnpj"):
        pecas_cnpj["Consulta Consolidada"] = consulta["cnpj"]

    resultados = []

    if not cnpj_req:
        # Sem CNPJ na requisição — não dá pra cruzar
        resultados.append({
            "verificacao": "CNPJ cruzado entre peças",
            "descricao": "CNPJ não extraído da requisição — verificar manualmente",
            "severidade": "ressalva",
        })
        return resultados

    if not pecas_cnpj:
        # Sem certidões com CNPJ — nada a comparar
        resultados.append({
            "verificacao": "CNPJ cruzado entre peças",
            "descricao": "Nenhuma certidão com CNPJ para comparar",
            "severidade": "conforme",
        })
        return resultados

    # Comparar cada peça
    divergencias = []
    for nome_peca, cnpj_peca in pecas_cnpj.items():
        cnpj_peca_norm = _normalizar_cnpj(cnpj_peca)
        if cnpj_peca_norm != cnpj_req_norm:
            divergencias.append(
                f"{nome_peca}: {cnpj_peca} ≠ Req: {cnpj_req}"
            )

    if divergencias:
        for div in divergencias:
            resultados.append({
                "verificacao": "CNPJ cruzado entre peças",
                "descricao": f"CNPJ divergente — {div}",
                "severidade": "bloqueio",
            })
    else:
        pecas_str = ", ".join(pecas_cnpj.keys())
        resultados.append({
            "verificacao": "CNPJ cruzado entre peças",
            "descricao": f"CNPJ consistente em todas as peças ({pecas_str})",
            "severidade": "conforme",
        })

    return resultados


# ══════════════════════════════════════════════════════════════════════
# VALIDAÇÃO CRUZADA DE RAZÃO SOCIAL
# ══════════════════════════════════════════════════════════════════════

def _validar_razao_social(res: dict) -> list[dict]:
    """
    Compara a razão social / nome do fornecedor (requisição) com o SICAF.

    Regras:
    - Nome igual → 🟢 conforme
    - Nome diferente com CNPJ OK → ⚠️ ressalva (possível nome fantasia vs razão social)
    - Sem dados para comparar → ignorar
    """
    ident = res.get("identificacao", {})
    certidoes_raw = res.get("certidoes", {})
    sicaf = certidoes_raw.get("sicaf", {})

    nome_req = (ident.get("fornecedor") or "").strip().upper()
    nome_sicaf = (sicaf.get("razao_social") or "").strip().upper()

    if not nome_req or not nome_sicaf:
        return []  # sem dados para comparar

    if nome_req == nome_sicaf:
        return [{
            "verificacao": "Razão Social (Req vs SICAF)",
            "descricao": f"Razão Social consistente: {sicaf.get('razao_social')}",
            "severidade": "conforme",
        }]

    # Verificar se CNPJ confere (mesmo com nome diferente)
    cnpj_req_norm = _normalizar_cnpj(ident.get("cnpj"))
    cnpj_sicaf_norm = _normalizar_cnpj(sicaf.get("cnpj"))
    cnpj_ok = cnpj_req_norm and cnpj_sicaf_norm and cnpj_req_norm == cnpj_sicaf_norm

    if cnpj_ok:
        return [{
            "verificacao": "Razão Social (Req vs SICAF)",
            "descricao": (
                f'Razão Social divergente: Requisição diz '
                f'"{ident.get("fornecedor")}", SICAF diz '
                f'"{sicaf.get("razao_social")}" '
                f'(CNPJ confere: {sicaf.get("cnpj")})'
            ),
            "severidade": "ressalva",
        }]

    return [{
        "verificacao": "Razão Social (Req vs SICAF)",
        "descricao": (
            f'Razão Social divergente e CNPJ não confere: '
            f'Req: "{ident.get("fornecedor")}" / '
            f'SICAF: "{sicaf.get("razao_social")}"'
        ),
        "severidade": "bloqueio",
    }]


# ══════════════════════════════════════════════════════════════════════
# VALIDAÇÃO INTERNA: ND/SI × DESCRIÇÃO DOS ITENS
# ══════════════════════════════════════════════════════════════════════

def _validar_nd_itens(res: dict) -> list[dict]:
    """
    Valida a compatibilidade entre a ND/SI indicada em cada item
    e a descrição do item, usando a tabela oficial de ND.

    Validação interna — não aparece como seção na interface,
    mas contribui para o resultado (⚠️ ressalva se incompatível).

    Regras (ESPECIFICACAO_LOGICA_NEGOCIO_v2):
    - ND de Material (30) com descrição de Serviço → ⚠️ AMARELO
    - ND de Serviço (39) com descrição de Material → ⚠️ AMARELO
    - Incompatibilidade não gera reprovação automática
    """
    itens = res.get("itens", [])
    ident = res.get("identificacao", {})
    nd_processo = ident.get("nd")

    if not itens:
        return []

    achados = []
    itens_ok = 0
    itens_incomp = 0

    for item in itens:
        nd_si = item.get("nd_si")
        descricao = item.get("descricao")
        num_item = item.get("item", "?")

        resultado = nd_lookup.validar_item(nd_si, descricao, nd_processo)

        if resultado is None:
            continue  # sem dados para validar

        if not resultado["compativel"]:
            itens_incomp += 1
            elem = resultado.get("elem")
            si = resultado.get("si")
            nd_nome = resultado.get("nd_nome") or ""

            # Montar descrição detalhada
            nd_si_fmt = f"{elem}"
            if si is not None:
                nd_si_fmt += f"/{si:02d}"
                if nd_nome:
                    nd_si_fmt += f" ({nd_nome})"

            achados.append({
                "verificacao": f"ND/SI × Descrição (Item {num_item})",
                "descricao": (
                    f"Item {num_item}: {resultado['mensagem']} "
                    f"— verificar ND/SI"
                ),
                "severidade": "ressalva",
            })
        else:
            itens_ok += 1

    # Se todos OK, registrar como conforme
    if itens_ok > 0 and itens_incomp == 0:
        achados.append({
            "verificacao": "ND/SI × Descrição dos itens",
            "descricao": "ND/SI compatível com a descrição dos itens",
            "severidade": "conforme",
        })

    return achados


# ══════════════════════════════════════════════════════════════════════
# CONSOLIDAÇÃO DO RESULTADO
# ══════════════════════════════════════════════════════════════════════

def _coletar_achados_req(validacoes_req: dict) -> list[dict]:
    """Converte validações da requisição (itens/cálculos) em achados."""
    achados = []

    # Verificar cálculos
    tem_divergencia = False
    for chave, val in validacoes_req.items():
        if chave.startswith("calculo_item_") and val["status"] == "ressalva":
            tem_divergencia = True
            achados.append({
                "verificacao": val["texto"],
                "descricao": val["resultado"],
                "severidade": "ressalva",
            })

    if not tem_divergencia:
        # Verificar se há itens (pode não ter por causa de OCR)
        sem_itens = validacoes_req.get("sem_itens")
        if sem_itens:
            achados.append({
                "verificacao": "Itens da requisição",
                "descricao": "Itens não extraídos automaticamente — verificar PDF",
                "severidade": "ressalva",
            })
        else:
            achados.append({
                "verificacao": "Cálculos da requisição",
                "descricao": "Cálculos da requisição corretos",
                "severidade": "conforme",
            })

    return achados


def _coletar_achados_nc(validacoes_nc: list) -> list[dict]:
    """Converte validações cruzadas NC em achados."""
    achados = []
    for val in validacoes_nc:
        achados.append({
            "verificacao": val["verificacao"],
            "descricao": val["resultado"],
            "severidade": val["status"],
        })
    return achados


def _coletar_achados_certidoes(certidoes: list) -> list[dict]:
    """
    Converte dados de certidões já processados (com status) em achados.
    Agrupa por tipo para evitar repetição excessiva na lista final.
    """
    achados = []

    # Agrupar certidões por tipo principal (indent == 0)
    tipos_bloqueio = []
    tipos_ressalva = []
    tipos_conforme = []

    for cert in certidoes:
        nome = cert.get("certidao", "")
        status = cert.get("status", "conforme")
        resultado = cert.get("resultado", "")
        validade = cert.get("validade", "—")
        indent = cert.get("indent", 0)

        if status == "bloqueio":
            # Detalhar cada bloqueio
            if indent == 0:
                tipos_bloqueio.append(f"{nome}: {resultado}")
            else:
                if validade and validade != "—":
                    tipos_bloqueio.append(f"{nome}: {validade}")
                else:
                    tipos_bloqueio.append(f"{nome}: {resultado}")
        elif status == "ressalva":
            if indent == 0:
                tipos_ressalva.append(f"{nome}: {resultado}")
            else:
                if validade and validade != "—":
                    tipos_ressalva.append(f"{nome}: {validade}")
                else:
                    tipos_ressalva.append(f"{nome}: {resultado}")

    # Gerar achados
    for desc in tipos_bloqueio:
        achados.append({
            "verificacao": "Certidões",
            "descricao": desc,
            "severidade": "bloqueio",
        })

    for desc in tipos_ressalva:
        achados.append({
            "verificacao": "Certidões",
            "descricao": desc,
            "severidade": "ressalva",
        })

    # Se nenhum bloqueio nem ressalva em certidões
    if not tipos_bloqueio and not tipos_ressalva and certidoes:
        achados.append({
            "verificacao": "Certidões",
            "descricao": "Todas as certidões regulares e vigentes",
            "severidade": "conforme",
        })

    return achados


def validar_processo(
    res: dict,
    validacoes_req: dict,
    validacoes_nc: list,
    certidoes: list,
    analise_sem_nc: bool = False,
) -> dict:
    """
    Consolida TODAS as validações do processo e determina o resultado final.

    Parâmetros:
        res:             dados brutos extraídos pelo extractor
        validacoes_req:  dict com validações dos itens/cálculos (de _calcular_validacoes_req)
        validacoes_nc:   lista de validações cruzadas NC (de _calcular_validacoes_nc)
        certidoes:       lista de certidões já adaptadas (de _adaptar_certidoes)
        analise_sem_nc:  True se o modo "Análise sem NC" está ativo

    Retorna dict com:
        tipo:       "approval" | "caveat" | "rejection"
        titulo:     texto do banner (ex: "✅ APROVAÇÃO")
        ressalvas:  lista de strings descrevendo problemas
        conformes:  lista de strings descrevendo pontos OK
    """
    todos_achados = []

    # 1. Validação cruzada de CNPJ
    todos_achados.extend(_validar_cnpj_cruzado(res))

    # 2. Validação cruzada de Razão Social
    todos_achados.extend(_validar_razao_social(res))

    # 3. Validações da requisição (cálculos dos itens)
    todos_achados.extend(_coletar_achados_req(validacoes_req))

    # 4. Validação interna ND/SI × descrição dos itens
    todos_achados.extend(_validar_nd_itens(res))

    # 5. Validações cruzadas NC (só se não for análise sem NC)
    if not analise_sem_nc:
        todos_achados.extend(_coletar_achados_nc(validacoes_nc))

    # 6. Certidões
    todos_achados.extend(_coletar_achados_certidoes(certidoes))

    # ── Separar em listas de ressalvas e conformes ──
    ressalvas = []
    conformes = []
    tem_bloqueio = False
    tem_ressalva = False

    for achado in todos_achados:
        sev = achado["severidade"]
        desc = achado["descricao"]

        # Limpar emojis duplicados para a lista final
        desc_limpo = (
            desc.replace("⚠️ ", "").replace("✅ ", "")
            .replace("🟢 ", "").replace("🔴 ", "")
            .replace("❌ ", "").strip()
        )

        if sev == "bloqueio":
            tem_bloqueio = True
            ressalvas.append(desc_limpo)
        elif sev == "ressalva":
            tem_ressalva = True
            ressalvas.append(desc_limpo)
        else:
            conformes.append(desc_limpo)

    # ── Determinar tipo de resultado ──
    if tem_bloqueio:
        tipo = "rejection"
        titulo = "❌ REPROVAÇÃO"
    elif tem_ressalva:
        tipo = "caveat"
        titulo = "⚠️ APROVAÇÃO COM RESSALVA"
    else:
        tipo = "approval"
        titulo = "✅ APROVAÇÃO"

    # Nota sobre análise parcial (sem NC)
    if analise_sem_nc and tipo == "approval":
        titulo = "✅ APROVAÇÃO (PARCIAL — AGUARDANDO NC)"

    return {
        "tipo": tipo,
        "titulo": titulo,
        "ressalvas": ressalvas,
        "conformes": conformes,
    }

