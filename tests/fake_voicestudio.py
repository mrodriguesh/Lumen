"""Voice Studio falso (fase 6): as rotas que o Lúmen usa, com um WAV de seno no lugar da fala, e o registro de tudo o
que chegou, para provar que nenhuma escrita acontece sem o clique do estudante. O /ws/tts é um WebSocket mínimo
(RFC 6455).

Também roda como processo (`python -m tests.fake_voicestudio --port N [--start S] [--crash]`), no lugar do backend de
verdade, para os testes do backend sem janela (D53): /health com o cabeçalho x-omnivoice-backend, 503 durante a subida
e saída quando a entrada padrão (o pipe do Lúmen) fecha, como o vigia OMNIVOICE_DESKTOP_CONTAINED do app."""
import base64
import hashlib
import io
import json
import math
import os
import re
import struct
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SR = 24000
PROFILES = [
    {"id": "1faf41ee", "name": "Jhonny Sirverhand", "kind": "clone", "language": "Auto", "image_url": None, "is_demo": 0, "seed": None},
    {"id": "demo0001", "name": "Demo Voice", "kind": "clone", "language": "English", "image_url": None, "is_demo": 1, "seed": None},
]
MODELS = [
    {"repo_id": "k2-fsa/OmniVoice", "label": "VoiceStudio TTS (k2-fsa/OmniVoice)", "role": "TTS", "size_gb": 2.4, "required": True,
     "installed": True, "supported": True, "license_info": {"license": "CC-BY-NC (version unspecified); Higgs Audio 2"}},
    {"repo_id": "Systran/faster-whisper-base", "label": "Whisper base", "role": "ASR", "size_gb": 0.15, "installed": True,
     "supported": True, "license_info": {"license": "mit"}},
    {"repo_id": "csukuangfj/sherpa-onnx-whisper-tiny", "label": "Whisper Tiny", "role": "ASR", "size_gb": 0.104, "installed": True,
     "supported": True, "license_info": {"license": "NOASSERTION"}},
    {"repo_id": "deepdml/faster-whisper-large-v3-turbo-ct2", "label": "Whisper large-v3 Turbo", "role": "ASR", "size_gb": 1.6,
     "installed": False, "supported": True, "license_info": {"license": "mit"}},
    {"repo_id": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "label": "Parakeet", "role": "ASR", "size_gb": 0.64,
     "installed": False, "supported": True, "license_info": {"license": "NOASSERTION"}},
]
# o que não muda nada do lado dele: leituras, fala, aquecer o modelo, o teste de pronúncia e a descrição de voz
READS_POST = ("/v1/audio/speech", "/setup/warmup", "/pronunciation/test", "/design/describe")


def sine(seconds, freq=220.0):
    n = int(SR * seconds)
    pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / SR))) for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return buf.getvalue(), pcm


class Fake:
    def __init__(self, port=0, start_s=0.0):
        self.calls, self.bodies, self.profiles = [], [], [dict(p) for p in PROFILES]
        self.loaded, self.takes, self.delay, self.unloaded = False, 4, 0.0, []
        self.models, self.tier, self.jobs, self.pron = [dict(m) for m in MODELS], "max", [], []
        self.ready_at, self.load_s, self.loading_since = time.monotonic() + start_s, 0.0, None
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("x-omnivoice-backend", "0.5.7")
                self.end_headers()
                self.wfile.write(data)

            def _starting(self):
                return time.monotonic() < fake.ready_at

            def do_GET(self):
                if self.path == "/__writes":  # para o teste de tela, que roda em outro processo (não entra no registro)
                    return self._send(200, fake.writes())
                fake.calls.append(("GET", self.path))
                p = self.path.split("?")[0]
                if p == "/health":
                    if self._starting():
                        return self._send(503, {"status": "starting", "step": "ml_imports", "label": "Loading ML runtime", "version": "0.5.7"})
                    return self._send(200, {"status": "ok", "device": "cuda", "version": "0.5.7"})
                if p == "/startup/progress":
                    done = not self._starting()
                    return self._send(200, {"status": "ready" if done else "starting", "steps": [
                        {"id": "a", "state": "done"}, {"id": "b", "state": "done" if done else "pending"}]})
                if self._starting():
                    return self._send(503, {"detail": "starting"})
                if p == "/ws/tts" and self.headers.get("Upgrade", "").lower() == "websocket":
                    return self._ws()
                if p == "/system/info":
                    return self._send(200, {"app_version": "0.5.7", "gpu_name": "GPU falsa", "device": "cuda", "generate_timeout_s": 30})
                if p == "/model/status":
                    if fake.loading_since is not None and time.monotonic() - fake.loading_since >= fake.load_s:
                        fake.loaded, fake.loading_since = True, None
                    loading = fake.loading_since is not None
                    return self._send(200, {"status": "ready" if fake.loaded else "loading" if loading else "idle",
                                            "loaded": fake.loaded, "loading": loading, "progress": 0.5 if loading else None})
                if p == "/engines/tts":
                    return self._send(200, {"active": "omnivoice", "active_model": "k2-fsa/OmniVoice", "backends": [
                        {"id": "omnivoice", "display_name": "VoiceStudio (k2-fsa/OmniVoice, 600+ languages)", "available": True,
                         "supports_cloning": True, "instruct_vocabulary": "tags", "max_ref_seconds": 20.0,
                         "supported_language_names": ["Portuguese", "English"]},
                        {"id": "kittentts", "display_name": "KittenTTS", "available": False, "reason": "not installed",
                         "supports_cloning": False, "one_click_install": True, "supported_language_names": ["English"]}]})
                if p == "/engines/asr":
                    return self._send(200, {"active": "faster-whisper", "active_model": "Systran/faster-whisper-base", "backends": [
                        {"id": "faster-whisper", "display_name": "faster-whisper", "available": True},
                        {"id": "moonshine", "display_name": "Moonshine", "available": False, "reason": "not installed"}]})
                if p == "/profiles":
                    return self._send(200, fake.profiles)
                if p.startswith("/profiles/") and p.endswith("/audio"):
                    return self._send(200, sine(0.5)[0], "audio/wav")
                if p == "/stats/usage":
                    return self._send(200, {"takes": fake.takes})
                if p == "/model/loaded":
                    return self._send(200, {"models": [{"id": "tts", "vram_mb": 2700}] if fake.loaded else [],
                                            "system": {"ram_available_gb": 3.1, "ram_total_gb": 15.8, "vram_free_gb": 8.8, "vram_total_gb": 12.0}})
                if p == "/pronunciation":
                    return self._send(200, fake.pron)
                if p == "/models":
                    return self._send(200, {"models": fake.models, "disk_free_gb": 18.5, "disk_headroom_gb": 2})
                if p == "/models/install/status":
                    return self._send(200, {"jobs": fake.jobs})
                if p == "/api/settings/performance-profile":
                    return self._send(200, {"global": fake.tier, "effective": {"tts": fake.tier}, "plan": {"resolved": fake.tier},
                                            "selections": {"tts": {"engine": "omnivoice"}}})
                if p == "/api/settings/storage/models-dir":
                    return self._send(200, {"configured": None, "effective": r"C:\Users\x\AppData\Local\OmniVoice\hf_cache", "restart_required": False})
                if p == "/api/settings/storage":
                    return self._send(200, {"min_free_gb": 10, "volumes": [{"path": "C:\\", "free_bytes": 18_500_000_000}],
                                            "categories": [{"id": "hf_cache", "path": r"C:\x\hf_cache", "bytes": 11_500_000_000},
                                                           {"id": "temp", "bytes": 120_000_000}]})
                return self._send(404, {"detail": "Not Found"})

            def do_DELETE(self):
                fake.calls.append(("DELETE", self.path))
                if self.path.startswith("/models/"):
                    repo = self.path[len("/models/"):]
                    for m in fake.models:
                        if m["repo_id"] == repo:
                            m["installed"] = False
                            return self._send(200, {"deleted": True, "repo_id": repo, "freed_bytes": 1000})
                    return self._send(404, {"detail": "isn't installed"})
                if self.path.startswith("/pronunciation/"):
                    eid = self.path.rsplit("/", 1)[1]
                    fake.pron = [e for e in fake.pron if e["id"] != eid]
                    return self._send(200, {"deleted": True})
                return self._send(404, {"detail": "Not Found"})

            def do_PUT(self):
                fake.calls.append(("PUT", self.path))
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.bodies.append(body)
                if self.path == "/api/settings/performance-profile":
                    fake.tier = body["tier"]
                    return self._send(200, {"global": fake.tier})
                return self._send(404, {"detail": "Not Found"})

            def do_POST(self):
                fake.calls.append(("POST", self.path))
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) or b"{}"
                if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                    body = dict(re.findall(r'name="([^"]+)"\r\n\r\n(.*?)\r\n', raw.decode("utf-8"), re.S))
                else:
                    body = json.loads(raw)
                fake.bodies.append(body)
                if self.path == "/v1/audio/speech":
                    if body.get("instruct") == "tag errada":
                        return self._send(400, {"error": {"message": "Unknown instruct item: tag errada"}})
                    time.sleep(fake.delay)
                    fake.loaded = True
                    wav, pcm = sine(min(0.2 + len(body["input"]) / 60, 3.0))
                    return self._send(200, pcm if body.get("response_format") == "pcm" else wav,
                                      "audio/pcm" if body.get("response_format") == "pcm" else "audio/wav")
                if self.path == "/setup/warmup":
                    if not fake.loaded and fake.loading_since is None:
                        fake.loading_since = time.monotonic()
                    return self._send(200, {"status": "warmup_started"})
                if self.path == "/pronunciation/test":
                    text = body.get("text", "")
                    for e in fake.pron:
                        if e.get("enabled", True):
                            text = re.sub(rf"\b{re.escape(e['term'])}\b", e["replacement"], text)
                    return self._send(200, {"input": body.get("text"), "substituted": text, "changed": text != body.get("text")})
                if self.path == "/pronunciation":
                    e = {"id": f"p{len(fake.pron) + 1}", "term": body["term"], "replacement": body.get("replacement", ""),
                         "type": "respelling", "language": body.get("language", "*"), "enabled": True}
                    fake.pron.append(e)
                    return self._send(200, e)
                if self.path == "/design/describe":
                    return self._send(200, {"attrs": {"Gender": "male", "Age": "middle-aged"}, "instruct": "male, middle-aged",
                                            "matched": [], "unmatched": ["cético"]})
                if self.path == "/profiles":
                    pid = f"d{len(fake.profiles):07d}"
                    fake.profiles.append({"id": pid, "name": body.get("name"), "kind": body.get("kind"), "language": body.get("language"),
                                          "image_url": None, "is_demo": 0, "seed": int(body.get("seed") or 42)})
                    return self._send(200, fake.profiles[-1])
                if self.path == "/models/install":
                    fake.jobs.append({"repo_id": body["repo_id"], "state": "downloading", "bytes_done": 10, "total_bytes": 100})
                    return self._send(200, {"started": True})
                if self.path == "/models/install/cancel":
                    for j in fake.jobs:
                        if j["repo_id"] == body["repo_id"]:
                            j["state"] = "cancelling"
                    return self._send(200, {"cancelling": body["repo_id"]})
                if self.path == "/engines/select":
                    return self._send(200, {"family": body["family"], "active": body["backend_id"]})
                if self.path.startswith("/engines/sidecar/") and self.path.endswith("/install"):
                    return self._send(200, {"status": "started"})
                if self.path == "/api/settings/storage/temp/clear":
                    return self._send(200, {"removed": 3, "freed_bytes": 120_000_000})
                if self.path.startswith("/model/unload/"):
                    fake.unloaded.append(self.path.rsplit("/", 1)[1])
                    fake.loaded = False
                    return self._send(200, {"ok": True})
                return self._send(404, {"detail": "Not Found"})

            def _ws(self):
                key = self.headers["Sec-WebSocket-Key"]
                accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                r, w = self.rfile, self.wfile
                b1, b2 = r.read(2)
                ln = b2 & 0x7F
                ln = struct.unpack(">H", r.read(2))[0] if ln == 126 else struct.unpack(">Q", r.read(8))[0] if ln == 127 else ln
                mask = r.read(4)
                req = json.loads(bytes(c ^ mask[i % 4] for i, c in enumerate(r.read(ln))))
                fake.bodies.append(req)
                fake.loaded = True

                def frame(op, data):
                    head = bytes([0x80 | op]) + (bytes([len(data)]) if len(data) < 126 else bytes([126]) + struct.pack(">H", len(data))
                                                 if len(data) < 65536 else bytes([127]) + struct.pack(">Q", len(data)))
                    w.write(head + data)
                    w.flush()
                frame(1, json.dumps({"type": "start", "sample_rate": SR}).encode())
                _, pcm = sine(min(0.2 + len(req["text"]) / 60, 3.0))
                for i in range(0, len(pcm), 9600):
                    frame(2, pcm[i:i + 9600])
                frame(1, json.dumps({"type": "done", "duration_s": len(pcm) / 2 / SR, "ttfa_ms": 5.0}).encode())
                try:
                    r.read(2)  # o close do cliente
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def writes(self):
        """O que muda algo do lado do Voice Studio: deve ficar vazio sem o clique do estudante (D46, D57)."""
        return [(m, p) for m, p in self.calls if not (m == "GET" or (m == "POST" and p.split("?")[0] in READS_POST))]


def _main():
    """O backend falso como processo: sai quando a entrada padrão fecha (como o OMNIVOICE_DESKTOP_CONTAINED do app)."""
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    print(f"argv {' '.join(args)} TEMP={os.environ.get('TEMP')} CONTAINED={os.environ.get('OMNIVOICE_DESKTOP_CONTAINED')}"
          f" HF_HOME={os.environ.get('HF_HOME')}", flush=True)
    if "--crash" in args:
        time.sleep(0.3)
        print("RuntimeError: falha falsa ao carregar o PyTorch", flush=True)
        sys.exit(3)
    Fake(port, float(args[args.index("--start") + 1]) if "--start" in args else 0.0)
    print(f"INFO:     Uvicorn running on http://127.0.0.1:{port}", flush=True)
    if os.environ.get("OMNIVOICE_DESKTOP_CONTAINED") == "1":
        while sys.stdin.buffer.read(1):
            pass
        os._exit(0)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    _main()
