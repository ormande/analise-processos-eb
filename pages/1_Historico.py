"""
Página dedicada ao histórico de análises.

Permite buscar, filtrar e visualizar todas as análises realizadas,
com estatísticas e exportação de dados.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from modules import database, components

# ── Configuração de fuso horário (Campo Grande-MS: GMT-4) ──────────────
TZ_CAMPO_GRANDE = timezone(timedelta(hours=-4))

def hoje_cg() -> date:
    """Retorna a data de hoje no fuso horário de Campo Grande (GMT-4)."""
    return datetime.now(TZ_CAMPO_GRANDE).date()

def agora_cg() -> datetime:
    """Retorna o datetime atual no fuso horário de Campo Grande (GMT-4)."""
    return datetime.now(TZ_CAMPO_GRANDE)

# ── Configuração da página ──────────────────────────────────────────
st.set_page_config(
    page_title="Histórico — SAL/CAF",
    page_icon="📊",
    layout="wide"
)

# ── CSS customizado ─────────────────────────────────────────────────
try:
    with open("assets/styles.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass  # CSS opcional

# ── Banco de dados ──────────────────────────────────────────────────
database.init_database()

# ── Título ─────────────────────────────────────────────────────────
st.title("📊 Histórico de Análises")
st.caption("SAL/CAF — Cmdo 9º Gpt Log")

# ── Estatísticas Gerais ────────────────────────────────────────────
stats = database.obter_estatisticas_analises()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total de Análises", stats["total"])

with col2:
    approval_count = stats["por_resultado"].get("approval", 0)
    st.metric("🟢 Aprovadas", approval_count)

with col3:
    caveat_count = stats["por_resultado"].get("caveat", 0)
    st.metric("⚠️ Ressalvas", caveat_count)

with col4:
    rejection_count = stats["por_resultado"].get("rejection", 0)
    st.metric("🔴 Reprovadas", rejection_count)

st.markdown("---")

# ── Filtros e Busca ────────────────────────────────────────────────
col_filtro1, col_filtro2, col_filtro3, col_filtro4 = st.columns(4)

with col_filtro1:
    busca_texto = st.text_input(
        "🔍 Buscar",
        placeholder="NUP, OM, fornecedor ou CNPJ...",
        key="busca_historico"
    )

with col_filtro2:
    resultado_filtro = st.selectbox(
        "Resultado",
        ["Todos", "🟢 Aprovadas", "⚠️ Ressalvas", "🔴 Reprovadas"],
        key="filtro_resultado"
    )
    resultado_map = {
        "Todos": None,
        "🟢 Aprovadas": "approval",
        "⚠️ Ressalvas": "caveat",
        "🔴 Reprovadas": "rejection",
    }
    resultado_filtro_val = resultado_map[resultado_filtro]

with col_filtro3:
    periodo = st.selectbox(
        "Período",
        ["Todos", "Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Personalizado"],
        key="filtro_periodo"
    )

with col_filtro4:
    limite_resultados = st.number_input(
        "Limite de resultados",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
        key="limite_historico"
    )

# ── Período personalizado ──────────────────────────────────────────
data_inicio = None
data_fim = None

if periodo == "Personalizado":
    col_data1, col_data2 = st.columns(2)
    with col_data1:
        data_inicio = st.date_input(
            "Data inicial",
            value=hoje_cg() - timedelta(days=30),
            key="data_inicio"
        )
    with col_data2:
        data_fim = st.date_input(
            "Data final",
            value=hoje_cg(),
            key="data_fim"
        )
elif periodo == "Últimos 7 dias":
    data_inicio = (hoje_cg() - timedelta(days=7)).strftime("%Y-%m-%d")
elif periodo == "Últimos 30 dias":
    data_inicio = (hoje_cg() - timedelta(days=30)).strftime("%Y-%m-%d")
elif periodo == "Últimos 90 dias":
    data_inicio = (hoje_cg() - timedelta(days=90)).strftime("%Y-%m-%d")

if isinstance(data_inicio, date):
    data_inicio = data_inicio.strftime("%Y-%m-%d")
if isinstance(data_fim, date):
    data_fim = data_fim.strftime("%Y-%m-%d")

# ── Buscar análises ──────────────────────────────────────────────────
analises = database.buscar_analises(
    busca=busca_texto if busca_texto else None,
    resultado_filtro=resultado_filtro_val,
    data_inicio=data_inicio,
    data_fim=data_fim,
    limite=limite_resultados,
)

# ── Exibir resultados ───────────────────────────────────────────────
st.markdown(f"### 📋 Resultados ({len(analises)} análise(s) encontrada(s))")

if analises:
    # Ícones por resultado
    icone_resultado = {
        "approval": "🟢",
        "caveat": "⚠️",
        "rejection": "🔴"
    }

    # Preparar dados para tabela
    dados_tabela = []
    for analise in analises:
        # Formatar data
        data_str = "—"
        if analise.get("data_analise"):
            try:
                dt = datetime.fromisoformat(analise["data_analise"])
                data_str = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, TypeError):
                data_str = str(analise["data_analise"])[:16]

        # Formatar valor
        valor_str = "—"
        if analise.get("valor_total"):
            try:
                valor = float(analise["valor_total"])
                valor_str = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except (ValueError, TypeError):
                valor_str = str(analise["valor_total"])

        dados_tabela.append({
            "ID": analise["id"],
            "Data": data_str,
            "NUP": analise.get("nup", "—"),
            "Resultado": f"{icone_resultado.get(analise.get('resultado'), '⚪')} {analise.get('resultado', '—').title()}",
            "OM": analise.get("om_requisitante", "—")[:40],
            "Fornecedor": analise.get("fornecedor", "—")[:40],
            "CNPJ": analise.get("cnpj", "—"),
            "Valor": valor_str,
            "Tipo": analise.get("tipo_processo", "—"),
            "Instrumento": analise.get("instrumento", "—"),
        })

    df = pd.DataFrame(dados_tabela)

    # Exibir tabela interativa
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Data": st.column_config.TextColumn("Data", width="medium"),
            "NUP": st.column_config.TextColumn("NUP", width="medium"),
            "Resultado": st.column_config.TextColumn("Resultado", width="medium"),
            "OM": st.column_config.TextColumn("OM", width="large"),
            "Fornecedor": st.column_config.TextColumn("Fornecedor", width="large"),
            "CNPJ": st.column_config.TextColumn("CNPJ", width="medium"),
            "Valor": st.column_config.TextColumn("Valor", width="medium"),
            "Tipo": st.column_config.TextColumn("Tipo", width="small"),
            "Instrumento": st.column_config.TextColumn("Instrumento", width="small"),
        }
    )

    # ── Ações em lote ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Ações")

    col_acao1, col_acao2, col_acao3 = st.columns(3)

    with col_acao1:
        if st.button("📥 Exportar para CSV", use_container_width=True):
            csv = df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                label="⬇️ Baixar CSV",
                data=csv,
                file_name=f"historico_analises_{agora_cg().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key="download_csv"
            )

    with col_acao2:
        if st.button("📊 Ver Estatísticas Detalhadas", use_container_width=True):
            st.session_state.mostrar_stats = True

    with col_acao3:
        if st.button("🔄 Atualizar", use_container_width=True):
            st.rerun()

    # ── Estatísticas detalhadas ─────────────────────────────────────
    if st.session_state.get("mostrar_stats", False):
        st.markdown("---")
        st.markdown("### 📊 Estatísticas Detalhadas")

        # Gráfico por mês
        if stats["por_mes"]:
            df_mes = pd.DataFrame(stats["por_mes"])
            df_mes["mes_formatado"] = pd.to_datetime(df_mes["mes"], format="%Y-%m").dt.strftime("%b/%Y")
            
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.markdown("**Análises por Mês**")
                st.bar_chart(
                    df_mes.set_index("mes_formatado")[["approval", "caveat", "rejection"]],
                    color=["#10b981", "#f59e0b", "#ef4444"]
                )
            
            with col_chart2:
                st.markdown("**Total por Mês**")
                st.line_chart(df_mes.set_index("mes_formatado")[["total"]])

        # Valor total
        if stats["valor_total"] > 0:
            valor_fmt = f"R$ {stats['valor_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            st.metric("💰 Valor Total Analisado", valor_fmt)

        if st.button("❌ Fechar Estatísticas"):
            st.session_state.mostrar_stats = False
            st.rerun()

    # ── Visualizar análise individual ───────────────────────────────
    st.markdown("---")
    st.markdown("### 👁️ Visualizar Análise")

    analise_selecionada_id = st.selectbox(
        "Selecione uma análise para visualizar",
        options=[a["id"] for a in analises],
        format_func=lambda x: f"ID {x} — {next((a['nup'] for a in analises if a['id'] == x), '—')}",
        key="select_analise"
    )

    if analise_selecionada_id and st.button("🔍 Carregar Análise", use_container_width=True):
        # Salvar ID no session_state e redirecionar para página principal
        st.session_state.carregar_analise_id = analise_selecionada_id
        st.info("🔄 Redirecionando para visualização da análise...")
        # Usar switch_page para voltar à página principal
        st.switch_page("app.py")

else:
    st.info("ℹ️ Nenhuma análise encontrada com os filtros selecionados.")

# ── Rodapé ──────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Histórico de Análises • SAL/CAF — Cmdo 9º Gpt Log")

