"""Quanto falta: cada etapa estimada com a velocidade medida neste PC e aprendida a cada aula.

A IA é estimada pelo que o próprio Ollama mede em cada resposta (tokens lidos e escritos por segundo, tempo de
carregar o modelo) e pelo tamanho típico de cada resposta. O resto (desenhar, enviar ao Notion, ler telas) pela
mediana dos segundos por unidade das últimas aulas. Durante uma etapa, o que já se sabe dela (tokens escritos,
progresso da transcrição) corrige a conta."""
import json
import statistics
import threading
import time

from . import store

KEEP = 15  # medidas guardadas por item; a mediana ignora uma aula fora do comum
_lock = threading.Lock()
current = None  # o Plan da tarefa em andamento (llm._chat avança e corrige as etapas da IA)

# Antes da 1ª aula: medidas deste projeto (qwen3:8b numa RTX 3060, aula de teste de ponta a ponta no Notion real).
PRIOR = {
    "llm_prompt_tps": 1870.0,  # tokens do pedido lidos por segundo
    "llm_gen_tps": 56.0,       # tokens escritos por segundo
    "llm_load_s": 3.6,         # carregar o modelo na GPU (0 se já estiver carregado)
    "chars_per_token": 2.65,
    "out_lesson": 1.0, "out_notes": 1.0, "out_charts": 1.0, "out_analysis": 1.0, "out_refine": 1.0,
    "out_connect": 1.0,  # correção sobre SHAPE (medido ÷ previsto)
    "screen_s": 2.3,           # leitura de uma tela pela IA de visão
    "music_rtf": 0.1,          # filtro de música, por segundo de áudio (separar na CPU: ≈ 0,15 s/s onde há música)
    "scan_rtf": 0.31,          # assistir o vídeo e ler as telas, por segundo de vídeo
    "mindmap_s": 4.9, "chart_s": 5.9, "upload_s": 1.3, "request_s": 1.0,
    "visual_s": 5.5,           # visualização 3D animada (visual3d; medido: 5,4 s na CPU do i5-11400F)
}


# Tamanho típico de cada resposta (tokens) = fixo + parte do pedido (tokens): aula maior, página maior. Medido:
# página de uma aula curta (2,2 mil tokens) ≈ 1.700; de uma longa (8,5 mil) ≈ 3.400; notas de uma parte ≈ 1.500.
SHAPE = {"lesson": (1300, 0.25), "notes": (300, 0.22), "charts": (400, 0.05), "analysis": (600, 0.04),
         "refine": (1500, 0.15), "connect": (250, 0.03)}  # refine e connect: sem medida ainda, aprendidos depois


def out_tokens(model, kind, prompt_tokens):
    """Quantos tokens a resposta deve ter, até o teto dela (llm.MAX_OUT)."""
    from .llm import MAX_OUT
    base, per = SHAPE[kind]
    return min(value(f"out_{kind}", model) * (base + per * prompt_tokens), MAX_OUT[kind])


def _data():
    try:
        return json.loads((store.DATA / "tempos.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def value(key, model=None, default=None):
    """Mediana do que foi medido neste PC (por modelo, quando é da IA) ou o valor inicial."""
    got = _data().get(f"{model}:{key}" if model else key) or []
    return statistics.median(got) if got else PRIOR[key] if default is None else default


def transcribe_seconds(duration, name):
    """Transcrever `duration` segundos de áudio com o modelo `name` (antes da 1ª medida: o benchmark)."""
    from .transcribe import speed_factor
    return (duration or 0) * value("transcribe_rtf", name, 1 / speed_factor(name))


def learn(key, v, model=None):
    if not (isinstance(v, (int, float)) and v > 0):
        return
    with _lock:
        d = _data()
        k = f"{model}:{key}" if model else key
        d[k] = (d.get(k) or [])[-(KEEP - 1):] + [round(float(v), 4)]
        try:
            store.DATA.mkdir(parents=True, exist_ok=True)
            tmp = store.DATA / "tempos.json.tmp"
            tmp.write_text(json.dumps(d), "utf-8")
            tmp.replace(store.DATA / "tempos.json")
        except OSError:
            pass  # sem gravar, a próxima estimativa usa o que já havia


def learn_llm(model, kind, stats, chars):
    """O fim de cada resposta do Ollama: velocidades medidas por ele mesmo e o tamanho da resposta."""
    ns = 1e9
    if stats.get("prompt_eval_count") and stats.get("prompt_eval_duration"):
        learn("llm_prompt_tps", stats["prompt_eval_count"] / (stats["prompt_eval_duration"] / ns), model)
        learn("chars_per_token", chars / stats["prompt_eval_count"], model)
    if stats.get("eval_count") and stats.get("eval_duration"):
        learn("llm_gen_tps", stats["eval_count"] / (stats["eval_duration"] / ns), model)
        if kind in SHAPE and stats.get("prompt_eval_count"):
            base, per = SHAPE[kind]
            learn(f"out_{kind}", stats["eval_count"] / (base + per * stats["prompt_eval_count"]), model)
    if stats.get("load_duration", 0) / ns > 0.5:  # só quando o modelo foi mesmo carregado
        learn("llm_load_s", stats["load_duration"] / ns, model)


def llm_seconds(model, chars, kind):
    """Uma resposta da IA: ler o pedido + escrever a resposta (+ carregar o modelo, se preciso)."""
    tokens = chars / value("chars_per_token", model)
    return (value("llm_load_s", model) * 0.5 + tokens / value("llm_prompt_tps", model)
            + out_tokens(model, kind, tokens) / value("llm_gen_tps", model))


class Plan:
    """As etapas que faltam, [(nome, segundos estimados)], e o tempo que falta somando todas."""

    def __init__(self, steps):
        self.steps = [(n, max(float(s), 0.0)) for n, s in steps]
        self.i, self.t0, self.live = -1, time.monotonic(), None

    def at(self, name, seconds=None):
        """Começou a etapa `name`: a próxima com esse nome (“notes” se repete numa aula longa) ou, se não houver
        outra, a mesma de novo (2ª tentativa da IA). Opcional: estimativa nova para ela."""
        names = [n for n, _ in self.steps]
        ahead = [j for j in range(self.i + 1, len(names)) if names[j] == name]
        j = ahead[0] if ahead else (self.i if 0 <= self.i < len(names) and names[self.i] == name else None)
        if j is None:
            return
        self.i, self.t0, self.live = j, time.monotonic(), None
        if seconds is not None:
            self.steps[j] = (name, max(float(seconds), 0.0))

    def name(self):
        return self.steps[self.i][0] if 0 <= self.i < len(self.steps) else None

    def writing(self, model, kind, n, chars):
        """A IA já escreveu n tokens desta resposta: falta o resto do tamanho típico, na velocidade medida. Passou
        dele: a resposta é das grandes, conta mais um quarto do que já escreveu (até o teto)."""
        if self.name() == kind and n >= 5:
            from .llm import MAX_OUT
            out = out_tokens(model, kind, chars / value("chars_per_token", model))
            if n > out * 0.9:
                out = min(n * 1.25, MAX_OUT[kind])
            self.update(max(out - n, 0) / value("llm_gen_tps", model) + 1)

    def progress(self, p):
        """Etapa com progresso conhecido (0–1): o ritmo até aqui diz quanto falta."""
        if p and 0.03 <= p < 1:
            self.update(self.elapsed() * (1 - p) / p)

    def set(self, name, seconds):
        """Estimativa nova para uma etapa que ainda vai acontecer."""
        self.steps = [(n, max(float(seconds), 0.0) if n == name else s) for n, s in self.steps]

    def update(self, left):
        """Quanto falta na etapa atual, medido por ela mesma (tokens escritos, progresso da transcrição)."""
        self.live = (max(float(left), 0.0), time.monotonic())

    def elapsed(self):
        return time.monotonic() - self.t0

    def left(self):
        now = time.monotonic()
        if self.i < 0:
            return sum(s for _, s in self.steps)
        _, est = self.steps[self.i]
        if self.live:
            cur = max(self.live[0] - (now - self.live[1]), 0.0)
        else:  # passou da estimativa: ainda falta um pouco, nunca “0 s” enquanto a etapa não termina
            cur = max(est - (now - self.t0), min(est * 0.15, 20.0), 1.0 if est else 0.0)
        return cur + sum(s for _, s in self.steps[self.i + 1:])
