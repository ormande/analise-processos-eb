# ESPECIFICAÇÃO DA LÓGICA DE NEGÓCIO
## Sistema de Análise Automatizada de Processos Requisitórios — EB

**Versão:** 2.0  
**Data:** 19/02/2026  
**Fase:** 2 — Lógica de negócio (o que o analista humano faz)  
**Base:** Entrevista com analista da SAL/CAF do Cmdo 9º Gpt Log  
**Referência:** Mapeamento de Padrões v2 (Fase 1) + Arquivo de modelos NE

---

## VISÃO GERAL

Este documento descreve o que um analista da SAL faz ao receber um processo requisitório. Não contém código — descreve exclusivamente a **lógica humana** que o sistema deve replicar.

**Princípio fundamental:** O sistema é ferramenta de **apoio**. Ele acusa divergências, mas **nunca reprova automaticamente** nada que envolva julgamento. Quem decide é o analista, em consulta com o superior imediato quando necessário. Mesmo erros aparentemente graves (cálculo, ND incorreta, prazo vencido) podem ser aprovados com ressalva dependendo do contexto.

---

## FLUXO GERAL

```
PROCESSO CHEGA NA SAL (PDF via SPED)
         │
         ▼
┌─ ETAPA 1: TRIAGEM RÁPIDA ─────────────────────┐
│  Folhear PDF inteiro (~2 min)                   │
│  • Todas as peças presentes?                    │
│  • Tem NC? (se não → modo "sem NC")            │
│  • Tem reprovação anterior?                     │
│  • NC é imagem ou texto?                        │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌─ ETAPA 2: ANÁLISE DETALHADA ───────────────────┐
│  Requisição → NC → Certidões → Despachos        │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌─ ETAPA 3: DECISÃO ─────────────────────────────┐
│  ✅ Aprovação (encaminhamento, sem despacho)    │
│  ⚠️ Aprovação com ressalva (despacho)          │
│  ❌ Reprovação (despacho)                       │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌─ ETAPA 4: OUTPUTS ─────────────────────────────┐
│  • Máscara da NE                                │
│  • Texto de despacho (só ressalva/reprovação)   │
│  • Dados para simulação ComprasNet              │
└─────────────────────────────────────────────────┘
```

**Simulação ComprasNet:** pode acontecer em paralelo com a análise. O sistema disponibiliza UASG, pregão, item e valor assim que a requisição for processada.

---

## ETAPA 1 — TRIAGEM RÁPIDA

O analista folheia o PDF inteiro sem ler em detalhe, procurando 4 coisas:

### 1.1 Completude das peças

| Peça | Obrigatória | Observação |
|------|------------|------------|
| Capa / Check List | Sempre | — |
| Termo de Abertura | Sempre | — |
| Requisição | Sempre | — |
| NC | Condicional | Se ausente → modo "análise sem NC" (ver 1.2) |
| SICAF | Sempre | — |
| CADIN | Sempre | — |
| Consulta Consolidada (TCU/CNJ) | Sempre | — |
| Despacho Fisc Adm | Sempre | 1º da cadeia |
| Despacho Cmt/Gestor | Sempre | 2º da cadeia |
| Despacho OD | Sempre | 3º da cadeia |
| Contrato | Se tipo contrato | — |
| Edital/página do pregão | Se tipo licitação | — |
| Comprovante participação pregão | Se tipo PART | OMs próximas |
| Pesquisa de preço + aceite | Se tipo CARONA | Documentos extras obrigatórios |

Peça obrigatória ausente (exceto NC) → ⚠️ **sinalizar** para o analista. Ele decide se reprova ou aguarda.

### 1.2 Processo sem NC

O processo pode chegar sem NC (crédito ainda não recebido). O sistema apresenta botão **"Análise sem NC?"**:

- **Ativado:** analisa tudo normalmente, pula validações que dependem da NC, não gera máscara. Resultado = "ANÁLISE PARCIAL — AGUARDANDO NC"
- Quando NC chegar, o analista complementa sem reprocessar tudo

### 1.3 Reprovação anterior

O analista procura despachos com palavras de reprovação. Se encontrar:
- Com correção posterior → ponto de atenção na análise
- Sem correção → sinalizar como irregularidade de tramitação

**Palavras de reprovação:** "reprovo", "reprovação", "reprovada", "divergência", "impedimento", "vencida", "incorreta", "restituir"

**Palavras de correção:** "aprovo", "aprovação", "corrigida", "sanada", "retificada", "deve avançar"

### 1.4 Formato da NC

O sistema detecta automaticamente: página com texto extraível → modo regex. Sem texto ou muito pouco → modo OCR (Tesseract).

---

## ETAPA 2 — ANÁLISE DETALHADA

### 2.1 REQUISIÇÃO (dados-chave)

O analista começa sempre pela requisição. Extrai:

**Identificação:** Nr Req, Setor, OM, NUP, Tipo Empenho

**Fornecedor:** Nome, CNPJ (para cruzar com certidões)

**Instrumento:** Nr Pregão/Contrato, UASG, Tipo participação (GER/PART/CAR)

**Fonte de recursos:** Número(s) da NC, PI

> **Detalhe importante:** O analista só anota o **PI** a partir da requisição. Os demais dados financeiros (PTRES, UGR, FONTE, ESF, ND) ele busca direto na NC quando necessário. Porém, o sistema deve **exibir todos os dados da NC na tela** para que o analista possa consultar sem precisar abrir o PDF.

**ACHADO do arquivo de modelos — múltiplas NCs por requisição:**
Uma requisição pode ter várias NCs (ex: Proc 64136.000430 tem 5 NCs do COTER: 2026NC400576 a 400582). Quando isso acontece, o sistema deve processar cada NC individualmente e mostrar todas na tela.

**Tabela de itens — verificações:**

| Verificação | O que o sistema faz | Severidade |
|-------------|-------------------|------------|
| QTD × P.Unit = P.Total | Calcula e compara | ⚠️ AMARELO se divergir |
| Soma itens = valor declarado | Soma e compara | ⚠️ AMARELO se divergir |
| ND vs descrição do item | Consulta tabela ND/subelementos | ⚠️ AMARELO se incompatível |
| Subelemento vs descrição | Consulta tabela | ⚠️ AMARELO se incompatível |
| Item disponível no pregão | Consulta base de pregões | ⚠️ AMARELO se indisponível |
| Valor unitário vs preço registrado | Compara com pregão | ⚠️ AMARELO se divergir |
| Quantidade vs disponível | Compara com saldo pregão | ⚠️ AMARELO se exceder |

**NENHUMA divergência na tabela de itens gera reprovação automática.** Todas são sinalizadas em amarelo para o analista avaliar. Exemplos de decisões que o analista pode tomar:
- Cálculo errado → aprovar com ressalva (empenhar a menos ou a mais)
- ND/SI incorreto → consultar superior; reprovar ou aprovar com ressalva dependendo do caso
- Quantidade indisponível → aprovar quantidade parcial
- Valor divergente → aprovar com o valor correto do sistema

### 2.2 NOTA DE CRÉDITO (NC)

Após a requisição, o analista vai para a NC.

**Verificação de ND:**

| Cenário | Severidade |
|---------|------------|
| ND NC = ND Req (ambas específicas) | 🟢 VERDE |
| ND NC = 339000 (genérica), Req = específica | ⚠️ AMARELO — Flag DETAORC |
| ND NC ≠ ND Req (ambas específicas e diferentes) | ⚠️ AMARELO — sinalizar para o analista |

**Verificação de valor:**

| Cenário | Severidade |
|---------|------------|
| Saldo ≥ valor requisição | 🟢 VERDE |
| Saldo < valor requisição | ⚠️ AMARELO — possível saldo em outro PI |

**Verificação de prazo de empenho:**

| Prazo | Severidade |
|-------|------------|
| > 15 dias | 🟢 VERDE |
| 7 a 15 dias | ⚠️ AMARELO — urgência |
| < 7 dias | ⚠️ AMARELO — urgência alta |
| Vencido | ⚠️ AMARELO — prazo expirado, sinalizar |

> **Nota:** Prazo vencido **não bloqueia automaticamente**. Ano passado ainda se empenhava com prazo passado. O sistema acusa e o analista decide conforme a orientação vigente.

**Linhas da NC (formato SIAFI):**
Cada linha = posição de saldo. Linhas com mesma ND e mesmos dados = mesmo saldo (não duplicar). Linhas com NDs diferentes = posições independentes.

**Dados da NC exibidos na tela (todos, para consulta do analista):**
- Número da NC
- Data de emissão
- Órgão emissor (UG emitente)
- ND
- PTRES
- UGR
- PI
- FONTE
- ESF
- Valor/saldo
- Prazo de empenho

### 2.3 CERTIDÕES

**2.3.1 SICAF**

| Item | 🟢 Verde | ⚠️ Amarelo | 🔴 Vermelho |
|------|---------|-----------|------------|
| CNPJ | = da requisição | — | ≠ da requisição |
| Razão Social | = da requisição | ≠ nome mas CNPJ OK | — |
| Situação | "Credenciado" | — | Outra situação |
| Impedimento Licitar | "Nada Consta" | — | "Consta" |
| Ocorrências | "Nada Consta" | "Consta" (verificar) | — |
| Ocorr. Imped. Indiretas | "Nada Consta" | "Consta" | — |
| Vínculo Serv. Público | "Nada Consta" | — | "Consta" |

**Validades individuais:**

| Situação | Severidade |
|----------|------------|
| Validade > hoje + 15 dias | 🟢 VERDE |
| Validade > hoje mas < 15 dias | ⚠️ AMARELO — pode vencer antes do empenho |
| Validade ≤ hoje | 🔴 VERMELHO — certidão vencida |

**2.3.2 CADIN**

| Situação | Severidade |
|----------|------------|
| "REGULAR" ou "NADA CONSTA" | 🟢 VERDE |
| Outra situação | 🔴 VERMELHO |
| CNPJ ≠ da requisição | 🔴 VERMELHO |

**2.3.3 Consulta Consolidada (TCU/CNJ/CEIS/CNEP)**

Todos devem ser "Nada Consta". Qualquer "Consta" → 🔴 VERMELHO.
CNPJ ≠ da requisição → 🔴 VERMELHO.

### 2.4 CONTRATO (quando aplicável)

| Item | 🟢 | 🔴 |
|------|---|---|
| Nr contrato = o da requisição | ✓ | Divergente |
| CNPJ contratada = CNPJ req/SICAF | ✓ | Divergente |
| Assinaturas presentes | ✓ | Sem assinatura |

### 2.5 DESPACHOS

**Se triagem NÃO acusou reprovação:** apenas confere presença dos 3 despachos obrigatórios.

| Despacho | OM subordinada | Cmdo/própria UASG |
|----------|---------------|-------------------|
| 1º | Fisc Adm da OM | Fisc Adm/CAF |
| 2º | Cmt da OM | Gestor Crédito/CAF |
| 3º | OD 9º Gpt Log | OD 9º Gpt Log |

**Se triagem ACUSOU reprovação:** lê todos os despachos em detalhe.

**NUP divergente em despacho:** ⚠️ amarelo — possível erro de digitação.

---

## ETAPA 3 — DECISÃO

### 3.1 ✅ APROVAÇÃO

Tudo OK, sem nenhuma ressalva. O processo é **encaminhado** ao OD. **Não gera despacho** — é apenas encaminhamento.

Texto padrão de aprovação (referência, classificação 004.12):
> "Informo que a presente requisição foi analisada, a mesma atende o aspecto formal; está de acordo com a legislação vigente e não há desvio de finalidade."

### 3.2 ⚠️ APROVAÇÃO COM RESSALVA

Tem pontos de atenção que não impedem o prosseguimento. **Gera despacho.**

### 3.3 ❌ REPROVAÇÃO

Tem problema que exige correção. **Gera despacho.**

---

## ETAPA 4 — OUTPUTS

### 4.1 MÁSCARA DA NE

Gerada conforme os padrões do arquivo NOVO_MODELO_CAMPO_DESCRICAO_NE do 9º Gpt Log.

**REGRA FUNDAMENTAL:** Nem todos os campos aparecem em toda máscara. Só incluir o campo se ele consta na NC. Se a NC não traz PTRES, não incluir PTRES. Se não traz FONTE, não incluir FONTE. Se não traz UGR, não incluir UGR.

**Template LICITAÇÃO (PART/GER/CAR):**
```
[Sigla OM], REQ [Nr]-[Setor], [Objeto resumido], [NC] de [data], 
[de/do] [Órgão], ND [código][, FONTE código][, PTRES código]
[, UGR código], PI [código], PE [Nr/Ano], UASG [código] ([PART/GER/CAR]).
```

**Exemplos reais do arquivo de modelos (copiar o estilo exato):**
```
18° B TRNP, REQ 314-ALMOX, AQS DE MATERIAL ESPORTIVO, 2025NC014619, 
de 28/08/2025, do COTER, ND 339030, PI FAOPPREININ, PE 90005/2024, 
UASG 160078 (PART).

CIA CMDO/9º GPT LOG, AQS VIDRO TEMPERADO, 2025NC419259, de 18/06/25, 
do DGP, ND 339000 FONTE 1005000142 PTRES 215845 PI D8SAFUNADOM, 
PE 90004/2024, UASG 160141 (PART).

9º B SUP, REQ 37-CL VIII, AQS DE MAT DE SAÚ, 2025NC419583, de 18JUN2025, 
do GDP, ND 33.90.30, PI D8SAFCTACL8, PE 90018/24, UASG 160136 (GER).
```

**Template CONTRATO:**
```
[Sigla OM], REQ [Nr]-[Setor], [Objeto resumido], [NC] de [data], 
[de/do] [Órgão], ND [código][, PTRES código][, UGR código], PI [código], 
CONT [Nr/Ano], UASG [código] ([GER]).
```

**Exemplos reais:**
```
9º GPT LOG, REQ 220-ENC SET MAT, CONT DE SEV, 2025NC428651, de 07OUT025, 
DA DGP, ND 339033, PTRES 171404, UGR 160505 PI IDDSATSPCEB, 
CONT 40/2024, UASG 160136 (GER).

18° B TRNP, REQ 285-APROV, AQS GEN ALIMENTICIOS, 2025NC413392, de 
18/08/2025, do COE, ND 339030, PI E6SUPLJA1QR. CONT 01/2025 UASG 160142 (GER).
```

**Template DISPENSA:**
```
[Sigla OM], DISP [Nr/Ano], [Objeto], [NC] de [data], ND [código], 
PI [código], DISP [Nr/Ano], UASG [código] ([GER/PART]).
```

**Exemplos reais:**
```
9º GPT LOG, DISP 153/2025, CONT SV GRAFICOS 2025NC014887, De 11AGO, 
ND 339039, PI I3DAFUNADOM. PE 90003/2025, UASG 160078 (PART).

9° B MNT, PEL SUP, LICENCA ANUAL DE PLATAFORMA ELELT, 2025NC410230, 
DISP 90010/2025, UASG 160136 (GER).
```

**Observações sobre o padrão real:**
- Formato de data varia muito (18/08/2025, 07OUT025, 18JUN2025, De 11AGO, 18 AGO 25, 24/09/25) — o sistema deve gerar no formato mais próximo do que veio na NC
- ND pode aparecer com ou sem pontos (339030 ou 33.90.30)
- A separação entre campos varia (vírgula, ponto, espaço) — manter o mais legível
- Sigla da OM é em MAIÚSCULAS e abreviada (9º GPT LOG, 18° B TRNP, 9° B MNT, CIA CMDO)
- Objeto é resumido em poucas palavras (AQS MAT LIMP, CONT SV GRAFICOS, AQS DE MAT DE SAÚ)
- Quando múltiplas NCs → gerar uma máscara para cada NC (cada empenho separado)

**A máscara é gerada SOMENTE quando:**
- A análise resultou em aprovação (com ou sem ressalva)
- A NC está presente

### 4.2 TEXTO DE DESPACHO

O sistema gera **somente o corpo do texto**, sem cabeçalho (sem "Despacho Nº", sem data, sem OM, sem assinatura). O texto aparece numa **caixa de texto editável** que o analista pode modificar antes de usar.

**Só gera despacho para:**
- ⚠️ Aprovação com ressalva
- ❌ Reprovação

**Aprovação simples NÃO gera despacho** — é apenas encaminhamento.

**O texto sempre começa com "Informo que..."**

**Exemplos reais de despachos (banco de referência do sistema):**

APROVAÇÃO COM RESSALVA — valor:
```
Informo que o saldo disponível para empenho é de R$ 34.625,95, faltando R$ 9,03 para o empenho no valor total de R$ 34.634,98.
```

APROVAÇÃO COM RESSALVA — quantidade:
```
Informo que na tabela de requisição, no item 103, é solicitado 56 unidades, porém a quantidade disponível para empenho do mesmo é de apenas 37 unidades.
```

APROVAÇÃO COM RESSALVA — ND incorreta:
```
Informo que na tabela de requisição consta ND final 88 e valor total R$ 1.000,00, onde o correto seria ND final 30 e valor total R$ 999,71.
```

APROVAÇÃO COM RESSALVA — pregão incorreto:
```
Informo que a Requisição solicita compra para o Pregão 90010/2024, porém o correto seria 90010/2025.
```

APROVAÇÃO COM RESSALVA — item incorreto:
```
Informo que a Requisição solicita compra para o item 3, porém o correto seria item 5.
```

APROVAÇÃO COM RESSALVA — valor divergente req vs contrato:
```
Informo que as tabelas da requisição e do contrato estão divergentes nos campos valor unitário e quantidades.
```

APROVAÇÃO COM RESSALVA — reprovação anterior superada:
```
Informo que o processo foi reprovado pelo Fiscal Administrativo (Despacho Nº 206) por divergência no Item 09. Contudo, consta nos autos a Requisição corrigida (pág. 61) alterando para o Item 10, já aprovada pelo CCOL (Despacho Nº 198). Sendo assim, a Requisição deve avançar para as próximas fases.
```

REPROVAÇÃO — certidão vencida:
```
Informo que a Certidão Negativa de Débitos Estaduais se encontra vencida, o que impede o andamento do processo.
```

REPROVAÇÃO — ND/SI incorreto:
```
Informo que a presente requisição foi analisada e apresenta divergências formais impeditivas. A ND 33.90.39 se refere à "Serviços", porém o item em questão (Calha em chapa de aço galvanizado) se enquadra em "Material", ND 33.90.30. Adicionalmente, o subelemento indicado na requisição (24 - Vistos Consulares) não é o subelemento correto para o empenho deste item.
```

REPROVAÇÃO — valor divergente:
```
Informo que o valor do item 1 na tabela de Requisição consta R$ 40,00, sendo que no sistema consta o valor de R$ 34,00, devendo atualizar também o valor total.
```

REPROVAÇÃO — CNPJ divergente:
```
Informo que o CNPJ do CADIN anexado é de outra empresa.
```

REPROVAÇÃO — item indisponível:
```
Informo que o item 124 da tabela de requisição não está disponível para empenho.
```

REPROVAÇÃO — tipo empenho indefinido:
```
Informo que o tipo de empenho deve ser definido se Ordinário ou Global e corrigir também o valor total da tabela de requisição.
```

### 4.3 DADOS PARA SIMULAÇÃO COMPRASNET

Disponíveis assim que a requisição for processada:

| Dado | Fonte |
|------|-------|
| UASG | Requisição |
| Nr Pregão/Contrato | Requisição |
| Nr do Item | Tabela de itens |
| Quantidade | Tabela de itens |
| Valor unitário | Tabela de itens |

---

## TABELA DE SEVERIDADES — CONSOLIDADA

### 🟢 VERDE — Conforme
Verificado e aprovado.

### ⚠️ AMARELO — Sinalização (analista decide)
1. ND genérica (339000) na NC → DETAORC
2. Razão Social divergente (CNPJ OK)
3. Certidão com vencimento < 15 dias
4. Ocorrências Impeditivas Indiretas "Consta" no SICAF
5. Valor da NC < valor da requisição
6. Reprovação anterior superada
7. NUP divergente em despacho
8. Prazo de empenho NC entre 7-15 dias
9. Máscara do requisitante diverge da gerada
10. **Prazo de empenho NC vencido** (sinalizar, não bloquear)
11. **Erro de cálculo na tabela de itens** (sinalizar, não bloquear)
12. **ND/SI incompatível com item** (sinalizar, não bloquear)
13. **ND NC ≠ ND Req (ambas específicas)** (sinalizar, não bloquear)
14. **Quantidade solicitada > disponível no pregão** (sinalizar)
15. **Valor unitário divergente do registrado** (sinalizar)
16. **Item indisponível no pregão** (sinalizar)
17. **Peça obrigatória ausente** (sinalizar, analista decide)

### 🔴 VERMELHO — Bloqueio provável (quase sempre reprova)
1. CNPJ divergente entre peças
2. Certidão vencida (SICAF)
3. Impedimento de Licitar "Consta"
4. TCU/CNJ/CEIS/CNEP "Consta"
5. CADIN irregular
6. Situação SICAF ≠ "Credenciado"
7. Vínculo com Serviço Público "Consta"
8. Nr contrato divergente (documento vs requisição)

> **Nota:** Mesmo itens vermelhos não geram reprovação automática pelo sistema. O vermelho indica que o analista DEVE investigar e que na grande maioria dos casos resultará em reprovação, mas a decisão continua sendo humana.

---

## MODO ESPECIAL: ANÁLISE SEM NC

Quando ativado (botão na triagem):

**Executa:** triagem, requisição, certidões, despachos, dados para simulação

**Não executa:** validação ND/valor NC, prazo de empenho, geração de máscara NE

**Output:** relatório de pré-análise com "ANÁLISE PARCIAL — AGUARDANDO NC"

---

## INTERFACE — 4 ESTÁGIOS

A interface apresenta 4 seções, cada uma com **seta para expandir/recolher** ou modo **tela inteira por seção**. O analista pode navegar entre seções livremente.

### ESTÁGIO 1 — IDENTIFICAÇÃO
Dados básicos extraídos da capa e requisição.

```
NUP:            65297.001232/2026-90
Tipo:           Contrato
OM:             Cmdo 9º Gpt Log
Setor:          Almox Cmdo
Objeto:         Sv Mnt Ar Condicionado (SFPC)
Fornecedor:     MOREIRA & LOPES SERVICOS LTDA
CNPJ:           24.043.951/0001-06
Tipo Empenho:   Global
Instrumento:    Contrato 59/2024 / UASG 160136
```

### ESTÁGIO 2 — REQUISIÇÃO E ITENS
Tabela de itens com validações e dados financeiros.

| Item | Descrição | QTD | ND/SI | P.Unit | P.Total | Status |
|------|-----------|-----|-------|--------|---------|--------|
| 4 | Mnt ar condicionado Split | 6.666 | 39.17 | R$ 0,30 | R$ 1.999,80 | 🟢 |

Cálculo: 🟢 Correto (6.666 × 0,30 = 1.999,80)
ND/SI: 🟢 339039/17 — Manutenção e Conservação de Bens Móveis

**Dados para simulação ComprasNet:** [botão copiar]

### ESTÁGIO 3 — NC E CERTIDÕES

**NC 2026NC400428 — dados completos:**
```
Número:         2026NC400428
Data emissão:   27/JAN/2026
UG Emitente:    167504 - CENTRO DE OBTENÇÕES DO EXÉRCITO
UG Favorecida:  167136 - 9° GRUPAMENTO LOGÍSTICO
ND:             339039
PTRES:          232180
FONTE:          1021000000
UGR:            167504
PI:             E3PCFSCDEGE
Saldo:          R$ 2.000,00
Prazo empenho:  30/JUN/2026 (131 dias)
```

| Verificação | Resultado |
|-------------|-----------|
| ND NC vs Req | 🟢 339039 = 339039 |
| Saldo vs Valor | 🟢 R$ 2.000,00 ≥ R$ 1.999,80 |
| Prazo | 🟢 131 dias restantes |

**Certidões:**
| Certidão | CNPJ | Resultado | Validade |
|----------|------|-----------|----------|
| SICAF | 🟢 24.043.951/0001-06 | 🟢 Credenciado | — |
| Receita Federal | — | — | 🟢 06/08/2026 |
| FGTS | — | — | ⚠️ 16/02/2026 (7d) |
| Trabalhista | — | — | 🟢 06/08/2026 |
| Estadual | — | — | 🟢 07/04/2026 |
| Municipal | — | — | 🟢 09/03/2026 |
| Impedimento Licitar | 🟢 Nada Consta | — | — |
| Imped. Indiretas | 🟢 Nada Consta | — | — |
| CADIN | 🟢 REGULAR | — | — |
| TCU | 🟢 Nada Consta | — | — |
| CNJ | 🟢 Nada Consta | — | — |
| CEIS | 🟢 Nada Consta | — | — |
| CNEP | 🟢 Nada Consta | — | — |

### ESTÁGIO 4 — DECISÃO E OUTPUTS

**Resultado: ⚠️ APROVAÇÃO COM RESSALVA**

Ressalvas:
- ⚠️ FGTS com validade próxima (16/02/2026 — 7 dias)
- ⚠️ Razão Social: req diz "MAIRA LOPES DA SILVA LTDA", SICAF diz "MOREIRA & LOPES SERVICOS LTDA" (CNPJ confere)

**Máscara da NE:** [botão copiar]
```
Cmdo 9º Gpt Log, Req 19 – Almox Cmdo (SFPC) – Sv Mnt Ar Cond, 
2026NC400428 de 27 JAN 26, do COEX, ND 339039, FONTE 1021000000, 
PTRES 232180, UGR 167504, PI E3PCFSCDEGE, 
CONTRATO 59/2024, UASG 160136 (GER).
```

**Despacho:** [caixa de texto editável]
```
Informo que a certidão do FGTS no SICAF possui validade próxima (16/02/2026). Adicionalmente, a razão social na requisição ("MAIRA LOPES DA SILVA LTDA") diverge da razão social no SICAF ("MOREIRA & LOPES SERVICOS LTDA"), embora o CNPJ (24.043.951/0001-06) seja o mesmo em ambas as peças.
```

---

## REGRAS DO BANCO DE DADOS

### UASGs
Quando uma UASG nova for encontrada num processo (não existente no banco), o sistema deve **armazenar automaticamente** no SQLite com: código UASG, nome da OM (extraído do processo), e data de primeiro uso.

### NDs e Subelementos
Tabela pré-carregada com os 352 registros da planilha TABELANATUREZADADESPESA2025.xlsx.

### Processos analisados
Cada análise é salva com: NUP, data análise, resultado (aprovado/ressalva/reprovado), dados extraídos, máscara gerada.

---

## TIPOS DE PROCESSO — DOCUMENTAÇÃO EXTRA

| Tipo | Documentos extras além do padrão |
|------|----------------------------------|
| Licitação GER | Edital (pág. com Lei do processo) |
| Licitação PART | Edital + comprovante de participação do pregão |
| CARONA | Relatório pesquisa de preço + aceite da empresa + aceite da UASG gerenciadora + BI com responsáveis da pesquisa |
| Contrato | Cópia do contrato + check list de contrato |
| Dispensa | Documentação específica de dispensa |

---

## APÊNDICE — PADRÕES DE DESPACHO ADICIONAIS (arquivo de modelos)

**Quando informar para anexar NE:**
```
Informo que, deverá anexar a NE [número] neste processo.
```

**Reprovação por item não disponível:**
```
Informo que o item 124 da tabela de requisição não está disponível para empenho.
```

**Reprovação por valor divergente no sistema:**
```
Informo que o valor do item 1 na tabela de Requisição consta R$ 40,00, sendo que no sistema consta o valor de R$ 34,00, devendo atualizar também o valor total.
```

**Ressalva por quantidade parcial disponível:**
```
Informo que na tabela de requisição consta o item 3 com valor unitário R$ 2,70, porém está disponível para empenho apenas o item 4 com valor unitário R$ 2,85.
```
