"""Provedores de IA atrás de uma interface só, para o orquestrador e as ferramentas não dependerem do modelo.

- Ollama (local, padrão): reaproveita o cliente de lumen/llm.py (streaming, cancelamento, erros em português).
- Claude (Anthropic) e OpenAI: BLOQUEADOS (cobrados por token, sem plano gratuito comprovado). As classes existem só para o
  status e o catálogo dizerem isso; toda chamada levanta `policy.Blocked` antes de qualquer requisição.
- Nenhuma outra IA em nuvem: o Gemini foi retirado do Lúmen (09/11/2026) e não há adaptador, modelo, chave nem rota dele.
  Quem decide é `policy.authorize`, a única lista; ela vale para o chat, o JSON e o alternativo.

Mensagens (formato interno, neutro):
  {"role": "user"|"assistant", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "input"}], "raw": <conteúdo do provedor>}
  {"role": "tool", "results": [{"id", "name", "content", "is_error"}]}

stream() gera eventos: {"type": "text", "text"} | {"type": "replace", "text"} | {"type": "status", "stage"} e, por
último, {"type": "done", "turn": {"text", "tool_calls", "stop", "raw", "model", "provider", "web": [...]}}."""
import json
import urllib.error
import urllib.request

from .. import AppError, llm
from . import policy, settings

# Modelos de embeddings que pedem instrução na pergunta (e não no documento).
QUERY_PREFIX = {"qwen3-embedding": "Instruct: Given a study question, retrieve note passages that answer it\nQuery: "}


class Truncated(AppError):
    """A resposta JSON parou no teto de tokens antes de terminar (laço ou excesso de itens): quem chamou decide se
    tenta de novo, mais enxuto."""

    def __init__(self):
        super().__init__("A IA chegou ao limite de tamanho da resposta antes de terminar.",
                         "Tente um pedido mais estreito.")


# --- Embeddings (Ollama) -----------------------------------------------------------------------------------------

def _installed(model, names):
    return names is not None and (model in names or f"{model}:latest" in names or
                                  (model.endswith(":latest") and model[:-7] in names))


def embed_ready(model):
    return bool(model) and _installed(model, llm.models())


KEEP_ALIVE = "10m"  # sobe para "30m" enquanto uma chamada de voz está aberta (4.3.6)


def embed(texts, model, query=False):
    if query:
        prefix = next((p for k, p in QUERY_PREFIX.items() if model.startswith(k)), "")
        texts = [prefix + t for t in texts]
    body = json.dumps({"model": model, "input": texts, "truncate": True, "keep_alive": KEEP_ALIVE}).encode()
    req = urllib.request.Request(llm.OLLAMA + "/api/embed", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AppError(f"O modelo de embeddings “{model}” não está instalado.",
                           "Baixe o modelo em Estudos → Configurações → Modelos.") from None
        raise AppError(f"O Ollama recusou o pedido de embeddings (HTTP {e.code}).") from None
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raise AppError("O Ollama não está rodando.", "Abra o aplicativo Ollama e tente de novo.") from None
    vectors = data.get("embeddings") or []
    if len(vectors) != len(texts):
        raise AppError("O Ollama devolveu embeddings incompletos.")
    return vectors


# --- Ollama -----------------------------------------------------------------------------------------------------

# Um num_ctx só em todas as chamadas dos Estudos: o Ollama recarrega o modelo quando ele muda de um pedido para outro.
# 16k cabe pergunta, material (context_chars padrão), histórico, ferramentas e resposta, e deixa o modelo inteiro na
# GPU; medido na fase 2 do Study AI 2.0 (docs/implementation/LUMEN_STUDY_AI_MODELS.md).
CTX = 16384
# A família qwen3.5 usa atenção híbrida: o cache do contexto quase não cresce (medido na fase 2: +0,5 GB de 16k para 32k,
# mesma velocidade). Com 16k, uma conversa real compactava a cada turno a partir do 4º (fase 3); com 32k, só as longas.
WIDE = ("qwen3.5",)


def family(model):
    """O nome do modelo sem o dono, em minúsculas: "huihui_ai/qwen3.5-abliterated:9b" → "qwen3.5-abliterated:9b". Quem
    reconhece uma família pelo prefixo do nome deve usar isto, senão as variantes publicadas por terceiros (namespace do
    Ollama ou hf.co/dono/…) caem fora da família mesmo sendo a mesma arquitetura."""
    return str(model or "").lower().rsplit("/", 1)[-1]


def window(model):
    """A janela de contexto que os Estudos usam com este modelo do Ollama."""
    return 2 * CTX if family(model).startswith(WIDE) else CTX


def num_ctx(chars, max_tokens, base=CTX):
    """A janela do modelo; o dobro só para um pedido que não cabe (material acima do padrão nas Configurações). Conta
    3 caracteres por token, o menor valor medido em português (3,0 a 3,7), para errar para mais."""
    return base if chars / 3 + max_tokens <= base else 2 * base


class Ollama:
    name, label, external = "ollama", "IA local (Ollama)", False

    def __init__(self, s=None, adult=False):
        """adult=True: o perfil adulto (D92). O modelo e a temperatura vêm da seção própria, e este objeto carrega a
        decisão da resposta inteira (entender, ferramentas, revisão, título): nada nele volta ao modelo principal."""
        self.s = s or settings.load()
        self.adult = adult
        self.model = settings.adult_model(self.s) if adult else settings.local_model(self.s)
        self.temperature = self.s["adult" if adult else "models"]["temperature"]
        self.fast = None  # o modelo das etapas curtas em JSON (entender, título, memória); None = o rápido dos ajustes

    def pin(self, model):
        """Fixa UM modelo local para a resposta inteira (Conversa rápida): resposta, entender a pergunta, título, memória e as
        demais etapas usam o mesmo, e nenhum outro é carregado no HD. Não muda nenhum ajuste."""
        if model:
            self.model = self.fast = model
        return self

    @property
    def window(self):
        return window(self.model)

    def ready(self):
        names = llm.models()
        if names is None:
            return False, "O Ollama não está rodando. Abra o aplicativo Ollama."
        if not _installed(self.model, names):
            return False, f"O modelo “{self.model}” não está instalado no Ollama."
        return True, ""

    @staticmethod
    def _messages(system, messages):
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "tool":
                for r in m["results"]:
                    out.append({"role": "tool", "content": r["content"], "tool_name": r["name"], "name": r["name"]})
            elif m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content", ""),
                            "tool_calls": [{"function": {"name": c["name"], "arguments": c["input"]}} for c in m["tool_calls"]]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def stream(self, system, messages, tools=None, check=lambda: None, max_tokens=4096, effort="medium", web=False,
               model=None, allow_external=True, think=False):
        """think (níveis Profundo e Máximo): o modelo raciocina antes; o raciocínio não vai para a resposta, e a tela só
        mostra a etapa "pensando"."""
        model = model or self.model
        body = {"model": model, "stream": True, "think": bool(think), "keep_alive": KEEP_ALIVE,
                "options": {"temperature": self.temperature, "num_predict": max_tokens},
                "messages": self._messages(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                "parameters": t["input_schema"]}} for t in tools]
        chars = sum(len(m.get("content") or "") for m in body["messages"]) + len(json.dumps(body.get("tools", "")))
        body["options"]["num_ctx"] = num_ctx(chars, max_tokens, window(model))
        try:
            yield from self._read(body, model, check)
        except AppError as e:
            if not think or "support thinking" not in str(e):
                raise
            body["think"] = False  # modelo sem raciocínio (o Ollama recusa antes de carregar): responde sem ele
            yield from self._read(body, model, check)

    def _read(self, body, model, check):
        text, calls, stop, usage = [], [], "end", {"input": 0, "output": 0, "limit": body["options"]["num_ctx"]}
        thinking = False
        for d in llm._stream("/api/chat", body, check, timeout=900):
            msg = d.get("message") or {}
            if msg.get("thinking") and not thinking:
                thinking = True
                yield {"type": "status", "stage": "thinking"}
            if msg.get("content"):
                text.append(msg["content"])
                yield {"type": "text", "text": msg["content"]}
            for i, call in enumerate(msg.get("tool_calls") or []):
                fn = call.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = None
                calls.append({"id": f"call_{len(calls)}_{i}", "name": fn.get("name", ""), "input": args})
            if d.get("done"):
                stop = "max_tokens" if d.get("done_reason") == "length" else "end"
                usage.update(input=d.get("prompt_eval_count") or 0, output=d.get("eval_count") or 0)
        if calls:
            stop = "tool_use"
        yield {"type": "done", "turn": {"text": "".join(text), "tool_calls": calls, "stop": stop, "raw": None,
                                        "model": model, "provider": self.name, "web": [], "usage": usage}}

    def json(self, system, user, schema, check=lambda: None, max_tokens=4096, model=None, allow_external=True, temperature=0.2):
        cut = []
        model = model or (self.model if self.adult else self.fast or settings.fast_model(self.s))
        out = llm._chat(model, system, user, check, lambda n: None, schema=schema,
                        num_ctx=num_ctx(len(system) + len(user) + len(json.dumps(schema)), max_tokens, window(model)),
                        temperature=temperature, keep_alive=KEEP_ALIVE, limit=max_tokens, on_cut=lambda: cut.append(1))
        if cut:
            raise Truncated()
        try:
            return json.loads(out)
        except ValueError:
            raise AppError("A IA devolveu uma resposta fora do formato.", "Tente de novo.") from None


def warm_local(s=None, keep_alive="30m"):
    """Carrega (ou mantém carregado) o modelo local dos Estudos com a mesma janela `num_ctx` usada nas respostas (D24),
    evitando recarga no primeiro turno de uma chamada de voz."""
    s = s or settings.load()
    model = settings.local_model(s)
    if not model:
        return False
    body = json.dumps({"model": model, "messages": [], "stream": False, "keep_alive": keep_alive,
                       "options": {"num_ctx": window(model)}}).encode()
    req = urllib.request.Request(llm.OLLAMA + "/api/chat", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            r.read()
        return True
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


# --- Anthropic / Claude ------------------------------------------------------------------------------------------

CLAUDE_WINDOW = 200_000  # a janela mínima dos modelos atuais (mostrada no catálogo)


class Anthropic:
    """Bloqueado pela política (cobrado por token, sem plano gratuito comprovado): existe só para o catálogo e o status
    dizerem isso. Nenhum método faz requisição: todo uso termina em `Blocked`, antes de qualquer rede. (O cliente do SDK
    da Anthropic que ficava aqui era inalcançável e saiu junto com a dependência em 21/11/2026.)"""
    name, label, external, window = "anthropic", "Claude (Anthropic)", True, CLAUDE_WINDOW

    def __init__(self, s=None):
        self.s = s or settings.load()
        self.model = self.s["models"]["anthropic"]

    def ready(self):
        return False, policy.blocked_message(self.name)

    def _guard(self, allow_external=True):
        policy.authorize(settings.load(), self.name)  # levanta Blocked: nenhum cliente é criado, nenhuma requisição sai
        raise policy.Blocked("paid_provider", policy.blocked_message(self.name))

    @staticmethod
    def models(key=None):
        policy.authorize(settings.load(), "anthropic")

    def stream(self, *args, **kwargs):
        self._guard(kwargs.get("allow_external", True))
        yield {}  # nunca alcançado: faz desta função um gerador, como a dos outros provedores

    def json(self, *args, **kwargs):
        self._guard(kwargs.get("allow_external", True))


class OpenAI:
    """Bloqueado pela política (cobrado por token, sem plano gratuito comprovado): existe só para o catálogo e o status
    dizerem isso. Nenhum método faz requisição: todo uso termina em `Blocked`, antes de qualquer rede."""
    name, label, external, window = "openai", "OpenAI", True, 128_000

    def __init__(self, s=None):
        self.s = s or settings.load()
        self.model = ""

    def ready(self):
        return False, policy.blocked_message(self.name)

    def _guard(self, allow_external=True, feature="chat"):
        policy.authorize(self.s, self.name, self.model, feature)
        raise policy.Blocked("paid_provider", policy.blocked_message(self.name))

    def models(self, key=None):
        self._guard()

    def stream(self, *args, **kwargs):
        self._guard(kwargs.get("allow_external", True))
        yield {}  # nunca alcançado: faz desta função um gerador, como a dos outros provedores

    def json(self, *args, **kwargs):
        self._guard(kwargs.get("allow_external", True))


# --- Escolha ------------------------------------------------------------------------------------------------------

def get(name, s=None):
    classes = {"ollama": Ollama, "anthropic": Anthropic, "openai": OpenAI}
    if name not in classes:
        policy.authorize(s or settings.load(), name)  # Blocked: removido (google/gemini) ou desconhecido
    return classes[name](s)  # Claude/OpenAI existem só para o status: ready() é sempre False e toda chamada levanta Blocked


def chain(s=None, model=None):
    """[principal, alternativo] que podem atender agora. Só entra o que a política libera (a IA local); um ajuste que
    aponte para outra coisa vira recusa explicada e a resposta vem da IA local. Nunca troca sozinha para um serviço pago:
    eles nunca ficam prontos. model: fixa esse modelo local no(s) provedor(es) local(is) (Conversa rápida)."""
    s = s or settings.load()
    order = [s["models"]["provider"]]
    if s["models"]["fallback"] not in ("none", order[0]):
        order.append(s["models"]["fallback"])
    out, reasons = [], []
    for name in order:
        try:
            p = get(name, s)
        except policy.Blocked as e:
            reasons.append(str(e))
            continue
        if model and isinstance(p, Ollama):
            p.pin(model)
        ok, why = p.ready()
        (out if ok else reasons).append(p if ok else f"{p.label}: {why}")
    if not out and "ollama" not in order:
        p = Ollama(s).pin(model)
        ok, why = p.ready()
        if ok:
            out.append(p)
        else:
            reasons.append(f"{p.label}: {why}")
    return out, reasons


def status(s=None):
    s = s or settings.load()
    names = llm.models()
    local, adult = settings.local_model(s), settings.adult_model(s)
    return {"ollama": {"running": names is not None, "model": local, "installed": _installed(local, names),
                       "embed": s["models"]["embed"], "embed_installed": _installed(s["models"]["embed"], names),
                       "models": sorted(n for n in names or [] if "embed" not in n.lower())},  # só modelos de chat nas listas
            "adult": {"enabled": s["adult"]["enabled"], "mode": s["adult"]["mode"], "model": adult,
                      "installed": bool(adult) and _installed(adult, names), "running": names is not None},
            "anthropic": {"has_key": bool(settings.api_key("anthropic")), "model": "", "ready": False,
                          "blocked": policy.BLOCKED_PROVIDERS["anthropic"]},
            "openai": {"has_key": bool(settings.api_key("openai")), "model": "", "ready": False,
                       "blocked": policy.BLOCKED_PROVIDERS["openai"]}}
