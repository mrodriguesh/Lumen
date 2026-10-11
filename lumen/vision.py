"""“Assistir a tela junto”: lê o que aparece na aula (slides, quadro, código, tabelas) com um modelo de visão local.

De onde vêm as telas:
- Gravação: a tela é capturada 1×/s enquanto o som é gravado (GDI do Windows, sem dependências novas). Só fica a
  tela nova que parou de mudar (≥ 1,5 s): transições e vídeo em movimento não viram foto. Áreas que mudam o tempo
  todo (câmera do professor, animação) são ignoradas na comparação, e a barra do Lumen também.
- Arquivo de vídeo: só os quadros-chave são decodificados (PyAV); os codificadores os colocam nas trocas de cena.

Cada tela guardada é lida pelo modelo de visão do Ollama (qwen3.5:4b, escolhido em bench/vision_bench.py: 100% do
texto lido em 18 telas, 18/18 decisões certas, nenhum texto de recomendação/notificação copiado, 1,5 s por tela e
3,1 GB de VRAM). Telas sem conteúdo da aula (rosto, anúncio, menus) são apagadas na hora. Na gravação, a leitura
acontece enquanto você assiste, entre uma tela e outra; o que sobrar é lido quando a aula for processada.
"""
import json
import os
import queue
import re
import shutil
import threading
import time
import unicodedata
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import AppError, llm

MODEL = "qwen3.5:4b"
SIZE = "≈ 3,3 GB"
WIDTH = 1280        # largura guardada e enviada ao modelo (bench: 100% do texto lido a 1280 e a 960)
GRID = (54, 96)     # miniatura cinza usada para comparar telas (células de 20×20 px numa tela 1080p)
DELTA = 10          # diferença de cinza (0–255) que conta como mudança numa célula
LIVE_ON, LIVE_OFF = 0.3, 0.05  # células que mudam em boa parte das capturas (câmera, vídeo, animação) saem da
#                    comparação e só voltam depois de paradas um bom tempo (uma transição não basta para sair)
NEW = 0.01          # fração das células paradas que muda para ser tela nova (uma linha nova num slide ≈ 1,5%)
SMALL = 0.05        # abaixo disto, é a mesma tela ganhando conteúdo (tópico novo, digitação); dois slides com
#                    pouco texto já diferem em ~20%
SIMILAR = 0.25      # parecida com uma tela de “pessoa falando” já lida: não relê (só esse tipo; slides não)
GAP_S = 20          # numa tela que vai ganhando conteúdo, guarda o estado mais recente a cada 20 s
STILL_S = 1.5       # a tela precisa ficar parada este tempo (descarta transições)
INTERVAL_S = 1.0
STOP_S = 5.0        # ao parar, espera a captura guardar a última tela; depois a pasta fecha mesmo assim
MAX_SHOTS = 300     # telas guardadas por aula (≈ 60–150 KB cada)
CTX = 4096          # pedido + imagem ≈ 1300 tokens; resposta < 600

SYSTEM = """Você assiste a uma aula em vídeo junto com um estudante e anota o que aparece na tela.
Responda só com JSON:
- titulo: o título do conteúdo, como aparece; se não houver, um título curto descritivo.
- texto: transcreva fielmente, linha por linha, todo o texto do conteúdo da aula (slide, quadro, código, tabela,
  fórmulas). Mantenha números, símbolos e o idioma original; em código, mantenha a indentação (os espaços no
  começo de cada linha). Em tabelas, uma linha por linha da tabela com as
  colunas separadas por " | ". NÃO inclua nada fora do conteúdo da aula: menus, abas, endereço, títulos de outros
  vídeos, recomendações, comentários, notificações, relógio, nomes de programas, botões do player. Se houver
  outras janelas além da aula (editor, chat, anotações, e-mail), ignore-as.
- descricao: se houver diagrama, gráfico, figura ou demonstração, diga em 1 a 2 frases o que mostra; senão "".
- tipo: o que a imagem mostra.
- conteudo_da_aula: true só se a tela mostra material de estudo: slide, quadro, código, tabela, diagrama, gráfico,
  fórmula ou demonstração num programa. false quando mostra principalmente uma pessoa falando (mesmo com o nome
  dela escrito), vinheta de abertura ou encerramento, anúncio, menu, área de trabalho ou tela sem relação com a aula.
  Se a mensagem disser a janela, use-a: o vídeo ou a transmissão da aula (navegador, player, reunião) conta; um
  programa do próprio estudante (editor de código, anotações, chat, e-mail, pastas) não conta, mesmo que o texto
  seja sobre a matéria.
- valores: em gráficos (barras, linhas, pizza) e tabelas com números, cada rótulo com o seu valor, como aparecem
  na imagem (ex.: {"rotulo": "Bubble sort", "valor": "5.200 ms"}); olhe a barra ou a fatia de cada rótulo. Senão []."""

KINDS = {"slide": "📑", "codigo": "💻", "tabela": "📊", "diagrama": "🧩", "grafico": "📈", "formula": "➗",
         "quadro": "✍️", "demonstracao": "🖱️", "pessoa": "🧑‍🏫", "anuncio": "📣", "outro": "🖥️"}
# A ordem importa: o modelo lê primeiro (título, texto) e só depois classifica (bench: com o tipo primeiro, ele
# chamava quase tudo de "pessoa"). Sem pedir a área do conteúdo: na captura real ela cortava o título dos slides;
# a imagem já vem recortada na janela da aula e sem faixas pretas (_trim).
SCHEMA = {"type": "object", "properties": {
    "titulo": {"type": "string"}, "texto": {"type": "string"}, "descricao": {"type": "string"},
    "tipo": {"type": "string", "enum": list(KINDS)},
    "conteudo_da_aula": {"type": "boolean"},
    "valores": {"type": "array", "items": {"type": "object", "properties": {
        "rotulo": {"type": "string"}, "valor": {"type": "string"}}, "required": ["rotulo", "valor"]}}},
    "required": ["titulo", "texto", "descricao", "tipo", "conteudo_da_aula", "valores"]}


# --- imagens ------------------------------------------------------------------------------------------------------

def _encode(frame, width=WIDTH):
    """VideoFrame do PyAV → JPEG de alta qualidade com no máximo `width` px de largura."""
    import av
    w = min(width, frame.width) // 2 * 2
    h = max(2, round(frame.height * w / frame.width / 2) * 2)
    frame = frame.reformat(width=w, height=h, format="yuvj420p", interpolation="AREA")
    enc = av.CodecContext.create("mjpeg", "w")
    enc.width, enc.height, enc.pix_fmt, enc.time_base = w, h, "yuvj420p", Fraction(1, 1)
    enc.options = {"qmin": "3", "qmax": "3"}
    return b"".join(bytes(p) for p in enc.encode(frame)) + b"".join(bytes(p) for p in enc.encode(None))


def _trim(img):
    """Tira faixas pretas uniformes das bordas (vídeo 4:3 numa tela 16:9, sobra do player em tela cheia)."""
    bright = img[..., :3].max(axis=2)
    rows, cols = np.flatnonzero(bright.max(axis=1) > 24), np.flatnonzero(bright.max(axis=0) > 24)
    if not len(rows) or (rows[-1] - rows[0]) * (cols[-1] - cols[0]) < 0.3 * bright.size:
        return img  # quase tudo escuro: melhor não mexer
    return np.ascontiguousarray(img[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1])


def _small(gray):
    """Imagem cinza (qualquer tamanho) → miniatura GRID pela média de blocos que cobrem a imagem inteira (em
    1366×768, por exemplo, os blocos não têm tamanho exato e nenhuma borda pode ficar de fora)."""
    if gray.shape[0] < GRID[0] or gray.shape[1] < GRID[1]:
        return np.zeros(GRID, np.float32)
    ys = np.linspace(0, gray.shape[0], GRID[0] + 1).astype(int)
    xs = np.linspace(0, gray.shape[1], GRID[1] + 1).astype(int)
    sums = np.add.reduceat(np.add.reduceat(gray.astype(np.float32), ys[:-1], axis=0), xs[:-1], axis=1)
    return sums / np.outer(np.diff(ys), np.diff(xs))


def _diff(a, b, mask=None):
    changed = np.abs(a - b) > DELTA
    if mask is None:
        return float(changed.mean())
    return float((changed & mask).sum() / max(mask.sum(), 1))


# --- quais telas guardar -----------------------------------------------------------------------------------------

class Scenes:
    """Diz quando aparece uma tela nova. Alimentado em ordem com miniaturas (ver _small).

    still_s > 0 (captura da tela, 1×/s): só conta a tela que ficou parada esse tempo, e as células que mudam quase
    sempre (câmera, vídeo, animação) ficam fora da comparação. still_s = 0 (quadros-chave de um arquivo, esparsos):
    compara a imagem inteira."""

    def __init__(self, still_s=STILL_S):
        self.still_s, self.keys, self.prev, self.since = still_s, [], None, 0.0
        self.motion, self.live = np.zeros(GRID, np.float32), np.zeros(GRID, bool)

    def feed(self, t, small):
        small = small.astype(np.float32)
        if self.prev is None:
            self.prev, self.since = small, t
            return not self.still_s and self._new(small, None)
        changed = np.abs(small - self.prev) > DELTA
        self.prev = small
        if not self.still_s:
            self.since = t
            return self._new(small, None)
        # Frequência de mudança de cada célula (média móvel), com histerese: a câmera do professor entra em “viva”
        # em ~4 capturas e não sai a cada instante parado; uma troca de slide (1 ou 2 mudanças) nunca entra.
        self.motion += 0.1 * (changed - self.motion)
        self.live = (self.live & (self.motion > LIVE_OFF)) | (self.motion > LIVE_ON)
        static = ~self.live
        if static.mean() < 0.4 or (changed & static).mean() > 0.002:  # quase tudo se mexe, ou ainda mudando
            self.since = t
            return False
        return t - self.since >= self.still_s and self._new(small, static)

    def _new(self, small, mask):
        if any(_diff(small, k, mask) < NEW for k in self.keys):
            return False  # igual a uma tela já guardada (inclusive um slide que voltou)
        self.keys.append(small)
        return True


class Picker:
    """Das telas novas, escolhe quais ler: cada tela diferente na hora; numa tela que vai ganhando pouco conteúdo
    (tópicos que aparecem um a um, código sendo digitado), guarda o estado mais recente e lê ao trocar de tela ou a
    cada GAP_S. `skip`: miniaturas de telas de “pessoa falando” já lidas; as parecidas não são relidas."""

    def __init__(self, still_s=STILL_S):
        self.scenes, self.held, self.last, self.last_at, self.skip = Scenes(still_s), None, None, None, []

    def feed(self, t, small, image):
        """image() → imagem da tela (só é chamado para telas candidatas; None = não guardar esta).
        Devolve [(t, imagem, miniatura)] a guardar."""
        out = []
        if self.scenes.feed(t, small):
            small = self.scenes.keys[-1]
            if any(_diff(small, s) < SIMILAR for s in self.skip):
                return out
            img = image()
            if img is None:
                self.scenes.keys.pop()  # não foi guardada: tenta de novo no próximo instante parado, em vez de
                return out              # dar a tela por vista (uma falha de uma vez perdia a tela parada para sempre)
            cand = (self.scenes.since, img, small)
            if self.last is None or _diff(small, self.last) >= SMALL or t - self.last_at >= GAP_S:
                out += self.flush(t)
                out.append(self._take(cand, t))
            else:
                self.held = cand
        if self.held and t - self.last_at >= GAP_S:
            out += self.flush(t)
        return out

    def flush(self, now=None):
        held, self.held = self.held, None
        return [self._take(held, now)] if held else []

    def _take(self, cand, now):
        self.last, self.last_at = cand[2], cand[0] if now is None else now  # GAP_S conta de quando foi guardada
        return cand


# --- anotações (Ollama) ------------------------------------------------------------------------------------------

def _words(text):
    return re.findall(r"\w+", str(text or "").lower())


def clean(d):
    """Resposta do modelo → anotação validada. keep = vale para a página."""
    d = d if isinstance(d, dict) else {}
    s = lambda k, n: str(d.get(k) or "").strip()[:n] if isinstance(d.get(k), (str, int, float)) else ""
    note = {"titulo": " ".join(s("titulo", 200).split()), "texto": s("texto", 4000), "descricao": s("descricao", 600),
            "tipo": d.get("tipo") if d.get("tipo") in KINDS else "outro", "aula": d.get("conteudo_da_aula") is True}
    # pares rótulo → valor de um gráfico, lidos na imagem (o texto solto "5.200 ms / Bubble sort / 180 ms" não diz
    # de quem é cada valor); com o texto vazio (acontece em gráficos), viram o texto da tela
    pairs = d.get("valores") if isinstance(d.get("valores"), list) else []
    note["valores"] = [{"rotulo": " ".join(str(p["rotulo"]).split())[:80], "valor": " ".join(str(p["valor"]).split())[:40]}
                       for p in pairs[:40] if isinstance(p, dict) and str(p.get("rotulo") or "").strip()
                       and str(p.get("valor") or "").strip()]
    if not note["texto"] and note["valores"]:
        note["texto"] = "\n".join(f"{p['rotulo']}: {p['valor']}" for p in note["valores"])
    # rosto com o nome escrito, ícone, tela em branco: o modelo às vezes diz "conteúdo". Sem texto, só vale figura
    words = len(_words(note["texto"]))
    note["keep"] = (note["aula"] and note["tipo"] not in ("pessoa", "anuncio")
                    and (words >= 2 or note["tipo"] in ("diagrama", "grafico", "quadro", "demonstracao"))
                    and words + len(_words(note["descricao"])) >= 4)
    return note


# Programas do próprio estudante: a tela deles nunca é lida nem guardada (privacidade), mesmo durante a aula.
# Navegadores, players, reuniões, Telegram e Discord (aulas e transmissões) ficam para o modelo decidir.
# bench/vision_bench.py: o modelo aceitou o VS Code do aluno como “aula” mesmo sabendo a janela; por isso a lista.
STUDENT_APPS = {"code.exe", "cursor.exe", "notepad.exe", "notepad++.exe", "sublime_text.exe", "devenv.exe",
                "pycharm64.exe", "idea64.exe", "winword.exe", "excel.exe", "onenote.exe", "onenoteim.exe",
                "notion.exe", "obsidian.exe", "evernote.exe", "whatsapp.exe", "whatsapp.root.exe", "slack.exe",
                "outlook.exe", "olk.exe", "thunderbird.exe", "explorer.exe", "windowsterminal.exe", "cmd.exe",
                "powershell.exe", "pwsh.exe"}


def student_app(window):
    return bool(window) and window.rsplit(" — ", 1)[-1].lower() in STUDENT_APPS


def ask(window=None):
    """Mensagem que acompanha a imagem. window = “título — programa.exe” da janela capturada (gravação)."""
    return "Anote esta tela da aula." + (f"\nJanela: {window}" if window else "")


def read(jpeg, model, check=lambda: None, keep_alive="3m", window=None):
    import base64
    raw = llm._chat(model, SYSTEM, ask(window), check, lambda n: None, schema=SCHEMA, num_ctx=CTX,
                    temperature=0, keep_alive=keep_alive, images=[base64.b64encode(jpeg).decode()], limit=3000)
    try:
        return clean(json.loads(raw))
    except ValueError:
        return clean({})


def ready(model):
    names = llm.models() or []
    return any(n == model or n == model + ":latest" for n in names)


# --- telas guardadas de uma aula ---------------------------------------------------------------------------------

class Shots:
    """<pasta>/NNNN.jpg + index.json: tempo, estado (pending | done) e anotação de cada tela."""

    def __init__(self, folder):
        self.dir, self.lock, self.closed = Path(folder), threading.Lock(), False
        try:
            self.items = json.loads((self.dir / "index.json").read_text("utf-8"))["shots"]
        except (OSError, ValueError, KeyError):
            self.items = []

    def _save(self):
        tmp = self.dir / "index.json.tmp"
        tmp.write_text(json.dumps({"shots": self.items}, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.dir / "index.json")

    def add(self, t, jpeg, window=None):
        with self.lock:
            if self.closed or len(self.items) >= MAX_SHOTS:
                return None
            self.dir.mkdir(parents=True, exist_ok=True)
            i = len(self.items)
            (self.dir / f"{i:04d}.jpg").write_bytes(jpeg)
            self.items.append({"id": i, "t": round(float(t), 1), "state": "pending", "note": None, "window": window})
            self._save()
            return i

    def done(self, i, note):
        with self.lock:
            if self.closed:
                return
            self.items[i].update(state="done", note=note)
            if not note["keep"]:  # sem conteúdo da aula: a imagem não serve e pode ser algo pessoal
                (self.dir / f"{i:04d}.jpg").unlink(missing_ok=True)
            self._save()

    def close(self):
        """Grava o índice final e marca a pasta como completa. Depois disso nada mais é gravado nela: uma captura
        ou leitura que termine atrasada não recria a pasta descartada nem muda a que já foi para a aula."""
        with self.lock:
            self.closed = True
            self.dir.mkdir(parents=True, exist_ok=True)
            self._save()
            (self.dir / "complete").touch()

    def image(self, i):
        return (self.dir / f"{int(i):04d}.jpg").read_bytes()

    def pending(self):
        with self.lock:
            return [s["id"] for s in self.items if s["state"] == "pending"]

    def prune(self, keep_ids):
        """Apaga as imagens que não foram para a página (a anotação fica, para “Refazer página”)."""
        if not self.items:
            return
        with self.lock:
            for s in self.items:
                if s["id"] not in keep_ids:
                    (self.dir / f"{s['id']:04d}.jpg").unlink(missing_ok=True)
                    if s["note"]:
                        s["note"]["keep"] = False
            self._save()


def _lines(note):
    """Linhas do texto da tela, na ordem e com todos os símbolos (“x > 0” e “x < 0”, “x²” e “x2” são telas
    diferentes); só caixa, espaços, marcadores de tópico e acentos compostos de jeitos diferentes são igualados
    (NFC; o NFKC trocaria “²” por “2”). Sem texto: título + figura."""
    out = []
    for ln in (note["texto"] or note["titulo"] + "\n" + note["descricao"]).splitlines():
        ln = " ".join(re.sub(r"^\s*[•◦▪‣\-–—*]\s+", "", unicodedata.normalize("NFC", ln)).casefold().split())
        if ln:
            out.append(ln)
    return out


def _within(big, small):
    """Todas as linhas de `small` aparecem em `big`, na mesma ordem."""
    rest = iter(big)
    return all(line in rest for line in small)


def select(items):
    """Anotações que valem para a página, sem perder conteúdo: uma tela igual a uma já escolhida (slide que voltou)
    conta uma vez; um slide que vai ganhando tópicos vira um só (o mais completo, com o tempo em que apareceu) só
    quando todas as linhas do anterior continuam no seguinte. Qualquer linha diferente mantém as duas."""
    out = []
    for s in sorted((s for s in items if s["state"] == "done" and s["note"] and s["note"]["keep"]),
                    key=lambda s: s["t"]):
        lines = _lines(s["note"])
        if any(_lines(o["note"]) == lines for o in out):
            continue
        if out:
            prev = _lines(out[-1]["note"])
            if prev and _within(lines, prev):  # a anterior continua inteira nesta: fica a mais completa
                out[-1] = {**s, "t": out[-1]["t"]}
                continue
            if lines and _within(prev, lines):  # esta é parte da anterior (um controle do player cobriu uma linha)
                continue
        out.append(s)
    return out


def screen_lines(notes):
    """(segundos, linha) para intercalar na transcrição que vai para a IA de texto."""
    out = []
    for n in notes:
        note = n["note"]
        body = " / ".join(x.strip() for x in note["texto"].splitlines() if x.strip())
        if note["descricao"]:
            body += (" " if body else "") + f"(figura: {note['descricao']})"
        out.append((n["t"], f"(na tela) {note['titulo']}: {body}"[:1500]))
    return out


# --- leitura das telas guardadas ---------------------------------------------------------------------------------

def analyze(shots, model, check, status, last=True):
    """Lê as telas pendentes. last: descarrega o modelo da VRAM depois da última (a IA de texto vem em seguida)."""
    todo = shots.pending()
    for k, i in enumerate(todo, 1):
        check()
        status(f"Lendo o que apareceu na tela ({k} de {len(todo)})…", (k - 1) / len(todo))
        shots.done(i, read(shots.image(i), model, check, keep_alive="0" if last and k == len(todo) else "3m",
                           window=shots.items[i].get("window")))


def extract(path, shots, model, check, status):
    """Vídeo de um arquivo: quadros-chave → telas novas, cada uma lida na hora (assim uma tela sem conteúdo, como o
    professor falando, não é lida de novo a cada quadro parecido)."""
    import av
    picker = Picker(still_s=0)

    def keep(found):
        for t, jpeg, small in found:
            i = shots.add(t, jpeg)
            if i is None:
                return False
            check()
            note = read(jpeg, model, check)
            shots.done(i, note)
            if note["tipo"] == "pessoa":
                picker.skip.append(small)
        return True

    try:
        with av.open(str(path)) as c:
            vs = next((s for s in c.streams.video if not s.disposition & av.stream.Disposition.attached_pic), None)
            if vs is None:
                return False  # só áudio (ou capa de MP3)
            vs.codec_context.skip_frame = "NONKEY"
            vs.thread_type = "AUTO"
            total = (c.duration or 0) / 1_000_000
            for frame in c.decode(vs):
                t = float(frame.time or 0)
                status(f"Assistindo o vídeo e lendo a tela… ({llm.fmt_time(t)})", t / total if total else None)
                small = _small(frame.to_ndarray(format="gray", width=GRID[1] * 4, height=GRID[0] * 4,
                                                interpolation="AREA"))
                image = lambda f=frame: _encode(av.VideoFrame.from_ndarray(_trim(f.to_ndarray(format="rgb24")),  # noqa
                                                                         format="rgb24"))
                if not keep(picker.feed(t, small, image)):
                    break
            keep(picker.flush())
    except av.error.FFmpegError:
        return False
    return True


# --- captura da tela durante a gravação --------------------------------------------------------------------------

class Screen:
    """Captura do monitor onde está a janela em foco (GDI do Windows via ctypes). Thread-safe por instância."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        self.c, self.w = ctypes, w
        u, g = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        u.GetDC.restype, u.GetDC.argtypes = w.HDC, [w.HWND]
        u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        u.GetForegroundWindow.restype = w.HWND
        u.MonitorFromWindow.restype, u.MonitorFromWindow.argtypes = w.HMONITOR, [w.HWND, w.DWORD]
        u.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.c_void_p]
        u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.FindWindowW.restype, u.FindWindowW.argtypes = w.HWND, [w.LPCWSTR, w.LPCWSTR]
        u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.IsWindowVisible.argtypes = u.IsIconic.argtypes = [w.HWND]
        u.WindowFromPoint.restype, u.WindowFromPoint.argtypes = w.HWND, [w.POINT]
        u.GetAncestor.restype, u.GetAncestor.argtypes = w.HWND, [w.HWND, w.UINT]
        u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
        u.GetWindow.restype, u.GetWindow.argtypes = w.HWND, [w.HWND, w.UINT]
        u.GetWindowLongW.restype, u.GetWindowLongW.argtypes = ctypes.c_long, [w.HWND, ctypes.c_int]
        k = ctypes.WinDLL("kernel32")
        k.OpenProcess.restype, k.OpenProcess.argtypes = w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.k = k
        try:
            self.dwm = ctypes.WinDLL("dwmapi")
            self.dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
        except OSError:
            self.dwm = None
        g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = w.HDC, [w.HDC]
        g.CreateCompatibleBitmap.restype = w.HBITMAP
        g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
        g.SelectObject.restype, g.SelectObject.argtypes = w.HGDIOBJ, [w.HDC, w.HGDIOBJ]
        g.BitBlt.argtypes = [w.HDC] + [ctypes.c_int] * 4 + [w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
        g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
        g.DeleteObject.argtypes, g.DeleteDC.argtypes = [w.HGDIOBJ], [w.HDC]
        self.u, self.g = u, g
        try:  # coordenadas e pixels reais em telas com escala (125%, 150%…), só nesta thread
            u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            pass

    def _title(self, hwnd):
        buf = self.c.create_unicode_buffer(256)
        self.u.GetWindowTextW(hwnd, buf, 256)
        return buf.value

    def _class(self, hwnd):
        buf = self.c.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        return buf.value

    SHELL = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}  # área de trabalho e barra de tarefas

    def window_at(self, points):
        """A janela (de nível superior) que contém a maioria dos pontos da tela, fora o Lumen e a área de trabalho."""
        votes = {}
        for x, y in points:
            h = self.u.WindowFromPoint(self.w.POINT(int(x), int(y)))
            root = self.u.GetAncestor(h, 2) if h else None  # 2 = GA_ROOT
            if root:
                votes[root] = votes.get(root, 0) + 1
        for hwnd in sorted(votes, key=votes.get, reverse=True):
            if self._class(hwnd) not in self.SHELL and not self._title(hwnd).startswith("Lumen"):
                return hwnd
        return None

    def rect(self, hwnd):
        """Borda visível da janela (sem a moldura invisível de redimensionar, que mostraria o que está atrás)."""
        r = self.w.RECT()
        ok = self.dwm and self.dwm.DwmGetWindowAttribute(hwnd, 9, self.c.byref(r), self.c.sizeof(r)) == 0
        if not ok and not self.u.GetWindowRect(hwnd, self.c.byref(r)):  # 9 = DWMWA_EXTENDED_FRAME_BOUNDS
            return None
        return r.left, r.top, r.right, r.bottom

    def label(self, hwnd):
        """“título — programa.exe”, para o modelo saber se é o player da aula ou um programa do estudante."""
        pid = self.w.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, self.c.byref(pid))
        exe = ""
        h = self.k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            buf, n = self.c.create_unicode_buffer(520), self.w.DWORD(520)
            if self.k.QueryFullProcessImageNameW(h, 0, buf, self.c.byref(n)):
                exe = os.path.basename(buf.value)
            self.k.CloseHandle(h)
        return f"{self._title(hwnd)[:150]} — {exe}".strip(" —")

    def _bitmap(self, width, height, draw):
        """draw(dc de memória, dc da tela) desenha num bitmap width×height; devolve BGRA (h×w×4) ou None."""
        c, g, u = self.c, self.g, self.u
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        bmp = g.CreateCompatibleBitmap(screen, width, height)
        old = g.SelectObject(mem, bmp)
        try:
            if not draw(mem, screen):
                return None
            # BITMAPINFOHEADER de 32 bits, de cima para baixo (altura negativa), + 1 cor que o GDI não usa
            info = (c.c_uint32 * 11)(40, width, (-height) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0, 0)
            buf = np.empty((height, width, 4), np.uint8)
            return buf if g.GetDIBits(mem, bmp, 0, height, buf.ctypes.data, info, 0) == height else None
        finally:
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(None, screen)

    def window_image(self, hwnd):
        """O conteúdo da própria janela (PrintWindow com PW_RENDERFULLCONTENT: o Windows desenha a janela, inclusive
        vídeo da GPU), sem o que estiver por cima dela: avisos, outros programas, a barra do Lumen. None se o
        programa não se deixa desenhar assim (sai preto)."""
        wr = self.w.RECT()
        box = self.rect(hwnd)
        if not box or not self.u.GetWindowRect(hwnd, self.c.byref(wr)) or wr.right <= wr.left or wr.bottom <= wr.top:
            return None
        buf = self._bitmap(wr.right - wr.left, wr.bottom - wr.top, lambda mem, _: self.u.PrintWindow(hwnd, mem, 2))
        if buf is None:
            return None
        img = buf[max(box[1] - wr.top, 0):box[3] - wr.top, max(box[0] - wr.left, 0):box[2] - wr.left]
        return img if img.size and img[::8, ::8, :3].max() > 16 else None

    def grab(self):
        """(BGRA h×w×4 do monitor, barra do Lumen nele ou None, canto (x, y) do monitor na tela).

        None se a janela principal do Lumen está na frente (você está mexendo nele, não assistindo). A barra
        flutuante não conta: clicar em Gravar nela a deixa em primeiro plano, e a aula continua atrás."""
        c, w, u, g = self.c, self.w, self.u, self.g
        fg = u.GetForegroundWindow()
        if fg and self._title(fg) == "Lumen":
            return None

        class MONITORINFO(c.Structure):
            _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]
        mi = MONITORINFO(cbSize=c.sizeof(MONITORINFO))
        if not u.GetMonitorInfoW(u.MonitorFromWindow(fg, 1), c.byref(mi)):  # 1 = MONITOR_DEFAULTTOPRIMARY
            return None
        r = mi.rcMonitor
        x, y, width, height = r.left, r.top, r.right - r.left, r.bottom - r.top
        # a cópia da tela só serve para ver o que mudou; a imagem guardada vem de window_image
        buf = self._bitmap(width, height, lambda mem, screen: g.BitBlt(mem, 0, 0, width, height, screen, x, y,
                                                                         0x00CC0020))  # SRCCOPY
        if buf is None:
            return None
        bar = None
        hwnd = u.FindWindowW(None, "Lumen · barra flutuante")
        rect = w.RECT()
        if hwnd and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd) and u.GetWindowRect(hwnd, c.byref(rect)):
            bar = (rect.left - x, rect.top - y, rect.right - x, rect.bottom - y)
        return buf, bar, (x, y)


class Watch:
    """Assiste a tela durante uma gravação: captura (1×/s) e lê as telas novas entre uma e outra.

    clock() = segundos já gravados (o tempo das telas segue o do áudio). paused() = True enquanto outra aula está
    sendo processada (a GPU fica para ela; as telas esperam). live = ler durante a gravação (só com GPU).

    Cada tela é recortada na janela onde a mudança aconteceu (o navegador com a aula, não a tela inteira com
    outros programas), e o modelo recebe o título e o programa dessa janela: o player da aula conta; as suas
    anotações, o seu editor ou um chat não, mesmo falando da matéria."""

    def __init__(self, folder, clock, model, paused=lambda: False, live=True, grabber=None):
        self.shots, self.clock, self.model, self.paused, self.live = Shots(folder), clock, model, paused, live
        self.picker, self.grabber, self.stop_ev, self.q = Picker(), grabber, threading.Event(), queue.Queue()
        self.smalls, self.mask, self.read_n, self.failed = {}, np.zeros(GRID, bool), 0, False
        self.refused, self.why = 0, ""  # capturas não guardadas e o último motivo (aparece durante a gravação)
        self.screen = None
        self.threads = [threading.Thread(target=self._capture, daemon=True)]
        if live:
            self.threads.append(threading.Thread(target=self._analyze, daemon=True))
        for t in self.threads:
            t.start()

    def counts(self):
        items = self.shots.items
        return {"seen": len(items), "read": self.read_n,
                "kept": sum(1 for s in items if s["note"] and s["note"]["keep"]),
                "refused": self.refused, "why": self.why}

    def _refuse(self, why):
        self.refused, self.why = self.refused + 1, why
        return None

    def _small(self, bgra, bar):
        small = _small(bgra[::4, ::4, 1])  # canal verde ≈ brilho; 1 pixel a cada 4 basta para a miniatura
        if bar:  # a barra do Lumen não conta como mudança de tela (fica mascarada até o fim)
            h, w = bgra.shape[:2]
            x1, y1 = max(bar[0] * GRID[1] // w, 0), max(bar[1] * GRID[0] // h, 0)
            x2, y2 = min(-(-bar[2] * GRID[1] // w), GRID[1]), min(-(-bar[3] * GRID[0] // h), GRID[0])
            self.mask[y1:y2, x1:x2] = True
        small[self.mask] = 0
        return small

    def _capture(self):
        import av
        try:
            self.screen = self.grabber or Screen()
        except (OSError, AttributeError):
            return  # sem Windows/GDI: grava só o áudio
        while not self.stop_ev.is_set():
            start = time.monotonic()
            try:
                got = self.screen.grab()
            except OSError:
                got = None
            if got:
                bgra, bar, origin = got
                small = self._small(bgra, bar)
                found = self.picker.feed(self.clock(), small, lambda: self._image(bgra, small, origin, av))
                self._keep(found)
            self.stop_ev.wait(max(INTERVAL_S - (time.monotonic() - start), 0.05))
        self._keep(self.picker.flush())

    def _image(self, bgra, small, origin, av):
        """(JPEG da janela onde a tela mudou, rótulo dela) ou None para não guardar.

        A primeira tela, sem mudança para comparar, usa a janela que ocupa mais o monitor. Nunca guarda a tela
        inteira nem pixels de outras janelas: a imagem vem só da própria janela (window_image). Se o programa não
        se deixar desenhar assim, a tela não é guardada: recortar a cópia da tela levaria junto o que estivesse por
        cima, e saber o que estava por cima no instante da cópia não é confiável. Sem janela clara, programa do
        estudante ou janela pequena (aviso, menu): também não guarda."""
        h, w = bgra.shape[:2]
        keys = self.picker.scenes.keys  # a candidata já é a última; compara com a tela distinta anterior
        ref = keys[-2] if len(keys) >= 2 else None
        if ref is None:
            cells = [(r, c) for r in np.linspace(5, GRID[0] - 6, 5) for c in np.linspace(9, GRID[1] - 10, 5)]
        else:
            changed = np.argwhere((np.abs(small - ref) > DELTA) & ~self.picker.scenes.live)
            cells = changed[np.linspace(0, len(changed) - 1, min(len(changed), 25)).astype(int)] if len(changed) else []
        hwnd = self.screen.window_at([(origin[0] + (c + .5) * w / GRID[1], origin[1] + (r + .5) * h / GRID[0])
                                      for r, c in cells]) if len(cells) else None
        if not hwnd:
            return self._refuse("não achei a janela da aula")
        label = self.screen.label(hwnd)
        box = self.screen.rect(hwnd)
        if student_app(label):
            return self._refuse("a janela em uso é de um programa seu (privacidade)")
        if not box or box[2] - box[0] < 320 or box[3] - box[1] < 180:
            return self._refuse("a janela em uso é pequena demais")
        img = self.screen.window_image(hwnd)
        if img is None or not img.size:
            return self._refuse("o programa não deixou o Lumen desenhar a janela (sai preta)")
        return _encode(av.VideoFrame.from_ndarray(_trim(np.ascontiguousarray(img)), format="bgra")), label

    def _keep(self, found):
        for t, (jpeg, window), small in found:
            i = self.shots.add(t, jpeg, window)
            if i is not None:
                self.smalls[i] = small
                self.q.put(i)

    def _analyze(self):
        while not self.stop_ev.is_set():
            try:
                i = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            while self.paused() and not self.stop_ev.is_set():
                time.sleep(1)
            if self.stop_ev.is_set() or self.failed:
                return  # o que faltar é lido ao processar a aula
            try:
                note = read(self.shots.image(i), self.model, window=self.shots.items[i].get("window"))
            except (AppError, OSError):
                self.failed = True  # Ollama fechado ou sem o modelo: tenta de novo só ao processar
                return
            if self.stop_ev.is_set():
                return  # a gravação parou no meio desta leitura: a pasta já pode estar indo para a aula; fica pendente
            self.shots.done(i, note)
            self.read_n += 1
            if note["tipo"] == "pessoa" and i in self.smalls:
                self.picker.skip.append(self.smalls[i])

    def stop(self):
        """Termina a captura (a tela mais recente, se ainda não guardada, entra) e fecha a pasta: o que estiver nela
        é o que vale. Uma captura presa (PrintWindow num programa travado) ou uma leitura em andamento que terminem
        depois não gravam mais nada."""
        self.stop_ev.set()
        self.threads[0].join(timeout=STOP_S)
        for t in self.threads[1:]:
            t.join(timeout=0.5)
        self.shots.close()


def adopt(screens, work):
    """Move as telas da gravação para a pasta da aula (a gravação em si é apagada depois da revisão)."""
    dest = Path(work) / "screens"
    src = Path(screens)
    if src.is_dir() and not dest.exists():
        shutil.move(str(src), str(dest))
    return dest
