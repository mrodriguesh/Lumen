# Auditoria: a IA Claude que já existe no Obsidian

Data: 31/10/2026. A auditoria só leu o cofre, que fica em `D:\downloads\cerebro\Cerebro Oficial`. Nenhum arquivo dele foi alterado.

## O que é

Não é um plugin do Obsidian, não é um servidor MCP e não é um cliente de API. É o **Claude Code aberto na raiz do cofre**, que se apoia em:

| Peça | Onde | Para que serve |
|---|---|---|
| Constituição | `CLAUDE.md` | Define 4 ambientes (as notas do usuário, a área da IA em `C04 Claude Obsidian/`, o fluxo entre os dois e `B02 Estudos`, que é do Lúmen). Também traz as regras: autoria, notas permanentes, sugestões em vez de editar, "não inventar", citar `[[Nota]]` e só gravar fora de C04 com pedido explícito. |
| Permissões | `.claude/settings.json` | `allow` permite editar em `C04 Claude Obsidian/**`. `ask` pede confirmação nas áreas do usuário (A00–A05, B01, B03–B05, C02, C03, C05, `Home.md`, `CLAUDE.md`, `.obsidian/**`). |
| Proteção do shell | `.claude/hooks/protege-areas.mjs` | Pede confirmação para comandos de shell que escrevem em área protegida. |
| Skills | `.claude/skills/*` (9) | `buscar-cerebro`, `processar-inbox`, `analisar-livro`, `detectar-duplicacao`, `sugerir-links`, `revisar-projeto`, `criar-briefing`, `analisar-lacunas`, `revisao-semanal`. |
| Agentes | `.claude/agents/*` (3) | `knowledge-librarian` (busca, só leitura), `research-assistant` (pesquisa externa) e `archive-curator` (saúde do cofre). |
| Memória | `C04 Claude Obsidian/04 Memory/*.md` | Current Context, Long Term Context, Preferences, Lessons Learned, Open Loops. São notas curtas e revisáveis. |
| Registros e decisões | `05 Logs/`, `11 Decisions/Decision Log.md` | Histórico mensal e decisões. |
| Modelo de entrega | `09 Templates/Template - Output IA.md` | Formato de toda entrega da IA (`type: ai-output`, `status: review-required`). |

### Autenticação

O Claude Code entra pela conta do usuário no próprio Claude Code. Essa sessão **não é** uma credencial da API da Anthropic. Por isso o Lúmen não a usa nem tenta usar: o Lúmen pede uma chave de API própria, que fica guardada no Gerenciador de Credenciais do Windows.

### O que não existe no sistema atual

- cliente de API;
- streaming próprio;
- índice de busca: o Claude Code pesquisa com as ferramentas dele, como grep e leitura de arquivos;
- vetores;
- MCP;
- plugin.

## Decisão por componente

| Componente | Classe | Decisão |
|---|---|---|
| Regras de autoria, "cite só o que abriu" e "nunca invente" | **A. Reaproveitar integralmente** | Viraram regras do prompt do LUMEN (`agent.SYSTEM`). Além disso, toda citação `[S#]` é conferida no código e as inválidas são removidas. |
| Formato de resposta de `buscar-cerebro` (o que você escreveu / fontes / projetos / tensões / lacunas) | **A** | Mesma estrutura nas respostas: "Nas suas fontes", "Síntese do Lumen", "Contexto geral", "O que não encontrei" e "Próximos passos". A autoria do usuário é separada da autoria da IA pelo campo `author`/`type` das notas. |
| Mapa de áreas `ask` do `.claude/settings.json` | **A** | `writes.py` lê esse mapa e avisa na prévia quando a pasta de destino é área protegida. |
| `Template - Output IA` e a pasta `01 Outputs` | **A** | As notas criadas pelo Lúmen seguem o modelo, com `author: lumen-ai`. A pasta padrão é `C04 Claude Obsidian/01 Outputs` (decisão do usuário). |
| Memória em notas (`04 Memory`) | **B. Reaproveitar parcialmente** | Importação com prévia para a memória do Lúmen: cada linha de lista vira uma memória com a origem registrada. Não há sincronização, porque o cofre continua sendo a memória do Claude Code e o Lúmen não escreve lá. |
| Skills `sugerir-links`, `detectar-duplicacao`, `analisar-lacunas`, `revisao-semanal`/`criar-briefing` | **C. Refatorar e integrar** | Viraram, respectivamente, conexões por link e mapa de conhecimento, checagem de títulos parecidos antes de salvar, o modo "O que falta estudar" e o modo "Plano de estudos". |
| Agente `knowledge-librarian` | **C** | Virou a ferramenta `search_knowledge` (só leitura), igual para qualquer provedor. |
| Runtime do Claude Code e a autenticação dele | **D. Substituir** | O Lúmen tem a própria camada de provedores: Ollama local e Claude pela API oficial (SDK `anthropic`), com a chave do usuário. |
| O Claude Code no cofre | **E. Manter como alternativa independente** | Continua funcionando como está. O Lúmen respeita `type:`/`author:`, as áreas protegidas e o modelo de saída, para os dois conviverem. |

## Por quê

- Não havia código de integração para reaproveitar. O valor do sistema existente está nas regras, nos formatos e nos roteiros (skills), e esses foram aproveitados.
- Reusar a sessão do Claude Code como credencial de API não é suportado oficialmente e misturaria credenciais. O caminho suportado é uma chave de API.
- O cofre segue sendo a fonte de verdade das regras. Se o `.claude/settings.json` mudar, o aviso de área protegida no Lúmen acompanha, porque é lido na hora da prévia.
