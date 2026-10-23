"""“Assistir a tela junto”: quais telas são guardadas, como são lidas e escolhidas, e o caminho até a página."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import sys
import types

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import jobs, llm, notion, record, server, sources, store, transcribe, vision
from tests.fake_notion import Fake
from tests.test_flow import wait
from tests.test_llm import GOOD, understood

RNG = np.random.default_rng(7)


def slide(kind, h=540, w=960, bullet=False, cam=False):
    """Tela sintética: fundo claro com “linhas de texto” escuras em posições que dependem do slide."""
    img = np.full((h, w), 235, np.uint8)
    rows = {"A": [60, 140, 220], "B": [100, 260, 380], "C": [80, 300, 420], "D": [180, 240, 300, 360]}[kind]
    for r in rows:
        img[r:r + 24, 80:80 + (700 if kind != "D" else 500)] = 30
    if bullet:
        img[450:474, 80:620] = 30  # um tópico novo aparece no mesmo slide (~2% da tela)
    if cam:  # câmera do professor num canto: muda a cada quadro
        img[h - 130:h - 10, w - 200:w - 10] = RNG.integers(0, 255, (120, 190), dtype=np.uint8)
    return img


def bgra(gray):
    return np.dstack([gray, gray, gray, np.full_like(gray, 255)])


def note(titulo="Tela", texto="linha um dois tres quatro", keep=True, tipo="slide", t=0.0, i=0):
    n = {"titulo": titulo, "texto": texto, "descricao": "", "tipo": tipo, "aula": keep, "keep": keep}
    return {"id": i, "t": t, "state": "done", "note": n}


class Scenes(unittest.TestCase):
    def run_screen(self, frames):
        """Captura 1×/s simulada: devolve os tempos das telas guardadas."""
        p, out = vision.Picker(), []
        for t, g in enumerate(frames):
            out += [round(x[0]) for x in p.feed(float(t), vision._small(g[::2, ::2]), lambda: b"jpg")]
        out += [round(x[0]) for x in p.flush()]
        return out

    def test_slides_between_a_speaker_in_a_youtube_video(self):
        # gravação real: 10 min de um vídeo do YouTube com 1 tela guardada, 5 min com nenhuma. O vídeo (80% da tela)
        # se mexe o tempo todo com a pessoa falando; ao cortar para um slide, a área só voltava a contar depois de
        # ~28 s parada, e os slides de 10–20 s nunca eram guardados
        rng = np.random.default_rng(0)

        def youtube(content):
            img = np.full((540, 960), 30, np.uint8)
            img[:40] = 60
            img[50:500, 20:820] = content[50:500, 20:820]
            return img

        def talking(n):
            return [youtube(rng.integers(0, 255, (540, 960), dtype=np.uint8)) for _ in range(n)]
        frames = (talking(40) + [youtube(slide("A"))] * 15 + talking(20) + [youtube(slide("B"))] * 12
                  + talking(10) + [youtube(slide("C"))] * 35)
        # cada slide, poucos segundos depois de aparecer (antes: só o C, aos 124 s)
        self.assertEqual(self.run_screen(frames), [41, 76, 98])

    def test_screens_in_an_edited_video_with_a_round_camera_and_captions(self):
        # gravação real: 8 min 43 s, 0 telas e nenhuma recusa. Vídeo editado em tela cheia: a imagem toda se mexe nas
        # falas, e nas telas de conteúdo uma câmera redonda e a legenda animada nunca param; a área do vídeo só voltava
        # à comparação quando a tela inteira parava (nunca)
        rng = np.random.default_rng(3)
        yy, xx = np.mgrid[0:540, 0:960]
        bubble = (yy - 430) ** 2 + (xx - 850) ** 2 < 70 ** 2

        def extras(g, t):
            g[bubble] = rng.integers(0, 255, bubble.sum())
            g[470:510, 250:710] = 20
            g[480:500, 270 + (t * 3) % 7 * 40:430 + (t * 3) % 7 * 40] = 230  # palavras da legenda trocando
            return g

        frames = []
        for kind, n in (("fala", 20), ("A", 15), ("fala", 10), ("B", 12), ("C", 18), ("fala", 15), ("D", 15)):
            for _ in range(n):
                t = len(frames)
                frames.append(extras(rng.integers(0, 255, (540, 960), dtype=np.uint8) if kind == "fala"
                                     else slide(kind), t))
        times = self.run_screen(frames)  # os slides aparecem aos 20, 45, 57 e 90 s
        self.assertEqual(len(times), 4, times)
        for shown, kept in zip((20, 45, 57, 90), times):
            self.assertLessEqual(kept - shown, 5)

    def test_a_screen_whose_image_failed_is_tried_again(self):
        # a captura da janela falhou uma vez (programa que ainda não desenhava, janela por cima…): a tela parada era dada
        # por vista e nunca mais tentada; num vídeo de aula quase parado, não sobrava nenhuma captura
        tries = []

        def image():
            tries.append(1)
            return None if len(tries) < 3 else b"jpg"
        p, out = vision.Picker(), []
        for t in range(40):
            out += p.feed(float(t), vision._small(slide("A")[::2, ::2]), image)
        self.assertEqual(len(tries), 3)  # 2 recusas, 1 guardada, e a tela parada não é guardada de novo
        self.assertEqual([round(x[0]) for x in out], [0])  # com o tempo em que apareceu

    def test_slides_bullets_and_revisit(self):
        a, b = slide("A"), slide("B")
        frames = [a] * 5 + [(a // 2 + b // 2)] + [b] * 5 + [slide("B", bullet=True)] * 5 + [slide("C")] * 5 + [a] * 5
        # A; B (depois da transição); B com o tópico novo (guardado quando o slide troca); C; A de novo não conta
        self.assertEqual(self.run_screen(frames), [0, 6, 11, 16])

    def test_professor_camera_in_a_corner(self):
        frames = ([slide("A", cam=True) for _ in range(15)] + [slide("C", cam=True) for _ in range(6)]
                  + [slide("D", cam=True) for _ in range(6)])
        times = self.run_screen(frames)
        # a câmera muda a cada captura: o Lumen aprende a ignorá-la (≈ 10 s) e depois vê cada slide na hora
        self.assertEqual(len(times), 3, times)
        self.assertLessEqual(times[0], 12)
        self.assertEqual(times[1:], [15, 21])

    def test_talking_head_is_kept_once(self):
        def head():
            g = np.full((540, 960), 120, np.uint8)
            g[60:480, 200:760] = RNG.integers(0, 255, (420, 560), dtype=np.uint8)  # pessoa se mexendo (45%)
            return g
        self.assertEqual(len(self.run_screen([head() for _ in range(30)])), 1)

    def test_whole_screen_moving_is_never_kept(self):
        self.assertEqual(self.run_screen([RNG.integers(0, 255, (540, 960), dtype=np.uint8) for _ in range(20)]), [])

    def test_typing_keeps_latest_state_every_gap(self):
        frames, g = [], slide("A")
        for t in range(70):  # uma linha nova a cada 6 s, como código sendo digitado
            if t and t % 6 == 0:
                g = g.copy()
                g[300 + t * 3:312 + t * 3, 80:600] = 30
            frames.append(g)
        times = self.run_screen(frames)
        self.assertEqual(times[0], 0)
        self.assertLess(len(times), 12, times)  # 11 linhas novas: não lê a cada uma
        self.assertEqual(times[-1], 66)  # o estado final não se perde

    def test_files_skip_frames_like_a_talking_head(self):
        def head():
            g = np.full((540, 960), 120, np.uint8)
            g[150:390, 330:630] = RNG.integers(0, 255, (240, 300), dtype=np.uint8)  # 14% da tela
            return vision._small(g[::2, ::2])
        p = vision.Picker(still_s=0)
        first = p.feed(0.0, head(), lambda: b"1")
        self.assertEqual(len(first), 1)
        p.skip.append(first[0][2])  # o modelo disse: pessoa falando
        self.assertEqual(p.feed(2.0, head(), lambda: b"2"), [])  # o professor se mexeu: não relê
        self.assertEqual(len(p.feed(4.0, vision._small(slide("A")[::2, ::2]), lambda: b"3")), 1)
        # dois slides com pouco texto diferem em ~23%: o segundo não pode ser tratado como o primeiro “crescendo”
        self.assertEqual(len(p.feed(6.0, vision._small(slide("B")[::2, ::2]), lambda: b"4")), 1)


class Cleanup(unittest.TestCase):
    def test_old_screens_are_purged(self):
        store.clear_local_data()
        old, new = jobs.work_dir("file:velha") / "screens", jobs.work_dir("file:nova") / "screens"
        rec = store.WORK / "uploads" / "ab12cd34_Aula.screens"
        for d in (old, new, rec):
            vision.Shots(d).add(1.0, b"jpg")
        week = time.time() - 8 * 86400
        for d in (old, rec):
            os.utime(d, (week, week))
        store.purge_old_uploads()
        self.assertEqual([old.exists(), new.exists(), rec.exists()], [False, True, False])
        self.assertTrue((old.parent).exists())  # a transcrição da aula continua (retomar)


class Small(unittest.TestCase):
    def test_covers_the_whole_screen_at_any_resolution(self):
        for h, w in ((768, 1366), (1080, 1920), (900, 1440), (135, 240)):
            g = np.zeros((h, w), np.uint8)
            g[-3:, -3:] = 255  # canto inferior direito
            s = vision._small(g)
            self.assertEqual(s.shape, vision.GRID)
            self.assertGreater(s[-1, -1], 0, (h, w))


class Notes(unittest.TestCase):
    def test_clean_rejects_empty_or_person(self):
        good = {"titulo": "Lei de Ohm", "texto": "V = R · I\nR: resistência", "descricao": "", "tipo": "slide",
                "conteudo_da_aula": True}
        self.assertTrue(vision.clean(good)["keep"])
        self.assertFalse(vision.clean({**good, "texto": "Prof. Marina", "titulo": ""})["keep"])  # rosto com nome
        self.assertFalse(vision.clean({**good, "tipo": "anuncio"})["keep"])
        icon = {**good, "texto": "", "titulo": "Ícone", "descricao": "Mostra um ícone de perfil de usuário genérico"}
        self.assertFalse(vision.clean(icon)["keep"])                       # sem texto e não é figura
        self.assertTrue(vision.clean({**icon, "tipo": "diagrama"})["keep"])  # diagrama só com setas e formas
        self.assertFalse(vision.clean({**good, "conteudo_da_aula": False})["keep"])
        self.assertEqual(vision.clean("lixo")["keep"], False)

    def test_select_merges_builds_and_drops_repeats(self):
        items = [note("Agenda", "Fotossíntese\n• fase clara", t=10, i=0),
                 note("Agenda", "Fotossíntese\n- fase clara\n- fase escura (Calvin)", t=25, i=1),  # o mesmo, completo
                 note("Rosto", "x", keep=False, t=30, i=2),
                 note("Tabela", "Algoritmo | Pior caso\nQuicksort | O(n²)", t=40, i=3),
                 note("Tabela", "Algoritmo | Pior caso", t=45, i=5),  # o controle do player cobriu uma linha
                 note("Agenda", "fotossíntese\nfase clara\nfase escura (calvin)", t=90, i=4)]  # voltou
        got = vision.select(items)
        self.assertEqual([(s["id"], s["t"]) for s in got], [(1, 10), (3, 40)])

    def test_select_keeps_screens_that_differ_only_in_symbols_or_order(self):
        # revisão do Codex: o conjunto de palavras juntava telas com operadores ou ordem diferentes
        items = [note("Condição", "Condição de validade\nx > 0", t=10, i=0),
                 note("Condição", "Condição de validade\nx < 0", t=20, i=1),
                 note("Ordem", "primeiro A\ndepois B", t=30, i=2),
                 note("Ordem", "depois B\nprimeiro A", t=40, i=3),
                 note("Código", "x = a - b", t=50, i=4),
                 note("Código", "x = a + b", t=60, i=5),
                 note("Fórmula", "y = x² + 1", t=70, i=6),  # 2ª revisão: o NFKC trocava “²” por “2”
                 note("Fórmula", "y = x2 + 1", t=80, i=7),
                 note("Acento", "func\u0327a\u0303o", t=90, i=8),  # “ç” e “ã” escritos em duas partes
                 note("Acento", "função", t=100, i=9)]
        self.assertEqual([s["id"] for s in vision.select(items)], [0, 1, 2, 3, 4, 5, 6, 7, 8])

    def test_trim_removes_black_bars_only(self):
        img = np.zeros((540, 960, 3), np.uint8)
        img[:, 120:840] = 200       # vídeo 4:3 numa tela 16:9
        img[300:310, 200:400] = 10  # texto escuro dentro do slide não é borda
        self.assertEqual(vision._trim(img).shape, (540, 720, 3))
        dark = np.full((540, 960, 3), 15, np.uint8)
        dark[200:220, 300:700] = 255  # tela quase toda escura (tema escuro com um texto): não corta
        self.assertEqual(vision._trim(dark).shape, (540, 960, 3))

    def test_screen_lines_go_in_time_order_into_the_transcript(self):
        lines = vision.screen_lines([note("Lei de Ohm", "V = R · I\nI: corrente", t=35)])
        self.assertEqual(lines, [(35, "(na tela) Lei de Ohm: V = R · I / I: corrente")])
        segs = [{"start": 0.0, "end": 31.0, "text": "Hoje vamos ver eletricidade."},
                {"start": 40.0, "end": 50.0, "text": "A tensão é resistência vezes corrente."}]
        self.assertEqual(llm.transcript_text(segs, lines).split("\n"),
                         ["[00:00] Hoje vamos ver eletricidade.", "[00:35] (na tela) Lei de Ohm: V = R · I / I: corrente",
                          "[00:40] A tensão é resistência vezes corrente."])

    def test_read_sends_image_and_schema(self):
        answer = json.dumps({"titulo": "T", "texto": "um dois tres quatro", "descricao": "", "tipo": "slide",
                             "conteudo_da_aula": True})
        with mock.patch.object(llm, "_chat", return_value=answer) as chat:
            n = vision.read(b"\xff\xd8jpeg", vision.MODEL)
        self.assertTrue(n["keep"])
        kw = chat.call_args.kwargs
        self.assertEqual(kw["images"], ["/9hqcGVn"])
        self.assertEqual(kw["schema"], vision.SCHEMA)
        self.assertEqual(kw["temperature"], 0)


def make_video(path, scenes, fps=5, size=(320, 180)):
    """MP4 (MPEG-4 Part 2, quadro-chave a cada 2 s) a partir de [(segundos, função que desenha o quadro)]."""
    import av
    with av.open(path, "w") as c:
        s = c.add_stream("mpeg4", rate=fps)
        s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        s.codec_context.gop_size = fps * 2
        for secs, draw in scenes:
            for _ in range(secs * fps):
                g = draw()
                for pkt in s.encode(av.VideoFrame.from_ndarray(np.dstack([g, g, g]), format="rgb24")):
                    c.mux(pkt)
        for pkt in s.encode(None):
            c.mux(pkt)


def fake_read(jpeg, model, check=lambda: None, keep_alive="3m"):
    """“Modelo” que reconhece as telas sintéticas pelo desenho."""
    import io
    import av
    with av.open(io.BytesIO(jpeg)) as c:
        g = next(c.decode(video=0)).to_ndarray(format="gray").astype(float)
    h, w = g.shape
    if np.abs(np.diff(g[int(h * .3):int(h * .7), int(w * .35):int(w * .65)], axis=1)).mean() > 20:  # ruído = rosto
        return vision.clean({"titulo": "", "texto": "", "descricao": "", "tipo": "pessoa",
                             "conteudo_da_aula": False})
    name = "A" if g[int(h * .36):int(h * .44)].mean() < 150 else "B"
    return vision.clean({"titulo": f"Slide {name}", "texto": f"slide {name} com quatro palavras", "descricao": "",
                         "tipo": "slide", "conteudo_da_aula": True})


class Extract(unittest.TestCase):
    def test_keyframes_to_notes(self):
        small = lambda k: lambda: slide(k, 180, 320)  # noqa: E731

        def head():  # professor falando: muda a cada quadro-chave, mas pouco da tela (14%)
            g = np.full((180, 320), 120, np.uint8)
            g[50:130, 110:210] = RNG.integers(0, 255, (80, 100), dtype=np.uint8)
            return g
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "aula.mp4")
            make_video(video, [(6, small("A")), (6, head), (6, small("B")), (6, small("A"))])
            shots = vision.Shots(os.path.join(tmp, "telas"))
            with mock.patch.object(vision, "read", side_effect=fake_read) as read:
                self.assertTrue(vision.extract(video, shots, vision.MODEL, lambda: None, lambda d, p: None))
            # A, o rosto (lido uma vez só, apesar de mudar a cada quadro-chave) e B; A de novo não é relido
            self.assertEqual(read.call_count, 3)
            got = vision.select(shots.items)
            self.assertEqual([(s["note"]["titulo"], s["t"]) for s in got], [("Slide A", 0.0), ("Slide B", 12.0)])
            self.assertEqual(sorted(os.listdir(shots.dir)), ["0000.jpg", "0002.jpg", "index.json"])  # rosto apagado

    def test_audio_only_has_no_screens(self):
        import av
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.wav")
            with av.open(path, "w") as c:
                s = c.add_stream("pcm_s16le", rate=16000)
                f = av.AudioFrame.from_ndarray(np.zeros((1, 16000), np.int16), format="s16", layout="mono")
                f.sample_rate = 16000
                for p in s.encode(f):
                    c.mux(p)
            self.assertFalse(vision.extract(path, vision.Shots(tmp), vision.MODEL, lambda: None, lambda d, p: None))


class FakeScreen:
    """Monitor 960×540 com duas janelas: a aula no navegador à esquerda (x < 640) e as anotações à direita."""

    SPLIT = 640  # onde a aula termina e as anotações começam

    def __init__(self, frames):
        self.frames, self.n = frames, 0

    def grab(self):
        g = self.frames[min(self.n, len(self.frames) - 1)]
        self.n += 1
        return bgra(g), (900, 0, 960, 540), (0, 0)  # barra do Lumen na borda direita

    def window_at(self, points, allow=lambda h: True):  # como Screen.window_at
        left = sum(x < self.SPLIT for x, _ in points)
        votes = {"aula": left, "notas": len(points) - left}
        ranked = ["aula", "notas"] if left * 2 >= len(points) else ["notas", "aula"]
        return next((h for h in ranked if votes[h] * 10 >= len(points) and allow(h)), ranked[0])

    def rect(self, hwnd):
        return (0, 0, self.SPLIT, 540) if hwnd == "aula" else (self.SPLIT, 0, 960, 540)

    def label(self, hwnd):
        return "Aula 4 - YouTube — msedge.exe" if hwnd == "aula" else "Minhas anotações - Notion — Notion.exe"

    def window_image(self, hwnd):  # o conteúdo da janela, sem o que está por cima (como o PrintWindow)
        l, t, r, b = self.rect(hwnd)
        return bgra(self.frames[min(self.n, len(self.frames)) - 1])[t:b, l:r]



RED = np.array([0, 0, 255, 255], np.uint8)  # BGRA


def with_popup(g):
    """A tela com uma conversa particular aberta por cima do vídeo da aula (em vermelho)."""
    img = bgra(g)
    img[200:320, 200:420] = RED
    return img


class Private(unittest.TestCase):
    """Revisão do Codex: recortar a janela da aula na cópia da tela levava junto o que estivesse por cima dela."""

    def run_watch(self, screen, frames=15):
        jpegs = []

        def fake(jpeg, *a, **k):
            jpegs.append(jpeg)
            return note()["note"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", side_effect=fake):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > frames + 3 and w.q.empty():
                    break
                time.sleep(0.01)
            w.stop()
        return jpegs

    @staticmethod
    def pixels(jpeg):
        import io
        import av
        with av.open(io.BytesIO(jpeg)) as c:
            return next(c.decode(video=0)).to_ndarray(format="rgb24")

    def test_window_content_leaves_out_what_is_on_top(self):
        class Popup(FakeScreen):
            def grab(self):
                g, bar, origin = super().grab()
                return with_popup(g[..., 0]), bar, origin
        jpegs = self.run_watch(Popup([slide("A")] * 5 + [slide("B")] * 10))
        self.assertTrue(jpegs)
        for j in jpegs:
            p = self.pixels(j)
            self.assertFalse(((p[..., 0] > 200) & (p[..., 1] < 80)).any(), "a conversa por cima foi parar na imagem")

    def test_window_that_cannot_be_drawn_alone_is_not_saved(self):
        # 2ª revisão do Codex: cobrir na cópia da tela o que estava por cima usava as janelas de depois da cópia;
        # uma conversa que fechasse ou mudasse de lugar nesse meio ficava na imagem
        class Popup(FakeScreen):
            def grab(self):
                g, bar, origin = super().grab()
                return with_popup(g[..., 0]), bar, origin

            def window_image(self, hwnd):  # programa que não se deixa desenhar
                return None
        self.assertEqual(self.run_watch(Popup([slide("A")] * 5 + [slide("B")] * 10)), [])

    def test_a_window_that_refuses_at_first_is_saved_when_it_allows(self):
        class Late(FakeScreen):
            asked = 0

            def window_image(self, hwnd):
                Late.asked += 1
                return None if Late.asked <= 3 else super().window_image(hwnd)
        jpegs = self.run_watch(Late([slide("A")] * 30))
        self.assertEqual(len(jpegs), 1)  # a mesma tela, parada o tempo todo, entra quando a janela deixa

    def test_an_error_on_one_screen_does_not_stop_the_capture(self):
        # antes, qualquer erro que não fosse OSError matava a thread da captura em silêncio, pelo resto da gravação
        class Flaky(FakeScreen):
            asked = 0

            def window_image(self, hwnd):
                Flaky.asked += 1
                if Flaky.asked == 1:
                    raise ValueError("imagem estranha")
                return super().window_image(hwnd)
        with self.assertLogs("lumen", "WARNING"):
            jpegs = self.run_watch(Flaky([slide("A")] * 6 + [slide("B")] * 9))
        self.assertEqual(len(jpegs), 2)  # A (na 2ª tentativa) e B

    def test_the_recording_says_why_nothing_was_captured(self):
        reasons = {}
        for name, patchw in (("sem janela", {"window_at": lambda self, pts, allow=None: None}),
                             ("privado", {"label": lambda self, h: "Meu código — Code.exe"}),
                             ("pequena", {"rect": lambda self, h: (0, 0, 300, 100)}),
                             ("preta", {"window_image": lambda self, h: None})):
            screen = type("S", (FakeScreen,), patchw)([slide("A")] * 12)
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01):
                w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
                for _ in range(500):
                    if screen.n > 14:
                        break
                    time.sleep(0.01)
                w.stop()
                reasons[name] = w.counts()
        self.assertTrue(all(c["seen"] == 0 and c["refused"] > 0 for c in reasons.values()))
        self.assertEqual([c["why"].split(" ")[0:3] for c in reasons.values()],
                         [["não", "achei", "a"], ["a", "janela", "em"], ["a", "janela", "em"], ["o", "programa", "não"]])

    def test_no_clear_window_or_small_window_is_not_saved(self):
        class Nowhere(FakeScreen):
            def window_at(self, points, allow=None):
                return None
        self.assertEqual(self.run_watch(Nowhere([slide("A")] * 5 + [slide("B")] * 10)), [])  # nada da tela inteira

        class Toast(FakeScreen):
            def rect(self, hwnd):
                return (600, 440, 900, 520)  # um aviso de 300×80
        self.assertEqual(self.run_watch(Toast([slide("A")] * 5 + [slide("B")] * 10)), [])


class Watching(unittest.TestCase):
    def test_capture_stuck_after_stop_writes_nothing(self):
        # 2ª revisão do Codex: PrintWindow preso além da espera de stop() voltava depois e gravava na pasta já
        # descartada (ou já movida para a aula)
        entered, release = threading.Event(), threading.Event()

        class Stuck(FakeScreen):
            calls = 0

            def window_image(self, hwnd):
                self.calls += 1
                if self.calls > 1:  # a 2ª tela: o programa trava enquanto é desenhado
                    entered.set()
                    release.wait(5)
                return super().window_image(hwnd)
        screen = Stuck([slide("A")] * 5 + [slide("B")] * 10)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "STOP_S", 0.1), \
                mock.patch.object(vision, "read", side_effect=lambda *a, **k: note()["note"]):
            folder = os.path.join(tmp, "g.screens")
            w = vision.Watch(folder, lambda: float(screen.n), vision.MODEL, grabber=screen)
            self.assertTrue(entered.wait(5))
            w.stop()
            self.assertTrue(w.threads[0].is_alive())  # ainda presa
            self.assertTrue(os.path.exists(os.path.join(folder, "complete")))
            self.assertEqual(len(w.shots.items), 1)
            import shutil
            shutil.rmtree(folder)  # a gravação foi descartada
            release.set()
            w.threads[0].join(5)
            self.assertFalse(w.threads[0].is_alive())
            self.assertFalse(os.path.exists(folder))  # não recriou a pasta
            self.assertEqual(len(w.shots.items), 1)

    def test_live_capture_reads_between_slides(self):
        frames = [slide("A")] * 5 + [slide("B")] * 5 + [slide("C")] * 5
        screen = FakeScreen(frames)
        notes = iter([note()["note"], {**note()["note"], "keep": False}, note()["note"]])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", side_effect=lambda *a, **k: dict(next(notes))):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > len(frames) + 3 and w.read_n == 3:
                    break
                time.sleep(0.01)
            w.stop()
            self.assertEqual(w.counts(), {"seen": 3, "read": 3, "kept": 2, "refused": 0, "why": ""})
            self.assertTrue((w.shots.dir / "complete").exists())
            self.assertFalse((w.shots.dir / "0001.jpg").exists())  # tela sem conteúdo: apagada na hora
            self.assertTrue(w.mask[:, -4:].all() and not w.mask[:, :80].any())  # barra do Lumen fora da comparação

    def test_crops_to_the_lesson_window_and_ignores_notes(self):
        def frame(kind, note_lines=0):
            g = slide(kind)
            g[:, 640:] = 250  # janela das anotações
            for k in range(note_lines):
                g[40 + k * 40:60 + k * 40, 680:900] = 40
            return g
        frames = [frame("A")] * 5 + [frame("B")] * 5 + [frame("B", 3)] * 5 + [frame("C", 3)] * 5
        screen = FakeScreen(frames)
        sizes, windows = [], []

        def fake(jpeg, *a, window=None, **k):
            import io
            import av
            with av.open(io.BytesIO(jpeg)) as c:
                sizes.append(next(c.decode(video=0)).width)
            windows.append(window)
            return note()["note"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", side_effect=fake):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > len(frames) + 3 and w.read_n == 3:
                    break
                time.sleep(0.01)
            w.stop()
        # A (a janela que ocupa mais a tela), B e C recortados na janela da aula; as 3 linhas digitadas nas
        # anotações (Notion) não viram tela nem vão para o modelo
        self.assertEqual(sizes, [640, 640, 640])
        self.assertEqual(windows, ["Aula 4 - YouTube — msedge.exe"] * 3)
        self.assertEqual(w.counts()["seen"], 3)

    def test_first_screen_in_student_app_does_not_block_the_lesson(self):
        class Notes(FakeScreen):  # no começo, só as anotações aparecem
            def window_at(self, points, allow=None):
                return "notas" if self.n < 6 else super().window_at(points, allow)
        screen = Notes([slide("A")] * 5 + [slide("B")] * 5 + [slide("C")] * 5)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01),                 mock.patch.object(vision, "read", return_value=note()["note"]):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > 18 and w.read_n == 2:
                    break
                time.sleep(0.01)
            w.stop()
        self.assertEqual([s["window"] for s in w.shots.items], ["Aula 4 - YouTube — msedge.exe"] * 2)  # B e C

    def windows_kept(self, screen, frames):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", return_value=note()["note"]):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > frames + 3 and w.q.empty():
                    break
                time.sleep(0.01)
            w.stop()
        return [s["window"].split(" - ")[0] for s in w.shots.items]

    def test_review_says_nothing_was_captured_and_why(self):
        # gravação sem nenhuma tela: a revisão dizia “nenhuma tela com conteúdo da aula foi encontrada”, como se as
        # telas tivessem sido lidas e descartadas
        from lumen import jobs
        screen = type("S", (FakeScreen,), {"window_image": lambda self, h: None})([slide("A")] * 12)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01):
            work = Path(tmp)
            w = vision.Watch(work / "screens", lambda: float(screen.n), vision.MODEL, grabber=screen)
            for _ in range(500):
                if screen.n > 14:
                    break
                time.sleep(0.01)
            w.stop()
            with self.assertLogs("lumen", "INFO"):
                out = jobs._screens({"kind": "recording"}, work, {"watch_screen": True})
        self.assertEqual((out["items"], out["seen"]), ([], 0))
        self.assertIn("Nenhuma tela foi guardada durante a gravação (o programa não deixou", out["warning"])

    def test_student_app_bigger_than_the_lesson_does_not_block_it(self):
        # gravação real: 0 telas. O VS Code atrás do navegador ocupava mais pontos do monitor que o vídeo; a primeira
        # tela (sem mudança para comparar, vai a janela que mais ocupa a tela) era recusada e tentada de novo para sempre
        screen = type("BigNotes", (FakeScreen,), {"SPLIT": 400})([slide("A")] * 5 + [slide("B")] * 5 + [slide("C")] * 5)
        self.assertEqual(self.windows_kept(screen, 15), ["Aula 4"] * 3)

    def test_writing_notes_beside_the_lesson_does_not_block_it(self):
        # as anotações ficam diferentes da última tela guardada: em toda tela nova, a mudança maior era nelas, e a
        # tela era recusada (privacidade) mesmo com o slide trocado
        def frame(kind, notes=False):
            g = slide(kind)
            if notes:
                g[:, 645:] = 60  # o que você escreveu nas anotações (mais células que a troca de slide)
            return g
        screen = FakeScreen([frame("A")] * 5 + [frame("A", True)] * 5 + [frame("B", True)] * 5 + [frame("C", True)] * 5)
        self.assertEqual(self.windows_kept(screen, 20), ["Aula 4"] * 3)  # A, B e C; as anotações nunca

    def test_stop_does_not_wait_for_a_slow_read(self):
        screen = FakeScreen([slide("A")] * 5)
        started, release = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            release.wait(10)
            return note()["note"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", side_effect=slow):
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL, grabber=screen)
            self.assertTrue(started.wait(5))
            t = time.monotonic()
            w.stop()
            self.assertLess(time.monotonic() - t, 6.5)
            release.set()
            time.sleep(0.2)
            self.assertEqual(w.shots.pending(), [0])  # a leitura que terminou depois de parar não grava nada

    def test_waits_while_another_lesson_is_processed(self):
        screen = FakeScreen([slide("A")] * 5)
        busy = threading.Event()
        busy.set()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vision, "INTERVAL_S", 0.01), \
                mock.patch.object(vision, "read", return_value=note()["note"]) as read:
            w = vision.Watch(os.path.join(tmp, "g.screens"), lambda: float(screen.n), vision.MODEL,
                             paused=busy.is_set, grabber=screen)
            time.sleep(0.3)
            read.assert_not_called()
            w.stop()
            self.assertEqual(w.shots.pending(), [0])  # fica para quando a aula for processada


class Lifecycle(unittest.TestCase):
    """Revisão do Codex: se o som parasse sozinho (falha, disco cheio), a captura da tela continuava e uma nova
    gravação deixava a antiga rodando sem dono."""

    def setUp(self):
        store.clear_local_data()
        store.save_config({**store.DEFAULTS, "watch_screen": True})
        self.watches = []

        def start_watch(path):
            w = mock.Mock(stopped=False)
            w.stop.side_effect = lambda: setattr(w, "stopped", True)
            self.watches.append(w)
            return w
        self.p = mock.patch.object(record, "_start_watch", side_effect=start_watch)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        try:
            record.discard()
        except Exception:
            pass

    def test_audio_failure_stops_the_screen_and_restart_is_clean(self):
        from tests.test_record import fake_soundcard
        broken = fake_soundcard(.3)
        calls = [0]
        rec = broken.get_microphone().recorder()
        real = rec.record

        def failing(numframes):
            calls[0] += 1
            if calls[0] > 20:
                raise OSError("dispositivo de áudio removido")
            return real(numframes)
        rec.record = failing
        broken.get_microphone = lambda **k: types.SimpleNamespace(recorder=lambda **kw: rec)
        with mock.patch.dict(sys.modules, {"soundcard": broken}):
            record.start("Aula")
            for _ in range(300):
                if not record.status()["active"]:
                    break
                time.sleep(0.01)
            self.assertFalse(record.status()["active"])
            self.assertTrue(self.watches[0].stopped)  # parou junto com o som
            self.assertIsNone(record._watch)
        from tests.test_record import fake_soundcard as ok
        with mock.patch.dict(sys.modules, {"soundcard": ok(.3)}):
            record.start("Aula 2")
            self.assertIs(record._watch, self.watches[1])
            record.discard()
        self.assertTrue(all(w.stopped for w in self.watches))

    def test_audio_that_dies_while_the_screen_starts_does_not_leave_it_running(self):
        from tests.test_record import fake_soundcard
        real_start = self.p.new if hasattr(self.p, "new") else None  # noqa: F841

        def slow_start(path):  # o som morre enquanto a captura da tela começa
            record._set(active=False)
            w = mock.Mock(stopped=False)
            w.stop.side_effect = lambda: setattr(w, "stopped", True)
            self.watches.append(w)
            return w
        with mock.patch.object(record, "_start_watch", side_effect=slow_start), \
                mock.patch.dict(sys.modules, {"soundcard": fake_soundcard(.3)}):
            record.start("Aula")
            self.assertTrue(self.watches[-1].stopped)
            self.assertIsNone(record._watch)


class Page(unittest.TestCase):
    def test_screen_text_blocks(self):
        # o modelo repete o título do slide na 1ª linha (sem colunas): não pode impedir a tabela
        table = notion._screen_text({"tipo": "tabela", "titulo": "Complexidade", "descricao": "",
                                     "texto": "Complexidade\nAlgoritmo | Pior caso\nQuicksort | O(n²)\nMerge sort | \nFonte: livro"})
        self.assertEqual([b["type"] for b in table], ["paragraph", "table"])
        self.assertEqual(table[1]["table"]["table_width"], 2)
        self.assertEqual(table[1]["table"]["children"][2]["table_row"]["cells"][1], [])
        tabs = notion._screen_text({"tipo": "tabela", "titulo": "T", "descricao": "",
                                    "texto": "Algoritmo\tPior caso\nQuicksort\tO(n²)"})
        self.assertEqual(tabs[0]["table"]["children"][1]["table_row"]["cells"][1][0]["text"]["content"], "O(n²)")
        code = notion._screen_text({"tipo": "codigo", "titulo": "Busca", "descricao": "Função",
                                    "texto": "Busca\ndef f():\n    return 1"})
        self.assertEqual([b["type"] for b in code], ["code", "paragraph"])
        self.assertEqual(code[0]["code"]["rich_text"][0]["text"]["content"], "def f():\n    return 1")  # indentação


class NotionLimits(unittest.TestCase):
    """Revisão do Codex: 20 telas com 80 linhas = 1.673 blocos em 33 no nível de cima; o Notion recusa acima de
    1000 blocos ou 500 KB por pedido."""

    def test_big_gallery_is_split_by_total_blocks_and_size(self):
        from tests.test_llm import GOOD
        screens = [{"titulo": f"Tela {k}", "tipo": "slide", "descricao": "Figura de exemplo", "t": k * 30.0,
                    "upload": None, "texto": "\n".join(f"linha {k}.{n} do slide com algum texto" for n in range(80))}
                   for k in range(20)]
        meta = {"course": "C", "source": "Arquivo — aula", "model": "m", "transcript_origin": "x", "screens": screens,
                "vision_model": vision.MODEL}
        title, blocks = notion.build_page(llm.validate(GOOD, 600), meta)
        self.assertGreater(sum(notion._count(b) for b in blocks), 1000)
        for batch in notion.batches(blocks):
            self.assertLessEqual(len(batch), 100)
            self.assertLessEqual(sum(notion._count(b) for b in batch), 1000)
            self.assertLessEqual(len(json.dumps({"children": batch})), 500_000)
        self.assertEqual([b for batch in notion.batches(blocks) for b in batch], blocks)  # nada perdido, na ordem
        fake = Fake()
        try:
            page = fake.add_page("Estudos")
            with mock.patch.object(store, "get_token", return_value="secret_test"):
                notion.publish("secret_test", page, title, blocks, lambda: None)
            self.assertEqual(fake.violations, [])
            self.assertEqual(len(fake.pages[page]["blocks"]), len(blocks) + 1)
        finally:
            fake.close()

    def test_fake_notion_rejects_oversized_requests(self):
        fake = Fake()
        try:
            page = fake.add_page("Estudos")
            big = [{"object": "block", "type": "toggle", "toggle": {"rich_text": [], "children": [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}] * 99}}] * 11
            with self.assertRaises(Exception):
                notion.request("PATCH", f"/blocks/{page}/children", "secret_test", {"children": big})
            self.assertIn("mais de 1000 blocos numa requisição", fake.violations)
        finally:
            fake.close()


class Flow(unittest.TestCase):
    """Gravação com a tela assistida → revisão (com as telas) → página com galeria, sem sobras no disco."""

    def setUp(self):
        store.clear_local_data()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        up = store.WORK / "uploads"
        up.mkdir(parents=True)
        self.wav = up / "ab12cd34_Aula.wav"
        self.wav.write_bytes(b"RIFF" + os.urandom(2048))
        shots = vision.Shots(self.wav.with_suffix(".screens"))
        self.jpeg = jpeg = vision._encode(__import__("av").VideoFrame.from_ndarray(bgra(slide("A")), format="bgra"))
        for t, n in [(5, note("Lei de Ohm", "V = R · I\nR: resistência")), (30, note("Rosto", keep=False)),
                     (60, note("Tabela", "Algoritmo | Pior caso\nQuicksort | O(n²)", tipo="tabela")),
                     (90, note("Código", "def f():\n    return 1", tipo="codigo"))]:
            shots.done(shots.add(t, jpeg), n["note"])
        (shots.dir / "complete").touch()
        tr = {"segments": [{"start": 0.0, "end": 40.0, "text": "A tensão é a resistência vezes a corrente."}],
              "language": "pt", "duration": 120.0, "device": "cuda", "second_opinion": False, "compute": "float16"}
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(transcribe, "downloaded", return_value=True),
                        mock.patch.object(transcribe, "transcribe", return_value=tr),
                        mock.patch.object(transcribe, "make_room"),
                        mock.patch.object(sources, "probe", return_value={"duration": 120.0, "format": "WAV"}),
                        mock.patch.object(vision, "ready", return_value=True),
                        mock.patch.object(llm, "_chat", return_value=json.dumps(GOOD)),
                        mock.patch("lumen.mindmap.render", return_value=None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def test_recording_screens_reach_the_page(self):
        spec = {"kind": "recording", "path": str(self.wav), "speed": "1", "language": "pt", "mode": "new",
                "course_id": self.root}
        jobs.start("process", jobs.process, spec)
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        sc = j["result"]["screens"]
        self.assertEqual([s["titulo"] for s in sc["items"]], ["Lei de Ohm", "Tabela", "Código"])
        self.assertEqual(sc["seen"], 4)
        work = jobs.work_dir(j["result"]["key"])
        self.assertFalse(self.wav.with_suffix(".screens").exists())  # foi para a pasta da aula
        code_id = sc["items"][2]["id"]
        understood(j["result"]["key"])
        jobs.start("process", jobs.finish, {**spec, "screens_off": [code_id]})  # o usuário desmarcou o código
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        prompts = [c.args[2] for c in llm._chat.call_args_list]
        prompt = next(p for p in prompts if "Transcrição da aula" in p)  # o do material (o dos gráficos vem depois)
        self.assertIn("(na tela) Lei de Ohm: V = R · I / R: resistência", prompt)
        self.assertFalse(any("def f()" in p for p in prompts))
        blocks = self.fake.pages[self.root]["blocks"]
        heads = [b["heading_2"]["rich_text"][0]["text"]["content"].split(" ", 1)[-1] for b in blocks if b["type"] == "heading_2"]  # sem o emoji
        self.assertEqual(heads[heads.index("Tópicos principais") + 1], "O que apareceu na tela")
        gallery = [b for b in blocks if b["type"] == "column_list"
                   and b["column_list"]["children"][0]["column"]["children"][0]["type"] == "image"]
        self.assertEqual(len(gallery), 1)
        imgs = [c["column"]["children"][0] for c in gallery[0]["column_list"]["children"]]
        self.assertEqual([i["type"] for i in imgs], ["image", "image"])
        self.assertTrue(all(self.fake.uploads[i["image"]["file_upload"]["id"]]["status"] == "uploaded" for i in imgs))
        self.assertIn("00:05 · 📑 Lei de Ohm", imgs[0]["image"]["caption"][0]["text"]["content"])
        toggles = [b for b in blocks if b["type"] == "toggle" and "Tabela" in b["toggle"]["rich_text"][0]["text"]["content"]]
        self.assertEqual(toggles[0]["toggle"]["children"][0]["type"], "table")
        # sobras: a gravação foi apagada; só ficam as imagens das telas que foram para a página
        self.assertFalse(self.wav.exists())
        self.assertEqual(sorted(p.name for p in (work / "screens").glob("*.jpg")), ["0000.jpg", "0002.jpg"])

    def test_missing_vision_model_keeps_the_lesson_going(self):
        vision.ready.return_value = False
        vision.Shots(self.wav.with_suffix(".screens")).add(100, self.jpeg)  # parou de gravar antes de ler esta
        jobs.start("process", jobs.process, {"kind": "recording", "path": str(self.wav), "speed": "1"})
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertIn("1 tela(s) ficaram sem leitura: o modelo de visão", j["result"]["screens"]["warning"])
        self.assertEqual(len(j["result"]["screens"]["items"]), 3)  # as já lidas durante a gravação continuam


class ScreenEndpoint(unittest.TestCase):
    def test_serves_only_jpeg_of_the_lesson(self):
        httpd = server.serve()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            folder = jobs.work_dir("file:abc") / "screens"
            shots = vision.Shots(folder)
            shots.add(1.0, b"\xff\xd8 jpeg")
            understood("file:abc")  # as telas da aula só aparecem depois da compreensão (test_understanding)

            def get(path, token=True):
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                c.request("GET", path + (f"&t={server.TOKEN}" if token else ""),
                          headers={"Host": f"127.0.0.1:{httpd.server_port}"})
                r = c.getresponse()
                return r.status, r.getheader("Content-Type"), r.read()
            self.assertEqual(get("/api/screen?key=file:abc&id=0"), (200, "image/jpeg; charset=utf-8", b"\xff\xd8 jpeg"))
            self.assertEqual(get("/api/screen?key=file:abc&id=0", token=False)[0], 403)
            self.assertEqual(get("/api/screen?key=file:abc&id=../../x")[0], 400)
            self.assertEqual(get("/api/screen?key=file:abc&id=7")[0], 400)
        finally:
            httpd.shutdown()
            httpd.server_close()


@unittest.skipUnless(os.name == "nt", "captura da tela só no Windows")
class RealScreen(unittest.TestCase):
    def test_grab_returns_the_monitor(self):
        """Só confere tamanho e que não veio preto; a imagem não é guardada nem exibida."""
        got = vision.Screen().grab()
        if got is None:
            self.skipTest("o Lumen está na frente")
        img, _, _ = got
        self.assertEqual(img.shape[2], 4)
        self.assertGreaterEqual(img.shape[1], 640)
        if float(img[::16, ::16, :3].std()) <= 0.5:
            self.skipTest("tela toda escura (bloqueada ou desligada)")


if __name__ == "__main__":
    unittest.main()
