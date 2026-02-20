# MAPEAMENTO DE PADRÕES — Processos Requisitórios do EB
## Documento de Referência para Desenvolvimento do Sistema

**Versão:** 2.0  
**Data:** 19/02/2026  
**Base:** 3 processos reais do Cmdo 9º Gpt Log (2 licitações + 1 contrato)

---

## 1. PROCESSOS ANALISADOS

| # | NUP | Tipo | ND | OM | Objeto | Páginas |
|---|-----|------|----|----|--------|---------|
| 1 | 65345.000389/2026-85 | Licitação (PART) | 339039 | 9º B Mnt | Serviço de calhas | ~30 |
| 2 | 64136.000407/2026-21 | Licitação (PART) | 339030 | 18º B Trnp | Material de limpeza | 139 |
| 3 | 65297.001232/2026-90 | Contrato (própria UASG) | 339039 | Cmdo 9º Gpt Log | Sv Mnt Ar Condicionado (SFPC) | 17 |

> **NOTA:** Processo 3 mapeado em 19/02/2026. Contrato da própria UASG (160136), empenho Global, NC em texto SIAFI (DEMONSTRA-DIARIO).

---

## 2. ESTRUTURA GERAL DO PDF COMPILADO

Todo processo compilado segue esta sequência de peças processuais:

```
┌─────────────────────────────────────────┐
│  CAPA (com lista de peças processuais)  │
├─────────────────────────────────────────┤
│  TERMO DE ABERTURA                      │
├─────────────────────────────────────────┤
│  CHECK LIST (quando CONTRATO)           │  ← SÓ em processos de contrato
├─────────────────────────────────────────┤
│  REQUISIÇÃO (com tabela de itens)       │
├─────────────────────────────────────────┤
│  EDITAL (páginas relevantes)            │  ← em licitação: pag do edital
│  ou CONTRATO (cópia integral)           │  ← em contrato: termo completo
├─────────────────────────────────────────┤
│  NOTA DE CRÉDITO (NC)                   │
├─────────────────────────────────────────┤
│  CERTIDÕES                              │
│  ├── CADIN                              │
│  ├── TCU / CNJ / CNEP / CNEI           │
│  └── SICAF                              │
├─────────────────────────────────────────┤
│  TERMO DE REFERÊNCIA (quando houver)    │
├─────────────────────────────────────────┤
│  DESPACHOS (cadeia de aprovação)        │
│  ├── Fiscal Administrativo              │
│  ├── Cmt da OM (OM externa)             │
│  │   ou Gestor Crédito/CAF (Cmdo)       │
│  └── OD do 9º Gpt Log                  │
└─────────────────────────────────────────┘
```

**Observação importante:** A ordem pode variar entre OMs. O sistema deve identificar cada peça pelo conteúdo, não pela posição no PDF.

---

## 3. PADRÕES DE EXTRAÇÃO POR PEÇA PROCESSUAL

### 3.1 CAPA

**Identificadores de página:**
- Texto contém "PROCESSO NUP" ou "PROTOCOLO GERAL"
- Texto contém "PEÇAS PROCESSUAIS"
- Texto contém "CHECK LIST"

**Campos e padrões regex:**

| Campo | Regex | Exemplo extraído |
|-------|-------|-----------------|
| NUP (formato EB) | `(\d{5}\.\d{6}/\d{4}-\d{2})` | `65345.000389/2026-85` |
| NUP (formato Protocolo) | `(\d{5}\.\d{6}/\d{4}-\d{2})` | `64136.000407/2026-21` |
| Assunto | `ASSUNTO:\s*(.+)` | `Requisição 08/2026 - aquisição de material - Lei 14.133` |
| Interessado | `INTERESSADO:\s*(.+)` | `Almox 18º B Trnp` |
| Órgão Origem | `Órgão de Origem:\s*(.+)` | `18º Batalhão de Transporte` |
| Classificação | `Classificação:\s*(\d{3}\.\d+)` | `031.12` |
| Seção | `SEÇÃO:\s*(.+)` | `Almoxarifado 2026` |

**Lista de peças processuais — padrão de versionamento:**
```
PEÇAS PROCESSUAIS
1- 8-Almox/Cmdo 18º B Trnp (a)          ← (a) = Documento de Origem
2- Req_08_-_Mat_Limpeza_assinado.pdf (c) ← (c) = Documento desentranhado (INATIVO)
3- 1 - Edital.pdf                         ← sem marcação = ATIVO
...
11- Req_08_-_Mat_Limpeza_assinado_assinado.pdf  ← versão corrigida (ATIVA)
```

**Legenda de marcações:**
- `(a)` = Documento de Origem
- `(b)` = Arquivos não imprimíveis
- `(c)` = Documento **desentranhado** (substituído — NÃO usar para análise)
- `(d)` = Documento desmembrado
- Sem marcação = documento ATIVO

**Regra crítica:** O sistema deve filtrar peças com marcação `(c)` e usar apenas a versão mais recente de cada tipo de documento.

---

### 3.2 TERMO DE ABERTURA

**Identificadores de página:**
- Texto contém "Termo de Abertura"
- Texto contém "autuo o presente processo para emissão de empenho"

**Campos:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Nº Termo | `Termo de Abertura Nº\s*(.+)` | `8-Almox/Cmdo 18º B Trnp` |
| Assunto | `Assunto:\s*(.+)` | `contratação de fornecedor mediante emissão de nota de empenho` |
| Responsável | Linha após "Nesta data..." | `YURI MENDES DOS SANTOS - 3º Sgt` |
| Data assinatura | `em\s+(\d{2}/\d{2}/\d{4})` | `05/02/2026` |

---

### 3.2.1 CHECK LIST (apenas processos de CONTRATO)

**Identificadores de página:**
- Texto contém "CHECK LIST - CONTRATO"
- Texto contém "PROTOCOLO GERAL"
- Texto contém "Movimento do Processo"

**Campos:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Tipo | `CHECK LIST - (.+)` | `CONTRATO DA PRÓPRIA UASG (LEI 8.666/93)` |
| Req referência | `Req nº\s*(\d+)` | `19` |
| Assunto resumido | campo ASSUNTO no rodapé | `Sv Mnt Ar Condicionado` |

**Importância para o sistema:** A presença do Check List de contrato é um **indicador de tipo** — se encontrar essa peça, o processo é de contrato e deve usar o template de NE de contrato. O check list também tem uma tabela de conferência com os documentos esperados (10 itens), que pode ser usada para verificar completude do processo.

---

### 3.3 REQUISIÇÃO

**Identificadores de página:**
- Texto contém "Req nº" ou "Req "
- Texto contém "Ao Sr Ordenador de Despesas"
- Texto contém "Tipo de Empenho"

**Campos do cabeçalho:**

| Campo | Regex / Padrão | Exemplo Proc 1 (ND 39) | Exemplo Proc 2 (ND 30) | Exemplo Proc 3 (Contrato) |
|-------|---------------|------------------------|------------------------|--------------------------|
| Nr Requisição | `Req\.?\s*(?:nº\s*)?(\S+)` | `03` | `08` | `19` |
| Setor | após `–` ou `-` na linha da Req | `ALMOX` | `Almox` | `9° Gpt Log` |
| OM | `Do\s+Cmt\s+d[oa]\s+(.+)` ou `Do\s+Enc\s+(.+)` | `9º B Mnt` | `18 B Trnp` | `Enc Set Mat/Cmdo 9° Gpt Log` |
| NUP da Req | `NUP:\s*(\d{5}\.\d{6}/\d{4}-\d{2})` | `65345.000389/2026-85` | `64136.000368/2026-62` | `65297.001232/2026-90` |
| Data | `Campo Grande,\s*MS,\s*(.+)` | `11 de janeiro de 2026` | `05 de fevereiro de 2026` | `09 de fevereiro de 2026` |
| Destinatário | `Ao\s+Sr\s+(.+)` | `Ordenador de Despesas do 9º Gpt Log` | `Ordenador de Despesas do 9º Gpt Log` | `Ordenador de Despesas do 9º Gpt Log` |
| Assunto | `Assunto:\s*(.+)` | `Contratação de serviço` | `Aquisição de material por meio de SRP` | `contratação de serviço por meio do contrato 59/2024` |
| Lei referência | `Rfr:\s*(.+)` ou `Lei Federal Nr (.+)` | `Lei Federal Nr 14.133` | `Lei Federal Nr 14.133` | `Portaria Ministerial nº 305` |
| Tipo Empenho | `Tipo de Empenho:\s*(\w+)` | `Ordinário` | `Ordinário` | `Global` |

**Campos exclusivos de contrato (Proc 3):**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Nr Contrato | `contrato\s*(?:nº\s*)?(\d+/\d{4})` | `59/2024` |
| UG gerenciadora | `gerenciad[oa]\s+pel[oa]\s+UG\s+(\d{6})` | `160136` |
| Fiscal de contrato | `Gestão e Fiscalização de Contrato:\s*(.+)` | `2º TEN PIQUELET` |
| Nome empresa | `Nome da empresa:\s*(.+)` | `MAIRA LOPES DA SILVA LTDA` |
| CNPJ empresa | `CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})` | `24.043.951/0001-06` |

**Tipos de empenho e identificação:**
- `Ordinário` = licitação (valor exato, pago de uma vez)
- `Global` = contrato (valor total conhecido, pagamento parcelado)
- `Estimativo` = contratos com valor estimado (parcelas mensais variáveis)

Regex: `Tipo de Empenho.*?(Ordinário|Global|Estimativo)`

**Fonte de recursos (dentro da requisição):**

| Campo | Regex | Exemplo Proc 1/2 | Exemplo Proc 3 (Contrato) |
|-------|-------|-------------------|---------------------------|
| NC | `(20\d{2}NC\d{6})` | `2026NC000270` | `2026NC400428` |
| Data NC | Texto adjacente ao NC | `11/JAN/2026` | `27 JAN 26` |
| Órgão emissor | `d[aoe]\s+(\w+)` após NC | `DGO` | `COEX` |
| ND | `ND\s*(33\d{4})` ou `ND\s*(\d{6})` | `339039`, `339000` | `339039` |
| PI | `PI\s*([A-Z0-9]+)` | `I3DAFUNADOM` | `E3PCFSCDEGE` |
| PTRES | `PTRES\s*(\d+)` | `171460` | `232180` |
| UGR | `UGR\s*(\d{6})` | `160073` | `167504` |

**Variação de órgão emissor da NC:**
- `DGO` = Diretoria de Gestão Orçamentária (NCs de material/serviço geral)
- `COEX` = Centro de Obtenções do Exército (NCs de contratos/serviços específicos)
- O órgão emissor é extraído do texto após a NC na requisição

**Variação de código UGR:**
- Proc 1/2: UGR `160073` (código UASG padrão)
- Proc 3: UGR `167504` (código de UG/GESTÃO do SIAFI — diferente do UASG)
- No SIAFI, UGs podem ter códigos de gestão diferentes dos de UASG. Ex: 167504 = COEX gestão, 160136 = 9º Gpt Log UASG mas 167136 = 9º Gpt Log gestão SIAFI

**Variações encontradas no formato de ND:**
- `339039` (6 dígitos, sem pontos)
- `339000` (genérico — requer DETAORC)
- `33.90.30` (com pontos — Proc 2 no corpo do texto)
- `339030` (6 dígitos)

**Regex unificado para ND:** `ND\s*(3[34]\d{4}|33\.90\.\d{2})`

**Pregão / UASG:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Nr Pregão | `(?:Pregão|PE)\s*(?:Eletrônico\s*)?(?:nº\s*)?(9\d{4}/\d{4})` | `90006/2024`, `9014/2025` |
| UASG | `(?:UASG|gerenciad[oa]\s+pel[oa])\s*(\d{6})` | `160141`, `160078` |
| Tipo participação | `(gerenciador\|participante\|carona)` | `participante` |

**Variações encontradas:**
- Proc 1: `PE 90006/2024, UASG 160141 (participante)`
- Proc 2: `Pregão Eletrônico nº 9014/2025 gerenciado pela 160078 – Colégio Militar de Campo Grande`

**Máscara pré-montada pelo requisitante (campo 6/7 da requisição):**
```
Proc 2 (Licitação): "18º B Trnp, Req 08 – Almox – Aqs de material de limpeza - 2026NC000276, de 
12/01/26, do DGO, ND 339000 – UGR 160073 - PI I3DAFUNADOM – PE 9014/2025 
UASG: 160078 – CMCG - (Part)"

Proc 3 (Contrato): "Cmdo 9º Gpt Log, Req 19 – Almox Cmdo (SFPC) – Sv Mnt 
Ar Cond, 2026NC400428 de 27 JAN 26, do COEX, ND 339039 PTRES 232180 UGR 
167504 PI E3PCFSCDEGE, CONTRATO 59/2024 da UASG 160136."
```
> Estas máscaras vêm pré-montadas pelo requisitante mas podem conter ERROS. O sistema deve gerar a máscara correta de forma independente e comparar.

**Diferenças estruturais na máscara Licitação vs Contrato:**
- Licitação: termina com `PE [Nr/Ano], UASG [código] ([PART/GER/CAR])`
- Contrato: termina com `CONTRATO [Nr/Ano] da UASG [código]` (sempre GER da própria UASG)

---

### 3.4 TABELA DE ITENS

**Formato identificado no Proc 1 (ND 39 — poucos itens):**
Tabela simples dentro do corpo da requisição, formato texto corrido ou tabela PDF.

| Item | Descrição | QTD | ND | SI | P. Unit | P. Total |
|------|-----------|-----|----|----|---------|----------|
| 81 | Serv calhas/rufos | 20 | 339039 | 24 | 38,99 | 779,90 |

**Formato identificado no Proc 2 (ND 30 — muitos itens):**
Tabela extensa no Termo de Referência, com colunas:
- Item (número sequencial)
- Descrição/Especificação
- CATMAT (código no Comprasnet)
- Unidade de Medida
- Quantidade Total
- Valor Unitário
- Valor Total

Exemplo:
```
119 | Pasta arquivo papelão PVC catálogo | 289041 | UN | 1520 | R$ 9,20 | R$ 13.984,00
```

**Obs:** Na Proc 2, a tabela de itens da REQUISIÇÃO do 18º B Trnp não lista todos os 301 itens do pregão — lista apenas os itens que aquela OM está pedindo, com as quantidades específicas dela. O sistema precisa cruzar os itens da requisição com o pregão.

**Formato identificado no Proc 3 (Contrato — item único):**
Tabela dentro da requisição com colunas extras de justificativa:

| Item | CatServ | Descrição | UND | QTD | ND/SI | P.UNT | P.TOTAL |
|------|---------|-----------|-----|-----|-------|-------|---------|
| 4 | 2771 | Manutenção preventiva, corretiva, instalação e remanejamento de ar condicionado Split | Sv | 6.666 | 39.17 | R$ 0,30 | R$ 1.999,80 |

**Observações sobre o formato de contrato:**
- O campo ND/SI aparece como `39.17` (ND 39 = 339039, SI 17 = manutenção conservação de bens móveis)
- O número do item (4) refere-se ao item do contrato/pregão original, não é sequencial da requisição
- QTD pode ser valor alto (6.666) representando unidades de serviço fracionadas
- Colunas extras: "JUSTIFICATIVA DO MOTIVO DA AQUISIÇÃO" e "JUSTIFICATIVA DA QUANTIDADE"
- O item do contrato usa CatServ (serviço) em vez de CatMat (material)

**Validações mecânicas na tabela:**
1. `QTD × P.Unit = P.Total` para cada linha
2. Soma de todos P.Total = Valor Total da Requisição
3. ND/SI de cada item compatível com descrição (via tabela de subelementos)
4. Item existe no pregão referenciado

---

### 3.5 NOTA DE CRÉDITO (NC)

**Identificadores de página:**
- Texto contém "Nota de Crédito Nº"
- Texto contém "UG EMITENTE"
- Texto contém "SISTEMA ORIGEM SIAFI"
- Formato de terminal mainframe (texto monospaced)

**Formato encontrado (Proc 2 — texto extraível):**

```
Nota de Crédito Nº 2026NC000276 da UG 160073
NÚMERO          2026NC000276
UG EMITENTE     160073
DATA EMISSÃO    12/01/2026
VALOR TOTAL     R$ 9.000,00
TIPO DESCENTRALIZAÇÃO  PROVISAO
DESCRIÇÃO       Atende 2/3 da Cota FUNADOM 01/04...
                Prazo de empenho 27 FEV 26.
                Cota 18 B Trnp
```

**Tabela de detalhamento (ORIGEM/DESTINO):**

```
TIPO    | ITEM | UG FAV | ESF | PTRES  | FONTE      | ND     | UGR    | PI           | VALOR
DESTINO |  1   | 160136 |  1  | 171460 | 1000000000 | 339000 | 160073 | I3DAFUNADOM  | R$ 9.000,00
```

**Campos e regex:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Número NC | `(20\d{2}NC\d{6})` | `2026NC000276` |
| UG Emitente | `UG EMITENTE\s*(\d{6})` | `160073` |
| Data Emissão | `DATA EMISSÃO\s*(\d{2}/\d{2}/\d{4})` | `12/01/2026` |
| Valor Total | `VALOR TOTAL\s*R\$\s*([\d.,]+)` | `9.000,00` |
| Esfera | `ESF\s*(\d)` na tabela destino | `1` (Federal) |
| Fonte | `FONTE\s*(\d{10})` ou coluna FONTE | `1000000000` |
| PTRES | `PTRES\s*(\d+)` ou coluna PTRES | `171460` |
| ND | `ND\s*(33\d{4})` ou coluna ND | `339000` |
| UGR | `UGR\s*(\d{6})` ou coluna UGR | `160073` |
| PI | `PI\s*([A-Z0-9]+)` ou coluna PI | `I3DAFUNADOM` |
| Prazo empenho | `[Pp]razo de empenho\s*(.+)` | `27 FEV 26` |

**Validações da NC:**
1. Valor NC ≥ Valor Total Requisição (se não, flag — mas NÃO bloqueia automaticamente, pode haver saldo PI)
2. ND da NC vs ND da Requisição (se NC = 339000 e Req = 339039, flag DETAORC necessário)
3. Prazo de empenho vs data atual (alerta de urgência se < 7 dias)
4. UG Emitente inicia com "160" (EB)

**NC em formato imagem (Proc 1):**
Quando a NC é screenshot do SIAFI, o sistema deve usar Tesseract OCR. O layout é de terminal mainframe com campos em posições fixas.

**NC em formato SIAFI texto — DEMONSTRA-DIARIO (Proc 3):**

Este formato é diferente da NC "padrão". É uma consulta ao diário contábil do SIAFI, com duas telas:

**Tela 1 — Cabeçalho:**
```
__ SIAFI2026-CONTABIL-DEMONSTRA-DIARIO (CONSULTA DIARIO CONTABIL)____________
27/01/26  14:54                              USUARIO : ANDRADE
DATA EMISSAO   : 27Jan26               NUMERO  : 2026R0000428
UG/GESTAO EMITENTE: 167504 / 00001 - CENTRO DE OBTENÇÕES DO EXÉRCITO - GESTOR
UG/GESTAO FAVORECIDA: 167136 / 00001  - 9° GRUPAMENTO LOGÍSTICO

DOCUMENTO WEB     : 2026NC400428

OBSERVACAO
SFPC - SV DE MANUTENÇÃO DE AR CONDICIONADO/ CONF ART 5° DA LEI 10834 DE 29 DEZ
 03 E A PORT 102 CMT EX DE 06 MAR 06. SIGELOG (EMPENHO ATÉ 30JUN26)

LANCADO POR : 61164961306 -  SPINDOLA       UG : 167504    27Jan26   11:53
```

**Tela 2 — Detalhamento contábil (linhas de evento):**
```
__ SIAFI2026-CONTABIL-DEMONSTRA-DIARIO (CONSULTA DIARIO CONTABIL)____________
DOCUMENTO WEB     : 2026NC400428

L    EVENTO ESF PTRES  FONTE       ND      UGR    PI              V A L O R
001 301203                                                        2.000,00
          1  232180 1021000000 339039 167504 E3PCFSCDEGE
002 301202                                                        2.000,00
          1  232180 1021000000 339039 167504 E3PCFSCDEGE
003 301201                                                        2.000,00
          1  232180 1021000000 339000 167504 E3PCFSCDEGE
```

**Campos do DEMONSTRA-DIARIO:**

| Campo | Regex / Posição | Exemplo |
|-------|----------------|---------|
| Número SIAFI | `NUMERO\s*:\s*(20\d{2}R\d{7})` | `2026R0000428` |
| Documento Web (= NC) | `DOCUMENTO WEB\s*:\s*(20\d{2}NC\d{6})` | `2026NC400428` |
| UG Emitente | `UG/GESTAO EMITENTE:\s*(\d{6})` | `167504` |
| Nome Emitente | após código UG emitente | `CENTRO DE OBTENÇÕES DO EXÉRCITO` |
| UG Favorecida | `UG/GESTAO FAVORECIDA:\s*(\d{6})` | `167136` |
| Nome Favorecida | após código UG favorecida | `9° GRUPAMENTO LOGÍSTICO` |
| Data Emissão | `DATA EMISSAO\s*:\s*(\S+)` | `27Jan26` |
| Observação | `OBSERVACAO\n(.+)` | `SFPC - SV DE MANUTENÇÃO...` |
| Prazo empenho | `EMPENHO ATÉ\s*(\S+)` dentro da obs | `30JUN26` |
| Evento | `(\d{3})\s+(\d{6})` em cada linha | `001 301203` |
| ESF / PTRES / FONTE / ND / UGR / PI | posições fixas na linha seguinte | ver tabela |
| Valor por linha | `([\d.,]+)$` no final da linha do evento | `2.000,00` |
| Lançado por | `LANCADO POR\s*:\s*(\d+)\s*-\s*(\w+)` | `61164961306 - SPINDOLA` |

**ACHADO CRÍTICO no Proc 3:** A NC tem 3 linhas de evento, com NDs DIFERENTES:
- Linhas 001/002: ND 339039 (específica) — R$ 2.000,00 cada
- Linha 003: ND 339000 (genérica) — R$ 2.000,00
- Valor Req: R$ 1.999,80

**Lógica correta das linhas de evento da NC (corrigido):**
Cada linha da NC representa uma **posição de saldo** naquela ND, NÃO uma parcela a somar. Se duas linhas aparecem com a mesma ND, mesma FONTE, mesmo PTRES, mesmo UGR, mesmo PI e mesmo valor — é o **mesmo saldo mostrado duas vezes** (operações contábeis diferentes sobre o mesmo recurso), não saldo duplicado.

O sistema deve:
1. Agrupar linhas por ND
2. Se houver linhas com ND idêntica e todos os campos iguais → usar o valor UMA VEZ (não somar)
3. Se houver linhas com ND diferente → cada uma representa saldo disponível naquela ND separadamente
4. Para validar contra a requisição: buscar a linha cuja ND corresponde à ND da requisição e verificar se o saldo ≥ valor da requisição
5. Se a NC tem ND genérica (339000) e a requisição tem ND específica (339039) → ⚠️ FLAG DETAORC (regra já mapeada)

**Todos os campos da NC podem variar entre linhas e entre NCs:** FONTE, ESF, PTRES, UGR, PI — cada campo depende da NC específica. O sistema não deve assumir valores padrão para nenhum campo.

**ACHADO: FONTE variável entre NCs:**
- Proc 3: FONTE = `1021000000`
- Proc 1/2: FONTE = `1000000000`
- FONTE é um campo variável da NC — o sistema deve sempre extrair e incluir na análise, sem assumir padrão

---

### 3.5.1 DOCUMENTO DO CONTRATO (apenas processos de contrato)

**Identificadores de página:**
- Texto contém "TERMO DE CONTRATO"
- Texto contém "CONTRATANTE" e "CONTRATADA"
- Texto contém "cláusulas e condições"

**Campos:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Nr Contrato | `Contrato.*?Nº\s*(\d{3}/\d{4})` | `059/2024` |
| PE de origem | `Pregão.*?Nº\s*(\d{3}/\d{4})` | `004/2023` |
| Proc Adm de origem | `Processo Administrativo.*?(\d{5}\.\d{6}/\d{4}-\d{2})` | `64320.006632/2023-41` |
| UASG gerenciadora PE | `UASG\s*(\d{6})` no corpo do contrato | `160140` |
| CNPJ Contratante | `inscrita no CNPJ.*?(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})` (1º) | `09.549.370/0001-57` |
| Razão Social Contratada | `CONTRATADA,?\s*e?\s*(.+?),\s*inscrita` | `MOREIRA & LOPES SERVICOS...` |
| CNPJ Contratada | `inscrita no CNPJ.*?(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})` (2º) | `24.043.951/0001-06` |
| Data assinatura | `Campo Grande.*?,\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})` | `16 de outubro de 2024` |

**Validações do contrato:**
1. CNPJ da contratada no contrato = CNPJ na requisição = CNPJ no SICAF → ✅
2. Nr do contrato na requisição = Nr do contrato no documento → ✅
3. Assinaturas presentes (Contratante + Contratado + Testemunhas)

**ACHADO — Divergência de Razão Social (Proc 3):**
- Termo de Abertura diz: `MAIRA LOPES DA SILVA LTDA` (nome da pessoa dona do CNPJ)
- Contrato diz: `MOREIRA & LOPES SERVICOS ELETRICOS E AR CONDICIONADO LTDA`
- SICAF diz: `MOREIRA & LOPES SERVICOS LTDA`
- CNPJ é o mesmo em todos: `24.043.951/0001-06`
- Severidade: ⚠️ ADVERTÊNCIA (amarelo) — mesma pessoa/CNPJ, só nome divergente
- Se o CNPJ não bater → ❌ BLOQUEIO GRAVE (vermelho)

---

### 3.6 CERTIDÕES — SICAF

**Identificadores de página:**
- Texto contém "Sistema de Cadastramento Unificado de Fornecedores - SICAF"
- Texto contém "Dados do Fornecedor"

**Campos:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| CNPJ | `CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})` | `41.835.803/0001-43` |
| Razão Social | `Razão Social:\s*(.+)` | `CARVALHO COMERCIO & SERVICOS LTDA` |
| Situação | `Situação do Fornecedor:\s*(\w+)` | `Credenciado` |
| Vencimento Cadastro | `Data de Vencimento do Cadastro:\s*(\d{2}/\d{2}/\d{4})` | `25/01/2027` |
| Porte | `Porte da Empresa:\s*(.+)` | `Empresa de Pequeno` |
| Ocorrência | `Ocorrência:\s*(\w+)` | `Consta` |
| Impedimento Licitar | `Impedimento de Licitar:\s*(.+)` | `Nada Consta` |
| Ocorr. Imped. Indiretas | `Ocorrências Impeditivas indiretas:\s*(.+)` | `Nada Consta` |

**Níveis de certidões no SICAF (validades individuais):**
- Receita Federal (e Dívida Ativa da União)
- FGTS
- Receita Estadual
- Receita Municipal
- Receita Trabalhista (CNDT)

**Cada certidão tem:** nome, tipo (Automática/Manual), data emissão, data validade.

**Regex para validades:** `Validade:\s*(\d{2}/\d{2}/\d{4})`

**Validações SICAF:**
1. Situação = "Credenciado" → ✅
2. Cada certidão com validade > data atual → ✅ (vencida = ⚠️ ressalva ou ❌ bloqueio)
3. Impedimento de Licitar = "Nada Consta" → ✅
4. Ocorrências Impeditivas Indiretas = "Consta" → ⚠️ RESSALVA (NÃO reprova automaticamente)
5. CNPJ do SICAF = CNPJ da requisição → ✅ (divergência = ❌ BLOQUEIO)

**ACHADO Proc 3 — Certidão próxima de vencer:**
- FGTS validade: 16/02/2026 (SICAF emitido 09/02/2026 — apenas 7 dias de margem)
- O sistema deve alertar certidões com validade < 15 dias à frente: ⚠️ ALERTA VENCIMENTO PRÓXIMO
- Motivo: entre a análise pela SAL e a emissão efetiva da NE, pode decorrer dias; se a certidão vencer nesse intervalo, será necessário novo SICAF

---

### 3.7 CERTIDÕES — CADIN

**Identificador:** Texto contém "CADIN" ou "Cadastro Informativo"

| Campo | Regex | Exemplo |
|-------|-------|---------|
| Situação | `Situação.*?:\s*(REGULAR\|IRREGULAR\|NADA CONSTA)` | `REGULAR` |

**Validação:** REGULAR ou NADA CONSTA → ✅. Qualquer outra coisa → ❌ BLOQUEIO.

---

### 3.8 CERTIDÕES — TCU / CNJ / CNEP / CNEI

**Identificador:** Texto contém "Consulta Consolidada" ou "TCU" ou "CNJ"

Formato unificado — geralmente uma consulta que retorna:

| Cadastro | Resultado esperado |
|----------|--------------------|
| CEIS (Empresas Inidôneas e Suspensas) | Nada Consta |
| CNEP (Empresas Punidas) | Nada Consta |
| CEPIM (Entidades sem fins lucrativos impedidas) | Nada Consta |
| Lista de Inidôneos do TCU | Nada Consta |
| CADICON / eTCE | Nada Consta |
| CNJ (Improbidade Administrativa) | Nada Consta |

**Regex:** `(?:Nada Consta|Nada consta|NADA CONSTA)`

**Validação:** Todos "Nada Consta" → ✅. Qualquer "Consta" → ❌ BLOQUEIO (exceto Ocorrências Impeditivas Indiretas do SICAF, que é ressalva).

---

### 3.9 DESPACHOS

**Identificadores de página:**
- Texto contém "Despacho Nº"
- Texto contém "EB:" seguido de NUP
- Assinatura eletrônica com código de verificação

**Estrutura de cada despacho:**

```
EB: [NUP do processo no EB] Classificação: [código]
MINISTÉRIO DA DEFESA
EXÉRCITO BRASILEIRO
[Nome da OM]
Despacho Nº [número]-[setor]/[OM]
[Cidade], [data].
Assunto: [texto]
[Corpo do despacho]
[NOME] - [Posto/Grad]
[Cargo]
Documento assinado eletronicamente...
```

**Campos:**

| Campo | Regex | Exemplo |
|-------|-------|---------|
| NUP EB | `EB:\s*(\d{5}\.\d{6}/\d{4}-\d{2})` | `65297.001503/2026-15` |
| Nr Despacho | `Despacho Nº\s*(\S+)` | `437-OD/Cmdo 9º Gpt Log` |
| Setor/OM | após "Despacho Nº" | `OD/Cmdo 9º Gpt Log` |
| Assinante | Nome em MAIÚSCULAS antes do posto | `RODRIGO DA SILVA ALVES` |
| Posto | após nome | `Cel` |
| Cargo | linha após posto | `Ordenador de Despesas do Cmdo 9º Gpt Log` |
| Data assinatura | `em\s+(\d{2}/\d{2}/\d{4})` | `13/02/2026` |

**Cadeia de despachos típica (Proc 2 — OM subordinada / participante):**

1. **Fiscal Administrativo da OM requisitante** (Cap Wendell — 18º B Trnp)  
   → "Atendido os requisitos da Lei nº 14.133, aprovo a presente Requisição e a submeto ao Cmt da OM"

2. **Cmt da OM requisitante** (TC Paulo Comunale — 18º B Trnp)  
   → "Aprovo a presente Requisição e a encaminho ao OD do Cmdo 9º Gpt Log, para fins de autorizar a emissão da Nota de Empenho"

3. **OD do 9º Gpt Log** (Cel Rodrigo da Silva Alves)  
   → "Encaminho processo para análise e verificação dos aspectos formais e legais, a fim de que a SAL emita parecer favorável"

**Cadeia de despachos típica (Proc 3 — Cmdo / contrato da própria UASG):**

1. **Fiscal Administrativo/CAF** (Maj Andre Luiz Cancela — Fisc Adm/CAF/Cmdo 9º Gpt Log)  
   → "aprovo a presente Requisição e submeto ao Ordenador de Despesas"

2. **Gestor de Crédito/CAF** (TC Rodrigo Santana Pinto — Ch CAF/Cmdo 9º Gpt Log)  
   → "Na qualidade de Gestor de Crédito do CAF, aprovo a presente Requisição e encaminho ao Ordenador de Despesas"

3. **OD do 9º Gpt Log** (Cel Rodrigo da Silva Alves)  
   → "Encaminho processo para análise e verificação dos aspectos formais e legais, a fim de que a SAL emita parecer favorável"

**Diferença na cadeia:**
- OM subordinada: Fisc Adm (OM) → Cmt (OM) → OD (9º Gpt Log)
- Cmdo/própria UASG: Fisc Adm (CAF) → Gestor Crédito (CAF) → OD (9º Gpt Log)
- Em ambos os casos, são sempre 3 despachos antes de chegar na SAL

**Observação:** O despacho do OD (item 3) é o que chega à SAL/CAF e dispara a análise do sistema. Os despachos 1 e 2 são pré-requisitos que devem estar presentes.

**ACHADO CRÍTICO — NUP divergente no despacho do OD (Proc 3):**
- NUP do processo: `65297.001232/2026-90`
- NUP no cabeçalho do Despacho 335-OD: `EB: 65297.001272/2026-31` (DIFERENTE!)
- O corpo do despacho refere-se ao processo correto
- Isso indica possível erro de digitação no cabeçalho do despacho, ou uso de NUP do próprio despacho (diferente do NUP do processo)
- O sistema deve: (1) extrair NUP do cabeçalho "EB:" e (2) comparar com NUP do processo. Se divergir → ⚠️ FLAG para analista verificar manualmente

**Análise de despachos pelo sistema (mecânico):**
- Verificar presença dos 3 despachos obrigatórios (Fisc Adm → Cmt → OD)
- Identificar palavras-chave: "aprovo", "ressalva", "reprovação", "restituir", "empenhe"
- Rastrear se existe despacho de reprovação anterior + correção posterior (reprovação superada)

---

## 4. PADRÕES DIVERGENTES ENTRE PROCESSOS

### 4.1 Formato do NUP

| Contexto | Formato | Exemplo |
|----------|---------|---------|
| Capa do Processo (sistema EB) | `XXXXX.XXXXXX/YYYY-DD` | `65297.001503/2026-15` |
| Protocolo Geral (sistema PG) | `XXXXX.XXXXXX/YYYY-DD` | `64136.000407/2026-21` |
| Requisição interna | pode ter NUP diferente do processo | `64136.000368/2026-62` |

> O NUP do processo pode ser diferente do NUP da requisição. O sistema deve usar o NUP da CAPA como identificador principal.

### 4.2 Formato da data

| Formato encontrado | Exemplo | Regex |
|--------------------|---------|-------|
| DD/MM/YYYY | `12/01/2026` | `\d{2}/\d{2}/\d{4}` |
| DD/MMM/YYYY | `11/JAN/2026` | `\d{2}/[A-Z]{3}/\d{4}` |
| DD de mês de YYYY | `05 de fevereiro de 2026` | `\d{1,2}\s+de\s+\w+\s+de\s+\d{4}` |
| DDMMMYY | `18JUN2025` | `\d{2}[A-Z]{3}\d{2,4}` |
| DDMmmYY (SIAFI) | `27Jan26` | `\d{2}[A-Z][a-z]{2}\d{2}` |
| DD MMM YY (NC req) | `27 JAN 26` | `\d{2}\s+[A-Z]{3}\s+\d{2}` |
| DDMMMYY (prazo) | `30JUN26` | `\d{2}[A-Z]{3}\d{2}` |
| Misto | `de 18 AGO 25` | diverso |

O sistema precisa de um parser de data flexível que aceite todos esses formatos.

### 4.3 Formato do número de pregão / contrato

| Formato | Exemplo | Tipo |
|---------|---------|------|
| XXXXX/YYYY | `90006/2024` | Pregão |
| XXXX/YYYY | `9014/2025` | Pregão |
| PE XXXXX/YYYY | `PE 90006/2024` | Pregão |
| XXX/YYYY | `004/2023` | Pregão SRP (no contrato) |
| XX/YYYY | `59/2024` | Contrato |

**NC — Formato do número:**

| Formato | Exemplo | Contexto |
|---------|---------|----------|
| YYYYNCXXXXXX | `2026NC000276` | NC padrão (NCs de crédito/provisão) |
| YYYYNCXXXXXX (400+) | `2026NC400428` | NC de contratos (série 400xxx) |
| YYYYRXXXXXXX | `2026R0000428` | Número interno SIAFI (DEMONSTRA-DIARIO) |

> **Observação:** O sistema deve usar o número `2026NCxxxxxx` como chave de referência. O número `2026Rxxxxxxx` é apenas o ID interno do SIAFI.

### 4.4 Formato da ND

| Formato | Exemplo | Significado |
|---------|---------|-------------|
| 6 dígitos | `339039` | ND completa (mais comum) |
| Com pontos | `33.90.30` | Mesmo que 339030 |
| Genérica | `339000` | Requer DETAORC |

### 4.5 Formato de valores monetários

| Formato | Exemplo |
|---------|---------|
| Com R$ e ponto/vírgula | `R$ 9.000,00` |
| Sem R$ | `9.000,00` |
| Com espaço | `R$ 779,896` |

---

## 5. MAPA DE VALIDAÇÕES CRUZADAS

### 5.1 CNPJ (deve ser idêntico em todas as peças)

```
Requisição (fornecedor) ←→ SICAF ←→ CADIN ←→ TCU/CNJ
```

Se qualquer CNPJ divergir → ❌ BLOQUEIO

### 5.2 ND (pode divergir legitimamente)

```
Requisição (ND específica, ex: 339039)
     ↕  comparar
NC (pode ser 339000 = genérica)
```

- Se iguais → ✅
- Se NC = 339000 e Req = específica → ⚠️ FLAG DETAORC (não bloqueia)
- Se ambas específicas mas diferentes → ❌ BLOQUEIO

### 5.3 Valor

```
Soma dos itens da requisição (QTD × P.Unit)
     ↕  comparar
Valor total declarado na requisição
     ↕  comparar
Valor total da NC
```

- Req soma = Req declarado → ✅ (cálculo correto)
- NC ≥ Req → ✅ (crédito suficiente)
- NC < Req → ⚠️ FLAG (pode haver saldo PI complementar — não bloqueia automaticamente)

### 5.4 Pregão × Item

```
Item da requisição (nr item + CATMAT)
     ↕  buscar
Base de pregões (PE + UASG + item)
     ↕  comparar
Preço unitário e disponibilidade
```

### 5.5 Prazo

```
Data atual
     ↕  comparar
Prazo de empenho da NC
```

- > 15 dias → ✅
- 7-15 dias → ⚠️ ALERTA
- < 7 dias → 🔴 URGENTE
- Vencido → ❌ NC expirada

---

## 6. GERAÇÃO DA MÁSCARA DA NE

### 6.1 Template — Licitação (Participante/Gerenciador/Carona)

```
[OM], [REQ Nr]-[Setor], [Objeto], [NC] de [data], 
[de/do] [Órgão], ND [código], PI [código], PE [Nr/Ano], 
UASG [código] ([PART/GER/CAR]).
```

**Exemplo gerado (Proc 1):**
```
9° B MNT, REQ 03-ALMOX, CONT SV CALHAS, 2026NC000270 de 11/JAN/2026, 
da DGO, ND 339039, PTRES 171460, UGR 160073, PI I3DAFUNADOM, 
PE 90006/2024, UASG 160141 (PART).
```

**Exemplo gerado (Proc 2):**
```
18° B TRNP, REQ 08-ALMOX, AQS MAT LIMP, 2026NC000276 de 12/01/2026, 
do DGO, ND 339000, UGR 160073, PI I3DAFUNADOM, 
PE 9014/2025, UASG 160078 (PART).
```

### 6.2 Template — Contrato

```
[OM], [REQ Nr]-[Setor] ([Seção]) – [Objeto], [NC] de [data], 
[de/do] [Órgão], ND [código], PTRES [código], UGR [código], PI [código], 
CONTRATO [Nr/Ano] da UASG [código].
```

**Exemplo gerado (Proc 3):**
```
Cmdo 9º Gpt Log, Req 19 – Almox Cmdo (SFPC) – Sv Mnt Ar Cond, 
2026NC400428 de 27 JAN 26, do COEX, ND 339039, FONTE 1021000000, 
PTRES 232180, UGR 167504, PI E3PCFSCDEGE, CONTRATO 59/2024 da UASG 160136.
```

**Observações do template de contrato:**
- UASG é sempre a da própria UG (160136), já que contrato é da própria UASG
- Tipo participação não se aplica (não existe PART/GER/CAR)
- PTRES e FONTE sempre incluídos
- Campo "Fisc Cnt" (Fiscal de Contrato) pode ser adicionado: `Fisc Cnt: 2º TEN PIQUELET`

### 6.3 Template — Dispensa

```
[OM], [DISP Nr/Ano], [Objeto], [NC] de [data], 
ND [código], PI [código], DISP [Nr/Ano], UASG [código] (GER).
```

### 6.4 Campos opcionais na máscara

| Campo | Quando incluir |
|-------|---------------|
| PTRES | Quando NC tem ND genérica (339000) ou quando vem de órgão externo |
| UGR | Sempre que disponível na NC |
| FONTE | Sempre incluir — é campo variável, não há valor padrão |
| Fisc Cnt | Quando houver contrato firmado (CONT) |

---

## 7. UASG — BASE DE REFERÊNCIA

| UASG | OM | Uso frequente |
|------|----|---------------|
| 160136 | 9º Gpt Log | GER (processos internos e contratos da própria UASG) |
| 160140 | Cmdo 9ª RM | GER (pregões SRP de serviço, ex: PE 004/2023 do contrato) |
| 160141 | CRO/9 | PART (pregões de serviço) |
| 160142 | 9º B Sup | GER/PART (material) |
| 160143 | H Mil A CG | PART (saúde) |
| 160078 | CMCG | GER (pregões grandes, ex: material limpeza) |

---

## 7.1 RESUMO — DIFERENÇAS CONTRATO vs LICITAÇÃO

| Aspecto | Licitação (Proc 1/2) | Contrato (Proc 3) |
|---------|---------------------|--------------------|
| Tipo empenho | Ordinário | Global |
| Peça processual extra | Edital (pág relevante) | Contrato completo + Check List |
| Referência na máscara | PE [Nr/Ano], UASG [código] (PART/GER) | CONTRATO [Nr/Ano] da UASG [código] |
| OM requisitante | OM subordinada (9º B Mnt, 18º B Trnp) | Cmdo 9º Gpt Log (própria UASG) |
| Cadeia despacho | Fisc Adm → Cmt OM → OD | Fisc Adm/CAF → Gestor Crédito/CAF → OD |
| Órgão emissor NC | DGO | COEX |
| Formato NC | Texto padrão ou imagem | SIAFI DEMONSTRA-DIARIO (texto monospaced) |
| NC linhas | Normalmente 1 linha | Pode ter múltiplas linhas com NDs diferentes |
| FONTE | 1000000000 | 1021000000 |
| Campo extra na req | — | Equipe Gestão/Fisc de Contrato |
| UGR | Código UASG (160073) | Código UG/GESTÃO SIAFI (167504) |

---

## 8. LACUNAS IDENTIFICADAS

1. ~~**Processo de contrato (65297.001232/2026-90):**~~ ✅ MAPEADO em 19/02/2026.

2. **Tabela de itens da requisição do Proc 2:** A requisição do 18º B Trnp lista os itens solicitados, mas não foi possível extrair a tabela completa com QTD e valores por item (estava no corpo do documento, não apenas no TR). Será mapeado com pdfplumber no protótipo.

3. **Formato da NC em imagem (OCR):** Proc 1 aparenta ter NC em formato de screenshot SIAFI. Padrão OCR precisa ser validado com Tesseract. Proc 3 trouxe NC em texto SIAFI (DEMONSTRA-DIARIO), o que ajuda a mapear o layout monospaced.

4. **Despachos de reprovação/correção:** Não encontrei exemplos reais de despacho de reprovação com correção posterior (reprovação superada). Será mapeado quando disponível.

5. **NC com múltiplas linhas de evento:** Proc 3 revelou que cada linha da NC é uma posição de saldo, não parcela a somar. Linhas com mesma ND e mesmos dados = mesmo saldo (não duplicar). O sistema precisa de lógica para identificar a linha correspondente à ND da requisição.

6. **Código UG/GESTÃO vs UASG:** Proc 3 revelou que NC do SIAFI usa códigos de gestão (167504, 167136) diferentes dos UASGs (160136). Necessário mapeamento UG/GESTÃO ↔ UASG para validação cruzada.

7. **Razão Social divergente com CNPJ correto:** Proc 3 mostrou que o Termo de Abertura pode conter nome diferente da razão social oficial. Sistema deve priorizar CNPJ sobre Razão Social — divergência de nome com CNPJ correto = ⚠️ advertência (amarelo); CNPJ divergente = ❌ bloqueio (vermelho).

---

## 9. PRÓXIMOS PASSOS

- [x] Mapear processo de contrato (65297.001232/2026-90)
- [ ] Validar regex contra pelo menos 5 processos de diferentes OMs
- [ ] Documentar variações de formatação entre OMs (9º B Mnt vs 18º B Trnp vs Cmdo 9º Gpt Log)
- [ ] Montar protótipo de extração com pdfplumber + regex usando os padrões mapeados
- [ ] Testar OCR da NC em formato imagem com Tesseract
- [ ] Construir mapeamento UG/GESTÃO ↔ UASG (167504→COEX, 167136→160136, etc)
- [ ] Obter exemplo real de despacho de reprovação com correção posterior
- [ ] Fase 2: Especificação técnica (lógica de negócio do analista humano)
