"""Conectores de conhecimento. Todos seguem a mesma interface, para entrar outra fonte no futuro sem mexer na busca:

- status(): {"connected": bool, "label": str, "message": str, ...} sem rede quando possível;
- test(): confere de verdade a conexão (lê algo real) e devolve o mesmo formato, com o resultado;
- versions(check): {source_id: (versão, info)} de TODOS os documentos atuais. Se a enumeração não terminar, lança erro
  (o índice então não apaga nada: um documento só sai do índice depois de uma enumeração completa);
- load(source_id, info, check): o Doc com o conteúdo, ou None se o documento deve ficar de fora;
- read(source_id): o texto original agora (leitura ao vivo, para a IA abrir o documento inteiro);
- open(doc): abre o original no aplicativo dele (Notion no navegador, Obsidian por obsidian://open, arquivo local).

Os conectores só leem. Gravar é com writes.py, sempre com prévia e confirmação."""
from dataclasses import dataclass, field


@dataclass
class Doc:
    source: str
    source_id: str
    title: str
    text: str
    path: str = ""
    url: str = ""
    kind: str = "note"
    author: str = ""          # user | ai | lumen | "" (desconhecido)
    tags: list = field(default_factory=list)
    links: list = field(default_factory=list)
    updated: str = ""
    version: str = ""
    meta: dict = field(default_factory=dict)


def registry():
    from . import files, notion, obsidian
    return {"obsidian": obsidian.Obsidian(), "notion": notion.Notion(), "files": files.Files()}


def get(name):
    src = registry().get(name)
    if src is None:
        from ... import AppError
        raise AppError("Fonte desconhecida.")
    return src
