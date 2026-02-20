# ══════════════════════════════════════════════════════════════════════
# modules/despacho_generator.py — Gerador de texto de despacho
# ══════════════════════════════════════════════════════════════════════
"""
Gera automaticamente o corpo do texto de despacho com base nos achados
da análise (ressalvas e bloqueios).

REGRAS:
- Só gera despacho para RESSALVA e REPROVAÇÃO (aprovação = encaminhamento)
- Sempre começa com "Informo que..."
- Sem cabeçalho, sem data, sem OM, sem assinatura — só o corpo do texto
- O texto aparece numa caixa de texto editável na interface

Categorias de achados e templates correspondentes:
- Certidão vencida → "a certidão [nome] no SICAF encontra-se VENCIDA..."
- CNPJ divergente → "o CNPJ do [peça] anexado não corresponde..."
- Razão Social divergente → "a razão social na requisição diverge..."
- ND divergente → "a ND da NC diverge da ND da requisição..."
- Saldo insuficiente → "o saldo disponível é de R$ X, faltando R$ Y..."
- Prazo vencido → "o prazo de empenho da NC está vencido..."
- Cálculo divergente → "na tabela de requisição, o cálculo do item X..."
- Impedimento licitar → "consta impedimento de licitar no SICAF..."
- CADIN irregular → "a situação no CADIN encontra-se irregular..."
- TCU/CNJ/CEIS/CNEP → "consta registro no [cadastro]..."
"""

from __future__ import annotations
import re


def _formatar_nome_certidao(nome: str) -> str:
    """
    Formata nomes de certidão que podem vir como snake_case.
    Ex: 'fgts' → 'FGTS', 'receita_estadual' → 'Receita Estadual'
    """
    # Siglas que devem ficar em UPPER
    siglas = {"fgts": "FGTS", "cndt": "CNDT", "tcu": "TCU", "cnj": "CNJ",
              "ceis": "CEIS", "cnep": "CNEP", "cadin": "CADIN", "sicaf": "SICAF"}

    nome_limpo = nome.strip().lower().replace("_", " ")

    if nome_limpo in siglas:
        return siglas[nome_limpo]

    # Capitalizar cada palavra
    return nome_limpo.title()


def gerar_despacho(resultado: dict) -> str:
    """
    Gera o texto do despacho com base no resultado da análise.

    Parâmetros:
        resultado: dict retornado por validator.validar_processo() com:
            - tipo: "approval" | "caveat" | "rejection"
            - ressalvas: lista de strings descrevendo problemas

    Retorna:
        String com o corpo do despacho, ou "" se aprovação simples.
    """
    tipo = resultado.get("tipo", "approval")

    # Aprovação simples → sem despacho (apenas encaminhamento)
    if tipo == "approval":
        return ""

    ressalvas = resultado.get("ressalvas", [])
    if not ressalvas:
        return ""

    # Classificar e gerar frases para cada ressalva
    frases = []
    for ressalva in ressalvas:
        frase = _classificar_e_gerar_frase(ressalva)
        if frase:
            frases.append(frase)

    if not frases:
        # Fallback genérico
        return (
            "Informo que a presente requisição foi analisada "
            "e apresenta divergências que requerem atenção."
        )

    # Montar texto final
    if len(frases) == 1:
        return f"Informo que {frases[0]}"

    # Múltiplas ressalvas: primeira com "Informo que", demais com "Adicionalmente"
    texto = f"Informo que {frases[0]}"
    for frase in frases[1:]:
        texto += f" Adicionalmente, {frase}"

    return texto


def _classificar_e_gerar_frase(ressalva: str) -> str | None:
    """
    Classifica uma ressalva e gera a frase correspondente para o despacho.
    Retorna None se não conseguir classificar.
    """
    ressalva_upper = ressalva.upper()

    # ── Certidão vencida ──
    # Padrão: "Fgts: 15/02/2026 (-4 dias)" ou "Receita Federal: 01/01/2026 (49 dias vencida)"
    match_vencida = re.search(
        r"(.+?):\s*(\d{2}/\d{2}/\d{4})\s*\((\d+)\s*dias?\s*vencida?\)",
        ressalva, re.IGNORECASE
    )
    if match_vencida:
        nome_cert = _formatar_nome_certidao(match_vencida.group(1))
        data_cert = match_vencida.group(2)
        dias = match_vencida.group(3)
        return (
            f"a certidão de {nome_cert} no SICAF encontra-se "
            f"VENCIDA desde {data_cert} ({dias} dias)."
        )

    # Certidão vencendo (próxima)
    match_proxima = re.search(
        r"(.+?):\s*(\d{2}/\d{2}/\d{4})\s*\((\d+)\s*dias?\)",
        ressalva, re.IGNORECASE
    )
    if match_proxima:
        nome_cert = _formatar_nome_certidao(match_proxima.group(1))
        data_cert = match_proxima.group(2)
        dias = match_proxima.group(3)
        return (
            f"a certidão de {nome_cert} no SICAF possui validade "
            f"próxima ({data_cert}, {dias} dias restantes)."
        )

    # Certidão com data simples (sem dias calculados)
    match_cert_data = re.search(
        r"(.+?):\s*(\d{2}/\d{2}/\d{4})",
        ressalva
    )
    if match_cert_data and any(kw in ressalva_upper for kw in
        ["FGTS", "RECEITA", "TRABALHISTA", "QUALIF", "MUNICIPAL", "ESTADUAL",
         "FEDERAL"]):
        nome_cert = _formatar_nome_certidao(match_cert_data.group(1))
        data_cert = match_cert_data.group(2)
        return (
            f"a certidão de {nome_cert} no SICAF requer verificação "
            f"(validade: {data_cert})."
        )

    # ── CNPJ divergente ──
    if "CNPJ DIVERGENTE" in ressalva_upper or "CNPJ" in ressalva_upper and "≠" in ressalva:
        # Extrair peças envolvidas
        match_cnpj = re.search(r"(\w+):\s*([\d./-]+)\s*≠\s*Req:\s*([\d./-]+)", ressalva)
        if match_cnpj:
            peca = match_cnpj.group(1)
            cnpj_peca = match_cnpj.group(2)
            cnpj_req = match_cnpj.group(3)
            return (
                f"o CNPJ constante no {peca} ({cnpj_peca}) não corresponde "
                f"ao CNPJ do fornecedor requisitado ({cnpj_req})."
            )
        return "o CNPJ do fornecedor diverge entre as peças do processo."

    # ── CNPJ não extraído ──
    if "CNPJ NÃO EXTRAÍDO" in ressalva_upper:
        return (
            "não foi possível extrair o CNPJ da requisição para "
            "validação cruzada — verificar manualmente."
        )

    # ── Razão Social divergente ──
    if "RAZÃO SOCIAL DIVERGENTE" in ressalva_upper or "RAZÃO SOCIAL" in ressalva_upper:
        match_rs = re.search(
            r'Requisição diz "(.+?)".*SICAF diz "(.+?)"',
            ressalva
        )
        if match_rs:
            nome_req = match_rs.group(1)
            nome_sicaf = match_rs.group(2)
            cnpj_match = re.search(r"CNPJ confere:\s*([\d./-]+)", ressalva)
            cnpj_info = f" (CNPJ {cnpj_match.group(1)} confere)" if cnpj_match else ""
            return (
                f'a razão social na requisição ("{nome_req}") diverge '
                f'da razão social no SICAF ("{nome_sicaf}"){cnpj_info}.'
            )
        return "a razão social diverge entre a requisição e o SICAF."

    # ── ND divergente ──
    if "ND" in ressalva_upper and ("≠" in ressalva or "GENÉRICA" in ressalva_upper or "GENERICA" in ressalva_upper):
        if "GENÉRICA" in ressalva_upper or "GENERICA" in ressalva_upper:
            match_nd = re.search(r"NC com ND genérica \((\S+)\).*Req usa (\S+)", ressalva, re.IGNORECASE)
            if match_nd:
                nd_nc = match_nd.group(1)
                nd_req = match_nd.group(2)
                return (
                    f"a NC possui ND genérica ({nd_nc}), enquanto a requisição "
                    f"utiliza ND {nd_req} — verificar necessidade de DETAORC."
                )
        match_nd = re.search(r"NC:\s*(\S+)\s*≠\s*Req:\s*(\S+)", ressalva)
        if match_nd:
            nd_nc = match_nd.group(1)
            nd_req = match_nd.group(2)
            return (
                f"a ND da NC ({nd_nc}) diverge da ND da requisição ({nd_req})."
            )
        return "a Natureza de Despesa (ND) diverge entre a NC e a requisição."

    # ── Saldo insuficiente ──
    if "SALDO" in ressalva_upper and "<" in ressalva:
        match_saldo = re.search(
            r"Saldo\s+(R\$\s*[\d.,]+)\s*<\s*(R\$\s*[\d.,]+)",
            ressalva, re.IGNORECASE
        )
        if match_saldo:
            saldo = match_saldo.group(1)
            valor = match_saldo.group(2)
            return (
                f"o saldo disponível para empenho é de {saldo}, "
                f"inferior ao valor da requisição ({valor})."
            )
        return "o saldo da NC é inferior ao valor da requisição."

    # ── Prazo vencido ──
    if "VENCIDO" in ressalva_upper and "PRAZO" in ressalva_upper:
        match_prazo = re.search(r"VENCIDO há (\d+) dias", ressalva, re.IGNORECASE)
        if match_prazo:
            dias = match_prazo.group(1)
            return (
                f"o prazo de empenho da NC está vencido há {dias} dias."
            )
        return "o prazo de empenho da NC está vencido."

    # ── Prazo urgente ──
    if "URGENTE" in ressalva_upper or ("PRAZO" in ressalva_upper and "DIAS" in ressalva_upper):
        match_urgente = re.search(r"(\d+)\s*dias\s*restantes", ressalva, re.IGNORECASE)
        if match_urgente:
            dias = match_urgente.group(1)
            return (
                f"o prazo de empenho da NC possui apenas {dias} dias restantes — urgente."
            )

    # ── Impedimento de Licitar ──
    if "IMPEDIMENTO" in ressalva_upper and "LICITAR" in ressalva_upper:
        return "consta impedimento de licitar no SICAF."

    # ── CADIN irregular ──
    if "CADIN" in ressalva_upper and ("IRREGULAR" in ressalva_upper or "BLOQUEIO" in ressalva_upper):
        return "a situação no CADIN encontra-se irregular."

    # ── TCU/CNJ/CEIS/CNEP ──
    for cadastro in ["TCU", "CNJ", "CEIS", "CNEP"]:
        if cadastro in ressalva_upper and "CONSTA" in ressalva_upper:
            return f"consta registro no {cadastro}, o que impede o andamento do processo."

    # ── Situação SICAF ──
    if "SITUAÇÃO DO FORNECEDOR" in ressalva_upper or "CREDENCIADO" in ressalva_upper:
        return "a situação do fornecedor no SICAF não está como 'Credenciado'."

    # ── Vínculo com Serviço Público ──
    if "VÍNCULO" in ressalva_upper and "SERVIÇO PÚBLICO" in ressalva_upper:
        return "consta vínculo com Serviço Público no SICAF."

    # ── Cálculo divergente ──
    if "ITEM" in ressalva_upper and ("CÁLCULO" in ressalva_upper or "≠" in ressalva):
        match_calc = re.search(r"Item\s+(\d+)", ressalva)
        if match_calc:
            item_nr = match_calc.group(1)
            return (
                f"na tabela de requisição, o cálculo do item {item_nr} apresenta divergência."
            )

    # ── Itens não extraídos ──
    if "ITENS NÃO EXTRAÍDOS" in ressalva_upper or "NENHUM ITEM" in ressalva_upper:
        return (
            "não foi possível extrair automaticamente os itens da tabela de requisição "
            "— verificar o layout da tabela no PDF."
        )

    # ── Ocorrências Impeditivas Indiretas ──
    if "OCORR" in ressalva_upper and "IMPED" in ressalva_upper:
        return (
            "constam Ocorrências Impeditivas Indiretas no SICAF — "
            "verificar no Relatório de Ocorrências."
        )

    # ── Fallback: incluir a ressalva como está ──
    return f"{ressalva.lower().rstrip('.')}."

