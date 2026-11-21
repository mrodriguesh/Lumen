"""Lúmen Study AI: assistente de estudos sobre o Notion e o Obsidian do usuário.

Camadas (cada uma num módulo):
- db: o banco local (SQLite com FTS5) onde ficam índice, conversas, memórias e atividades;
- settings: ajustes e o único segredo (a chave da Anthropic, no keyring);
- sources/*: conectores que leem o conhecimento (Obsidian direto do disco, Notion pela API, pastas autorizadas, web);
- index: divide em trechos, indexa (palavras e vetores) e sincroniza em segundo plano;
- search: entende a pergunta e busca (BM25 + semântica, combinadas por RRF);
- providers: modelos de IA (Ollama local e, se o usuário permitir, Claude) atrás de uma interface só;
- tools, agent: ferramentas com nível de permissão e o orquestrador que responde com fontes verificáveis;
- memory, chats, learn, writes, data: memória, conversas e projetos, modos de estudo, gravação com prévia e dados.

Nada aqui grava em notas ou páginas do usuário sem prévia e confirmação (writes.py)."""
