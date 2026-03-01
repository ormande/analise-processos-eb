import streamlit as st
import pandas as pd
import time
import os
import json
import tempfile
from datetime import datetime, date, timezone, timedelta
from modules import (
    mock_data, components, database, extractor,
    validator, ne_generator, despacho_generator,
)

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
    
    Em caso de erro, levanta exceção com mensagem clara.
    """
    tmp_path = None
    try:
        # Validar tamanho do arquivo (máximo 50MB)
        tamanho_mb = len(pdf_file.getvalue()) / (1024 * 1024)
        if tamanho_mb > 50:
            raise ValueError(
                f"Arquivo muito grande ({tamanho_mb:.1f} MB). "
                "O tamanho máximo permitido é 50 MB."
            )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_file.getvalue())
            tmp_path = tmp.name
        
        resultado = extractor.extrair_processo(tmp_path)
        
        # Validar se extração retornou dados mínimos
        if not resultado or not isinstance(resultado, dict):
            raise ValueError(
                "A extração do PDF não retornou dados válidos. "
                "Verifique se o arquivo é um PDF compilado válido."
            )
        
        return resultado
        
    except ValueError as e:
        # Erros de validação - re-raise com mensagem clara
        raise
    except Exception as e:
        # Outros erros - fornecer contexto
        raise Exception(
            f"Erro ao processar o PDF '{pdf_file.name}': {str(e)}\n\n"
            "Possíveis causas:\n"
            "- Arquivo corrompido ou incompleto\n"
            "- Formato de PDF não suportado\n"
            "- Problema temporário de leitura\n\n"
            "Tente novamente ou verifique o arquivo."
        ) from e
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


def _adaptar_nc(res: dict) -> list[dict]:
    """
    Retorna lista de cards das NCs para exibição na interface.
    
    Se houver múltiplas NCs no processo, retorna todas adaptadas.
    Se houver apenas 1 NC, retorna lista com 1 item (mantém compatibilidade).
    Se não houver NC real, retorna lista com 1 item de fallback.

    Prioridade:
    1. Dados reais extraídos do documento NC (passo 2 — implementado)
    2. Fallback: patch do mock com campos da requisição (número, ND, PI etc.)
    """
    ncs_reais = res.get("nota_credito", [])
    ident     = res.get("identificacao", {})

    if ncs_reais:
        # Adaptar todas as NCs reais
        ncs_adaptadas = []
        nd_req = ident.get("nd")  # ND da requisição para comparação
        
        for nc_real in ncs_reais:
            dias = nc_real.get("dias_restantes")
            # dias pode ser int (calculado) ou None (prazo não extraído)
            dias_str = dias if dias is not None else "N/A"

            # ── Selecionar ND que confere com a requisição ──
            linhas_evento = nc_real.get("linhas_evento", [])
            nd_selecionada = nc_real.get("nd") or "—"
            nd_divergente = False
            nota_multiplas_nds = ""
            
            if linhas_evento and nd_req:
                # Extrair todas as NDs distintas das linhas de evento
                nds_distintas = set()
                for linha in linhas_evento:
                    nd_linha = linha.get("nd")
                    if nd_linha:
                        nds_distintas.add(nd_linha)
                
                # Normalizar ND da requisição (remover pontos para comparação)
                nd_req_norm = nd_req.replace(".", "")
                
                # Procurar ND que confere com a requisição
                nd_conferente = None
                for nd_linha in nds_distintas:
                    nd_linha_norm = nd_linha.replace(".", "")
                    if nd_linha_norm == nd_req_norm:
                        nd_conferente = nd_linha
                        break
                
                if nd_conferente:
                    # Encontrou ND que confere: usar essa
                    nd_selecionada = nd_conferente
                    # Buscar linha de evento correspondente para pegar outros campos
                    linha_conferente = next(
                        (l for l in linhas_evento if l.get("nd") == nd_conferente),
                        None
                    )
                    if linha_conferente:
                        # Atualizar campos com dados da linha que confere
                        nc_real = nc_real.copy()  # Não modificar original
                        nc_real["nd"] = linha_conferente.get("nd")
                        nc_real["ptres"] = linha_conferente.get("ptres")
                        nc_real["fonte"] = linha_conferente.get("fonte")
                        nc_real["ugr"] = linha_conferente.get("ugr")
                        nc_real["pi"] = linha_conferente.get("pi")
                        nc_real["esf"] = linha_conferente.get("esf")
                        # Saldo da linha que confere
                        nc_real["saldo"] = linha_conferente.get("valor")
                else:
                    # Nenhuma ND confere: usar primeira e sinalizar divergência
                    nd_selecionada = nc_real.get("nd") or "—"
                    nd_divergente = True
                
                # Nota se houver múltiplas NDs diferentes
                if len(nds_distintas) > 1:
                    nds_lista = sorted(nds_distintas)
                    nota_multiplas_nds = f" (NC possui saldos em outras NDs: {', '.join(nds_lista)})"

            ncs_adaptadas.append({
                "numero":        nc_real.get("numero") or "—",
                "data_emissao":  nc_real.get("data_emissao") or "—",
                "ug_emitente":   _fmt_ug(nc_real.get("ug_emitente"),
                                         nc_real.get("nome_emitente")),
                "ug_favorecida": _fmt_ug(nc_real.get("ug_favorecida"),
                                         nc_real.get("nome_favorecida")),
                "nd":            nd_selecionada + nota_multiplas_nds if nota_multiplas_nds else nd_selecionada,
                "nd_divergente": nd_divergente,  # Flag para indicar divergência
                "ptres":         nc_real.get("ptres") or "—",
                "fonte":         nc_real.get("fonte") or "—",
                "ugr":           nc_real.get("ugr") or "—",
                "pi":            nc_real.get("pi") or "—",
                "esf":           nc_real.get("esf") or "—",
                # saldo pode ser None quando não foi possível extrair
                "saldo":         nc_real.get("saldo"),
                "prazo_empenho": nc_real.get("prazo_empenho") or "—",
                "dias_restantes": dias_str,
            })
        return ncs_adaptadas

    # ── Fallback: construir NC a partir dos dados da requisição ──
    # (sem documento NC no PDF — campos financeiros vêm do texto da req)
    return [{
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
    }]


def _calcular_validacoes_nc(notas_credito: list[dict], itens: list, res: dict) -> list:
    """
    Calcula as validações cruzadas entre as NCs e a Requisição.
    Considera TODAS as NCs quando há múltiplas:
    1. ND das NCs vs ND da Requisição (verifica se pelo menos uma confere)
    2. Saldo total de todas as NCs vs Valor Total dos itens
    3. Prazo de empenho mais próximo do vencimento (mais urgente)

    Retorna lista de dicts no formato esperado por render_validacoes_nc().
    Regras de severidade conforme ESPECIFICACAO_LOGICA_NEGOCIO_v2:
    - 🟢 conforme, ⚠️ ressalva, 🔴 bloqueio (vermelho → "bloqueio")
    """
    validacoes = []
    ident = res.get("identificacao", {})

    # ── Dados da Requisição ──
    nd_req    = ident.get("nd")
    total_req = sum(item.get("p_total") or 0.0 for item in itens)

    # ── Agregar dados de todas as NCs ──
    nds_nc = [nc.get("nd") for nc in notas_credito if nc.get("nd") and nc.get("nd") != "—"]
    saldos_nc = [nc.get("saldo") for nc in notas_credito if nc.get("saldo") is not None]
    total_saldo = sum(saldos_nc) if saldos_nc else None

    # Encontrar prazo mais urgente (menor dias_restantes)
    prazos_urgentes = []
    for nc in notas_credito:
        dias = nc.get("dias_restantes")
        if dias is not None and isinstance(dias, int):
            prazo_raw = nc.get("prazo_empenho") or "—"
            prazos_urgentes.append((dias, prazo_raw, nc.get("numero", "—")))

    # 1. ND das NCs vs ND da Requisição
    if nds_nc and nd_req:
        nd_req_norm = nd_req.replace(".", "")
        
        # Verificar se pelo menos uma NC tem a mesma ND da requisição
        ncs_conferem = [nd for nd in nds_nc if nd.replace(".", "") == nd_req_norm]
        ncs_genericas = [nd for nd in nds_nc if nd.replace(".", "") == "339000"]
        
        if ncs_conferem:
            # Pelo menos uma NC confere
            if len(nds_nc) == 1:
                validacoes.append({
                    "verificacao": "ND da NC vs ND da Requisição",
                    "resultado":   f"{nds_nc[0]} = {nd_req}",
                    "status":      "conforme",
                })
            else:
                # Múltiplas NCs: mostrar quais conferem
                nds_str = " + ".join([f"NC{i+1}: {nd}" for i, nd in enumerate(nds_nc)])
                validacoes.append({
                    "verificacao": "ND das NCs vs ND da Requisição",
                    "resultado":   f"{nds_str} — {len(ncs_conferem)} confere(m) com Req: {nd_req}",
                    "status":      "conforme",
                })
        elif ncs_genericas:
            # Todas são genéricas
            if len(nds_nc) == 1:
                validacoes.append({
                    "verificacao": "ND da NC vs ND da Requisição",
                    "resultado":   f"⚠️ NC com ND genérica ({nds_nc[0]}) — Req usa {nd_req} — verificar DETAORC",
                    "status":      "ressalva",
                })
            else:
                nds_str = " + ".join([f"NC{i+1}: {nd}" for i, nd in enumerate(nds_nc)])
                validacoes.append({
                    "verificacao": "ND das NCs vs ND da Requisição",
                    "resultado":   f"⚠️ {nds_str} — todas genéricas, Req usa {nd_req} — verificar DETAORC",
                    "status":      "ressalva",
                })
        else:
            # Nenhuma confere
            if len(nds_nc) == 1:
                validacoes.append({
                    "verificacao": "ND da NC vs ND da Requisição",
                    "resultado":   f"⚠️ NC: {nds_nc[0]} ≠ Req: {nd_req} — verificar com analista",
                    "status":      "ressalva",
                })
            else:
                nds_str = " + ".join([f"NC{i+1}: {nd}" for i, nd in enumerate(nds_nc)])
                validacoes.append({
                    "verificacao": "ND das NCs vs ND da Requisição",
                    "resultado":   f"⚠️ {nds_str} ≠ Req: {nd_req} — verificar com analista",
                    "status":      "ressalva",
                })
    else:
        nd_info = (nds_nc[0] if nds_nc else None) or nd_req or "não extraído"
        validacoes.append({
            "verificacao": "ND da NC vs ND da Requisição",
            "resultado":   f"— ({nd_info})",
            "status":      "conforme",
        })

    # 2. Saldo total de todas as NCs vs Valor Total Requisição
    if total_saldo is not None and total_saldo > 0 and total_req > 0:
        def _fmt(v):
            """Formata valor monetário em R$ brasileiro."""
            valor_formatado = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {valor_formatado}"

        if len(saldos_nc) > 1:
            # Múltiplas NCs: mostrar soma
            saldos_str = " + ".join([_fmt(s) for s in saldos_nc])
            if total_saldo >= total_req:
                validacoes.append({
                    "verificacao": "Saldo vs Valor Requisição",
                    "resultado":   f"{saldos_str} = {_fmt(total_saldo)} ≥ {_fmt(total_req)}",
                    "status":      "conforme",
                })
            else:
                validacoes.append({
                    "verificacao": "Saldo vs Valor Requisição",
                    "resultado":   (
                        f"⚠️ {saldos_str} = {_fmt(total_saldo)} < {_fmt(total_req)} — "
                        "pode haver saldo complementar de outras datas"
                    ),
                    "status":      "ressalva",
                })
        else:
            # Uma NC
            if total_saldo >= total_req:
                validacoes.append({
                    "verificacao": "Saldo vs Valor Requisição",
                    "resultado":   f"{_fmt(total_saldo)} ≥ {_fmt(total_req)}",
                    "status":      "conforme",
                })
            else:
                validacoes.append({
                    "verificacao": "Saldo vs Valor Requisição",
                    "resultado":   (
                        f"⚠️ Saldo {_fmt(total_saldo)} < {_fmt(total_req)} — "
                        "pode haver saldo complementar de outras datas"
                    ),
                    "status":      "ressalva",
                })
    else:
        validacoes.append({
            "verificacao": "Saldo vs Valor Requisição",
            "resultado":   "— (saldo não extraído)",
            "status":      "conforme",
        })

    # 3. Prazo de empenho mais urgente (menor dias_restantes)
    if prazos_urgentes:
        # Ordenar por dias_restantes (menor = mais urgente)
        prazos_urgentes.sort(key=lambda x: x[0])
        dias, prazo_raw, numero_nc = prazos_urgentes[0]
        
        if dias < 0:
            status  = "ressalva"
            texto   = f"⚠️ VENCIDO há {abs(dias)} dias ({prazo_raw})"
            if len(prazos_urgentes) > 1:
                texto += f" — NC mais urgente: {numero_nc}"
        elif dias <= 7:
            status  = "ressalva"
            texto   = f"⚠️ {prazo_raw} — URGENTE: {dias} dias restantes"
            if len(prazos_urgentes) > 1:
                texto += f" — NC mais urgente: {numero_nc}"
        elif dias <= 15:
            status  = "ressalva"
            texto   = f"⚠️ {prazo_raw} — {dias} dias (atenção: pode vencer antes do empenho)"
            if len(prazos_urgentes) > 1:
                texto += f" — NC mais urgente: {numero_nc}"
        else:
            status  = "conforme"
            texto   = f"{prazo_raw} — {dias} dias restantes"
            if len(prazos_urgentes) > 1:
                texto += f" — NC mais urgente: {numero_nc}"
        
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
        return (dt - hoje_cg()).days
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
        imp_upper = imp.upper()
        # Sistema indisponível → ressalva (amarelo), não bloqueio
        if "INDISPONÍVEL" in imp_upper or "INDISPONIVEL" in imp_upper:
            st_imp = "ressalva"
        elif "NADA CONSTA" in imp_upper:
            st_imp = "conforme"
        else:
            st_imp = "bloqueio"
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
        vinc_upper = vinc.upper()
        # Sistema indisponível → ressalva (amarelo), não bloqueio
        if "INDISPONÍVEL" in vinc_upper or "INDISPONIVEL" in vinc_upper:
            st_vinc = "ressalva"
        elif "NADA CONSTA" in vinc_upper:
            st_vinc = "conforme"
        else:
            st_vinc = "bloqueio"
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
        sit_cadin_upper = sit_cadin.upper()
        # Sistema indisponível → ressalva (amarelo), não bloqueio
        if "INDISPONÍVEL" in sit_cadin_upper or "INDISPONIVEL" in sit_cadin_upper:
            st_cadin = "ressalva"
        elif sit_cadin in ("REGULAR", "NADA CONSTA"):
            st_cadin = "conforme"
        else:
            st_cadin = "bloqueio"
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
            resultado_upper = resultado.upper()
            
            # Sistema indisponível → ressalva (amarelo), não bloqueio
            # Indisponível ≠ empresa irregular
            if "INDISPONÍVEL" in resultado_upper or "INDISPONIVEL" in resultado_upper:
                st_cad = "ressalva"
            elif "NADA CONSTA" in resultado_upper:
                st_cad = "conforme"
            else:
                st_cad = "bloqueio"
            
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

# ── Navegação ─────────────────────────────────────────────────────────
pagina = st.sidebar.radio(
    "Navegação",
    ["📋 Análise", "📊 Histórico", "📦 Base de Dados"],
    label_visibility="collapsed",
)

st.sidebar.divider()

# ── Link para histórico completo ───────────────────────────────
if st.sidebar.button("📊 Ver Histórico Completo", use_container_width=True):
    st.switch_page("pages/1_Historico.py")

st.sidebar.divider()

# ── Histórico de Análises (resumo rápido) ────────────────────────────
st.sidebar.markdown("### 📊 Histórico Rápido")

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
st.sidebar.markdown("**v0.5.0 — Interface Renovada**")


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: HISTÓRICO
# ══════════════════════════════════════════════════════════════════════
if pagina == "📊 Histórico":
    st.info("📊 **Página de Histórico** — Use o menu lateral para acessar a página dedicada com busca, filtros e estatísticas completas.")
    st.markdown("---")
    
    # Botão para acessar página completa
    st.markdown("### Acesse a página completa:")
    if st.button("🔗 Ir para Histórico Completo", use_container_width=True, type="primary"):
        st.switch_page("pages/1_Historico.py")
    
    # Mostrar resumo rápido
    stats = database.obter_estatisticas_analises()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total", stats["total"])
    with col2:
        st.metric("🟢 Aprovadas", stats["por_resultado"].get("approval", 0))
    with col3:
        st.metric("⚠️ Ressalvas", stats["por_resultado"].get("caveat", 0))
    
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: BASE DE DADOS (Pregões e Contratos)
# ══════════════════════════════════════════════════════════════════════
if pagina == "📦 Base de Dados":

    # ── Pregões (Licitações) ─────────────────────────────────────────
    pregoes_db = database.listar_pregoes(limite=50)

    st.markdown(
        '<div class="db-section-header">'
        '<h4 style="margin:0;color:#e2e8f0">📦 Pregões Eletrônicos</h4>'
        f'<span class="db-count">{len(pregoes_db)} registrado(s)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if pregoes_db:
        html_pe = '<table class="db-table"><thead><tr>'
        html_pe += '<th>Nº PE</th><th>OM Gerenciadora</th><th>Objeto</th>'
        html_pe += '<th>Fornecedores</th><th>Processos</th><th>CNPJ / Razão Social</th>'
        html_pe += '</tr></thead><tbody>'

        for pg in pregoes_db:
            nr = pg.get("numero", "—")
            uasg = pg.get("uasg_gerenciadora") or "—"
            om = pg.get("nome_om_gerenciadora") or "—"
            om_display = f"{uasg} — {om}" if om != "—" else uasg
            objeto = (pg.get("objeto") or "—")[:80]
            fornecedores = pg.get("fornecedores", [])
            n_fornec = len(fornecedores)
            n_proc = len(pg.get("processos_vinculados", []))

            # Montar lista de fornecedores
            forn_html = ""
            if fornecedores:
                for f in fornecedores:
                    cnpj = f.get("cnpj", "—")
                    razao = f.get("razao_social", "")
                    forn_html += f'<span class="mono">{cnpj}</span> {razao}<br>'
            else:
                forn_html = '<span class="text-muted">—</span>'

            html_pe += (
                f'<tr>'
                f'<td><strong>PE {nr}</strong></td>'
                f'<td>{om_display}</td>'
                f'<td>{objeto}</td>'
                f'<td style="text-align:center">{n_fornec}</td>'
                f'<td style="text-align:center">{n_proc}</td>'
                f'<td>{forn_html}</td>'
                f'</tr>'
            )

        html_pe += '</tbody></table>'
        st.markdown(html_pe, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="db-empty">Nenhum pregão registrado ainda.<br>'
            '<small>Pregões são registrados automaticamente ao analisar processos.</small></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")
    st.markdown("")

    # ── Contratos ────────────────────────────────────────────────────
    contratos_db = database.listar_contratos(limite=50)

    st.markdown(
        '<div class="db-section-header">'
        '<h4 style="margin:0;color:#e2e8f0">📄 Contratos</h4>'
        f'<span class="db-count">{len(contratos_db)} registrado(s)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if contratos_db:
        html_ct = '<table class="db-table"><thead><tr>'
        html_ct += '<th>Nº Contrato</th><th>Objeto</th><th>Processos</th>'
        html_ct += '<th>CNPJ / Contratada</th><th>Vigência</th><th>PE Origem</th>'
        html_ct += '</tr></thead><tbody>'

        for ct in contratos_db:
            nr = ct.get("numero", "—")
            objeto = (ct.get("objeto") or "—")[:80]
            n_proc = len(ct.get("processos_vinculados", []))
            contratada = ct.get("contratada") or "—"
            cnpj_ct = ct.get("cnpj_contratada") or ""

            # Vigência
            vig_inicio = ct.get("vigencia_inicio")
            vig_fim = ct.get("vigencia_fim")
            if vig_inicio:
                vigencia = f"{vig_inicio} a {vig_fim or '—'}"
            else:
                vigencia = "—"

            # Pregão de origem — validar 5 dígitos
            pe_origem = ct.get("pregao_origem") or "—"
            pe_display = pe_origem
            if pe_origem != "—":
                pe_num = pe_origem.replace("/", "").replace("-", "").strip()
                # Extrair apenas parte numérica antes do ano
                pe_parts = pe_origem.split("/")
                if pe_parts and len(pe_parts[0].strip()) == 5:
                    pe_display = f"PE {pe_origem}"
                elif pe_parts and pe_parts[0].strip().isdigit():
                    pe_display = f'PE {pe_origem} <span class="text-muted">⚠️</span>'
                else:
                    pe_display = pe_origem

            # CNPJ + nome
            forn_display = ""
            if cnpj_ct:
                forn_display = f'<span class="mono">{cnpj_ct}</span><br>{contratada}'
            else:
                forn_display = contratada

            html_ct += (
                f'<tr>'
                f'<td><strong>{nr}</strong></td>'
                f'<td>{objeto}</td>'
                f'<td style="text-align:center">{n_proc}</td>'
                f'<td>{forn_display}</td>'
                f'<td>{vigencia}</td>'
                f'<td>{pe_display}</td>'
                f'</tr>'
            )

        html_ct += '</tbody></table>'
        st.markdown(html_ct, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="db-empty">Nenhum contrato registrado ainda.<br>'
            '<small>Contratos são registrados automaticamente ao analisar processos.</small></div>',
            unsafe_allow_html=True,
        )

    # Rodapé
    st.markdown("---")
    st.caption("Base de Dados Orgânica • SAL/CAF — Cmdo 9º Gpt Log")
    st.stop()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: ANÁLISE
# ══════════════════════════════════════════════════════════════════════
if pagina == "📋 Análise":
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
    nota_credito_raw    = _dc.get("nota_credito", {})
    # Garantir que nota_credito seja sempre um dict (compatibilidade)
    nota_credito        = nota_credito_raw if isinstance(nota_credito_raw, dict) else (nota_credito_raw[0] if isinstance(nota_credito_raw, list) and nota_credito_raw else {})
    # Criar lista de NCs adaptadas (pode ser uma lista de dicts ou apenas um dict)
    notas_credito       = [nota_credito] if isinstance(nota_credito, dict) else (nota_credito_raw if isinstance(nota_credito_raw, list) else [])
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
    
    # Reconstruir 'res' (resultado da extração) para compatibilidade com código abaixo
    res = {
        "identificacao": identificacao,
        "itens": itens,
        "nota_credito": [nota_credito] if isinstance(nota_credito, dict) else (nota_credito if isinstance(nota_credito, list) else []),
        "certidoes": {"sicaf": {}, "cadin": {}, "consulta_consolidada": {}},  # Simplificado
        "validacoes_contrato": _dc.get("validacoes_contrato", []),
        "contrato": _dc.get("contrato", {}),
    }

# ══════════════════════════════════════════════════════════════════════
# MODO NORMAL — Processar PDF
# ══════════════════════════════════════════════════════════════════════
if not _modo_historico:
    # ── Estado vazio (sem PDF) ──────────────────────────────────────
    # Se não há PDF mas há análise em andamento/concluída, continuar exibindo
    if not pdf_file and "resultado_extracao" not in st.session_state:
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
    # Se não há PDF mas há resultado_extracao, pular processamento (análise já em andamento/concluída)
    if not pdf_file and "resultado_extracao" in st.session_state:
        # Análise já existe, pular processamento
        pass
    elif pdf_file:
        # Usar file_id (único por upload) para detectar se é um novo PDF
        _pdf_id = getattr(pdf_file, "file_id", pdf_file.name)
        if (
            "resultado_extracao" not in st.session_state
            or st.session_state.get("ultimo_pdf_id") != _pdf_id
        ):
            # Placeholders para feedback visual
            status_info = st.empty()
            status_info.info("🔄 **Processando PDF...** Por favor, aguarde.")
            progress_bar = st.progress(0)
            status_text = st.empty()

            try:
                # Etapa 1 — extração real do PDF
                status_text.markdown("📄 **Etapa 1/4:** Lendo e extraindo dados do PDF...")
                progress_bar.progress(0.10)
                resultado_extracao = _processar_pdf(pdf_file)

                # Verificar se extração retornou dados
                ident_check = resultado_extracao.get("identificacao", {})
                if not ident_check.get("nup") and not ident_check.get("om"):
                    st.warning(
                        f"⚠️ **Atenção:** A extração retornou poucos dados para '{pdf_file.name}'. "
                        "Verifique se o PDF está completo e legível."
                    )

                # Etapa 2 — validação da requisição
                status_text.markdown("✅ **Etapa 2/4:** Validando requisição e itens...")
                progress_bar.progress(0.40)
                time.sleep(0.1)

                # Etapa 3 — verificação de certidões
                status_text.markdown("🔍 **Etapa 3/4:** Verificando certidões e NC...")
                progress_bar.progress(0.70)
                time.sleep(0.1)

                # Etapa 4 — geração de resultado
                status_text.markdown("📊 **Etapa 4/4:** Gerando resultado final...")
                progress_bar.progress(0.90)
                time.sleep(0.1)

                progress_bar.progress(1.00)
                status_text.markdown("✅ **Processamento concluído!**")
                time.sleep(0.3)

                # Limpar feedback
                status_info.empty()
                progress_bar.empty()
                status_text.empty()

                st.session_state.resultado_extracao = resultado_extracao
                st.session_state.pdf_processado     = True
                st.session_state.ultimo_pdf         = pdf_file.name
                st.session_state.ultimo_pdf_id      = _pdf_id

                # ── Registrar pregão/contrato no banco (automático) ─────────
                try:
                    _registrar_pregao_automatico(resultado_extracao)
                    _registrar_contrato_automatico(resultado_extracao)
                except Exception as e:
                    print(f"[AVISO] Erro ao registrar no banco: {e}")

            except Exception as e:
                # Limpar feedback em caso de erro
                status_info.empty()
                progress_bar.empty()
                status_text.empty()
                
                # Mensagem de erro mais clara
                st.error(
                    f"❌ **Erro ao processar o PDF:**\n\n"
                    f"**Detalhes:** {str(e)}\n\n"
                    f"**Sugestões:**\n"
                    f"- Verifique se o arquivo não está corrompido\n"
                    f"- Tente abrir o PDF em outro leitor para confirmar que está íntegro\n"
                    f"- Se o erro persistir, entre em contato com o suporte"
                )
                st.stop()

    # ── Adaptar dados reais do extrator ─────────────────────────────
    res = st.session_state.get("resultado_extracao", {})

    identificacao  = _adaptar_identificacao(res)
    itens          = _adaptar_itens(res)
    validacoes_req = _calcular_validacoes_req(itens)
    simulacao      = _adaptar_simulacao(res, itens)
    notas_credito  = _adaptar_nc(res)  # Agora retorna lista
    # Para compatibilidade: manter nota_credito como primeira NC (usado em outros lugares)
    nota_credito   = notas_credito[0] if notas_credito else {}
    validacoes_nc  = _calcular_validacoes_nc(notas_credito, itens, res)

    # ── Certidões — dados reais do extrator ──────────────────────────
    certidoes = _adaptar_certidoes(res)

    # ── Resultado da análise — validator (passo 4) ──────────────────
    # No modo histórico, usar res já reconstruído; no modo normal, usar res do processamento
    if not _modo_historico:
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
    else:
        # Modo histórico: resultado, máscara e despacho já foram salvos
        # mascara, despacho e divergencias_mascara já foram carregados acima
        pass

# ── Garantir que 'res' esteja sempre definido ────────────────────────
if "_modo_historico" in locals() and _modo_historico:
    # No modo histórico, res já foi criado acima
    pass
elif "res" not in locals():
    # Fallback: criar res vazio se não foi definido
    res = {}


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

# Validações de contrato (proteger contra res não definido)
_vals_contrato = res.get("validacoes_contrato", []) if "res" in locals() and res else []
_tem_bloqueio_contrato = any(v.get("status") == "vermelho" for v in _vals_contrato) if _vals_contrato else False
_tem_ressalva_contrato = any(v.get("status") == "amarelo" for v in _vals_contrato) if _vals_contrato else False

if _tem_bloqueio_cert or _tem_bloqueio_contrato:
    icone_e3 = "🔴"
elif _tem_ressalva_cert or _tem_ressalva_nc or _tem_ressalva_contrato:
    icone_e3 = "⚠️"
else:
    icone_e3 = "🟢"

icone_e4 = {"approval": "🟢", "caveat": "⚠️", "rejection": "🔴"}.get(
    resultado.get("tipo", "caveat"), "⚠️"
)

# ── Botões de ação no topo (Salvar e Descartar) ───────────────────────
if not _modo_historico and st.session_state.get("resultado_extracao"):
    st.markdown("---")
    
    # Campo de observações no topo
    # O st.text_input já gerencia automaticamente o session_state com a key
    observacoes_topo = st.text_input(
        "Observações (opcional)",
        placeholder="Anotações livres sobre esta análise...",
        key="obs_salvar",
        value=st.session_state.get("obs_salvar", "")
    )
    
    # Botões de ação
    col_salvar_topo, col_descartar_topo = st.columns(2)
    
    with col_salvar_topo:
        if st.button("💾 Salvar Análise", type="primary", use_container_width=True, key="btn_salvar_topo"):
            # Mesma lógica do botão de salvar de baixo
            try:
                nup = identificacao.get("nup", "SEM_NUP")
                despacho_final = st.session_state.get("despacho_editado") or despacho
                observacoes_usuario = st.session_state.get("obs_salvar", "")
                
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
                st.rerun()
            except Exception as e:
                st.error(
                    f"❌ **Erro ao salvar análise:**\n\n"
                    f"**Detalhes:** {str(e)}\n\n"
                    f"**Sugestões:**\n"
                    f"- Verifique se o banco de dados está acessível\n"
                    f"- Tente salvar novamente\n"
                    f"- Se o erro persistir, verifique os logs do sistema"
                )
    
    with col_descartar_topo:
        if st.button("🗑️ Descartar Análise", use_container_width=True, key="btn_descartar_topo"):
            st.session_state["mostrar_modal_descartar"] = True
            st.rerun()
    
    # Modal de confirmação para descartar
    if st.session_state.get("mostrar_modal_descartar", False):
        st.markdown("---")
        st.warning("⚠️ **Descartar Análise**")
        st.markdown("Tem certeza que deseja descartar esta análise? Esta ação não pode ser desfeita.")
        
        col_confirmar, col_cancelar = st.columns(2)
        with col_confirmar:
            if st.button("✅ Sim, Descartar", type="primary", use_container_width=True, key="btn_confirmar_descartar"):
                # Limpar todos os dados da análise
                st.session_state.pop("resultado_extracao", None)
                st.session_state.pop("pdf_processado", None)
                st.session_state.pop("ultimo_pdf", None)
                st.session_state.pop("ultimo_pdf_id", None)
                st.session_state.pop("despacho_editado", None)
                st.session_state.pop("obs_salvar", None)
                st.session_state.pop("mostrar_modal_descartar", None)
                st.rerun()
        
        with col_cancelar:
            if st.button("❌ Cancelar", use_container_width=True, key="btn_cancelar_descartar"):
                st.session_state.pop("mostrar_modal_descartar", None)
                st.rerun()
    
    st.markdown("")  # Espaçamento

# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 1 — IDENTIFICAÇÃO
# ══════════════════════════════════════════════════════════════════════
with st.expander("🟢 ESTÁGIO 1 — IDENTIFICAÇÃO", expanded=True):
    components.render_identificacao(identificacao)
    st.markdown("")  # Espaçamento inferior


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
    components.render_verificacoes_req(validacoes_req)

    # ── Simulação ComprasNet (campos essenciais) ──
    st.markdown("---")
    st.markdown("##### Dados para Simulação ComprasNet")

    campos_sim = [
        ("UASG",        simulacao.get("uasg", "—")),
        ("Instrumento", simulacao.get("instrumento", "—")),
        ("CNPJ",        simulacao.get("cnpj", "—")),
        ("PI",          simulacao.get("pi", "—")),
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
    
    # Espaçamento inferior para aumentar a box do estágio 2
    st.markdown("")
    st.markdown("")


# ══════════════════════════════════════════════════════════════════════
# ESTÁGIO 3 — NC E CERTIDÕES
# ══════════════════════════════════════════════════════════════════════
with st.expander(f"{icone_e3} ESTÁGIO 3 — NC E CERTIDÕES", expanded=True):
    st.markdown("##### Nota de Crédito")

    if analise_sem_nc:
        st.warning("⚠️ **Modo Análise sem NC ativado** — validações da NC foram puladas.")
    else:
        # Exibir múltiplas NCs em abas se houver mais de uma
        if len(notas_credito) > 1:
            # Criar abas para cada NC
            tabs = st.tabs([f"NC {i+1}: {nc.get('numero', '—')}" for i, nc in enumerate(notas_credito)])
            for tab, nc in zip(tabs, notas_credito):
                with tab:
                    components.render_nota_credito_card(nc)
        else:
            # Uma única NC: exibir normalmente
            components.render_nota_credito_card(notas_credito[0] if notas_credito else {})

        st.markdown("")
        st.markdown("**Validações Cruzadas:**")
        components.render_validacoes_nc(validacoes_nc)

    st.markdown("---")
    st.markdown("##### Certidões")
    components.render_certidoes_table(certidoes)

    # ── Validações do Contrato (se processo for de contrato) ──
    validacoes_contrato = res.get("validacoes_contrato", []) if "res" in locals() and res else []
    dados_contrato = res.get("contrato", {}) if "res" in locals() and res else {}
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
    # Usar session_state para persistir o despacho editado
    if "despacho_editado" not in st.session_state:
        st.session_state["despacho_editado"] = despacho
    
    despacho_editado = st.session_state.get("despacho_editado", despacho)

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
            value=st.session_state.get("despacho_editado", despacho),
            height=150,
            label_visibility="collapsed",
            key="text_area_despacho"
        )
        # Salvar no session_state sempre que for editado
        st.session_state["despacho_editado"] = despacho_editado

        copiar_para_clipboard(despacho_editado, "btn_despacho")
    else:
        st.markdown("---")
        st.success("✅ Processo aprovado — encaminhar ao OD para autorização do empenho.")

    # ── Botão Salvar Análise (final da página) ────────────────────────
    if not _modo_historico:
        st.markdown("---")

        # Campo de observações já está no topo, então só mostrar botão aqui
        if st.button("💾 Salvar Análise", type="primary",
                     use_container_width=True, key="btn_salvar"):
            try:
                nup = identificacao.get("nup", "SEM_NUP")
                despacho_final = despacho_editado or despacho
                observacoes_usuario = st.session_state.get("obs_salvar", "")
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
                st.error(
                    f"❌ **Erro ao salvar análise:**\n\n"
                    f"**Detalhes:** {str(e)}\n\n"
                    f"**Sugestões:**\n"
                    f"- Verifique se o banco de dados está acessível\n"
                    f"- Tente salvar novamente\n"
                    f"- Se o erro persistir, verifique os logs do sistema"
                )
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
