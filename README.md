# Brasil Democracia 2026 — automação de rascunhos

Repositório confirmado do projeto: **Jotaorto/brasil-democracia-2026**, branch padrão `main`, visibilidade **privada** na preparação de 08/10/2026.

Esta integração guarda a receita solicitada de validação e coleta de rascunhos. Commits em `main` executam somente testes e rascunho offline; a consulta dos quatro feeds EBC ocorre no agendamento autorizado ou em execução manual com `collect=true`. **Não publica o Site, não altera os dados editoriais e não inicia uma segunda rotina editorial de notícias.** A atualização editorial já associada ao Site permanece independente.

Site: [Brasil Democracia 2026](https://brasil-democracia-2026-jota.jotaortojotaorto.chatgpt.site/).

## Estado e limite de gastos

O usuário não autorizou gastos e confirmou tornar este repositório público para usar o runner padrão gratuito e iniciar a coleta periódica de rascunhos. A mudança de visibilidade ainda precisa ser confirmada na API do GitHub antes da execução efetiva. O saldo, a franquia e o orçamento do GitHub Actions desta conta não foram confirmados. Por esse motivo, o job contém a condição `github.event.repository.private == false`, avaliada antes da alocação do runner. **Enquanto o repositório estiver privado, uma execução manual, agendada ou um commit em `main` deve apresentar o job como `Skipped`; não haverá testes, coleta, checkout ou execução de runner nesse job.** Um resultado `Skipped` não comprova a execução bem-sucedida dos scripts, mesmo que o GitHub apresente a verificação geral como sucesso.

O gatilho `push` existe somente para validar os arquivos e produzir um rascunho offline após commits em `main`; ele nunca consulta os feeds. Não há gatilho `pull_request`. O cron de coleta está programado, mas continua bloqueado enquanto o repositório for privado. Manter esse bloqueio. A mudança autorizada para público deve ser verificada antes do commit técnico que inicia o primeiro teste efetivo.

Esta variante usa apenas o runner padrão `ubuntu-24.04`, gratuito em repositórios públicos, e registra os JSON nos logs e no resumo do job. **Não usa upload de artefatos, cache de dependências, GitHub Packages, imagens de runner, serviços pagos ou IA paga.** A documentação oficial informa que logs e resumos não entram na franquia de armazenamento de artefatos. Não são acessados ou alterados orçamento, cartão ou plano da conta. O bloqueio de repositório privado e a ausência de armazenamento de artefatos preservam a restrição de não gastar.

## Arquivos necessários

- `.github/workflows/observatory-drafts.yml`: validação offline em commits de `main`, coleta de rascunhos agendada/manual e bloqueio de repositório privado.
- `scripts/automation/validate_observatory.py`: validação estrutural de leitura, sem verificação factual.
- `scripts/automation/collect_headlines.py`: rascunhos separados; consulta apenas quatro feeds EBC permitidos.
- `tests/test_automation.py`: testes offline com fixtures técnicas.
- `worker/observatory-data.json`: snapshot do catálogo editorial da fonte atual do Site.

Não incluir tokens, credenciais, arquivos `.env`, acessos de publicação, caches, ambientes Python, pesos de modelos ou arquivos de investigação privados. Esta é uma integração mínima, não um espelho integral da infraestrutura do Site.

## Primeiro teste e execução manual

Com os arquivos presentes na branch padrão e o repositório confirmado como público, um commit técnico em `main` deve iniciar os testes e a geração do rascunho offline automaticamente. Conferir em **Actions → Observatório - rascunhos de fontes**. Alternativamente, abrir **Run workflow**, selecionar `main` e deixar `collect=false`.

No estado privado atual, confirmar que o job ficou `Skipped`. Uma execução permitida por `push` ou manual com `collect=false` deve executar os testes, validar o catálogo e produzir um rascunho explicitamente offline, vazio e não publicado. `collect=true` consulta as fontes EBC dentro da janela de data e registra um rascunho para revisão humana; não publica manchetes no Site. Na tela da execução, abrir o resumo do job ou a etapa **Registrar JSON nos logs e resumo** para consultar `validation.json` e `observatory-news-draft.json`. Não haverá arquivos disponíveis na seção Artifacts.

## Coleta periódica autorizada

Cron UTC `17 3,7,11,15,19,23 8-25 10 *`: seis tentativas por dia, às **00:17, 04:17, 08:17, 12:17, 16:17 e 20:17 de Brasília**, de 8 a 25 de outubro de 2026. O agendamento opera na branch padrão e pode atrasar ou perder execuções; estar programado não comprova que uma coleta ocorreu. A condição de visibilidade privada bloqueia a execução antes de alocar um runner.

Janela: **08/10/2026 00h até 26/10/2026 00h, horário de Brasília**, com fim exclusivo. O guard precede o checkout e a coleta; o coletor repete esse limite.

O cron não contém ano; o guard impede consultas em 2027 ou depois. Ao encerrar a operação, desativar/remover a receita para evitar novos registros de tentativa. Esta coleta produz somente rascunhos nos logs; a rotina editorial existente do Site continua sendo a responsável por notícias publicadas.

O workflow usa Ubuntu 24.04, Python 3.13, biblioteca padrão, permissões `contents: read`, checkout sem credenciais persistidas e ações oficiais fixadas por SHA completo. Não há secrets de deploy, escrita no Git, comandos de push, PR, mensagens ou comandos de publicação. Os arquivos temporários do runner não são persistidos fora dele; a saída fica somente em logs/resumo, sujeitos à retenção configurada no GitHub. Resumos excessivamente grandes são substituídos por indicação para consultar os JSON completos nos logs.

## Executar no computador do projeto

Na raiz dos arquivos, com Python 3.13 ou posterior:

```powershell
python -m unittest discover -s tests -p test_automation.py -v
python scripts/automation/validate_observatory.py worker/observatory-data.json --report out/validation.json
python scripts/automation/collect_headlines.py --data worker/observatory-data.json --output out/observatory-news-draft.json --offline
```

Origem do snapshot: fonte atual do Site reaberta como versão **40**, commit `ef6c9b29b36c653d5c2b3f44b007e9cf708ee9c6`. Validação local em 08/10/2026: **20 testes offline passaram**; o catálogo teve zero erros estruturais, com avisos preservados. Essa evidência não confirma uma execução no GitHub e não substitui a revisão editorial.

## Referências oficiais

- [Execução manual e branch padrão](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
- [Condições para execução de jobs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions).
- [Uso e cobrança do GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
- [Agendamentos na branch padrão](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

O cron desta receita é de coleta de rascunhos; nenhum novo agendamento de publicação editorial foi instalado. Qualquer etapa futura de publicação deve preservar a rotina editorial do Site e ser tratada separadamente.
