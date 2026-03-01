"""
Componentes de UI reutilizáveis para a interface Streamlit.

Todos os componentes usam classes CSS definidas em assets/styles.css
para garantir compatibilidade com o tema escuro.
"""

import streamlit as st


def fmt_brl(valor):
    """Formata número para padrão brasileiro: 2000.00 → 2.000,00"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_status_badge(status):
    """Retorna HTML de badge de status."""
    configs = {
        "conforme": ("badge-conforme", "✅ Conforme"),
        "ressalva": ("badge-ressalva", "⚠️ Ressalva"),
        "bloqueio": ("badge-bloqueio", "❌ Bloqueio"),
    }
    classe, texto = configs.get(status, ("badge-conforme", "—"))
    return f'<span class="{classe}">{texto}</span>'


def render_identificacao(data):
    """Renderiza o painel de identificação com HTML customizado (cores visíveis)."""
    campos_esq = [
        ("NUP", data.get("nup", "—")),
        ("Tipo", data.get("tipo", "—")),
        ("OM Requisitante", data.get("om_requisitante", "—")),
        ("Setor", data.get("setor", "—")),
        ("Objeto", data.get("objeto", "—")),
    ]
    campos_dir = [
        ("Fornecedor", data.get("fornecedor", "—")),
        ("CNPJ", data.get("cnpj", "—")),
        ("Tipo Empenho", data.get("tipo_empenho", "—")),
        ("Instrumento", data.get("instrumento", "—")),
        ("UASG", data.get("uasg", "—")),
    ]

    html = '<div class="ident-grid">'

    # Coluna esquerda
    html += '<div>'
    for label, valor in campos_esq:
        html += (
            '<div class="ident-campo">'
            f'<div class="ident-label">{label}</div>'
            f'<div class="ident-valor">{valor}</div>'
            '</div>'
        )
    html += '</div>'

    # Coluna direita
    html += '<div>'
    for label, valor in campos_dir:
        html += (
            '<div class="ident-campo">'
            f'<div class="ident-label">{label}</div>'
            f'<div class="ident-valor">{valor}</div>'
            '</div>'
        )
    html += '</div>'

    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def render_nota_credito_card(nc):
    """Renderiza card da NC com todos os campos em monospace."""
    # Saldo: formatar como BRL quando disponível, ou "— (não extraído)"
    saldo_val = nc.get("saldo")
    saldo_str = f"R$ {fmt_brl(saldo_val)}" if saldo_val is not None else "— (não extraído)"

    # Prazo: adicionar dias restantes se disponível
    prazo_val = nc.get("prazo_empenho") or "—"
    dias_val  = nc.get("dias_restantes")
    if dias_val is not None and prazo_val != "—":
        prazo_str = f"{prazo_val} ({dias_val} dias)"
    else:
        prazo_str = prazo_val

    # ND: adicionar sinalização se divergente
    nd_val = nc.get("nd", "—")
    if nc.get("nd_divergente"):
        nd_val = f"⚠️ {nd_val} (não confere com requisição)"
    
    campos = [
        ("Número",        nc.get("numero", "—")),
        ("Data emissão",  nc.get("data_emissao", "—")),
        ("UG Emitente",   nc.get("ug_emitente", "—")),
        ("UG Favorecida", nc.get("ug_favorecida", "—")),
        ("ND",            nd_val),
        ("PTRES",         nc.get("ptres", "—")),
        ("FONTE",         nc.get("fonte", "—")),
        ("UGR",           nc.get("ugr", "—")),
        ("PI",            nc.get("pi", "—")),
        ("ESF",           nc.get("esf", "—")),
        ("Saldo",         saldo_str),
        ("Prazo empenho", prazo_str),
    ]

    linhas = ""
    for label, valor in campos:
        linhas += (
            '<div class="card-linha">'
            f'<span class="card-label">{label}</span>'
            f'<span class="card-valor">{valor}</span>'
            '</div>'
        )

    html = (
        '<div class="card-nc">'
        f'<div class="card-titulo">📄 NC {nc["numero"]}</div>'
        f'{linhas}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_validacoes_nc(validacoes):
    """Renderiza tabela de validações cruzadas da NC."""
    html = '<table class="tabela-analise">'
    html += ('<thead><tr>'
             '<th>Verificação</th>'
             '<th>Resultado</th>'
             '<th style="text-align:center">Status</th>'
             '</tr></thead><tbody>')

    for val in validacoes:
        icone = {"conforme": "✅", "ressalva": "⚠️", "bloqueio": "❌"}.get(
            val["status"], "—"
        )
        classe_row = f"row-{val['status']}"

        html += (
            f'<tr class="{classe_row}">'
            f'<td>{val["verificacao"]}</td>'
            f'<td>{val["resultado"]}</td>'
            f'<td style="text-align:center">{icone}</td>'
            '</tr>'
        )

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


def render_certidoes_table(certidoes):
    """Renderiza tabela de certidões com indentação e cores por status."""
    html = '<table class="tabela-analise">'
    html += ('<thead><tr>'
             '<th>Certidão</th>'
             '<th>CNPJ / Resultado</th>'
             '<th>Validade</th>'
             '<th style="text-align:center">Status</th>'
             '</tr></thead><tbody>')

    for cert in certidoes:
        classe_row = f"row-{cert['status']}"
        icone = {"conforme": "🟢", "ressalva": "⚠️", "bloqueio": "🔴"}.get(
            cert["status"], "—"
        )
        # Destaque de validade curta ou vencida
        validade_html = cert["validade"]
        if cert["status"] == "ressalva" and cert["validade"] != "—":
            validade_html = f'<span class="val-ressalva">{cert["validade"]}</span>'
        elif cert["status"] == "bloqueio" and cert["validade"] != "—":
            validade_html = f'<span class="val-bloqueio">{cert["validade"]}</span>'

        html += (
            f'<tr class="{classe_row}">'
            f'<td>{cert["certidao"]}</td>'
            f'<td>{cert["resultado"]}</td>'
            f'<td>{validade_html}</td>'
            f'<td style="text-align:center">{icone}</td>'
            '</tr>'
        )

    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)


def render_verificacoes_req(validacoes):
    """Renderiza verificações da requisição com HTML estilizado (sem caixa preta)."""
    html = ''
    for val in validacoes.values():
        status = val.get("status", "conforme")
        classe = "verif-conforme" if status == "conforme" else "verif-ressalva"
        html += f'<div class="verif-item {classe}">{val["resultado"]}</div>'
    st.markdown(html, unsafe_allow_html=True)


def render_resultado_banner(resultado):
    """Renderiza banner grande com resultado da análise."""
    classe = {
        "approval": "banner-approval",
        "caveat": "banner-caveat",
        "rejection": "banner-rejection",
    }.get(resultado["tipo"], "banner-caveat")

    html = (
        f'<div class="banner-resultado {classe}">'
        f'{resultado["titulo"]}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_findings(ressalvas, conformes):
    """Renderiza listas de ressalvas e pontos conformes."""
    if ressalvas:
        st.markdown("**Ressalvas / Problemas:**")
        for r in ressalvas:
            st.markdown(f"- ⚠️ {r}")
        st.markdown("")

    if conformes:
        st.markdown("**Pontos conformes:**")
        for c in conformes:
            st.markdown(f"- ✅ {c}")
