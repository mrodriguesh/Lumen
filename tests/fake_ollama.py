"""Ollama falso em 127.0.0.1 para os testes do Lúmen Study AI: /api/tags, /api/chat (streaming, JSON e ferramentas),
/api/embed e /api/pull. Troca llm.OLLAMA enquanto está aberto. As respostas são roteiros simples e determinísticos."""
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from lumen import llm, vault

CONCEPTS = {"memori": 0, "hipoca": 0, "consol": 0, "lembra": 0, "behavi": 1, "condic": 1, "cognit": 2}


def embed_text(t):
    v = np.zeros(32, dtype=np.float32)
    for tok in vault.tokens(t):
        v[CONCEPTS.get(tok, 3 + zlib.crc32(tok.encode()) % 29)] += 1
    return v.tolist()


class FakeOllama:
    def __init__(self, models=("qwen3:8b", "qwen3-embedding:0.6b")):
        self.models, self.requests = list(models), []
        self.answer = "Segundo suas notas, a consolidação depende do sono [S1]. Uma fonte inventada [S9]."
        self.tool_plan = []    # chamadas de ferramenta a fazer antes de responder: [(nome, argumentos)]
        self.json_replies = {}  # trecho do system → dict devolvido em modo JSON
        self.json_raw = []      # respostas JSON cruas, usadas em ordem antes das outras: [(texto, done_reason)]
        self.no_think, self.no_tools = set(), set()  # modelos que recusam think / ferramentas (HTTP 400, como o real)
        self.cut = []           # trechos da última mensagem cuja resposta para no teto (done_reason "length")
        # Streaming de verdade (a Conversa rápida): com delay > 0, a resposta de texto sai pedaço a pedaço, com essa pausa
        # entre eles; se gate for um threading.Event, a resposta espera nele antes do pedaço hold_after (interromper no meio).
        self.delay, self.gate, self.hold_after = 0.0, None, 3
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, payload, stream=False, slow=False):
                if stream and slow and fake.delay:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    try:
                        for i, x in enumerate(payload):
                            if fake.gate is not None and i == fake.hold_after:
                                fake.gate.wait(60)
                            self.wfile.write((json.dumps(x) + "\n").encode())
                            self.wfile.flush()
                            time.sleep(fake.delay)
                    except OSError:
                        pass  # o cliente (Lúmen) cancelou a resposta
                    return
                body = b"".join((json.dumps(x) + "\n").encode() for x in payload) if stream else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/x-ndjson" if stream else "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m} for m in fake.models]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                fake.requests.append((self.path, body))
                if self.path == "/api/embed":
                    if body.get("model") not in fake.models:
                        return self._send(404, {"error": "model not found"})
                    return self._send(200, {"embeddings": [embed_text(t) for t in body["input"]]})
                if self.path == "/api/pull":
                    fake.models.append(body["model"])
                    return self._send(200, [{"status": "pulling", "total": 100, "completed": 40},
                                            {"status": "pulling", "total": 100, "completed": 100}, {"status": "success"}], stream=True)
                if self.path == "/api/chat":
                    if body.get("model") not in fake.models:
                        return self._send(404, {"error": "model not found"})
                    if body.get("think") and body["model"] in fake.no_think:
                        return self._send(400, {"error": f'"{body["model"]}" does not support thinking'})
                    if body.get("tools") and body["model"] in fake.no_tools:
                        return self._send(400, {"error": f'registry.ollama.ai/library/{body["model"]} does not support tools'})
                    return self._send(200, fake.chat(body), stream=True, slow=not body.get("format"))
                self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.old = llm.OLLAMA
        llm.OLLAMA = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        llm.OLLAMA = self.old
        self.httpd.shutdown()
        self.httpd.server_close()

    def chat(self, body):
        system = body["messages"][0]["content"] if body["messages"] and body["messages"][0]["role"] == "system" else ""
        if body.get("format") and self.json_raw:  # ex.: o laço até o teto, com o JSON cortado
            content, reason = self.json_raw.pop(0)
            return [{"message": {"role": "assistant", "content": content}, "done": False},
                    {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": reason}]
        if body.get("format"):
            text = system + "\n" + body["messages"][-1]["content"]
            reply = next((v for k, v in self.json_replies.items() if k in text), None)
            if reply is None:
                reply = self.default_json(text)
            # como o Ollama real: o conteúdo vem antes; o último pedaço só fecha (done)
            return [{"message": {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)}, "done": False},
                    {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}]
        done_tools = sum(1 for m in body["messages"] if m["role"] == "tool")
        if body.get("tools") and done_tools < len(self.tool_plan):
            name, args = self.tool_plan[done_tools]
            return [{"message": {"role": "assistant", "content": "",
                                 "tool_calls": [{"function": {"name": name, "arguments": args}}]}, "done": False},
                    {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}]
        words = self.answer.split(" ")
        # como o real: o último pedaço traz as contagens (aqui, 3 caracteres por token do que foi enviado)
        prompt = sum(len(m.get("content") or "") for m in body["messages"]) // 3
        last = body["messages"][-1].get("content") or ""
        reason = "length" if any(c in last for c in self.cut) else "stop"
        return [{"message": {"role": "assistant", "content": w + (" " if i < len(words) - 1 else "")}, "done": False}
                for i, w in enumerate(words)] + [{"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": reason,
                                                  "prompt_eval_count": prompt, "eval_count": len(words)}]

    @staticmethod
    def default_json(system):
        if "analisa pedidos de estudo" in system:
            return {"intent": "explain", "topic": "memória e sono", "query": "Como o sono ajuda a memória?",
                    "keywords": ["memória", "sono"], "expansions": ["consolidação", "hipocampo"], "level": "", "needs_web": False,
                    "effort": "equilibrado", "reason": "quer entender um mecanismo"}
        if "o que um assistente de estudos deve LEMBRAR" in system:
            return {"memories": [{"content": "Prefere explicações com exemplos práticos.", "category": "profile",
                                  "confidence": .9, "scope": "global", "reason": "pediu exemplos"},
                                 {"content": "Está estudando memória para uma prova.", "category": "long_term",
                                  "confidence": .6, "scope": "global", "reason": "mencionou a prova"}]}
        if "título curto" in system:
            return {"title": "Sono e memória"}
        if "flashcards" in system or "Crie de 6 a 12 flashcards" in system:
            return {"cards": [{"question": "O que consolida a memória?", "answer": "O sono.", "explanation": "Ver nota.", "source": "S1"},
                              {"question": "Inventada?", "answer": "Sim.", "explanation": "", "source": "geral"}]}
        return {}
