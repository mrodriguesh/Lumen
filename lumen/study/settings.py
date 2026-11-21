"""Ajustes do Lúmen Study AI (DATA/study/settings.json) e credenciais guardadas no cofre do sistema (keyring).

Cada valor é validado contra o tipo do padrão e, quando há, contra uma lista fechada ou um intervalo. Chaves
desconhecidas são ignoradas (um ajuste antigo ou forjado não entra)."""
import copy
import json
import os
import re
import shutil
import threading

import keyring

from .. import AppError, llm, store
from . import db, policy

LOCK = threading.RLock()
KEY_ACCOUNTS = {"anthropic": "anthropic-api-key", "openai": "openai-api-key"}
KEY_ACCOUNT = KEY_ACCOUNTS["anthropic"]
# A conta do cofre (serviço "Lumen") onde ficava a chave do Gemini. Não é mais lida nem gravada: o nome só existe para a
# migração apagar essa entrada, e somente ela (forget_legacy_gemini_key).
LEGACY_GEMINI_ACCOUNT = "google-api-key"

DEFAULTS = {
    "catalog": {"disabled": []},
    "pdf": {"dark": False, "cover_image": True},
    "models": {
        "provider": "ollama",        # principal: só ollama (nenhuma IA em nuvem: lumen/study/policy.py)
        "fallback": "none",          # alternativo quando o principal falha: none | ollama
        "local": "",                 # vazio = Automático: RECOMMENDED, se instalado; senão o da IA local dos Ajustes
        "fast": "",                  # para entender a pergunta e extrair memórias; vazio = Automático (ou o local)
        "max": "",                   # o do nível de esforço Máximo; vazio = Automático (RECOMMENDED, se instalado; ou o local)
        "anthropic": "",             # bloqueado pela política: só "" é aceito (o campo existe para ler ajustes antigos)
        "openai": "",                # idem
        "image_provider": "local",   # só local: a imagem em nuvem está bloqueada
        "image_openai": "",          # bloqueado (ajuste antigo)
        "video_provider": "none",    # só none: o Lúmen não gera vídeo em nuvem
        "video_model": "",           # bloqueado (ajuste antigo)
        "embed": "qwen3-embedding:0.6b",
        "temperature": 0.3,
        "context_chars": 16000,      # quanto texto das fontes entra numa resposta
        "stream": True,
    },
    "adult": {                       # perfil adulto (D92): modelo local dedicado, com configuração própria e independente
        "enabled": False,            # chave geral: desligado, só o modelo principal responde
        "mode": "auto",              # auto (decide pelo pedido, em processo local) | main (só se eu escolher na conversa) | adult
        "model": "",                 # vazio = o recomendado (ADULT_RECOMMENDED), se instalado
        "instructions": "",          # estilo próprio deste perfil; não substitui as instruções gerais do estudante
        "temperature": 0.8,          # própria: não mexe na do modelo principal
    },
    "quick": {                       # Conversa rápida da barra flutuante: ajustes próprios, independentes do chat principal
        "model": "",                 # vazio = o modelo rápido do Lúmen (fast_model, resolvido na hora); senão, um modelo local instalado
        "new_chat": "normal",        # normal | temporary: como começa uma conversa nova (não transforma a atual)
    },
    "search": {
        "notion": True, "obsidian": True, "files": True, "web": False,
        "hybrid": True, "rerank": False, "max_sources": 8, "scientific": False, "cache_days": 7,
        "images": True,              # ler as imagens das notas (cofre e Notion) com a visão local, em segundo plano
    },
    "memory": {
        "enabled": True,             # usar memórias nas respostas
        "auto": True,                # salvar novas memórias sozinho (as de confiança média viram sugestão)
        "projects": True,            # memória separada por projeto
        "long_term": True,
        "history": True,             # guardar conversas no histórico
        "temporary_private": True,   # conversa temporária não lê memórias pessoais
    },
    "personal": {
        "instructions": "", "detail": "equilibrado", "tone": "didatico", "format": "estruturado",
        "language": "pt-BR", "study": "",
    },
    "privacy": {
        "open_windows": False,       # a IA pode abrir páginas e notas sozinha (senão, mostra um botão)
        "organize": "ai",            # ai = criar nas áreas IA por pedido explícito | ask = prévia | off = nunca
        "retention_conversations": 0,  # dias; 0 = guardar até o usuário apagar
        "retention_activity": 90,
    },
    "connectors": {
        "folders": [],               # pastas autorizadas para leitura (arquivos locais)
        "obsidian_output": "C04 Claude Obsidian/01 Outputs",
        "notion_parent": "",         # vazio = página principal dos Ajustes
    },
    "agent": {"obsidian": True, "notion": True, "edge": True, "vault": True, "calculator": True},
    "performance": {"sync_minutes": 10, "yield_to_lessons": True, "embed_batch": 16,
                    "images_per_sync": 30},  # imagens das notas lidas por sincronização (≈ 2 s cada na GPU)
    "voice": {                       # fase 6 (D46 a D52); quem fala: lumen/study/listen.py
        "engine": "voicestudio",     # voicestudio (as vozes do estudante) | chatterbox (local, D44) | off
        "fallback": "off",           # com o Voice Studio fora do ar: chatterbox | off (nunca troca de voz em silêncio)
        "voice_id": "1faf41ee",      # o perfil do Voice Studio, pelo id (o nome pode mudar lá); o do Jhonny
        "chat_voice": "", "summary_voice": "", "review_voice": "", "practice_voice": "",  # por uso; vazio = a padrão
        "speed": 1.0,
        "language": "pt",            # pt | "" (o Voice Studio detecta)
        "seed": 1,                   # fixa: a voz soa igual todo dia; 0 = uma nova a cada pedido
        "style": "",                 # as tags de estilo que o motor aceita (instruct_vocabulary); vazio = a da voz
        "autoplay": False,           # ler cada resposta sozinho
        "read": "answer",            # answer = a resposta inteira | short = só o primeiro parágrafo
        "verify_long": True,         # conferir cada frase dos áudios longos com o Whisper (gera de novo se errar)
        "send_alone": False,         # apertar para falar: enviar sozinho depois de transcrever
        "summary_after_lesson": False,  # gerar o resumo em áudio no fim de cada aula (gasta a placa)
        # fase 6, parte 2 (D53 a D59)
        "vs_autostart": True,        # com o Voice Studio fechado, o Lúmen sobe o backend dele sem janela
        "vs_idle_minutes": 15,       # e o desliga depois disso parado (não com o app aberto)
        "vs_warm_on_open": False,    # deixar a voz pronta (backend e modelo) quando o Lúmen abre
        "chat_quality": "quality",   # passos da fala do chat (listen.STEPS); 16 por escolha na escuta cega (D56): +0,5 s no 1º som
        "long_quality": "quality",   # passos dos áudios longos (resumo e revisão)
        "cache_mb": 500,             # frases já faladas em MEDIA/audio/cache (0 = sem cache)
        "review_dialog": False,      # revisão em áudio a duas vozes: o narrador pergunta, a voz padrão responde
        "narrator_voice": "",        # a voz do narrador na revisão a duas vozes
        # fase 6, parte 3: conversa por voz em tempo real (seção 4.2; padrões vindos das medições na seção 5)
        "call_mode": "handsfree",    # handsfree (VAD) | ptt (segurar) | tap (tocar para falar)
        "call_silence": "normal",    # fast (450 ms) | normal (700 ms) | patient (1100 ms)
        "call_barge_in": True,       # interromper falando por cima
        "call_headphones": False,    # True = fone (sensível) | False = caixa de som (AEC + barreira de energia)
        "call_early": True,          # resposta antecipada aos ~250 ms de silêncio (descarta se voltar a falar)
        "call_mic": "",              # id do microfone do Windows; vazio = o padrão do sistema
        "call_voice": "",            # perfil do Voice Studio do uso "call"; vazio = a padrão (Jhonny)
        "call_speed": 1.0,           # velocidade da voz na chamada (0,7 a 1,3)
        "call_quality": "balanced",  # fast (8) | balanced (12) | quality (16 passos; D56)
        "call_first_quality": "same",  # same (1º trecho com os mesmos passos) | fast (8 passos só no 1º trecho: sai ~0,3 s antes; pedido da escuta cega)
        "call_length": "short",      # short (1 a 3 frases) | chat (conversa) | detailed (detalhada)
        "call_effort": "auto",       # auto (teto Equilibrado, salvo pedido na fala) | rapido | equilibrado
        "call_earcon": True,         # som curto e suave de "entendi" quando a vez do estudante termina
        "call_filler": False,        # preencher espera longa com frase curta guardada ("Deixa eu ver…"), máx. 1 por turno
        "call_asr": "auto",          # auto (Parakeet CPU int8; ou pela VRAM livre) | parakeet | whisper
        "call_captions": True,       # mostrar legendas ao vivo
        "call_autostop": 5,          # minutos de silêncio para fechar o microfone: 2, 5, 10 ou 0 (nunca)
        "call_save": "history",      # history (no histórico) | temporary (só na memória; áudio nunca é salvo)
        "call_timings": False,       # mostrar em cada turno os tempos medidos de cada etapa
    },
}

ENUMS = {
    ("models", "provider"): policy.PROVIDERS,
    ("models", "fallback"): ("none",) + policy.PROVIDERS,
    ("models", "image_provider"): ("local",),
    ("models", "video_provider"): ("none",),
    ("models", "anthropic"): ("",), ("models", "openai"): ("",), ("models", "image_openai"): ("",),
    ("models", "video_model"): ("",),
    ("adult", "mode"): ("auto", "main", "adult"),
    ("quick", "new_chat"): ("normal", "temporary"),
    ("personal", "detail"): ("breve", "equilibrado", "detalhado"),
    ("personal", "tone"): ("didatico", "direto", "conversacional", "formal"),
    ("personal", "format"): ("estruturado", "topicos", "texto"),
    ("personal", "language"): ("pt-BR", "en", "es"),
    ("privacy", "organize"): ("ai", "ask", "off"),
    ("voice", "engine"): ("voicestudio", "chatterbox", "off"),
    ("voice", "fallback"): ("chatterbox", "off"),
    ("voice", "language"): ("pt", ""),
    ("voice", "read"): ("answer", "short"),
    ("voice", "chat_quality"): ("fast", "balanced", "quality", "max"),
    ("voice", "long_quality"): ("fast", "balanced", "quality", "max"),
    ("voice", "call_mode"): ("handsfree", "ptt", "tap"),
    ("voice", "call_silence"): ("fast", "normal", "patient"),
    ("voice", "call_quality"): ("fast", "balanced", "quality"),
    ("voice", "call_first_quality"): ("same", "fast"),
    ("voice", "call_length"): ("short", "chat", "detailed"),
    ("voice", "call_effort"): ("auto", "rapido", "equilibrado"),
    ("voice", "call_asr"): ("auto", "parakeet", "whisper"),
    ("voice", "call_save"): ("history", "temporary"),
}
INT_ENUMS = {("voice", "call_autostop"): (0, 2, 5, 10)}
VOICE_IDS = ("voice_id", "chat_voice", "summary_voice", "review_voice", "practice_voice", "narrator_voice", "call_voice")
VOICE_ID = re.compile(r"[\w-]{0,64}")
MIC_ID = re.compile(r"[\w.{}:/-]{0,160}")
STYLE = re.compile(r"[\w ,-]{0,200}")  # tags separadas por vírgula ("low pitch, whisper"); quem confere é o motor
RANGES = {
    ("models", "temperature"): (0.0, 1.0), ("models", "context_chars"): (4000, 120000),
    ("adult", "temperature"): (0.0, 1.5),
    ("search", "max_sources"): (3, 20), ("search", "cache_days"): (0, 90),
    ("privacy", "retention_conversations"): (0, 3650), ("privacy", "retention_activity"): (7, 3650),
    ("performance", "sync_minutes"): (2, 1440), ("performance", "embed_batch"): (1, 64),
    ("performance", "images_per_sync"): (0, 500),
    ("voice", "speed"): (0.7, 1.3), ("voice", "call_speed"): (0.7, 1.3), ("voice", "seed"): (0, 2_147_483_647),
    ("voice", "vs_idle_minutes"): (5, 240), ("voice", "cache_mb"): (0, 5000),
}
LONG = {("personal", "instructions"): 4000, ("personal", "study"): 2000, ("adult", "instructions"): 2000}
MODEL_NAME = re.compile(r"[\w.\-/]+(?::[\w.\-]+)?")  # nome de modelo do Ollama ("dono/modelo:tag", "hf.co/dono/repo:quant")


def _file():
    return db.HOME / "settings.json"


def _merged():
    """Os ajustes salvos sobre os padrões, como estão no disco (sem a política)."""
    out = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        saved = {}
    for section, values in (saved if isinstance(saved, dict) else {}).items():
        if section in out and isinstance(values, dict):
            for key, value in values.items():
                if key in out[section] and type(value) is type(out[section][key]):
                    out[section][key] = value
    return out


def load():
    """Os ajustes em vigor. A política de custo (policy.normalize) vale sempre na leitura: um ajuste antigo que apontava
    para um serviço pago nunca volta a valer, mesmo que o arquivo ainda o guarde."""
    with LOCK:
        out = _merged()
        policy.normalize(out)
        quick = out["quick"]  # arquivo editado à mão: valor fora da lista volta ao padrão (nunca um nome que não é de modelo)
        if quick["new_chat"] not in ENUMS[("quick", "new_chat")]:
            quick["new_chat"] = DEFAULTS["quick"]["new_chat"]
        if quick["model"] and not MODEL_NAME.fullmatch(quick["model"]):
            quick["model"] = ""
        return out


def _check(section, key, value):
    default = DEFAULTS[section][key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise AppError("Ajuste inválido.", "Recarregue a janela e tente de novo.")
        return value
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AppError("Ajuste inválido.", "Use um número.")
        if (section, key) in INT_ENUMS:
            iv = int(value)
            if iv != value or iv not in INT_ENUMS[(section, key)]:
                raise AppError("Opção desconhecida.", "Escolha uma das opções da lista.")
            return iv
        low, high = RANGES.get((section, key), (float("-inf"), float("inf")))
        value = min(max(value, low), high)
        return int(value) if isinstance(default, int) else float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise AppError("Ajuste inválido.", "Use um texto.")
        value = value.strip()[:LONG.get((section, key), 200)]
        if (section, key) in ENUMS and value not in ENUMS[(section, key)]:
            raise AppError("Opção desconhecida.", "Escolha uma das opções da lista.")
        if (section, key) == ("adult", "model") and value and not MODEL_NAME.fullmatch(value):
            raise AppError("Nome de modelo inválido.", "Escolha um modelo da lista de modelos instalados.")
        if (section, key) == ("quick", "model") and value:
            # Só um modelo local de chat que está instalado agora: nada de caminho, URL ou provedor vindo da tela (o nome é só um nome do Ollama)
            if not MODEL_NAME.fullmatch(value):
                raise AppError("Nome de modelo inválido.", "Escolha um modelo da lista de modelos instalados.")
            choices = quick_choices()
            if choices is None:
                raise AppError("Não consegui conferir os modelos instalados.", "Abra o Ollama e tente de novo.")
            if value not in choices:
                raise AppError("Esse modelo não está instalado.", "Escolha um modelo da lista de modelos instalados.")
        if section == "voice" and key in VOICE_IDS and not VOICE_ID.fullmatch(value):
            raise AppError("Voz inválida.", "Escolha uma voz da lista.")
        if (section, key) == ("voice", "call_mic") and not MIC_ID.fullmatch(value):
            raise AppError("Microfone inválido.", "Escolha um microfone da lista.")
        if (section, key) == ("voice", "style") and not STYLE.fullmatch(value):
            raise AppError("Estilo inválido.", "Use as tags do motor separadas por vírgula, como “low pitch, whisper”.")
        return value
    raise AppError("Este ajuste não pode ser alterado aqui.")


def save(patch):
    """Aplica as mudanças válidas e devolve os ajustes completos. Pastas autorizadas têm a rota delas (folders)."""
    if not isinstance(patch, dict):
        raise AppError("Ajuste inválido.")
    with LOCK:
        current = load()
        for section, values in patch.items():
            if section not in DEFAULTS or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key in DEFAULTS[section] and not isinstance(DEFAULTS[section][key], list):
                    current[section][key] = _check(section, key, value)
        write(current)
        return current


BACKUP_TAG = "remocao-gemini-20261109"


def _backup_name():
    return _file().with_name(f"settings.json.antes-{BACKUP_TAG}.bak")


def write(data):
    db.HOME.mkdir(parents=True, exist_ok=True)
    bak = _backup_name()
    if _file().exists() and not bak.exists():  # a 1ª gravação depois da remoção guarda o arquivo como estava (restauração)
        shutil.copy2(_file(), bak)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, _file())


def obsolete(saved):
    """O que o arquivo de ajustes ainda guarda da integração retirada (Gemini) ou de uma escolha que apontaria para fora do PC.
    `saved` é o JSON como está no disco. Lista vazia = nada a migrar. Só nomes de campos e IDs de provedor, nunca segredos."""
    if not isinstance(saved, dict):
        return []
    out = []
    if "gemini" in saved:
        out.append("gemini: aceites, época da chave e travas removidos")
    models, privacy = saved.get("models"), saved.get("privacy")
    if isinstance(models, dict):
        for key in ("google", "image_google"):
            if key in models:
                out.append(f"models.{key} removido")
        for key, ok in (("provider", policy.PROVIDERS), ("fallback", ("none",) + policy.PROVIDERS),
                        ("image_provider", ("local",)), ("video_provider", ("none",))):
            if key in models and isinstance(models[key], str) and models[key] not in ok:
                out.append(f"models.{key}: {models[key]!r} não existe mais")
    if isinstance(privacy, dict) and "external" in privacy:
        out.append("privacy.external removido (não há envio a provedores externos)")
    return out


def forget_legacy_gemini_key():
    """Apaga do cofre do sistema SÓ a entrada do Lúmen que guardava a chave do Gemini (serviço "Lumen", conta
    "google-api-key"). Não lê o valor, não toca nas credenciais do Drive, do Notion nem de outros aplicativos. Devolve
    True se havia a entrada. Apagar aqui não revoga a chave na conta Google."""
    try:
        keyring.delete_password(store.APP, LEGACY_GEMINI_ACCOUNT)
        return True
    except keyring.errors.PasswordDeleteError:
        return False  # já não existia
    except keyring.errors.KeyringError:
        return False  # cofre indisponível: a próxima abertura tenta de novo


def migrate():
    """Migração pequena e idempotente da retirada do Gemini: grava no arquivo de ajustes as escolhas que a política já
    neutralizava na leitura (provedor principal Gemini → IA local; alternativo Gemini → nenhum; imagem em nuvem → local;
    vídeo em nuvem → desativado) e deixa de gravar os campos exclusivos. O modelo local escolhido é preservado, e nenhum
    nome de modelo é inventado. Guarda uma única cópia do arquivo original (settings.json.antes-….bak) e registra o que
    mudou. Depois apaga a chave do Gemini do cofre. Rodar de novo não faz nada (e não cria outra cópia). Devolve o que mudou."""
    with LOCK:
        try:
            saved = json.loads(_file().read_text("utf-8")) if _file().exists() else None
        except (OSError, ValueError):
            saved = None
        found = obsolete(saved)
        if found:
            current = _merged()
            policy.normalize(current)
            write(current)
    if found:
        from . import activity
        activity.log("migracao-gemini", target="integração Gemini retirada", permission="automática",
                     result=f"{len(found)} ajuste(s)", detail="; ".join(found)[:280])
    forget_legacy_gemini_key()
    return found


def set_folders(folders):
    with LOCK:
        current = load()
        current["connectors"]["folders"] = folders
        write(current)
        return current


# Campo vazio = Automático: o modelo recomendado pela medição neste PC (fase 2 do Study AI 2.0,
# docs/implementation/LUMEN_STUDY_AI_MODELS.md), se estiver instalado; senão, o da IA local dos Ajustes. O rápido fica
# igual ao principal: os modelos carregam de um HD, e trocar de modelo a cada pergunta custa de 5 s a 2 min. O do nível
# Máximo é o maior que cabe e venceu os outros grandes nos duelos (D31).
RECOMMENDED = {"local": "qwen3.5:4b", "fast": "", "max": "qwen3.5:9b"}


def _recommended(role):
    """O recomendado, se instalado. Com o Ollama fora do ar não dá para saber: fica o recomendado (a tela já avisa
    que o Ollama não roda), para uma falha passageira não trocar de modelo no meio de uma resposta."""
    name = RECOMMENDED[role]
    if not name:
        return ""
    names = llm.models()
    return name if names is None or name in names or f"{name}:latest" in names else ""


def local_model(s=None):
    s = s or load()
    return s["models"]["local"] or _recommended("local") or store.load_config()["ollama_model"]


def fast_model(s=None):
    s = s or load()
    return s["models"]["fast"] or _recommended("fast") or local_model(s)


def max_model(s=None):
    s = s or load()
    return s["models"]["max"] or _recommended("max") or local_model(s)


# Sem escolha do estudante, o perfil adulto usa este, se instalado (medição de 08/11/2026, docs/implementation/
# LUMEN_STUDY_AI_PERFIL_ADULTO_20261108.md): o Qwen3.5-9B Ultra Uncensored Heretic (llmfan46, Q4_K_M, Apache-2.0) com o renderizador
# e o analisador do próprio qwen3.5 do Ollama. O nome começa por "qwen3.5": a janela de 32k vale para ele (providers.window).
ADULT_RECOMMENDED = "qwen3.5-heretic:9b"


def adult_model(s=None):
    """O modelo do perfil adulto: o escolhido ou o recomendado instalado; "" se nenhum (nunca cai no principal)."""
    s = s or load()
    if s["adult"]["model"]:
        return s["adult"]["model"]
    name = ADULT_RECOMMENDED
    names = llm.models()
    return name if name and (names is None or name in names or f"{name}:latest" in names) else ""


def _has(names, model):
    """O modelo está na lista do Ollama (com ou sem a etiqueta :latest)?"""
    return bool(model) and (model in names or f"{model}:latest" in names or (model.endswith(":latest") and model[:-7] in names))


def quick_choices(s=None):
    """Os modelos que a Conversa rápida aceita escolher: os de chat instalados no Ollama, sem embeddings e sem o modelo dedicado
    ao perfil adulto (esse só responde pelo perfil). None se o Ollama não responde (não dá para conferir o que está instalado)."""
    s = s or load()
    names = llm.models()
    if names is None:
        return None
    reserved = s["adult"]["model"] or ADULT_RECOMMENDED
    return sorted(n for n in names if "embed" not in n.lower() and not (_has([n], reserved) or _has([reserved], n)))


def quick_resolve(s=None):
    """O modelo que a Conversa rápida usa AGORA. Padrão: o rápido do Lúmen (fast_model, resolvido nesta hora, nunca um nome fixo);
    com escolha própria (quick.model), a escolhida. Se ele não está instalado, o primeiro local que está (o rápido, depois o principal) e
    `fallback` = True, para a resposta dizer qual modelo respondeu de fato; sem nenhum, `unavailable`. Com o Ollama fora do ar não há
    como conferir: devolve o pedido como está e a resposta falha com a mensagem do Ollama. Nunca baixa nem chama nada fora do PC."""
    s = s or load()
    chosen = s["quick"]["model"]
    wanted = chosen or fast_model(s)
    names = llm.models()
    out = {"source": "chosen" if chosen else "fast", "requested": wanted, "model": wanted, "fallback": False,
           "unavailable": False, "running": names is not None}
    if names is None or _has(names, wanted):
        return out
    for alt in (fast_model(s), local_model(s)):
        if alt != wanted and _has(names, alt):
            return {**out, "model": alt, "fallback": True}
    return {**out, "unavailable": True}


def quick_view(s=None):
    """O que a tela de ajustes da Conversa rápida mostra: as escolhas salvas, o que cada uma resolve agora e a lista de opções."""
    s = s or load()
    return {"settings": dict(s["quick"]), "fast": fast_model(s), "resolved": quick_resolve(s), "choices": quick_choices(s) or [],
            "running": llm.models() is not None}


def api_key(provider="anthropic"):
    """Obtém uma credencial sem persistir nem devolver seu valor pela API de configurações."""
    account = KEY_ACCOUNTS.get(provider)
    if not account:
        raise AppError("Provedor de IA desconhecido.")
    try:
        return keyring.get_password(store.APP, account) or ""
    except keyring.errors.KeyringError as e:
        raise AppError("O cofre seguro do sistema não está disponível.",
                       "Verifique o Gerenciador de Credenciais do Windows. Nenhuma chave foi salva em texto puro.") from e


def set_api_key(value, provider="anthropic"):
    account = KEY_ACCOUNTS.get(provider)
    if not account:
        raise AppError("Provedor de IA desconhecido.")
    if value:  # remover uma chave antiga é sempre permitido; guardar uma nova de um serviço pago ou removido, não
        policy.authorize(load(), provider)
    if value:
        try:
            keyring.set_password(store.APP, account, value)
        except keyring.errors.KeyringError as e:
            raise AppError("Não foi possível salvar a chave no cofre seguro.",
                           "Verifique o Gerenciador de Credenciais do Windows. Nenhuma cópia insegura foi criada.") from e
    else:
        try:
            keyring.delete_password(store.APP, account)
        except keyring.errors.PasswordDeleteError:
            pass
        except keyring.errors.KeyringError as e:
            raise AppError("Não foi possível remover a chave do cofre seguro.",
                           "Verifique o Gerenciador de Credenciais do Windows.") from e


def public(s=None):
    """Ajustes para a tela: sem segredo, só se há chave."""
    s = copy.deepcopy(s or load())
    s["has_anthropic_key"] = bool(api_key("anthropic"))
    s["resolved"] = {"local": local_model(s), "fast": fast_model(s), "max": max_model(s), "adult": adult_model(s),
                     "quick": quick_resolve(s)["model"]}
    return s
