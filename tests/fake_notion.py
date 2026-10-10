"""Servidor Notion falso que confere os limites documentados da API e guarda o que foi criado."""
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lumen import notion


def _check_request(body):
    """Limites de cada requisição: 1000 blocos contando os internos e 500 KB."""
    def count(blocks):
        return sum(1 + count(b[b["type"]].get("children", [])) for b in blocks)
    assert count(body.get("children", [])) <= 1000, "mais de 1000 blocos numa requisição"
    assert len(json.dumps(body)) <= 500_000, "requisição acima de 500 KB"


def _check_blocks(blocks, depth=1):
    assert len(blocks) <= 100, "mais de 100 blocos numa requisição"
    assert depth <= 3 or not blocks, "aninhamento acima do permitido"
    for b in blocks:
        body = b[b["type"]]
        for rt in body.get("rich_text", []):
            assert len(rt["text"]["content"]) <= 2000, "rich text acima de 2000 caracteres"
        _check_blocks(body.get("children", []), depth + 1)


class Fake:
    def __init__(self, fail_append=False):
        self.pages, self.children, self.calls, self.violations, self.blocks = {}, {}, [], [], {}
        self.uploads, self.fail_upload = {}, False
        self.fail_append = fail_append
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                multipart = (self.headers.get("Content-Type") or "").startswith("multipart/form-data")
                body = raw if multipart else (json.loads(raw) if raw else None)
                path = self.path.split("?")[0].removeprefix("/v1")
                fake.calls.append((method, path))
                try:
                    assert self.headers["Notion-Version"] == notion.VERSION, "Notion-Version errado"
                    assert self.headers["Authorization"] == "Bearer secret_test", "token errado"
                    code, data = fake.route(method, path, body)
                except AssertionError as e:
                    fake.violations.append(str(e))
                    code, data = 400, {"code": "validation_error"}
                self._reply(code, data)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_PATCH(self):
                self._do("PATCH")

            def do_DELETE(self):
                self._do("DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.old_api = notion.API
        notion.API = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        notion.API = self.old_api
        self.httpd.shutdown()
        self.httpd.server_close()

    def add_page(self, title, parent=None):
        pid = str(uuid.uuid4())
        self.pages[pid] = {"id": pid, "title": title, "parent": parent, "in_trash": False,
                           "blocks": [], "icon": None, "cover": None}
        self.children[pid] = []
        if parent:
            self.children[parent].append({"type": "child_page", "id": pid, "child_page": {"title": title}})
        return pid

    def route(self, method, path, body):
        parts = path.strip("/").split("/")
        if method == "POST" and path == "/search":
            return 200, {"results": [{"id": p["id"], "in_trash": p["in_trash"],
                                      "parent": p.get("parent_raw") or ({"type": "page_id", "page_id": p["parent"]} if p["parent"] else {"type": "workspace"}),
                                      "properties": {
                "title": {"type": "title", "title": [{"plain_text": p["title"]}]}}} for p in self.pages.values()]}
        if method == "POST" and path == "/file_uploads":
            uid = str(uuid.uuid4())
            self.uploads[uid] = {"status": "pending", "content_type": body.get("content_type"), "size": 0}
            return 200, {"id": uid, "upload_url": f"/v1/file_uploads/{uid}/send", "status": "pending"}
        if method == "POST" and parts[0] == "file_uploads" and parts[2:] == ["send"]:
            if self.fail_upload:
                return 400, {"code": "validation_error"}
            assert isinstance(body, bytes) and b'name="file"' in body, "envio sem o campo multipart “file”"
            self.uploads[parts[1]].update(status="uploaded", size=len(body))
            return 200, {"id": parts[1], "status": "uploaded"}
        if method == "POST" and path == "/pages":
            cov = (body.get("cover") or {})
            if cov.get("type") == "file_upload":
                assert self.uploads.get(cov["file_upload"]["id"], {}).get("status") == "uploaded", "capa sem upload concluído"
            _check_request(body)
            _check_blocks(body.get("children", []))
            parent = body["parent"]["page_id"]
            if parent not in self.pages:
                return 404, {"code": "object_not_found"}
            pid = self.add_page(body["properties"]["title"]["title"][0]["text"]["content"], parent)
            self.pages[pid]["blocks"] = list(body.get("children", []))
            for b in self.pages[pid]["blocks"]:
                b["id"] = str(uuid.uuid4())
                self.blocks[b["id"]] = b
            self.pages[pid]["icon"] = body.get("icon")
            self.pages[pid]["cover"] = body.get("cover")
            return 200, {"id": pid, "url": f"https://www.notion.so/{pid.replace('-', '')}"}
        if parts[0] == "pages" and len(parts) == 2:
            p = self.pages.get(parts[1])
            if not p:
                return 404, {"code": "object_not_found"}
            if method == "PATCH":
                p["in_trash"] = body["in_trash"]
            return 200, {"id": p["id"], "in_trash": p["in_trash"], "url": f"https://www.notion.so/{p['id']}"}
        if method == "DELETE" and parts[0] == "blocks" and len(parts) == 2:
            bid = parts[1]
            if bid not in self.blocks:
                return 404, {"code": "object_not_found"}
            self.blocks[bid]["in_trash"] = True
            for p in self.pages.values():
                p["blocks"][:] = [b for b in p["blocks"] if b["id"] != bid]
            return 200, self.blocks[bid]
        if parts[0] == "blocks" and parts[2:] == ["children"]:
            if method == "GET":
                kids = [c for c in self.children.get(parts[1], []) if not self.pages[c["id"]]["in_trash"]]
                return 200, {"results": kids, "has_more": False, "next_cursor": None}
            if self.fail_append:
                return 400, {"code": "validation_error"}
            if parts[1] not in self.pages and parts[1] not in self.blocks:
                return 404, {"code": "object_not_found"}
            _check_request(body)
            _check_blocks(body["children"])

            def images(blocks):  # também dentro de colunas e toggles
                for b in blocks:
                    if b["type"] == "image" and b["image"]["type"] == "file_upload":
                        assert self.uploads.get(b["image"]["file_upload"]["id"], {}).get("status") == "uploaded", \
                            "imagem sem upload concluído"
                    images(b[b["type"]].get("children", []))
            images(body["children"])
            body = json.loads(json.dumps(body))
            for b in body["children"]:
                b["id"] = str(uuid.uuid4())
                self.blocks[b["id"]] = b
            target = self.pages.get(parts[1]) or {"blocks": self.blocks[parts[1]][self.blocks[parts[1]]["type"]].setdefault("children", [])}
            target["blocks"] += body["children"]
            return 200, {"results": [{"id": b["id"], "type": b["type"]} for b in body["children"]]}
        return 404, {"code": "object_not_found"}
