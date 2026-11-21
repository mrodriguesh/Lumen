# Recuperar a Proteção do cérebro sem o Lúmen

Você precisa do backup, da chave exportada separadamente e do Restic oficial: https://restic.net. O Lúmen usa Restic 0.19.1. Python 3.11 ou posterior permite usar o utilitário independente fornecido.

## Se o backup está no Google Drive

1. Baixe o catálogo `snapshot-ORIGEM-ID.json`, os arquivos `object-HASH.bin`, este guia e `recuperar-drive.py` da pasta privada do Lúmen. O catálogo lista exatamente quais objetos são necessários. O download pode ser feito pelo site do Drive em outro computador; não requer credenciais da instalação original.
2. Extraia o download do Drive para uma pasta separada. Não execute arquivos de notas ou plugins.
3. Monte o repositório (o último caminho deve ser novo):

```text
python recuperar-drive.py snapshot-ORIGEM-ID.json PASTA_DOS_OBJETOS NOVO_REPOSITORIO
```

O utilitário confere caminhos, tamanho e SHA-256 antes de montar os arquivos. Se faltar um objeto ou houver corrupção, ele recusa a montagem. Nunca busca dados nas origens ou no cache do Lúmen.

## Verificar e recuperar

Use a pasta `repository` do backup local ou `NOVO_REPOSITORIO` montado acima:

```text
restic -r NOVO_REPOSITORIO check --read-data
restic -r NOVO_REPOSITORIO snapshots
restic -r NOVO_REPOSITORIO restore ID --target PASTA_NOVA
```

Restic pedirá a senha sem mostrá-la. A chave exportada pelo Lúmen é um JSON: use apenas o valor do campo `password` nesse prompt. Não passe a senha na linha de comando, não publique o JSON e não guarde a chave junto do backup. O identificador `set_id` ajuda a reconhecer o conjunto.

`obsidian/files` contém os bytes originais. `notion` contém Markdown, JSON estruturado e anexos locais. Cada `manifest.json` apresenta hashes, janela de captura, exclusões e pendências. Um snapshot pode ser recuperável e ainda ter cobertura parcial; confira o manifesto. O Notion não oferece uma transação global nem expõe todos os recursos do workspace pela API.

No cofre Obsidian, a cópia para navegar fica em `Lumen - Backup do Notion/Particular`, seguindo os títulos e as subpáginas conhecidas. `Anexos` guarda os arquivos e `Dados originais` guarda os dados estruturados. Essa organização não modifica os arquivos originais dos snapshots: a captura recuperada continua identificada pelos IDs e preserva os vínculos entre páginas no manifesto. `Estrutura a conferir` indica um ancestral sem acesso ou um vínculo que precisa de conferência. Notas editadas na cópia são preservadas e apresentadas como pendência.

Para comparar os arquivos de um item, calcule SHA-256 e compare com o manifesto. No Windows, `Get-FileHash -Algorithm SHA256 CAMINHO` faz essa leitura. O Lúmen também oferece Recuperar e faz a comparação automaticamente.

Abra primeiro as notas e anexos isolados. Não habilite plugins do `.obsidian` nem execute scripts restaurados automaticamente. Preserve o estado atual antes de substituir originais. Para reconstruir páginas suportadas, importe a chave no Lúmen, recupere o snapshot e use “Reconstruir em nova área do Notion”. O JSON offline continua sendo a referência para propriedades e recursos sem equivalência.

## Política efetiva

Todas as versões são mantidas, sem limpeza automática. Nenhum snapshot é removido para liberar espaço. O destino sem espaço fica pendente; as últimas versões válidas permanecem disponíveis. Monitore o espaço exibido nos Ajustes. Uma cópia no mesmo disco físico protege contra alterações/exclusões, mas não contra a falha desse disco.
