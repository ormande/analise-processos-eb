# PRIMEIRO PROMPT PARA O CURSOR

Cole isso no chat do Cursor (Ctrl+L ou Cmd+L) quando abrir o projeto:

---

Leia os arquivos docs/MAPEAMENTO_PADROES_PROCESSOS_v2.md e 
docs/ESPECIFICACAO_LOGICA_NEGOCIO_v2.md completamente antes de 
começar a codar.

Depois, crie o módulo modules/extractor.py que faz a extração de 
dados de um PDF compilado de processo requisitório do Exército Brasileiro 
usando pdfplumber.

O módulo deve ter uma função principal:

```python
def extrair_processo(pdf_path: str) -> dict:
    """
    Recebe o caminho de um PDF compilado e retorna um dicionário 
    com todos os dados extraídos, organizados por seção:
    
    {
        "identificacao": { nup, tipo, om, setor, objeto, fornecedor, cnpj, 
                           tipo_empenho, instrumento, uasg },
        "itens": [ { item, catserv, descricao, und, qtd, nd_si, p_unit, p_total } ],
        "nota_credito": [ { numero, data, ug_emitente, ug_favorecida, nd, ptres, 
                            fonte, ugr, pi, esf, valor, prazo_empenho } ],
        "certidoes": { sicaf: {...}, cadin: {...}, tcu: {...}, cnj: {...}, 
                       ceis: {...}, cnep: {...} },
        "despachos": [ { numero, autor, tipo, texto_resumo } ],
        "metadata": { total_paginas, paginas_com_texto, paginas_ocr }
    }
    ```

Regras:
1. Use pdfplumber para extração de texto
2. Use regex para identificar padrões (ver MAPEAMENTO_PADROES)
3. Cada seção do PDF (capa, requisição, NC, SICAF, etc.) deve ter 
   sua própria função auxiliar
4. Se uma página não tem texto extraível (NC em imagem), marque-a 
   como "requer_ocr": True — o OCR será implementado depois
5. Teste com os 3 PDFs em tests/
6. Trate erros gracefully — se não encontrar um campo, retorne None 
   em vez de dar erro

Comece implementando apenas a extração da CAPA e da REQUISIÇÃO.
Depois eu peço as próximas seções.

---
