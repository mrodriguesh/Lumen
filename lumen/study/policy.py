"""Política de custo e privacidade das IAs do Lúmen — a ÚNICA que decide o que pode sair do PC (revisada em 09/11/2026).

Regra do operador: nada que possa cobrar. Por isso a política é uma lista de permissões, não de proibições: só entra o que
roda no PC; tudo o que é externo, desconhecido ou de preço incerto fica bloqueado.

- Local (Ollama): sempre liberado. Roda no PC, sem cota de API (o limite é o hardware e a janela de contexto).
- Google Gemini: RETIRADO do Lúmen em 09/11/2026 (decisão do estudante: seguir só com IA local). Não há provedor, modelo,
  chave, tela nem rota dele; "google" e "gemini" são IDs removidos e uma configuração antiga com eles volta ao local.
- Claude (Anthropic) e OpenAI: API cobrada por token, sem plano gratuito de API comprovado em fonte oficial: bloqueados.
- Imagem, vídeo, voz, transcrição, embeddings, busca e armazenamento em nuvem: bloqueados. Ficam o gerador de imagens
  local, a pesquisa guiada no Edge e os motores de voz e de embeddings locais.

Todo caminho que poderia falar com um serviço externo (chat, JSON, alternativo, imagem, vídeo, listagem de modelos) chama
`authorize()` ANTES de qualquer requisição. Configurações antigas passam por `normalize()` ao serem lidas."""
from .. import AppError

REVIEWED = "2026-11-09"

LOCAL = "ollama"
PROVIDERS = (LOCAL,)                    # a única IA que o Lúmen usa: nada sai do PC
BLOCKED_PROVIDERS = {
    "anthropic": "O Claude (API da Anthropic) é cobrado por token e não há plano gratuito de API comprovado em fonte oficial.",
    "openai": "A API da OpenAI é cobrada por token e não há plano gratuito de API comprovado em fonte oficial.",
}
# IDs que já foram provedores e não existem mais. Ficam aqui só para a recusa dizer o motivo (e para os testes provarem que
# um ajuste, um pedido ou uma conversa antiga com eles não reativa nada).
REMOVED_PROVIDERS = {
    "google": "A integração com o Gemini foi retirada do Lúmen: o Lúmen usa só a IA local (Ollama).",
    "gemini": "A integração com o Gemini foi retirada do Lúmen: o Lúmen usa só a IA local (Ollama).",
}
ACTION = "Use a IA local (Ollama) em Estudos → Configurações → Modelos."

FEATURES = {
    "image": "Imagens em nuvem estão bloqueadas. Use o gerador de imagens local.",
    "video": "Vídeo em nuvem está bloqueado: o Lúmen não gera vídeo.",
    "web_search": "A busca hospedada por provedor de IA está bloqueada. Use a pesquisa guiada no Edge.",
    "tts": "Voz em nuvem está bloqueada. O Lúmen usa as vozes locais.",
    "asr": "Transcrição em nuvem está bloqueada. O Lúmen usa a transcrição local.",
    "embeddings": "Embeddings em nuvem estão bloqueados: as notas não saem do PC para indexação.",
    "storage": "Armazenamento remoto (arquivos, cache de contexto) está bloqueado: nada é enviado para guarda.",
}


def blocked_message(provider):
    return BLOCKED_PROVIDERS[provider] + " Ele está bloqueado no Lúmen."


class Blocked(AppError):
    """A chamada foi recusada pela política ANTES de qualquer requisição. `code` identifica o motivo para a tela e os testes."""

    def __init__(self, code, message, action=""):
        super().__init__(message, action)
        self.code = code


def authorize(s, provider, model="", feature="chat"):
    """Levanta Blocked se a chamada sairia do PC (e portanto poderia custar dinheiro). Chamada ANTES de qualquer requisição
    externa; só o local passa. `s` e `model` ficam na assinatura dos chamadores; a decisão não depende deles."""
    if provider == LOCAL:
        return
    if provider in BLOCKED_PROVIDERS:
        raise Blocked("paid_provider", blocked_message(provider), ACTION)
    if feature != "chat" and feature in FEATURES:
        raise Blocked("paid_feature", FEATURES[feature], ACTION)
    if provider in REMOVED_PROVIDERS:
        raise Blocked("removed_provider", REMOVED_PROVIDERS[provider], ACTION)
    raise Blocked("unknown_provider", "Provedor de IA desconhecido: o Lúmen só usa a IA local.", ACTION)


def normalize(s):
    """Neutraliza, no dicionário de ajustes `s`, qualquer escolha antiga que apontaria para fora do PC. Devolve a lista do que
    mudou (provedores e modelos, nunca segredos). Não apaga histórico, memórias nem o modelo local escolhido."""
    m, changes = s["models"], []

    def put(key, value):
        if m[key] != value:
            changes.append(f"models.{key}: {m[key]!r} → {value!r}")
            m[key] = value

    if m["provider"] not in PROVIDERS:
        put("provider", LOCAL)
    if m["fallback"] not in ("none",) + PROVIDERS:
        put("fallback", "none")
    for key in ("anthropic", "openai", "image_openai", "video_model"):
        put(key, "")
    put("image_provider", "local")
    put("video_provider", "none")
    return changes
