"""Servidor Notion falso que confere os limites documentados da API e guarda o que foi criado."""
import json
import secrets
import threading
import urllib.parse
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
        for rich in [body.get("rich_text", []), body.get("caption", []), *body.get("cells", [])]:
            assert len(rich) <= 100, "mais de 100 pedaços de texto num bloco"
            for rt in rich:
                assert len(rt.get("text", {}).get("content", "")) <= 2000, "rich text acima de 2000 caracteres"
        _check_blocks(body.get("children", []), depth + 1)


class Fake:
    def __init__(self, fail_append=False):
        self.pages, self.children, self.calls, self.violations, self.blocks = {}, {}, [], [], {}
        self.uploads, self.fail_upload = {}, False
        self.fail_append = fail_append
        # visualização 3D: envio que falha só para um tipo (ex.: "image/gif") e pedido que o Notion faz mas cuja
        # resposta se perde (resultado incerto: o Lumen não pode repetir às cegas)
        self.fail_types, self.lose_reply = set(), 0
        # Capas do Notion: corpos dos PATCH de página, bancos (data sources), páginas só-leitura e o PATCH que
        # responde 200 sem trocar a capa (para provar que só o status não basta)
        self.patches, self.sources, self.read_only, self.ignore_cover = [], {}, set(), False
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
                fake.query = dict(urllib.parse.parse_qsl(self.path.partition("?")[2]))
                fake.calls.append((method, path))
                if path.startswith("/files/"):  # o arquivo da capa (URL temporária): nunca recebe o token
                    if self.headers.get("Authorization"):
                        fake.violations.append("token enviado para a URL do arquivo")
                    raw = (fake.uploads.get(path.split("/")[2]) or {}).get("file", b"")
                    self.send_response(200 if raw else 404)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
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

        self.query = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.old_api = notion.API
        notion.API = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        notion.API = self.old_api
        self.httpd.shutdown()
        self.httpd.server_close()

    def add_page(self, title, parent=None, row_of=None, title_key="title", props=None, searchable=True):
        """Página; `row_of`: registro de um banco (add_source), com a propriedade de título `title_key` e `props`."""
        pid = str(uuid.uuid4())
        self.pages[pid] = {"id": pid, "title": title, "parent": parent, "in_trash": False,
                           "blocks": [], "icon": None, "cover": None, "title_key": title_key, "props": props or {},
                           "searchable": searchable}
        self.children[pid] = []
        if row_of:
            self.pages[pid]["parent_raw"] = {"type": "data_source_id", "data_source_id": row_of,
                                             "database_id": self.sources[row_of]["database"]}
        elif parent:
            self.children[parent].append({"type": "child_page", "id": pid, "child_page": {"title": title}})
        return pid

    def add_source(self, title):
        """Banco de dados (data source) cujos registros são páginas."""
        sid = str(uuid.uuid4())
        self.sources[sid] = {"title": title, "database": str(uuid.uuid4())}
        return sid

    def add_upload(self, data):
        """Um arquivo já enviado (ex.: a capa que a página tinha antes)."""
        uid = str(uuid.uuid4())
        self.uploads[uid] = {"status": "uploaded", "file": data, "body": data}
        return uid

    def page_json(self, p):
        """Como o GET /v1/pages/{id} responde (versão 2026-03-11): a capa enviada volta como arquivo do Notion com
        uma URL temporária, assinada de novo a cada leitura."""
        parent = p.get("parent_raw") or ({"type": "page_id", "page_id": p["parent"]} if p["parent"] else {"type": "workspace"})
        cov = p.get("cover")
        if cov and cov.get("type") == "file_upload":
            cov = {"type": "file", "file": {
                "url": f"http://127.0.0.1:{self.httpd.server_port}/files/{cov['file_upload']['id']}/capa.png"
                       f"?X-Amz-Signature={secrets.token_hex(8)}",
                "expiry_time": "2099-01-01T00:00:00.000Z"}}
        title = [{"type": "text", "text": {"content": p["title"], "link": None}, "plain_text": p["title"], "href": None}]
        return {"object": "page", "id": p["id"], "created_time": "2026-10-01T12:00:00.000Z",
                "last_edited_time": p.get("edited", "2026-10-20T12:00:00.000Z"), "in_trash": p["in_trash"],
                "is_archived": False, "is_locked": False, "parent": parent, "cover": cov, "icon": p.get("icon"),
                "properties": {p.get("title_key", "title"): {"id": "title", "type": "title", "title": title},
                               **p.get("props", {})},
                "url": f"https://www.notion.so/{p['title'].replace(' ', '-')}-{p['id'].replace('-', '')}",
                "public_url": None}

    def route(self, method, path, body):
        parts = path.strip("/").split("/")
        if method == "GET" and path == "/users/me":
            return 200, {"id": "lumen-test-bot", "type": "bot"}
        if method == "POST" and path == "/search":  # por título, paginada (o cursor é a posição)
            q = (body.get("query") or "").casefold()
            hits = [p for p in self.pages.values() if p.get("searchable", True) and q in p["title"].casefold()]
            at, size = int(body.get("start_cursor") or 0), min(int(body.get("page_size") or 100), 100)
            more = at + size < len(hits)
            return 200, {"object": "list", "results": [self.page_json(p) for p in hits[at:at + size]],
                         "has_more": more, "next_cursor": str(at + size) if more else None}
        if method == "GET" and parts[0] == "data_sources" and len(parts) == 2:
            src = self.sources.get(parts[1])
            if not src:
                return 404, {"code": "object_not_found"}
            return 200, {"object": "data_source", "id": parts[1], "title": [{"plain_text": src["title"]}]}
        if method == "GET" and parts[0] == "file_uploads" and len(parts) == 2:
            up = self.uploads.get(parts[1])
            if not up:
                return 404, {"code": "object_not_found"}
            return 200, {"object": "file_upload", "id": parts[1], "status": up["status"]}
        if method == "POST" and path == "/file_uploads":
            uid = str(uuid.uuid4())
            self.uploads[uid] = {"status": "pending", "content_type": body.get("content_type"), "size": 0}
            return 200, {"id": uid, "upload_url": f"/v1/file_uploads/{uid}/send", "status": "pending"}
        if method == "POST" and parts[0] == "file_uploads" and parts[2:] == ["send"]:
            if self.fail_upload or self.uploads[parts[1]].get("content_type") in self.fail_types:
                return 400, {"code": "validation_error"}
            assert isinstance(body, bytes) and b'name="file"' in body, "envio sem o campo multipart “file”"
            file = body.partition(b"\r\n\r\n")[2].rsplit(b"\r\n--", 1)[0]  # o arquivo, sem o envelope multipart
            self.uploads[parts[1]].update(status="uploaded", size=len(body), body=body, file=file)
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
            self.children[parent][-1]["created_by"] = {"id": "lumen-test-bot"}
            self.pages[pid]["blocks"] = list(body.get("children", []))
            self.register_blocks(self.pages[pid]["blocks"])
            self.pages[pid]["icon"] = body.get("icon")
            self.pages[pid]["cover"] = body.get("cover")
            return 200, {"id": pid, "url": f"https://www.notion.so/{pid.replace('-', '')}"}
        if parts[0] == "pages" and len(parts) == 2:
            p = self.pages.get(parts[1])
            if not p:
                if parts[1] in set(self.sources) | {s["database"] for s in self.sources.values()}:
                    return 400, {"code": "validation_error"}  # o ID é de um banco, não de uma página
                return 404, {"code": "object_not_found"}
            if method == "PATCH":
                self.patches.append((p["id"], body))
                if p["id"] in self.read_only:
                    return 403, {"code": "restricted_resource"}
            if method == "PATCH" and "in_trash" in body:
                p["in_trash"] = body["in_trash"]
            if method == "PATCH" and "properties" in body:  # renomear (curso ou módulo renomeado no Lumen)
                p["title"] = body["properties"]["title"]["title"][0]["text"]["content"]
            if method == "PATCH" and "cover" in body:
                if body["cover"].get("type") == "file_upload":
                    assert self.uploads.get(body["cover"]["file_upload"]["id"], {}).get("status") == "uploaded", \
                        "capa sem upload concluído"
                if not self.ignore_cover:
                    p["cover"] = body["cover"]
            return 200, self.page_json(p)
        if method == "DELETE" and parts[0] == "blocks" and len(parts) == 2:
            bid = parts[1]
            if bid in self.pages:  # subpágina (bloco child_page): vai para a lixeira, como no Notion
                self.pages[bid]["in_trash"] = True
                return 200, {"id": bid, "type": "child_page", "in_trash": True}
            if bid not in self.blocks:
                return 404, {"code": "object_not_found"}
            self.blocks[bid]["in_trash"] = True
            for p in self.pages.values():
                p["blocks"][:] = [b for b in p["blocks"] if b["id"] != bid]
            return 200, self.blocks[bid]
        if method == "GET" and parts[0] == "blocks" and len(parts) == 2:  # um bloco, como o Notion devolve
            b = self.blocks.get(parts[1])
            if not b:
                return 404, {"code": "object_not_found"}
            b = json.loads(json.dumps(b))
            img = b.get(b.get("type")) or {}
            if img.get("type") == "file_upload":  # a imagem anexada volta como arquivo do Notion (URL temporária)
                uid = img.pop("file_upload")["id"]
                img.update(type="file", file={"url": f"http://127.0.0.1:{self.httpd.server_port}/files/{uid}/imagem"
                                                      f"?X-Amz-Signature={secrets.token_hex(8)}",
                                              "expiry_time": "2099-01-01T00:00:00.000Z"})
            for t in img.get("caption") or []:
                t["plain_text"] = t["text"]["content"]
            return 200, {**b, "object": "block", "in_trash": bool(b.get("in_trash"))}
        if parts[0] == "blocks" and parts[2:] == ["children"]:
            if method == "GET":
                kids = [c for c in self.children.get(parts[1], []) if not self.pages[c["id"]]["in_trash"]]
                kids += [b for b in (self.pages.get(parts[1]) or {}).get("blocks", [])]  # e o conteúdo da página
                if parts[1] in self.blocks:
                    parent = self.blocks[parts[1]]
                    kids += parent[parent["type"]].get("children", [])
                # paginada como a API (até 100 por resposta; o cursor é a posição)
                at, size = int(self.query.get("start_cursor") or 0), min(int(self.query.get("page_size") or 100), 100)
                more = at + size < len(kids)
                return 200, {"results": kids[at:at + size], "has_more": more, "next_cursor": str(at + size) if more else None}
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
            self.register_blocks(body["children"])
            target = self.pages.get(parts[1]) or {"blocks": self.blocks[parts[1]][self.blocks[parts[1]]["type"]].setdefault("children", [])}
            target["blocks"] += body["children"]
            if self.lose_reply:  # o Notion gravou, mas a resposta não chega
                self.lose_reply -= 1
                return 502, {"code": "bad_gateway"}
            return 200, {"results": [{"id": b["id"], "type": b["type"]} for b in body["children"]]}
        return 404, {"code": "object_not_found"}

    def register_blocks(self, blocks):
        for b in blocks:
            b["id"] = str(uuid.uuid4())
            b["created_by"] = {"id": "lumen-test-bot"}
            self.blocks[b["id"]] = b
            self.register_blocks(b[b["type"]].get("children", []))
