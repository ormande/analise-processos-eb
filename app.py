import streamlit as st
import pandas as pd
import time
import os
import json
import tempfile
from datetime import datetime, date
from modules import (
    mock_data, components, database, extractor,
    validator, ne_generator, despacho_generator,
)

# ── Configuração da página ──────────────────────────────────────────
st.set_page_config(
    page_title="Análise de Processos — SAL/CAF",
    page_icon="📋",
    layout="wide"
)

# ── Banco de dados ──────────────────────────────────────────────────
database.init_database()

# ── CSS customizado ─────────────────────────────────────────────────
with open("assets/styles.css", "r", encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# ── Função para copiar texto via JavaScript ─────────────────────────
def copiar_para_clipboard(texto, chave):
    """Copia texto para a área de transferência usando JavaScript.

    Usa fallback com textarea + execCommand('copy') no parent frame,
    pois navigator.clipboard não funciona em iframes do Streamlit.
    """
    if st.button("📋 Copiar", key=chave):
        # Escapar para inserir com segurança dentro do JS
        js_texto = (
            texto
            .replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("$", "\\$")
            .replace("\n", "\\n")
            .replace("\r", "")
        )
        st.components.v1.html(
            f"""<script>
            (function() {{
                var texto = `{js_texto}`;
                // Tentar API moderna (funciona em HTTPS / localhost)
                if (window.parent && window.parent.navigator && window.parent.navigator.clipboard) {{
                    window.parent.navigator.clipboard.writeText(texto).catch(function() {{
                        fallbackCopy(texto);
                    }});
                }} else {{
                    fallbackCopy(texto);
                }}
                function fallbackCopy(t) {{
                    var ta = window.parent.document.createElement('textarea');
                    ta.value = t;
                    ta.style.position = 'fixed';
                    ta.style.left = '-9999px';
                    ta.style.top = '-9999px';
                    window.parent.document.body.appendChild(ta);
                    ta.focus();
                    ta.select();
                    try {{ window.parent.document.execCommand('copy'); }}
                    catch(e) {{ }}
                    window.parent.document.body.removeChild(ta);
                }}
            }})();
            </script>""",
            height=0,
        )
        st.toast("Copiado!")


# ══════════════════════════════════════════════════════════════════════
# FUNÇÕES DE PROCESSAMENTO E ADAPTAÇÃO
# Convertem a saída do extrator para o formato esperado pelos componentes
# ══════════════════════════════════════════════════════════════════════

def _registrar_pregao_automatico(res: dict) -> None:
    """
    Registra automaticamente o pregão no banco ao processar um PDF.
    Extrai dados da identificação e itens e faz merge no banco.
    Só registra se houver número de pregão no processo.
    """
    ident = res.get("identificacao", {})
    nr_pregao = ident.get("nr_pregao")

    if not nr_pregao:
        return  # Não é licitação ou pregão não encontrado

    nup = ident.get("nup")
    detalhes = ident.get("pregao_detalhes", {})

    # Montar dados do fornecedor
    fornecedor = None
    if ident.get("cnpj"):
        fornecedor = {
            "cnpj": ident["cnpj"],
            "razao_social": ident.get("fornecedor", ""),
        }

    # Simplificar itens para o banco de pregões
    itens_simplificados = []
    for item in res.get("itens", []):
        itens_simplificados.append({
            "item": item.get("item"),
            "descricao": item.get("descricao", ""),
            "und": item.get("und", ""),
            "catserv": item.get("catserv", ""),
        })

    try:
        database.registrar_pregao(
            numero=nr_pregao,
            uasg_gerenciadora=detalhes.get("uasg_gerenciadora") or ident.get("uasg"),
            nome_om_gerenciadora=detalhes.get("nome_om_gerenciadora"),
            objeto=detalhes.get("objeto_pregao") or ident.get("objeto"),
            fornecedor=fornecedor,
            itens=itens_simplificados if itens_simplificados else None,
            nup=nup,
        )
    except Exception as e:
        print(f"[AVISO] Erro ao registrar pregão: {e}")


def _registrar_contrato_automatico(res: dict) -> None:
    """
    Registra automaticamente o contrato no banco ao processar um PDF.
    Só registra se houver número de contrato no processo.
    """
    ident = res.get("identificacao", {})
    nr_contrato = ident.get("nr_contrato")
    dados_contrato = res.get("contrato", {})

    if not nr_contrato:
        return  # Não é processo de contrato

    nup = ident.get("nup")

    try:
        database.registrar_contrato(
            numero=nr_contrato,
            uasg_contratante=dados_contrato.get("uasg_contratante") or ident.get("uasg"),
            nome_contratante=dados_contrato.get("nome_contratante") or ident.get("om"),
            cnpj_contratante=dados_contrato.get("cnpj_contratante"),
            contratada=dados_contrato.get("contratada") or ident.get("fornecedor"),
            cnpj_contratada=dados_contrato.get("cnpj_contratada") or ident.get("cnpj"),
            objeto=dados_contrato.get("objeto") or ident.get("objeto"),
            valor_total=dados_contrato.get("valor_total"),
            vigencia_inicio=dados_contrato.get("vigencia_inicio"),
            vigencia_fim=dados_contrato.get("vigencia_fim"),
            pregao_origem=dados_contrato.get("pregao_origem"),
            tem_assinaturas=dados_contrato.get("tem_assinaturas", False),
            nup=nup,
        )
    except Exception as e:
        print(f"[AVISO] Erro ao registrar contrato: {e}")


def _processar_pdf(pdf_file) -> dict:
    """
    Salva o PDF carregado em arquivo temporário, extrai os dados
    com o módulo extractor e retorna o resultado.
    Em caso de erro, retorna dict vazio.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_file.getvalue())
            tmp_path = tmp.name
        return extractor.extrair_processo(tmp_path)
    except Exception as e:
        print(f"[ERRO] Falha na extração do PDF '{pdf_file.name}': {e}")
        return {}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _adaptar_identificacao(res: dict) -> dict:
    """
    Converte o dicionário 'identificacao' do extrator para o formato
    esperado pelo componente render_identificacao().

    Mapeamentos principais:
        extrator['om']     → interface['om_requisitante']
        extrator['objeto'] → interface['objeto'] (fallback: 'assunto')
    """
    ident = res.get("identificacao", {})
    return {
        "nup":             ident.get("nup") or "—",
        "tipo":            ident.get("tipo") or "—",
        "om_requisitante": ident.get("om") or "—",
        "setor":           ident.get("setor") or "—",
        "objeto":          ident.get("objeto") or ident.get("assunto") or "—",
        "fornecedor":      ident.get("fornecedor") or "—",
        "cnpj":            ident.get("cnpj") or "—",
        "tipo_empenho":    ident.get("tipo_empenho") or "—",
        "instrumento":     ident.get("instrumento") or "—",
        "uasg":            ident.get("uasg") or "—",
    }


def _adaptar_itens(res: dict) -> list:
    """
    Retorna a lista de itens extraídos adicionando campo 'status'
    padrão 'conforme' para compatibilidade com a interface.
    """
    itens = res.get("itens", [])
    for item in itens:
        item.setdefault("status", "conforme")
    return itens


def _calcular_validacoes_req(itens: list) -> dict:
    """
    Calcula validações da tabela de itens da requisição:
    - Verifica se qtd × p_unit ≈ p_total (tolerância: R$ 0,02)
    - Calcula o valor total do processo

    Retorna dict no mesmo formato de mock_data.get_validacoes_requisicao().
    Divergências geram status 'ressalva' (⚠️), não reprovação automática.
    """
    validacoes = {}

    def _fmt_brl(v: float) -> str:
        """Formata float para moeda brasileira."""
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    for item in itens:
        qtd    = item.get("qtd")
        p_unit = item.get("p_unit")
        p_total = item.get("p_total")
        num    = item.get("item", "?")

        if qtd is not None and p_unit is not None and p_total is not None:
            calculado  = round(qtd * p_unit, 2)
            divergencia = abs(calculado - p_total) > 0.02

            qtd_fmt    = f"{qtd:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
            punit_fmt  = f"R$ {_fmt_brl(p_unit)}"
            ptotal_fmt = f"R$ {_fmt_brl(p_total)}"
            calc_fmt   = f"R$ {_fmt_brl(calculado)}"

            if divergencia:
                status    = "ressalva"
                resultado = (
                    f"⚠️ Item {num}: {qtd_fmt} × {punit_fmt} = {calc_fmt} "
                    f"≠ {ptotal_fmt} declarado"
                )
            else:
                status    = "conforme"
                resultado = f"✅ Item {num}: {qtd_fmt} × {punit_fmt} = {ptotal_fmt}"

            validacoes[f"calculo_item_{num}"] = {
                "texto":    f"Verificação de cálculo (Item {num})",
                "resultado": resultado,
                "status":   status,
            }
        elif qtd is not None or p_unit is not None or p_total is not None:
            # Dados parciais — não foi possível calcular completamente
            validacoes[f"calculo_item_{num}"] = {
                "texto":    f"Verificação de cálculo (Item {num})",
                "resultado": f"⚠️ Item {num}: dados incompletos — verificar manualmente",
                "status":   "ressalva",
            }

    # Linha de total geral
    total = sum(item.get("p_total") or 0.0 for item in itens)
    if total > 0:
        total_fmt = f"R$ {_fmt_brl(total)}"
        validacoes["valor_total"] = {
            "texto":    "Valor total",
            "resultado": f"✅ Total do processo: {total_fmt}",
            "status":   "conforme",
        }

    # Fallback quando nenhum item foi extraído
    if not validacoes:
        validacoes["sem_itens"] = {
            "texto":    "Itens da requisição",
            "resultado": (
                "⚠️ Nenhum item extraído automaticamente — "
                "verificar o layout da tabela no PDF"
            ),
            "status":   "ressalva",
        }

    return validacoes


def _adaptar_simulacao(res: dict, itens: list) -> dict:
    """
    Monta os dados para a simulação ComprasNet a partir dos dados reais.
    O subelemento (SI) é extraído do campo ND/SI do primeiro item.

    Formatos de ND/SI aceitos:
        "39.17"      → SI = 17
        "33.90.39/24"→ SI = 24
    """
    ident   = res.get("identificacao", {})
    # Primeiro item com quantidade definida
    primeiro = next((i for i in itens if i.get("qtd") is not None), {})

    # Extrair subelemento (SI) do campo ND/SI — último número após "." ou "/"
    nd_si_raw = (primeiro.get("nd_si") or "").strip()
    si = None
    for sep in ("/", "."):
        if sep in nd_si_raw:
            ultima_parte = nd_si_raw.split(sep)[-1].strip()
            if ultima_parte.isdigit() and 1 <= len(ultima_parte) <= 2:
                si = ultima_parte.lstrip("0") or "0"
                break

    qtd_fmt = None
    if primeiro.get("qtd") is not None:
        q = primeiro["qtd"]
        qtd_fmt = f"{q:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return {
        "uasg":        ident.get("uasg") or "—",
        "instrumento": ident.get("instrumento") or "—",
        "cnpj":        ident.get("cnpj") or "—",
        "item":        str(primeiro.get("item", "—")) if primeiro else "—",
        "pi":          ident.get("pi") or "—",
        "quantidade":  qtd_fmt or "—",
        "si":          si or "—",
    }


def _fmt_ug(codigo: str | None, nome: str | None) -> str:
    """Formata código UG com nome: '167504 — CENTRO DE OBTENÇÕES DO EXÉRCITO'."""
    if codigo and nome:
        return f"{codigo} — {nome}"
    return codigo or "—"


def _adaptar_nc(res: dict) -> dict:
    """
    Retorna o card da NC para exibição na interface.

    Prioridade:
    1. Dados reais extraídos do documento NC (passo 2 — implementado)
    2. Fallback: patch do mock com campos da requisição (número, ND, PI etc.)
    """
    ncs_reais = res.get("nota_credito", [])
    ident     = res.get("identificacao", {})

    if ncs_reais:
        nc_real = ncs_reais[0]   # usar a primeira NC

        dias = nc_real.get("dias_restantes")
        # dias pode ser int (calculado) ou None (prazo não extraído)
        dias_str = dias if dias is not None else "N/A"

        return {
            "numero":        nc_real.get("numero") or "—",
            "data_emissao":  nc_real.get("data_emissao") or "—",
            "ug_emitente":   _fmt_ug(nc_real.get("ug_emitente"),
                                     nc_real.get("nome_emitente")),
            "ug_favorecida": _fmt_ug(nc_real.get("ug_favorecida"),
                                     nc_real.get("nome_favorecida")),
            "nd":            nc_real.get("nd") or "—",
            "ptres":         nc_real.get("ptres") or "—",
            "fonte":         nc_real.get("fonte") or "—",
            "ugr":           nc_real.get("ugr") or "—",
            "pi":            nc_real.get("pi") or "—",
            "esf":           nc_real.get("esf") or "—",
            # saldo pode ser None quando não foi possível extrair
            "saldo":         nc_real.get("saldo"),
            "prazo_empenho": nc_real.get("prazo_empenho") or "—",
            "dias_restantes": dias_str,
        }

    # ── Fallback: construir NC a partir dos dados da requisição ──
    # (sem documento NC no PDF — campos financeiros vêm do texto da req)
    return {
        "numero":        ident.get("nc") or "—",
        "data_emissao":  ident.get("data_nc") or "—",
        "ug_emitente":   ident.get("orgao_emissor_nc") or "—",
        "ug_favorecida": "—",
        "nd":            ident.get("nd") or "—",
        "ptres":         ident.get("ptres") or "—",
        "fonte":         ident.get("fonte") or "—",
        "ugr":           ident.get("ugr") or "—",
        "pi":            ident.get("pi") or "—",
        "esf":           "—",
        "saldo":         None,
        "prazo_empenho": "— (não extraído)",
        "dias_restantes": "N/A",
    }


def _calcular_validacoes_nc(nota_credito: dict, itens: list, res: dict) -> list:
    """
    Calcula as validações cruzadas entre a NC e a Requisição:
    1. ND da NC vs ND da Requisição
    2. Saldo da NC vs Valor Total dos itens
    3. Prazo de empenho vs data atual

    Retorna lista de dicts no formato esperado por render_validacoes_nc().
    Regras de severidade conforme ESPECIFICACAO_LOGICA_NEGOCIO_v2:
    - 🟢 conforme, ⚠️ ressalva, 🔴 bloqueio (vermelho → "bloqueio")
    """
    validacoes = []
    ident = res.get("identificacao", {})

    # ── Dados da NC ──
    nd_nc     = nota_credito.get("nd")
    saldo_nc  = nota_credito.get("saldo")
    prazo_raw = nota_credito.get("prazo_empenho")
    dias      = nota_credito.get("dias_restantes")

    # ── Dados da Requisição ──
    nd_req    = ident.get("nd")
    total_req = sum(item.get("p_total") or 0.0 for item in itens)

    # 1. ND NC vs ND Requisição
    if nd_nc and nd_req:
        nd_nc_norm  = nd_nc.replace(".", "")
        nd_req_norm = nd_req.replace(".", "")

        if nd_nc_norm == nd_req_norm:
            validacoes.append({
                "verificacao": "ND da NC vs ND da Requisição",
                "resultado":   f"{nd_nc} = {nd_req}",
                "status":      "conforme",
            })
        elif nd_nc_norm == "339000":
            validacoes.append({
                "verificacao": "ND da NC vs ND da Requisição",
                "resultado":   f"⚠️ NC com ND genérica ({nd_nc}) — Req usa {nd_req} — verificar DETAORC",
                "status":      "ressalva",
            })
        else:
            validacoes.append({
                "verificacao": "ND da NC vs ND da Requisição",
                "resultado":   f"⚠️ NC: {nd_nc} ≠ Req: {nd_req} — verificar com analista",
                "status":      "ressalva",
            })
    else:
        nd_info = nd_nc or nd_req or "não extraído"
        validacoes.append({
            "verificacao": "ND da NC vs ND da Requisição",
            "resultado":   f"— ({nd_info})",
            "status":      "conforme",
        })

    # 2. Saldo NC vs Valor Total Requisição
    if saldo_nc is not None and total_req > 0:
        def _fmt(v):
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        if saldo_nc >= total_req:
            validacoes.append({
                "verificacao": "Saldo vs Valor Requisição",
                "resultado":   f"{_fmt(saldo_nc)} ≥ {_fmt(total_req)}",
                "status":      "conforme",
            })
        else:
            validacoes.append({
                "verificacao": "Saldo vs Valor Requisição",
                "resultado":   (
                    f"⚠️ Saldo {_fmt(saldo_nc)} < {_fmt(total_req)} — "
                    "pode haver saldo complementar em outro PI"
                ),
                "status":      "ressalva",
            })
    else:
        validacoes.append({
            "verificacao": "Saldo vs Valor Requisição",
            "resultado":   "— (saldo não extraído)",
            "status":      "conforme",
        })

    # 3. Prazo de empenho
    if prazo_raw and prazo_raw != "—":
        if dias is not None and isinstance(dias, int):
            if dias < 0:
                status  = "ressalva"
                texto   = f"⚠️ VENCIDO há {abs(dias)} dias ({prazo_raw})"
            elif dias <= 7:
                status  = "ressalva"
                texto   = f"⚠️ {prazo_raw} — URGENTE: {dias} dias restantes"
            elif dias <= 15:
                status  = "ressalva"
                texto   = f"⚠️ {prazo_raw} — {dias} dias (atenção: pode vencer antes do empenho)"
            else:
                status  = "conforme"
                texto   = f"{prazo_raw} — {dias} dias restantes"
        else:
            status = "conforme"
            texto  = prazo_raw
        validacoes.append({
            "verificacao": "Prazo de empenho",
            "resultado":   texto,
            "status":      status,
        })
    else:
        validacoes.append({
            "verificacao": "Prazo de empenho",
            "resultado":   "— (prazo não extraído)",
            "status":      "conforme",
        })

    return validacoes


# ══════════════════════════════════════════════════════════════════════
# ADAPTAÇÃO DAS CERTIDÕES — dados reais do extrator para a UI
# ══════════════════════════════════════════════════════════════════════

def _dias_ate(data_str: str) -> int | None:
    """Calcula dias entre hoje e data DD/MM/YYYY. Retorna None se inválida."""
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y").date()
        return (dt - date.today()).days
    except (ValueError, TypeError):
        return None


def _status_validade(dias: int | None) -> str:
    """Retorna status conforme dias restantes de validade."""
    if dias is None:
        return "conforme"
    if dias < 0:
        return "bloqueio"
    if dias <= 15:
        return "ressalva"
    return "conforme"


def _texto_dias(dias: int) -> str:
    """Retorna texto legível dos dias restantes."""
    if dias < 0:
        return f"{abs(dias)} dias vencida"
    if dias == 0:
        return "vence hoje"
    return f"{dias} dias"


def _adaptar_certidoes(res: dict) -> list[dict]:
    """
    Converte dados reais de certidões (extraídos do PDF) para o formato
    esperado por render_certidoes_table():
        { certidao, resultado, validade, status, indent }

    Regras de severidade (conforme ESPECIFICACAO_LOGICA_NEGOCIO_v2):
    - Validade > 15 dias → 🟢
    - Validade ≤ 15 dias → ⚠️
    - Validade vencida → 🔴
    - Impedimento/Consta → 🔴
    - CADIN irregular → 🔴
    """
    certidoes_extraidas = res.get("certidoes", {})
    sicaf = certidoes_extraidas.get("sicaf", {})
    cadin = certidoes_extraidas.get("cadin", {})
    cc    = certidoes_extraidas.get("consulta_consolidada", {})

    lista = []

    # ──────────────────────────────────────────────────────────────────
    # SICAF
    # ──────────────────────────────────────────────────────────────────
    if sicaf and sicaf.get("cnpj"):
        # Credenciamento
        situacao = sicaf.get("situacao", "—")
        st_cred = "conforme" if situacao == "Credenciado" else "bloqueio"

        # Validade do cadastro
        data_venc = sicaf.get("data_vencimento_cadastro")
        dias_venc = _dias_ate(data_venc) if data_venc else None
        val_cred_txt = (
            f"Cadastro: {data_venc} ({_texto_dias(dias_venc)})"
            if dias_venc is not None else "—"
        )
        st_venc = _status_validade(dias_venc)

        # Pior status entre situação e vencimento do cadastro
        prioridade = {"conforme": 0, "ressalva": 1, "bloqueio": 2}
        st_final = st_cred if prioridade[st_cred] > prioridade[st_venc] else st_venc

        lista.append({
            "certidao": "Credenciamento",
            "resultado": f"{sicaf['cnpj']} — {situacao}",
            "validade": val_cred_txt,
            "status": st_final,
            "indent": 1,
        })

        # Certidões individuais (validades)
        nomes_validade = {
            "receita_federal":  "Receita Federal",
            "fgts":             "FGTS",
            "trabalhista":      "Trabalhista (CNDT)",
            "receita_estadual": "Receita Estadual",
            "receita_municipal": "Receita Municipal",
            "qualif_economica": "Qualif. Econômico-Financeira",
        }
        validades = sicaf.get("validades", {})

        for chave, nome_cert in nomes_validade.items():
            data_val = validades.get(chave)
            if data_val:
                dias = _dias_ate(data_val)
                st_val = _status_validade(dias)
                val_txt = f"{data_val} ({_texto_dias(dias)})" if dias is not None else data_val
            else:
                st_val = "conforme"
                val_txt = "—"

            lista.append({
                "certidao": nome_cert,
                "resultado": "—",
                "validade": val_txt,
                "status": st_val,
                "indent": 1,
            })

        # Impedimento de Licitar
        imp = sicaf.get("impedimento_licitar", "—")
        st_imp = "conforme" if "NADA CONSTA" in imp.upper() else "bloqueio"
        lista.append({
            "certidao": "Impedimento de Licitar",
            "resultado": imp,
            "validade": "—",
            "status": st_imp,
            "indent": 1,
        })

        # Ocorrências Impeditivas Indiretas
        oii = sicaf.get("ocorrencias_impeditivas_indiretas", "—")
        st_oii = "conforme" if "NADA CONSTA" in oii.upper() else "ressalva"
        lista.append({
            "certidao": "Ocorr. Imped. Indiretas",
            "resultado": oii.split(".")[0],  # Pegar só "Consta" sem frase longa
            "validade": "—",
            "status": st_oii,
            "indent": 1,
        })

        # Vínculo com Serviço Público
        vinc = sicaf.get("vinculo_servico_publico", "—")
        st_vinc = "conforme" if "NADA CONSTA" in vinc.upper() else "bloqueio"
        lista.append({
            "certidao": "Vínculo Serv. Público",
            "resultado": vinc,
            "validade": "—",
            "status": st_vinc,
            "indent": 1,
        })
    else:
        lista.append({
            "certidao": "SICAF",
            "resultado": "⚠️ Não encontrado no PDF",
            "validade": "—",
            "status": "ressalva",
            "indent": 0,
        })

    # ──────────────────────────────────────────────────────────────────
    # CADIN
    # ──────────────────────────────────────────────────────────────────
    if cadin and cadin.get("cnpj"):
        sit_cadin = cadin.get("situacao", "—")
        st_cadin = (
            "conforme"
            if sit_cadin in ("REGULAR", "NADA CONSTA")
            else "bloqueio"
        )
        lista.append({
            "certidao": "CADIN",
            "resultado": f"{cadin['cnpj']} — {sit_cadin}",
            "validade": "—",
            "status": st_cadin,
            "indent": 0,
        })
    else:
        lista.append({
            "certidao": "CADIN",
            "resultado": "⚠️ Não encontrado no PDF",
            "validade": "—",
            "status": "ressalva",
            "indent": 0,
        })

    # ──────────────────────────────────────────────────────────────────
    # Consulta Consolidada (TCU, CNJ, CEIS, CNEP)
    # ──────────────────────────────────────────────────────────────────
    cadastros = cc.get("cadastros", []) if cc else []
    if cadastros:
        for cad in cadastros:
            resultado = cad.get("resultado", "—")
            eh_nada_consta = "NADA CONSTA" in resultado.upper()
            st_cad = "conforme" if eh_nada_consta else "bloqueio"
            lista.append({
                "certidao": cad.get("nome_curto", cad.get("cadastro", "—")),
                "resultado": resultado,
                "validade": "—",
                "status": st_cad,
                "indent": 0,
            })
    else:
        lista.append({
            "certidao": "Consulta Consolidada",
            "resultado": "⚠️ Não encontrada no PDF",
            "validade": "—",
            "status": "ressalva",
            "indent": 0,
        })

    return lista


# ── Sidebar ─────────────────────────────────────────────────────────
st.sidebar.markdown("### 📋 Análise de Processos")
st.sidebar.markdown("**SAL/CAF — Cmdo 9º Gpt Log**")
st.sidebar.divider()

pdf_file = st.sidebar.file_uploader(
    "Arraste o PDF aqui ou clique para selecionar", type=["pdf"]
)
analise_sem_nc = st.sidebar.toggle("Análise sem NC?", value=False)

st.sidebar.divider()

# ── Histórico de Análises ────────────────────────────────────────────
st.sidebar.markdown("### 📊 Histórico")

historico = database.listar_analises(limite=20)

if historico:
    # Ícones por resultado
    _icone_resultado = {
        "approval": "🟢", "caveat": "⚠️", "rejection": "🔴"
    }

    for i, h in enumerate(historico):
        icone = _icone_resultado.get(h["resultado"], "⚪")
        nup_curto = h["nup"] or "—"
        om_curto = (h["om_requisitante"] or "")[:20]
        data_str = ""
        if h.get("data_analise"):
            try:
                dt = datetime.fromisoformat(h["data_analise"])
                data_str = dt.strftime("%d/%m %H:%M")
            except (ValueError, TypeError):
                data_str = str(h["data_analise"])[:10]

        label = f"{icone} {nup_curto}"
        if om_curto:
            label += f" — {om_curto}"

        col_btn, col_del = st.sidebar.columns([5, 1])
        with col_btn:
            if st.button(label, key=f"hist_{h['id']}", use_container_width=True):
                st.session_state.carregar_analise_id = h["id"]
                st.session_state.pop("resultado_extracao", None)
                st.session_state.pop("ultimo_pdf", None)
                st.rerun()
        with col_del:
            if st.button("🗑️", key=f"del_{h['id']}",
                         help=f"Excluir análise {nup_curto}"):
                database.excluir_analise(h["id"])
                # Limpar se estava visualizando esta análise
                if st.session_state.get("visualizando_historico_id") == h["id"]:
                    st.session_state.pop("visualizando_historico_id", None)
                    st.session_state.pop("dados_historico", None)
                st.rerun()

    st.sidebar.caption(f"{len(historico)} análise(s) salva(s)")
else:
    st.sidebar.markdown("*Nenhuma análise salva ainda*")

st.sidebar.divider()

# ── Base de Pregões ──────────────────────────────────────────────────
st.sidebar.markdown("### 📦 Base de Pregões")

pregoes_db = database.listar_pregoes(limite=30)

if pregoes_db:
    for pg in pregoes_db:
        nr = pg["numero"]
        uasg = pg.get("uasg_gerenciadora") or "—"
        om = pg.get("nome_om_gerenciadora") or ""
        n_fornec = len(pg.get("fornecedores", []))
        n_proc = len(pg.get("processos_vinculados", []))

        with st.sidebar.expander(f"PE {nr} — UASG {uasg}", expanded=False):
            if om:
                st.caption(f"OM Gerenciadora: {om}")
            if pg.get("objeto"):
                st.caption(f"Objeto: {pg['objeto']}")
            st.caption(
                f"Fornecedores: {n_fornec} · "
                f"Processos: {n_proc}"
            )
            # Listar fornecedores
            for forn in pg.get("fornecedores", []):
                cnpj = forn.get("cnpj", "—")
                razao = forn.get("razao_social", "")
                st.markdown(f"- `{cnpj}` {razao}")
            # Listar processos vinculados
            if pg.get("processos_vinculados"):
                procs = ", ".join(pg["processos_vinculados"])
                st.markdown(f"📄 NUPs: {procs}")

    st.sidebar.caption(f"{len(pregoes_db)} pregão(ões) cadastrado(s)")
else:
    st.sidebar.markdown("*Nenhum pregão registrado ainda*")

# ── Base de Contratos ────────────────────────────────────────────────
st.sidebar.markdown("### 📄 Base de Contratos")

contratos_db = database.listar_contratos(limite=30)

if contratos_db:
    for ct in contratos_db:
        nr = ct["numero"]
        contratada = ct.get("contratada") or "—"
        n_proc = len(ct.get("processos_vinculados", []))

        with st.sidebar.expander(f"Contrato {nr}", expanded=False):
            if ct.get("contratada"):
                st.caption(f"Contratada: {ct['contratada']}")
            if ct.get("cnpj_contratada"):
                st.caption(f"CNPJ: {ct['cnpj_contratada']}")
            if ct.get("objeto"):
                obj_resumo = ct['objeto'][:100]
                st.caption(f"Objeto: {obj_resumo}")
            if ct.get("valor_total"):
                st.caption(f"Valor: {ct['valor_total']}")
            if ct.get("vigencia_inicio"):
                st.caption(f"Vigência: {ct['vigencia_inicio']} a {ct.get('vigencia_fim', '—')}")
            if ct.get("pregao_origem"):
                st.caption(f"Pregão de origem: PE {ct['pregao_origem']}")
            assin = "Sim ✅" if ct.get("tem_assinaturas") else "Não ⚠️"
            st.caption(f"Assinaturas: {assin}")
            if ct.get("processos_vinculados"):
                procs = ", ".join(ct["processos_vinculados"])
                st.markdown(f"📄 NUPs: {procs}")

    st.sidebar.caption(f"{len(contratos_db)} contrato(s) cadastrado(s)")
else:
    st.sidebar.markdown("*Nenhum contrato registrado ainda*")

st.sidebar.divider()
st.sidebar.markdown("**v0.4.0 — Hist + Pregões + Contratos**")


# ══════════════════════════════════════════════════════════════════════
# MODO HISTÓRICO — Carregar análise salva
# ══════════════════════════════════════════════════════════════════════
_modo_historico = False

if "carregar_analise_id" in st.session_state:
    _analise_id = st.session_state.pop("carregar_analise_id")
    _analise_salva = database.carregar_analise(_analise_id)
    if _analise_salva:
        st.session_state.visualizando_historico_id = _analise_id
        st.session_state.dados_historico = _analise_salva
    else:
        st.warning("Análise não encontrada no banco de dados.")

if "visualizando_historico_id" in st.session_state and not pdf_file:
    _modo_historico = True
    _dados_hist = st.session_state["dados_historico"]
    _dc = _dados_hist.get("dados_completos", {})

    st.info(
        f"📂 Visualizando análise salva — "
        f"**{_dados_hist.get('nup', '—')}** "
        f"({_dados_hist.get('data_analise', '')[:16]})"
    )

    # Reconstruir variáveis a partir dos dados salvos
    identificacao       = _dc.get("identificacao", {})
    itens               = _dc.get("itens", [])
    validacoes_req      = _dc.get("validacoes_req", {})
    nota_credito        = _dc.get("nota_credito", {})
    validacoes_nc       = _dc.get("validacoes_nc", [])
    certidoes           = _dc.get("certidoes", [])
    resultado           = _dc.get("resultado", {
        "tipo": "caveat", "titulo": "Análise carregada do histórico",
        "ressalvas": [], "conformes": []
    })
    # Garantir chaves mínimas no resultado
    resultado.setdefault("tipo", "caveat")
    resultado.setdefault("titulo", "—")
    resultado.setdefault("ressalvas", [])
    resultado.setdefault("conformes", [])
    mascara             = _dados_hist.get("mascara_ne")
    despacho            = _dados_hist.get("despacho") or ""
    divergencias_mascara = _dc.get("divergencias_mascara", [])
    mascara_requisitante = identificacao.get("mascara_requisitante")

    # Reconstruir simulação a partir dos dados salvos
    simulacao = {
        "uasg":        identificacao.get("uasg", "—"),
        "instrumento": identificacao.get("instrumento", "—"),
        "cnpj":        identificacao.get("cnpj", "—"),
        "item":        ", ".join(str(it.get("item", "")) for it in itens) if itens else "—",
        "pi":          identificacao.get("pi", "—"),
        "quantidade":  ", ".join(str(it.get("quantidade", "")) for it in itens) if itens else "—",
        "si":          ", ".join(str(it.get("si", "")) for it in itens) if itens else "—",
    }

# ══════════════════════════════════════════════════════════════════════
# MODO NORMAL — Processar PDF
# ══════════════════════════════════════════════════════════════════════
if not _modo_historico:
    # ── Estado vazio (sem PDF) ──────────────────────────────────────
    if not pdf_file:
        st.markdown(
            '<div class="estado-vazio">'
            '<div class="icone">📄</div>'
            '<div class="titulo">Faça upload de um processo compilado (PDF) para iniciar a análise</div>'
            '<div class="subtitulo">Formatos aceitos: PDF compilado do SPED</div>'
            '</div>',
            unsafe_allow_html=True
        )
        st.stop()

    # ── Limpar estado do histórico ao subir novo PDF ─────────────────
    if pdf_file and "visualizando_historico_id" in st.session_state:
        del st.session_state["visualizando_historico_id"]
        st.session_state.pop("dados_historico", None)

    # ── Processamento do PDF (roda apenas uma vez por arquivo) ──────
    # Usar file_id (único por upload) para detectar se é um novo PDF
    _pdf_id = getattr(pdf_file, "file_id", pdf_file.name)
    if (
        "resultado_extracao" not in st.session_state
        or st.session_state.get("ultimo_pdf_id") != _pdf_id
    ):
        progress_bar = st.progress(0)

        # Etapa 1 — extração real do PDF
        progress_bar.progress(0.15, text="Lendo e extraindo dados do PDF...")
        resultado_extracao = _processar_pdf(pdf_file)

        # Verificar se extração retornou dados
        ident_check = resultado_extracao.get("identificacao", {})
        if not ident_check.get("nup") and not ident_check.get("om"):
            print(f"[AVISO] Extração retornou dados vazios para '{pdf_file.name}'")

        # Etapas seguintes
        progress_bar.progress(0.50, text="Validando requisição...")
        time.sleep(0.2)
        progress_bar.progress(0.75, text="Verificando certidões...")
        time.sleep(0.2)
        progress_bar.progress(1.00, text="Gerando resultado...")
        time.sleep(0.2)
        progress_bar.empty()

        st.session_state.resultado_extracao = resultado_extracao
        st.session_state.pdf_processado     = True
        st.session_state.ultimo_pdf         = pdf_file.name
        st.session_state.ultimo_pdf_id      = _pdf_id

        # ── Registrar pregão/contrato no banco (automático) ─────────
        _registrar_pregao_automatico(resultado_extracao)
        _registrar_contrato_automatico(resultado_extracao)

    # ── Adaptar dados reais do extrator ─────────────────────────────
    res = st.session_state.get("resultado_extracao", {})

    identificacao  = _adaptar_identificacao(res)
    itens          = _adaptar_itens(res)
    validacoes_req = _calcular_validacoes_req(itens)
    simulacao      = _adaptar_simulacao(res, itens)
    nota_credito   = _adaptar_nc(res)
    validacoes_nc  = _calcular_validacoes_nc(nota_credito, itens, res)

    # ── Certidões — dados reais do extrator ──────────────────────────
    certidoes = _adaptar_certidoes(res)

    # ── Resultado da análise — validator (passo 4) ──────────────────
    resultado = validator.validar_processo(
        res, validacoes_req, validacoes_nc, certidoes, analise_sem_nc
    )

    # ── Máscara da NE (ne_generator — passo 5) ──────────────────────
    mascara = ne_generator.gerar_mascara(res)

    # ── Comparação de máscaras (sistema vs requisitante) ─────────────
    mascara_requisitante = res.get("identificacao", {}).get("mascara_requisitante")
    divergencias_mascara = ne_generator.comparar_mascaras(mascara, mascara_requisitante)

    # ── Despacho (despacho_generator — passo 6) ─────────────────────
    despacho = despacho_generator.gerar_despacho(resultado)


# ── Ícones dinâmicos de status dos estágios ─────────────────────────
# Proteger contra dicts que podem não ter as chaves (modo histórico)
_vals_req = validacoes_req.values() if isinstance(validacoes_req, dict) else validacoes_req
tem_ressalva_req = any(
    v.get("status") == "ressalva" for v in _vals_req
    if isinstance(v, dict)
)
icone_e2 = "⚠️" if tem_ressalva_req else "🟢"

# Estágio 3: ícone baseado nas certidões reais + validações NC + contrato
_tem_bloqueio_cert = any(c.get("status") == "bloqueio" for c in certidoes if isinstance(c, dict))
_tem_ressalva_cert = any(c.get("status") == "ressalva" for c in certidoes if isinstance(c, dict))

# validacoes_nc pode ser dict ou list dependendo do modo
_vals_nc = validacoes_nc.values() if isinstance(validacoes_nc, dict) else validacoes_nc
_tem_ressalva_nc = any(
    v.get("status") == "ressalva" for v in _vals_nc
    if isinstance(v, dict)
)

# Validações de contrato
_vals_contrato = res.get("validacoes_contrato", [])
_tem_bloqueio_contrato = any(v.get("status") == "vermelho" for v in _vals_contrato)
_tem_ressalva_contrato = any(v.get("status") == "amarelo" for v in _vals_contrato)

if _tem_bloqueio_cert or _tem_bloqueio_contrato:
    icone_e3 = "🔴"
elif _tem_ressalva_cert or _tem_ressalva_nc or _tem_ressalva_contrato:
    icone_e3 = "⚠️"
else:
    icone_e3 = "🟢"

icone_e4 = {"approval": "🟢", "caveat": "⚠️", "rejection": "🔴"}.get(
    resultado.get("tipo", "caveat"), "⚠️"
)


# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 1 — IDENTIFICAÇÃO
# ══════════════════════════════════════════════════════════════════════
with st.expander("🟢 ESTÁGIO 1 — IDENTIFICAÇÃO", expanded=True):
    components.render_identificacao(identificacao)


# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 2 — REQUISIÇÃO E ITENS
# ══════════════════════════════════════════════════════════════════════
with st.expander(f"{icone_e2} ESTÁGIO 2 — REQUISIÇÃO E ITENS", expanded=True):
    st.markdown("##### Tabela de Itens")

    if itens:
        def _fmt_valor(v, decimais=2):
            """Formata número para BRL; retorna '—' se None."""
            if v is None:
                return "—"
            fmt = f"{v:,.{decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {fmt}" if decimais == 2 else fmt

        df_itens = pd.DataFrame([
            {
                "Item":     item.get("item", "—"),
                "CatServ":  item.get("catserv") or "—",
                "Descrição": item.get("descricao") or "—",
                "UND":      item.get("und") or "—",
                "QTD":      _fmt_valor(item.get("qtd"), decimais=3).replace("R$ ", ""),
                "ND/SI":    item.get("nd_si") or "—",
                "P. Unit":  _fmt_valor(item.get("p_unit")),
                "P. Total": _fmt_valor(item.get("p_total")),
            }
            for item in itens
        ])
        st.dataframe(df_itens, width="stretch", hide_index=True)
    else:
        st.warning(
            "⚠️ Nenhum item extraído automaticamente — "
            "verificar o layout da tabela no PDF."
        )

    st.markdown("**Verificações:**")
    for val in validacoes_req.values():
        st.markdown(val["resultado"])

    # ── Simulação ComprasNet (campos lado a lado) ──
    st.markdown("---")
    st.markdown("##### Dados para Simulação ComprasNet")

    campos_sim = [
        ("UASG",        simulacao.get("uasg", "—")),
        ("Instrumento", simulacao.get("instrumento", "—")),
        ("CNPJ",        simulacao.get("cnpj", "—")),
        ("Item(ns)",    simulacao.get("item", "—")),
        ("PI",          simulacao.get("pi", "—")),
        ("Quantidade",  simulacao.get("quantidade", "—")),
        ("SI",          simulacao.get("si", "—")),
    ]

    html_sim = '<div class="simulacao-grid">'
    for label, valor in campos_sim:
        html_sim += (
            '<div class="simulacao-campo">'
            f'<div class="sim-label">{label}</div>'
            f'<div class="sim-valor">{valor}</div>'
            '</div>'
        )
    html_sim += '</div>'
    st.markdown(html_sim, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 3 — NC E CERTIDÕES
# ══════════════════════════════════════════════════════════════════════
with st.expander(f"{icone_e3} ESTÁGIO 3 — NC E CERTIDÕES", expanded=True):
    st.markdown("##### Nota de Crédito")

    if analise_sem_nc:
        st.warning("⚠️ **Modo Análise sem NC ativado** — validações da NC foram puladas.")
    else:
        components.render_nota_credito_card(nota_credito)

        st.markdown("")
        st.markdown("**Validações Cruzadas:**")
        components.render_validacoes_nc(validacoes_nc)

    st.markdown("---")
    st.markdown("##### Certidões")
    components.render_certidoes_table(certidoes)

    # ── Validações do Contrato (se processo for de contrato) ──
    validacoes_contrato = res.get("validacoes_contrato", [])
    dados_contrato = res.get("contrato", {})
    if validacoes_contrato or dados_contrato:
        st.markdown("---")
        st.markdown("##### Contrato")

        # Resumo do contrato
        if dados_contrato:
            cols_ct = st.columns(2)
            with cols_ct[0]:
                nr_ct_doc = dados_contrato.get("nr_contrato_doc", "—")
                st.metric("Nº Contrato (documento)", nr_ct_doc)
                contratada = dados_contrato.get("contratada", "—")
                st.caption(f"Contratada: {contratada}")
                cnpj_ct = dados_contrato.get("cnpj_contratada", "—")
                st.caption(f"CNPJ: {cnpj_ct}")
            with cols_ct[1]:
                vig = "—"
                if dados_contrato.get("vigencia_inicio"):
                    vig = f'{dados_contrato["vigencia_inicio"]} a {dados_contrato.get("vigencia_fim", "—")}'
                st.metric("Vigência", vig)
                if dados_contrato.get("valor_total"):
                    st.caption(f"Valor: {dados_contrato['valor_total']}")
                if dados_contrato.get("pregao_origem"):
                    st.caption(f"Pregão de origem: PE {dados_contrato['pregao_origem']}")

        # Validações cruzadas
        if validacoes_contrato:
            st.markdown("**Validações do Contrato:**")
            for val in validacoes_contrato:
                status = val.get("status", "")
                campo = val.get("campo", "")
                msg = val.get("mensagem", "")
                if status == "verde":
                    st.success(f"✅ **{campo}**: {msg}")
                elif status == "amarelo":
                    st.warning(f"⚠️ **{campo}**: {msg}")
                elif status == "vermelho":
                    st.error(f"🔴 **{campo}**: {msg}")


# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 4 — DECISÃO E OUTPUTS
# ══════════════════════════════════════════════════════════════════════
with st.expander(f"{icone_e4} ESTÁGIO 4 — DECISÃO E OUTPUTS", expanded=True):
    st.markdown("##### Resultado da Análise")
    components.render_resultado_banner(resultado)
    components.render_findings(
        resultado.get("ressalvas", []),
        resultado.get("conformes", [])
    )

    # ── Máscara da NE (largura total + botão único) ──
    if not analise_sem_nc and mascara:
        st.markdown("---")
        st.markdown("##### Máscara da NE")
        st.code(mascara, language=None)
        copiar_para_clipboard(mascara, "btn_mascara")

        # ── Divergências com máscara do requisitante ──
        if divergencias_mascara:
            with st.expander(
                f"⚠️ {len(divergencias_mascara)} divergência(s) "
                "entre a máscara do sistema e a do requisitante",
                expanded=False,
            ):
                st.caption(
                    "A máscara do sistema prevalece. "
                    "As divergências abaixo são apenas informativas."
                )
                for div in divergencias_mascara:
                    st.markdown(
                        f"- **{div['campo']}**: "
                        f"sistema = `{div['sistema']}` · "
                        f"requisitante = `{div['requisitante']}`"
                    )
        elif mascara_requisitante:
            st.caption("✅ Máscara conferida — sem divergências com a máscara do requisitante.")

    elif not analise_sem_nc and not mascara and resultado["tipo"] != "rejection":
        st.markdown("---")
        st.info("ℹ️ Máscara da NE não gerada — NC não extraída do PDF.")

    # ── Despacho (só para ressalva e reprovação) ──
    despacho_editado = despacho  # valor padrão (será sobrescrito se editável)

    if resultado.get("tipo") != "approval":
        st.markdown("---")

        st.markdown(
            '<div class="despacho-header">'
            '<span class="dh-titulo">✏️ Texto do Despacho</span>'
            '<span class="dh-dica">Clique no texto para editar</span>'
            '</div>',
            unsafe_allow_html=True
        )

        despacho_editado = st.text_area(
            "Texto do Despacho (editável)",
            value=despacho,
            height=150,
            label_visibility="collapsed"
        )

        copiar_para_clipboard(despacho_editado, "btn_despacho")
    else:
        st.markdown("---")
        st.success("✅ Processo aprovado — encaminhar ao OD para autorização do empenho.")

    # ── Botão Salvar Análise ─────────────────────────────────────────
    if not _modo_historico:
        st.markdown("---")

        col_salvar, col_obs = st.columns([1, 3])
        with col_obs:
            observacoes_usuario = st.text_input(
                "Observações (opcional)",
                placeholder="Anotações livres sobre esta análise...",
                key="obs_salvar",
            )
        with col_salvar:
            st.markdown("")  # espaçamento vertical
            if st.button("💾 Salvar Análise", type="primary",
                         use_container_width=True, key="btn_salvar"):
                try:
                    nup = identificacao.get("nup", "SEM_NUP")
                    despacho_final = despacho_editado or despacho
                    analise_id = database.salvar_analise(
                        nup=nup,
                        resultado_tipo=resultado.get("tipo", "caveat"),
                        identificacao=identificacao,
                        itens=itens,
                        nota_credito=nota_credito,
                        certidoes=certidoes,
                        validacoes_req=validacoes_req,
                        validacoes_nc=validacoes_nc,
                        resultado_validacao=resultado,
                        mascara_ne=mascara,
                        despacho=despacho_final,
                        divergencias_mascara=divergencias_mascara,
                        observacoes=observacoes_usuario or None,
                    )
                    st.success(f"✅ Análise salva com sucesso! (ID {analise_id})")
                    time.sleep(0.5)
                    st.rerun()  # Atualizar sidebar com novo histórico
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")
    else:
        # Modo histórico: mostrar observações e botão para voltar
        st.markdown("---")
        _obs_salva = st.session_state.get("dados_historico", {}).get("observacoes")
        if _obs_salva:
            st.caption(f"📝 Observações: {_obs_salva}")

        if st.button("🔙 Voltar para nova análise", use_container_width=True):
            st.session_state.pop("visualizando_historico_id", None)
            st.session_state.pop("dados_historico", None)
            st.rerun()


# ── Rodapé ──────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Análise concluída • SAL/CAF — Cmdo 9º Gpt Log")
