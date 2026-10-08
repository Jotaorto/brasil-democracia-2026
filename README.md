# Brasil Democracia 2026 — automação de rascunhos

Repositório do projeto: **Jotaorto/brasil-democracia-2026**, branch padrão `main`. Visibilidade **pública** confirmada na API em 08/10/2026 às 18:23 UTC.

A receita testa os scripts, valida o catálogo e consulta quatro feeds EBC para gerar rascunhos com fonte e data. A publicação do [Site Brasil Democracia 2026](https://brasil-democracia-2026-jota.jotaortojotaorto.chatgpt.site/) continua pelo fluxo editorial existente. Este workflow não altera o catálogo, não publica o Site e não transforma manchetes em incidentes, condenações ou relações do grafo.

## Execução

- Agendamento: seis tentativas diárias às **00:17, 04:17, 08:17, 12:17, 16:17 e 20:17 de Brasília**, de 8 a 25 de outubro de 2026.
- Push em `main` sem o marcador `[coletar]`: testes, validação e rascunho offline.
- Push em `main` com `[coletar]` na mensagem do commit: solicita explicitamente uma coleta inicial ou de verificação, após testes e validação.
- Execução manual: `collect=false` por padrão; `collect=true` solicita a consulta das quatro fontes.
- Reexecutar um commit marcado repete somente a leitura das fontes; não publica notícias.

A janela é [08/10/2026 00h, 26/10/2026 00h), horário de Brasília. O guard com ano roda antes do checkout e da coleta, e o coletor repete a verificação. O cron não contém ano; o guard bloqueia consultas em anos posteriores. Remover ou desativar o workflow ao encerrar a operação. Agendamentos podem atrasar ou perder execuções.

## Limite de gastos e acesso

Somente runner padrão `ubuntu-24.04` em repositório público, Python 3.13 e biblioteca padrão. O job bloqueia antes da alocação do runner se o repositório voltar a ser privado. Não há upload de artefatos, cache, GitHub Packages, IA paga, serviços pagos ou secrets de deploy. JSON temporário fica somente nos logs e no resumo do job; não há escrita no Git ou comandos de publicação. Logs e resumos não entram na franquia de armazenamento de artefatos.

Ações oficiais fixadas por SHA completo, permissões `contents: read` e checkout sem credenciais persistidas. Não incluir tokens, arquivos `.env`, acessos de publicação, ambientes Python, caches, pesos de modelos ou arquivos privados de investigação.

## Resultado e cobertura

Na execução do Actions, abrir o resumo do job ou a etapa **Registrar JSON nos logs e resumo**. Os relatórios `validation.json` e `observatory-news-draft.json` ficam nesses registros; não há download na seção Artifacts.

- `complete`: quatro fontes disponíveis, mesmo se nenhum item recente for aceito.
- `partial`: uma a três fontes disponíveis. O job pode ficar verde; a cobertura é parcial.
- `unavailable`: nenhuma fonte disponível; a coleta retorna código 2 e o relatório de diagnóstico permanece nos logs.
- `skipped`: consulta não realizada; não considerar como coleta bem-sucedida.

Conservar `published=false`, `requiresEditorialReview=true` e `editorialSeedModified=false`. `checkedAt` nulo significa fonte indisponível; `attemptedAt` registra a tentativa. A validação é estrutural, não uma verificação factual.

## Arquivos e origem

- `.github/workflows/observatory-drafts.yml`
- `scripts/automation/validate_observatory.py`
- `scripts/automation/collect_headlines.py`
- `tests/test_automation.py`
- `worker/observatory-data.json`
- `docs/actions-pins.json`

Snapshot do catálogo: fonte do Site versão **40**, commit `ef6c9b29b36c653d5c2b3f44b007e9cf708ee9c6`. Integração mínima da automação, sem espelho integral do Site. Vinte testes locais passaram; o snapshot foi validado com zero erros e treze avisos preservados. Os registros atuais do Actions comprovam separadamente o resultado hospedado.

## Referências oficiais

- [Execução manual](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
- [Condições dos jobs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions).
- [Uso e cobrança](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
- [Agendamentos](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Primeira coleta verificada

[Execução inicial no GitHub Actions](https://github.com/Jotaorto/brasil-democracia-2026/actions/runs/37824127591), em 08/10/2026 às 15:25 de Brasília: workflow concluído com sucesso, 20 testes aprovados, validação com zero erros e 13 avisos preservados. As quatro fontes responderam; foram gerados 22 rascunhos após deduplicação. Status `complete`, `published=false`, `requiresEditorialReview=true` e `editorialSeedModified=false`. Esse resultado confirma a coleta inicial, não uma publicação no Site nem a execução de horários futuros.
