"""
Dados mock estáticos para demonstração da interface.
Baseados no Processo 65297.001232/2026-90 (contrato ar condicionado).

As datas de certidões e NC são calculadas dinamicamente com base
na data atual para demonstrar corretamente os status.
"""

from datetime import date, datetime


def _dias_ate(data_str: str) -> int:
    """Calcula dias entre hoje e uma data no formato DD/MM/YYYY."""
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y").date()
        return (dt - date.today()).days
    except ValueError:
        return 0


def _status_validade(dias: int) -> str:
    """Retorna status baseado nos dias restantes."""
    if dias < 0:
        return "bloqueio"
    elif dias <= 30:
        return "ressalva"
    return "conforme"


def _texto_dias(dias: int) -> str:
    """Retorna texto legível dos dias restantes."""
    if dias < 0:
        return f"{abs(dias)} dias vencida"
    elif dias == 0:
        return "vence hoje"
    else:
        return f"{dias} dias"


def get_identificacao():
    return {
        "nup": "65297.001232/2026-90",
        "tipo": "Contrato",
        "om_requisitante": "Cmdo 9º Gpt Log",
        "setor": "Almox Cmdo",
        "objeto": "Sv Mnt Ar Condicionado (SFPC)",
        "fornecedor": "MOREIRA & LOPES SERVICOS LTDA",
        "cnpj": "24.043.951/0001-06",
        "tipo_empenho": "Global",
        "instrumento": "Contrato 59/2024",
        "uasg": "160136 — 9º Gpt Log",
    }


def get_itens():
    return [
        {
            "item": 4,
            "catserv": 2771,
            "descricao": (
                "Manutenção preventiva, corretiva, instalação e "
                "remanejamento de aparelho de ar condicionado Split"
            ),
            "und": "Sv",
            "qtd": 6.666,
            "nd_si": "39.17",
            "p_unit": 0.30,
            "p_total": 1999.80,
            "status": "conforme",
        }
    ]


def get_validacoes_requisicao():
    return {
        "calculo": {
            "texto": "Verificação de cálculo",
            "resultado": "✅ Correto — 6.666 × R$ 0,30 = R$ 1.999,80",
            "status": "conforme",
        },
        "nd_subelemento": {
            "texto": "ND/Subelemento",
            "resultado": "✅ 339039 / SI 17 — Manutenção e Conservação de Bens Móveis",
            "status": "conforme",
        },
        "valor_total": {
            "texto": "Valor total declarado",
            "resultado": "✅ R$ 1.999,80",
            "status": "conforme",
        },
    }


def get_comprasnet_simulacao():
    return {
        "uasg": "160136",
        "instrumento": "Contrato 59/2024",
        "cnpj": "24.043.951/0001-06",
        "item": "4",
        "pi": "E3PCFSCDEGE",
        "quantidade": "6.666",
        "si": "17",
    }


def get_nota_credito():
    prazo = "30/06/2026"
    dias_prazo = _dias_ate(prazo)

    return {
        "numero": "2026NC400428",
        "data_emissao": "27/JAN/2026",
        "ug_emitente": "167504 — Centro de Obtenções (COEX)",
        "ug_favorecida": "160136 — 9º Grupamento Logístico",
        "nd": "339039",
        "ptres": "232180",
        "fonte": "1021000000",
        "ugr": "167504",
        "pi": "E3PCFSCDEGE",
        "esf": "1 (Federal)",
        "saldo": 2000.00,
        "prazo_empenho": prazo,
        "dias_restantes": dias_prazo,
    }


def get_validacoes_nc():
    prazo = "30/06/2026"
    dias_prazo = _dias_ate(prazo)

    return [
        {
            "verificacao": "ND da NC vs ND da Requisição",
            "resultado": "339039 = 339039",
            "status": "conforme",
        },
        {
            "verificacao": "Saldo vs Valor Requisição",
            "resultado": "R$ 2.000,00 ≥ R$ 1.999,80",
            "status": "conforme",
        },
        {
            "verificacao": "Prazo de empenho",
            "resultado": f"{prazo} — {_texto_dias(dias_prazo)}",
            "status": _status_validade(dias_prazo),
        },
    ]


def get_certidoes():
    # ── Datas das certidões (mock baseado no processo real) ──
    datas = {
        "fgts": "16/02/2026",
        "receita_federal": "06/08/2026",
        "trabalhista": "06/08/2026",
        "receita_estadual": "07/04/2026",
        "receita_municipal": "09/03/2026",
        "qualif_economica": "30/06/2026",
        "credenciamento": "24/03/2026",
    }

    # Calcular status dinâmico para cada certidão
    def _cert_status(chave):
        dias = _dias_ate(datas[chave])
        status = _status_validade(dias)
        validade = f"{datas[chave]} ({_texto_dias(dias)})"
        return validade, status

    val_cred, st_cred = _cert_status("credenciamento")
    val_rf, st_rf = _cert_status("receita_federal")
    val_fgts, st_fgts = _cert_status("fgts")
    val_trab, st_trab = _cert_status("trabalhista")
    val_est, st_est = _cert_status("receita_estadual")
    val_mun, st_mun = _cert_status("receita_municipal")
    val_qef, st_qef = _cert_status("qualif_economica")

    return [
        # ── SICAF ──
        {
            "certidao": "Credenciamento",
            "resultado": "24.043.951/0001-06 — Credenciado",
            "validade": f"Cadastro: {val_cred}",
            "status": st_cred,
            "indent": 1,
        },
        {
            "certidao": "Receita Federal",
            "resultado": "—",
            "validade": val_rf,
            "status": st_rf,
            "indent": 1,
        },
        {
            "certidao": "FGTS",
            "resultado": "—",
            "validade": val_fgts,
            "status": st_fgts,
            "indent": 1,
        },
        {
            "certidao": "Trabalhista (CNDT)",
            "resultado": "—",
            "validade": val_trab,
            "status": st_trab,
            "indent": 1,
        },
        {
            "certidao": "Receita Estadual",
            "resultado": "—",
            "validade": val_est,
            "status": st_est,
            "indent": 1,
        },
        {
            "certidao": "Receita Municipal",
            "resultado": "—",
            "validade": val_mun,
            "status": st_mun,
            "indent": 1,
        },
        {
            "certidao": "Qualif. Econômico-Financeira",
            "resultado": "—",
            "validade": val_qef,
            "status": st_qef,
            "indent": 1,
        },
        {
            "certidao": "Impedimento de Licitar",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 1,
        },
        {
            "certidao": "Ocorr. Imped. Indiretas",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 1,
        },
        # ── Demais certidões ──
        {
            "certidao": "CADIN",
            "resultado": "24.043.951/0001-06 — REGULAR",
            "validade": "—",
            "status": "conforme",
            "indent": 0,
        },
        {
            "certidao": "TCU — Licitantes Inidôneos",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 0,
        },
        {
            "certidao": "CNJ — Improbidade",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 0,
        },
        {
            "certidao": "CEIS — Inidôneas/Suspensas",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 0,
        },
        {
            "certidao": "CNEP — Empresas Punidas",
            "resultado": "Nada Consta",
            "validade": "—",
            "status": "conforme",
            "indent": 0,
        },
    ]


def get_resultado_analise(tipo="caveat"):
    # Calcular status do FGTS dinamicamente
    dias_fgts = _dias_ate("16/02/2026")
    fgts_texto = _texto_dias(dias_fgts)
    fgts_data = "16/02/2026"

    if dias_fgts < 0:
        fgts_ressalva = f"FGTS vencida: {fgts_data} ({fgts_texto})"
    elif dias_fgts <= 30:
        fgts_ressalva = f"FGTS com validade próxima: {fgts_data} ({fgts_texto})"
    else:
        fgts_ressalva = None

    resultados = {
        "approval": {
            "tipo": "approval",
            "titulo": "✅ APROVAÇÃO",
            "ressalvas": [],
            "conformes": [
                "CNPJ consistente em todas as peças",
                "ND compatível (339039 = 339039)",
                "Saldo NC suficiente (R$ 2.000,00 ≥ R$ 1.999,80)",
                "Todas as certidões regulares e vigentes",
                "Cadeia de despachos completa (3/3)",
                "Cálculos da requisição corretos",
            ],
        },
        "caveat": {
            "tipo": "caveat",
            "titulo": "⚠️ APROVAÇÃO COM RESSALVA",
            "ressalvas": [
                r for r in [
                    fgts_ressalva,
                    (
                        'Razão Social divergente: Requisição diz '
                        '"MAIRA LOPES DA SILVA LTDA", SICAF diz '
                        '"MOREIRA & LOPES SERVICOS LTDA" '
                        '(CNPJ confere: 24.043.951/0001-06)'
                    ),
                ] if r is not None
            ],
            "conformes": [
                "CNPJ consistente em todas as peças",
                "ND compatível (339039 = 339039)",
                "Saldo NC suficiente",
                "Cadeia de despachos completa (3/3)",
                "Cálculos da requisição corretos",
            ],
        },
        "rejection": {
            "tipo": "rejection",
            "titulo": "❌ REPROVAÇÃO",
            "ressalvas": [
                "Certidão Estadual vencida: 01/01/2026 (49 dias vencida)",
                "CNPJ do CADIN divergente do CNPJ da requisição",
            ],
            "conformes": [
                "ND compatível (339039 = 339039)",
                "Saldo NC suficiente",
            ],
        },
    }
    return resultados.get(tipo, resultados["caveat"])


def get_mascara_ne():
    return (
        "Cmdo 9º Gpt Log, Req 19 – Almox Cmdo (SFPC) – Sv Mnt Ar Cond, "
        "2026NC400428 de 27 JAN 26, do COEX, ND 339039, FONTE 1021000000, "
        "PTRES 232180, UGR 167504, PI E3PCFSCDEGE, "
        "CONTRATO 59/2024, UASG 160136 (GER)."
    )


def get_despacho_default(tipo="caveat"):
    # Gerar texto dinâmico baseado no status atual do FGTS
    dias_fgts = _dias_ate("16/02/2026")

    if dias_fgts < 0:
        fgts_texto = (
            f'Informo que a certidão do FGTS no SICAF encontra-se '
            f'VENCIDA desde 16/02/2026 ({abs(dias_fgts)} dias).'
        )
    else:
        fgts_texto = (
            f'Informo que a certidão do FGTS no SICAF possui validade '
            f'próxima (16/02/2026, {dias_fgts} dias restantes).'
        )

    despachos = {
        "caveat": (
            f'{fgts_texto} Adicionalmente, a razão social na '
            'requisição ("MAIRA LOPES DA SILVA LTDA") diverge da razão '
            'social no SICAF ("MOREIRA & LOPES SERVICOS LTDA"), embora '
            'o CNPJ (24.043.951/0001-06) seja o mesmo em ambas as peças.'
        ),
        "rejection": (
            'Informo que a Certidão Negativa de Débitos Estaduais se '
            'encontra vencida, o que impede o andamento do processo. '
            'Adicionalmente, o CNPJ constante no CADIN anexado não '
            'corresponde ao CNPJ do fornecedor requisitado.'
        ),
    }
    return despachos.get(tipo, "")
