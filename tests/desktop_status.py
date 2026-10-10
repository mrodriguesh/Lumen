"""Leitura curta do estado de uma instância local, sem imprimir o token."""
import json
import sys
import urllib.request
from html.parser import HTMLParser


class Meta(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "lumen-token":
            self.token = attrs["content"]


url = "http://127.0.0.1:" + sys.argv[1]
p = Meta()
p.feed(urllib.request.urlopen(url).read().decode())
r = urllib.request.Request(url + "/api/widget", headers={"X-Lumen-Token": p.token})
d = json.load(urllib.request.urlopen(r))
print(json.dumps({"recording_active": d["recording"]["active"], "job_status": d["job"]["status"]}))
