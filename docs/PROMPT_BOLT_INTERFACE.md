# PROMPT — Streamlit Interface for Procurement Process Analyzer

## ROLE
You are a senior full-stack developer specialized in building professional Streamlit dashboards. You write clean, modular Python code with excellent UI/UX practices.

## TASK
Build a complete Streamlit application interface for a Brazilian Army procurement process analyzer. The app analyzes PDF documents and displays results in 4 stages. For now, use **static mock data** — no PDF processing, no backend logic. The goal is a pixel-perfect interface that will later receive a real backend.

## CONTEXT
This system is used by military procurement analysts (SAL/CAF) at the 9th Logistics Group (Campo Grande, Brazil) to review procurement requisitions before issuing commitment notes (Nota de Empenho). The analyst uploads a compiled PDF and the system extracts, validates, and presents findings across 4 stages. The language of the interface must be **Brazilian Portuguese**.

## TECHNICAL STACK
- Python 3.11+
- Streamlit (latest)
- No external CSS frameworks — use Streamlit native components + custom CSS via `st.markdown`
- SQLite for persistence (schema only, no data operations yet)
- Single-file app: `app.py` with helper modules in `/modules/`

## PROJECT STRUCTURE
```
analise-processos/
├── app.py                    # Main Streamlit app
├── modules/
│   ├── __init__.py
│   ├── mock_data.py          # All mock/static data
│   ├── components.py         # Reusable UI components
│   └── database.py           # SQLite schema (create tables only)
├── assets/
│   └── styles.css            # Custom CSS
├── data/
│   └── nd_subelementos.db    # SQLite database (created on first run)
└── requirements.txt
```

## INTERFACE SPECIFICATION

### Global Layout

- **Page config:** wide layout, page title "Análise de Processos — SAL/CAF", favicon 📋
- **Sidebar:**
  - App title: "📋 Análise de Processos"
  - Subtitle: "SAL/CAF — Cmdo 9º Gpt Log"
  - Divider
  - PDF upload widget (accepts `.pdf` only)
  - Toggle: "Análise sem NC?" (default OFF)
  - Divider
  - Section: "Histórico" — placeholder for past analyses list
  - Footer: version number "v0.1.0 — MVP"

- **Main area:** 4 collapsible sections (use `st.expander` or custom accordion). Each section has:
  - Header with stage name + status indicator (🟢/⚠️/🔴)
  - Content area that expands to show full details
  - All sections visible by default on load (expanded)

### Color System (use throughout)

```css
/* Define as CSS variables */
--color-green: #22c55e;      /* Conforme */
--color-green-bg: #f0fdf4;
--color-yellow: #eab308;     /* Ressalva / Alerta */
--color-yellow-bg: #fefce8;
--color-red: #ef4444;        /* Bloqueio */
--color-red-bg: #fef2f2;
--color-blue: #3b82f6;       /* Info / Neutro */
--color-blue-bg: #eff6ff;
--color-gray: #6b7280;       /* Disabled / Placeholder */
--color-gray-bg: #f9fafb;
```

Use `st.markdown` with HTML/CSS to create colored status badges:
- 🟢 `<span style="background:#f0fdf4;color:#16a34a;padding:2px 8px;border-radius:4px;font-weight:600">✅ Conforme</span>`
- ⚠️ `<span style="background:#fefce8;color:#ca8a04;padding:2px 8px;border-radius:4px;font-weight:600">⚠️ Ressalva</span>`
- 🔴 `<span style="background:#fef2f2;color:#dc2626;padding:2px 8px;border-radius:4px;font-weight:600">❌ Bloqueio</span>`

### STAGE 1 — IDENTIFICAÇÃO

A clean card/panel displaying extracted identification data in a 2-column grid layout.

**Fields (left column):**
| Label | Mock Value |
|-------|-----------|
| NUP | 65297.001232/2026-90 |
| Tipo | Contrato |
| OM Requisitante | Cmdo 9º Gpt Log |
| Setor | Almox Cmdo |
| Objeto | Sv Mnt Ar Condicionado (SFPC) |

**Fields (right column):**
| Label | Mock Value |
|-------|-----------|
| Fornecedor | MOREIRA & LOPES SERVICOS LTDA |
| CNPJ | 24.043.951/0001-06 |
| Tipo Empenho | Global |
| Instrumento | Contrato 59/2024 |
| UASG | 160136 — 9º Gpt Log |

**Stage status indicator:** 🟢 (all fields extracted successfully)

### STAGE 2 — REQUISIÇÃO E ITENS

Two sub-sections:

**2a. Tabela de Itens**

Use `st.dataframe` or custom HTML table with colored status column:

| Item | CatServ | Descrição | UND | QTD | ND/SI | P. Unit | P. Total | Status |
|------|---------|-----------|-----|-----|-------|---------|----------|--------|
| 4 | 2771 | Manutenção preventiva, corretiva, instalação e remanejamento de aparelho de ar condicionado Split | Sv | 6.666 | 39.17 | R$ 0,30 | R$ 1.999,80 | 🟢 |

Below the table, show validation results:
```
Verificação de cálculo: ✅ Correto — 6.666 × R$ 0,30 = R$ 1.999,80
ND/Subelemento: ✅ 339039 / SI 17 — Manutenção e Conservação de Bens Móveis
Valor total declarado: ✅ R$ 1.999,80
```

**2b. Dados para Simulação ComprasNet**

A small info box with a "Copiar" button:
```
UASG: 160136
Contrato: 59/2024
Item: 4
Quantidade: 6.666
Valor unitário: R$ 0,30
```

**Stage status indicator:** 🟢

### STAGE 3 — NC E CERTIDÕES

Two sub-sections:

**3a. Nota de Crédito**

Display ALL NC fields in a styled card (the analyst needs to see everything without opening the PDF):

```
┌─ NC 2026NC400428 ──────────────────────────────────┐
│  Data emissão:    27/JAN/2026                       │
│  UG Emitente:     167504 — Centro de Obtenções (COEX)│
│  UG Favorecida:   167136 — 9° Grupamento Logístico  │
│  ND:              339039                             │
│  PTRES:           232180                             │
│  FONTE:           1021000000                         │
│  UGR:             167504                             │
│  PI:              E3PCFSCDEGE                        │
│  ESF:             1 (Federal)                        │
│  Saldo:           R$ 2.000,00                        │
│  Prazo empenho:   30/JUN/2026 (131 dias)            │
└─────────────────────────────────────────────────────┘
```

Below the card, show cross-validations:

| Verificação | Resultado | Status |
|-------------|-----------|--------|
| ND da NC vs ND da Requisição | 339039 = 339039 | 🟢 Conforme |
| Saldo vs Valor Requisição | R$ 2.000,00 ≥ R$ 1.999,80 | 🟢 Suficiente |
| Prazo de empenho | 30/JUN/2026 — 131 dias restantes | 🟢 Normal |

**3b. Certidões**

Full table with all certidões and their statuses:

| Certidão | CNPJ/Resultado | Validade | Status |
|----------|---------------|----------|--------|
| **SICAF** | | | |
| ∟ Credenciamento | 24.043.951/0001-06 — Credenciado | Cadastro: 24/03/2026 | 🟢 |
| ∟ Receita Federal | — | 06/08/2026 | 🟢 |
| ∟ FGTS | — | 16/02/2026 | ⚠️ 7 dias |
| ∟ Trabalhista | — | 06/08/2026 | 🟢 |
| ∟ Receita Estadual | — | 07/04/2026 | 🟢 |
| ∟ Receita Municipal | — | 09/03/2026 | 🟢 |
| ∟ Qualif. Econômico-Financeira | — | 30/06/2026 | 🟢 |
| ∟ Impedimento Licitar | Nada Consta | — | 🟢 |
| ∟ Ocorr. Imped. Indiretas | Nada Consta | — | 🟢 |
| **CADIN** | 24.043.951/0001-06 — REGULAR | — | 🟢 |
| **TCU — Licitantes Inidôneos** | Nada Consta | — | 🟢 |
| **CNJ — Improbidade** | Nada Consta | — | 🟢 |
| **CEIS — Inidôneas/Suspensas** | Nada Consta | — | 🟢 |
| **CNEP — Empresas Punidas** | Nada Consta | — | 🟢 |

Highlight rows with ⚠️ or 🔴 using yellow/red background.

**Stage status indicator:** ⚠️ (due to FGTS near expiry)

### STAGE 4 — DECISÃO E OUTPUTS

**4a. Resultado da Análise**

Large banner showing the final result:

```
⚠️ APROVAÇÃO COM RESSALVA
```

Use a colored container:
- Approval: green background
- Approval with caveat: yellow background  
- Rejection: red background

Below the banner, list all findings:

**Ressalvas (⚠️):**
```
• FGTS com validade próxima: 16/02/2026 (7 dias restantes)
• Razão Social divergente: Requisição diz "MAIRA LOPES DA SILVA LTDA", 
  SICAF diz "MOREIRA & LOPES SERVICOS LTDA" (CNPJ confere: 24.043.951/0001-06)
```

**Pontos conformes (🟢):**
```
• CNPJ consistente em todas as peças
• ND compatível (339039 = 339039)
• Saldo NC suficiente
• Todas as certidões regulares (exceto FGTS próximo do vencimento)
• Cadeia de despachos completa (3/3)
• Cálculos da requisição corretos
```

**4b. Máscara da NE**

Read-only text box with "📋 Copiar" button:
```
Cmdo 9º Gpt Log, Req 19 – Almox Cmdo (SFPC) – Sv Mnt Ar Cond, 2026NC400428 de 27 JAN 26, do COEX, ND 339039, FONTE 1021000000, PTRES 232180, UGR 167504, PI E3PCFSCDEGE, CONTRATO 59/2024, UASG 160136 (GER).
```

**4c. Despacho**

**Editable** `st.text_area` with pre-filled text. Label: "Texto do Despacho (editável)". Height: ~150px.

Pre-filled mock text:
```
Informo que a certidão do FGTS no SICAF possui validade próxima (16/02/2026). Adicionalmente, a razão social na requisição ("MAIRA LOPES DA SILVA LTDA") diverge da razão social no SICAF ("MOREIRA & LOPES SERVICOS LTDA"), embora o CNPJ (24.043.951/0001-06) seja o mesmo em ambas as peças.
```

Below the text area: "📋 Copiar Despacho" button.

**Important:** The despacho section should ONLY appear when result is "Aprovação com Ressalva" or "Reprovação". For plain "Aprovação", hide this section and show only: "✅ Processo aprovado — encaminhar ao OD para autorização do empenho."

**Stage status indicator:** ⚠️

### CONDITIONAL STATES

The interface should handle 3 visual states (switch via a selectbox in sidebar for demo purposes):

**State 1: Approval (green)**
- Banner: "✅ APROVAÇÃO"
- No despacho section
- Message: "Processo aprovado — encaminhar ao OD."
- All items green

**State 2: Approval with Caveat (yellow) — DEFAULT for demo**
- Banner: "⚠️ APROVAÇÃO COM RESSALVA"
- Despacho section visible (editable)
- Mix of green and yellow items

**State 3: Rejection (red)**
- Banner: "❌ REPROVAÇÃO"
- Despacho section visible (editable)
- Red items highlighted prominently
- Mock data for rejection: FGTS expired (not just near-expiry), change validade to 01/01/2026

### EMPTY / UPLOAD STATE

When no PDF is uploaded, show:
- Centered illustration/icon (📄 large emoji or SVG)
- Text: "Faça upload de um processo compilado (PDF) para iniciar a análise"
- Subtext: "Formatos aceitos: PDF compilado do SPED"
- The 4 stages should be hidden until a file is uploaded

### ADDITIONAL UI ELEMENTS

**Toast/notification system:** Use `st.toast` for quick feedback:
- "Máscara copiada!" when copy button is clicked
- "Despacho copiado!" when despacho copy is clicked
- "Análise concluída em X segundos" after processing

**Progress indicator:** When PDF is "processing" (simulated), show `st.progress_bar` with stages:
- 25% — Extraindo dados...
- 50% — Validando requisição...
- 75% — Verificando certidões...
- 100% — Gerando resultado...

**Expandable details:** Each validation row should have a small "ℹ️" icon that shows additional context on hover or click (use `st.popover` or tooltip).

## RULES

1. **All text in Brazilian Portuguese** — labels, buttons, messages, everything
2. **No real PDF processing** — all data is mock/static from `mock_data.py`
3. **Responsive design** — must look good on 1366px and 1920px widths
4. **Professional appearance** — clean, minimal, military-formal aesthetic. No playful colors or casual design
5. **Copy to clipboard** — implement using `st.code` with built-in copy, or JavaScript injection via `st.components.v1.html`
6. **Performance** — page should load instantly (no heavy computations)
7. **Modular code** — UI components in `components.py`, data in `mock_data.py`, keep `app.py` clean
8. **CSS must be in `assets/styles.css`** and loaded via `st.markdown` — no inline styles longer than 1 line
9. **Status badges** must be consistent everywhere — same colors, same format, same size
10. **The sidebar demo selector** (approval/caveat/rejection) is temporary for development — label it clearly as "🔧 Demo: Tipo de Resultado"

## OUTPUT

Generate all files listed in the project structure. Every file must be complete, functional, and ready to run with `streamlit run app.py`. Include a `requirements.txt` with pinned versions.

## STYLE

- Clean, professional, government/military aesthetic
- Color palette: primarily white/gray backgrounds with colored accents for status
- Typography: system fonts, clear hierarchy (large headings, medium labels, small captions)
- Spacing: generous padding between sections, compact within cards
- Tables: alternating row colors, clear borders, highlighted status cells
- Cards/panels: subtle shadows or borders, rounded corners (4px)
- The overall feel should be: "serious tool for serious work" — not a startup dashboard
