# Fase 7 — evidências de 04/11/2026

## Escopo e preservação

Trabalho sobre a branch `estudos`, HEAD `88160399ce8858aa1dff3d976f0767e3f7595823`, preservando as 52 entradas rastreadas modificadas e 68 não rastreadas encontradas no começo. Nenhum commit, reset, clean, stash ou checkout destrutivo.

Restauração: `D:\Lumen\restauracao\study-fase7-20261104`. O ZIP contém 258 arquivos/42.625.933 bytes de fontes, arquivos novos, ferramentas e executáveis herdados. Manifesto SHA-256 e leitura de cada entrada do ZIP conferidos. ZIP SHA-256: `43d4db99660a5279b45b74d220b0e4b1c7136cfd47333e6daf7cd63f9987fe1f`. Não inclui perfil pessoal, credenciais, caches ou modelos.

O executável inicial, preservado no ZIP, tinha SHA-256 `1A6B0C6353DEFBA22A0C1BC7C91368C37B438A50FBD61E95ADAA8A1F42F53E4D`. Durante o trabalho, outra sessão alterou launcher, visual e executável; o usuário confirmou essa concorrência. Hash observado depois: `1B560E6B0F9145BB928ADF12112784C7219EC07234E7808A8A7355D8D8A83A2F`. Esta sessão não escreveu C# nem recompilou o aplicativo; preservou as mudanças paralelas.

## Entrega implementada

Arquivos novos desta sessão: `lumen/study/artifacts.py`, `lumen/study/pdf.py`, `tests/test_study_pdf.py` e este registro. Ligações pontuais em `agent`, `registry`, `attachments`, `api`, `writes`, `settings`, `data`, `images`, `search`, `server`, `store`, `imagegen`, `cdp`, `charts`, `llm` e na interface dos Estudos. `app.js` e demais arquivos compartilhados mantêm também alterações herdadas/paralelas; não se atribui todo o diff desses arquivos à fase 7.

- `/imagem [quadrada|paisagem|retrato|capa] <descrição>`: gerador local existente, fila `jobs`, liberação da VRAM do Ollama, cancelamento do processo iniciado pela tarefa, arquivo na conversa e aviso “Gerada por IA, pode conter erros”.
- `/pdf [tipo] <assunto>`: `revisao`, `apostila`, `cornell`, `exercicios`, `flashcards`, `plano`, `simulado`, `mapa`, `explicacao`.
- A4 claro por padrão, opção escura, tema pelo `DECOR_SYSTEM`, capa de `cover.py` ou uma ilustração opcional, mapa pelo HTML de `mindmap.py` e explicação existente com diagrama. Imagens comprimidas. Mesmo auxiliar `lumen/cdp.py`, com `Page.printToPDF`.
- Até duas imagens das fontes selecionadas e um gráfico solicitado em apostila, Cornell, plano ou explicação. `charts.validate` confere os valores junto dos rótulos; o quadro estático usa o renderer existente. Valores não sustentados pela fonte não viram desenho. A busca preserva a URL do Notion para as referências.
- Revisão de uma página, até 6 blocos; ajuste limitado a 90% sem ocultar conteúdo. Se ainda não couber, erro explícito. Até 30 páginas por documento. Gabarito em página separada; flashcards com colunas do verso espelhadas para borda longa e tamanho real.
- Arquivos seguem a conversa: persistência, reabertura, exclusão e política de anexos temporários. Produções da IA não entram como fontes. PNG leva procedência, reconhecida também na reimportação e nas imagens das notas.
- Obsidian e Notion pelo fluxo existente de prévia e confirmação. Cofre preserva autoria da IA e referências. Notion exige leitura do bloco persistido e comparação dos bytes; resultado incerto fica `unconfirmed`.
- Botão **Gerar PDF** nas explicações e seção **PDFs e imagens** nas configurações. Interface verificada nas quatro larguras.

## Migração de imagem

24 arquivos, 6.786.395.497 bytes, copiados de `%LOCALAPPDATA%\Lumen\imagem` para `D:\Lumen\imagem`, conferidos individualmente por tamanho e SHA-256. Manifesto: `migracao-imagem.json` na restauração.

O usuário saiu pelo menu; a ausência da instância e do backend foi confirmada antes de alterar somente `image_dir` no JSON pessoal. Demais campos preservados. Corrigido o descarte desse campo por `store.DEFAULTS`; destino efetivo e `imagegen.ready()` conferidos. Geração real usou a cópia do D:. **Origem no C: preservada; nenhuma liberação de espaço no C: é atribuída a essa migração.**

## Testes e comandos

Ambiente: `TEMP`/`TMP` em `D:\Lumen\temp-fase7`, `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`; `tests/__init__.py` cria outro `LUMEN_DATA` dentro desse temporário. Medições fora de `tests` usam `LUMEN_DATA` próprio e verificam `store.DATA` e `db.MEDIA` efetivos. Voice Studio falso nos testes; microfone simulado.

Evidências em `D:\Lumen\validacao-fase7-20261104`:

| Comando/verificação | Resultado |
|---|---|
| `.venv\Scripts\python.exe -m unittest tests.test_study_pdf -v` | **13 testes passaram em 176,851 s** (`fase7-final.log`), mais o teste de imagens/gráficos (`grafico-final.log`) e o de URL do Notion (`fontes-final.log`): **15 novos testes exercitados**. A rodada de fontes/índice passou 9 testes. |
| `.venv\Scripts\python.exe -m unittest discover -s tests -t . -v` | **764 testes passaram em 1.441,940 s**; log `suite-final.log`, saída 0. As últimas correções tiveram regressões focadas posteriores. A primeira execução não produziu resumo final e não é contada como aprovada. |
| `py -3.14 tests/study_ui.py` | **Passou, 28 verificações**. Inclui `/imagem`, PDF real, download, reabertura, botão da explicação e configurações em 1440, 1100, 760 e 520 px; sem erro de página/CSP. Log `ui-final-2.log`. Uma repetição anterior expirou na navegação inicial; a espera foi ajustada para DOM carregado com até 60 s. |
| `py_compile` dos módulos novos/alterados e `node --check` dos scripts da interface | Passaram nos comandos executados. |
| Extração de texto, links, páginas e recursos de fontes pelo `pypdf` | Nove tipos produzidos com Ollama falso e Edge real; A4, texto e links conferidos. Gabarito separado e espelhamento dos cartões conferidos. |
| Renderização dos PDFs e inspeção visual | `pypdfium2` 5.14.0, já instalado no Python 3.14. Cada página das amostras foi renderizada. Corrigidos o grid do Cornell, a página inicial dos flashcards e o mapa pequeno; páginas corrigidas reinspecionadas. |

Falhas encontradas e corrigidas durante a implementação: campo de configuração descartado; cancelamento da difusão ausente; trava reentrante indevida na gravação temporária; corrida na leitura de `DevToolsActivePort`; CSS Cornell aplicado ao corpo; alinhamento duplex; trechos de estrutura usados como material; revisão ultrapassando uma página. Os testes novos cobrem os caminhos correspondentes.

## Medições reais locais

- **Imagem:** Z-Image-Turbo existente, 1152×768, **148,27 s**, 927.459 bytes, nenhuma fonte. `real\imagem-real.png` e `real\medicao.json`. SHA-256 `3df7bb41cf34ac73f60b1d25bc774621ba6fcfbffe967141968e30fdcf7dabec`.
- **PDF do cofre:** nota de 20.463 bytes sobre criação de motion graphics, lida sem alteração (SHA-256 antes/depois `ff4747fe45b9c2d95c8644bc3509d8f2c83143c2b7effc8f9ae9900947c3cb3f`). Automático dos Estudos, uma instância separada do Ollama em `127.0.0.1:11435`, sem parar ou reconfigurar o Ollama pessoal. **83,79 s, uma página, seis blocos com `S1`**. Arquivo final em `real-conferido\revisao-real.pdf`; relatório em `real-conferido\medicao.json`. O layout teve uma reimpressão sem IA para tornar visível uma abreviação no resumo.
- As primeiras tentativas revelaram um problema real: a busca acertava a nota, mas retornava apenas títulos como “Minhas anotações”. O documento saía como conhecimento geral. `pdf.material` passou a usar a ferramenta `read_document`, limitada a 12 mil caracteres por nota e pelo orçamento da tarefa. A repetição foi motivada por esse defeito e, depois, pela paginação; a imagem não foi repetida.
- O primeiro ensaio escolheu por engano uma nota do espelho do Notion e foi descartado. As medições válidas acima usam a nota original em `B02 Estudos`; não se atribui a esse ensaio uma validação do cofre.
- Os servidores Ollama dessas medições foram encerrados pela própria sessão, depois de liberar apenas seus modelos. Nenhum serviço ou modelo do Voice Studio foi descarregado, reiniciado ou modificado.

## Limites e verificações humanas

Testes com serviços falsos, geração local real, API local do Ollama, navegador de teste e janela nativa são evidências distintas. **Não foi feita publicação real no Notion, nem validada a janela nativa WebView2 nesta sessão.** O teste do Notion usa servidor falso, incluindo leitura persistida e erro de confirmação.

Imagens novas por difusão ficam restritas a `/imagem` e à capa opcional. Apostila, Cornell, plano e explicação podem reutilizar até duas imagens das fontes selecionadas. Pedidos explícitos de gráfico/tabela/números/função nesses formatos usam `charts.validate` e um quadro estático de `charts.py`; até um gráfico, sem aceitar valores não conferidos. Não há seleção livre de imagens de toda a biblioteca. Revisão de uma página, cartões e exercícios mantêm seus layouts próprios. A impressão física duplex depende do driver/impressora do usuário.

Permanecem os testes humanos da fase 6: chamada real por dois minutos, fone/caixa, interrupção, mapa mental e abrir/fechar Voice Studio. A escuta cega é opcional; a chave não foi lida e o padrão de oito passos não foi ativado.

Nenhuma dependência ou motor foi instalado. Nenhuma memória global foi atualizada. A direção de segundo cérebro foi registrada no README, STATUS/decisões e continuidade do projeto.

## Limpeza e encerramento

Processos de teste encerrados e porta 11435 sem servidor. Logs, amostras e restauração foram preservados. **Limpeza de seis pastas temporárias/bancos isolados pendente:** a revisão automática rejeitou a exclusão, inclusive a tentativa com caminho literal previamente conferido; a única razão retornada foi `blocked by policy`. Nenhuma tentativa de contornar esse bloqueio foi feita.

Restaram aproximadamente **26 MB**: `D:\Lumen\temp-fase7` e as subpastas `data` dos ensaios `real`, `real-cofre`, `real-cofre-final`, `real-final-lido` e `real-conferido`, dentro de `D:\Lumen\validacao-fase7-20261104`. Lista de arquivos/tamanhos em `limpeza-pendente.json`; resultados consolidados em `verificacao-final.json`. Não apagar a restauração, os modelos ou a origem das imagens ao tratar essa pendência.

## Próximo passo exato

As verificações automatizadas e as medições desta tabela estão concluídas. Agora, sair normalmente do Lúmen e reabrir para carregar os módulos novos; testar os dois comandos e **Gerar PDF** na janela nativa. Para validar envio real, usar a prévia e conferir o arquivo persistido no destino escolhido. Se a conferência humana encontrar algo, os pontos são `lumen/study/pdf.py::make/html`, `lumen/study/artifacts.py::run/save` e o passo 13 de `tests/study_ui.py`. Gráficos e imagens originais já estão integrados; manter os testes de dados inválidos e procedência. A próxima fase de implementação é a 8, a definir na próxima sessão.
