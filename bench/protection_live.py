"""Prova real autorizada: apenas áreas identificadas; nunca apaga conteúdo pessoal.

Execute com --run. Estado e evidências permitem retomar sem recriar páginas.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from lumen import store, notion, protection as p, protection_drive as pd, protection_notion as pn


def main(root):
    root.mkdir(parents=True, exist_ok=True)
    original = store.load_config()
    p.HOME = root / "app"
    vault = root / "cofre-teste"
    vault.mkdir(exist_ok=True)
    destination = root / "destino-local"
    destination.mkdir(exist_ok=True)
    token = store.get_token()
    p.configure(vault=str(vault), roots=[], notion_parent=original["root_page_id"])
    p.password(create=True)
    notion.backup_rate_enabled = True
    report_path = root / "evidencias.json"
    report = p.read(report_path)
    def save():
        p.write(report_path, report)
    def page(key, title, parent, blocks):
        if report.get(key):
            return report[key]
        marker = title + " · " + p.configuration()["set_id"][:8]
        if report.get(key + "_pending"):
            children = notion.all_children(token, parent)
            candidates = [b for b in children if b["type"] == "child_page" and b["child_page"]["title"] == marker]
            if len(candidates) != 1:
                raise RuntimeError("Criação incerta: conferir área de teste antes de repetir.")
            report[key] = candidates[0]["id"]
        else:
            report[key + "_pending"] = True
            save()
            report[key] = notion.request("POST", "/pages", token, {"parent": {"page_id": parent},
                "properties": {"title": {"title": notion._rt(marker)}}, "children": blocks}, once=True)["id"]
        save()
        return report[key]
    parent = page("test_root", "Lumen - TESTE Protecao do cerebro", original["root_page_id"],
                  [notion._b("paragraph", notion._rt("Área isolada criada para verificar captura, anexos e recuperação. Não contém material pessoal."))])
    png = vault / "imagem ç.png"
    if not png.exists():
        Image.new("RGB", (80, 60), (45, 140, 190)).save(png)
    note = vault / "Nota ç.md"
    if not note.exists() and not report.get("local_deleted"):
        note.write_text("---\ntipo: teste\n---\n# Proteção\nVersão UM, bytes originais.\n![[imagem ç.png]]\n", "utf-8")
    (vault / "mapa.canvas").write_text('{"nodes":[],"edges":[]}', "utf-8")
    if not report.get("source_page"):
        upload = notion.upload_image(token, png.read_bytes(), "teste.png")
        page("source_page", "Nota com anexo ç", parent, [notion._b("paragraph", notion._rt("Notion: versão UM, texto original.")),
             {"object":"block", "type":"image", "image":{"type":"file_upload", "file_upload":{"id":upload}}}])
    page("same_title_page", "Nota com anexo ç", parent, [notion._b("paragraph", notion._rt("Título igual, identidade diferente."))])
    p.configure(roots=[parent], notion_parent=parent)
    if not report.get("first_local"):
        t = time.monotonic()
        m = p.capture_vault(vault, p.HOME / "capture/obsidian")
        report["first_local"] = p.commit_capture("obsidian", m)
        report["capture_snapshot_seconds"] = round(time.monotonic()-t, 3)
        report["original_hashes"] = {rel:item["sha256"] for rel,item in m["items"].items()}
        save()
    nfolder = p.HOME / "capture/notion"
    nfolder.mkdir(parents=True, exist_ok=True)
    if not report.get("first_notion"):
        t = time.monotonic()
        m = pn.capture(token, [parent], nfolder, discover=False)
        report["first_notion"] = p.commit_capture("notion", m)
        report["notion_seconds"] = round(time.monotonic()-t, 3)
        report["notion_capture"] = {"items":len(m["items"]),"pending":m["pending"]}
        save()
    pn.mirror_to_vault(vault, p.read(nfolder / "manifest.json"))
    pn.mirror_to_notion(token, parent, p.read(p.HOME / "capture/obsidian/manifest.json"))
    report["mirrors"] = {key:p.state().get(key) for key in ("notion_obsidian","obsidian_notion")}
    save()
    if not p.configuration()["local"]:
        p.choose_local(destination)
    p.deliver_local()
    for source in ("obsidian", "notion"):
        key = "cloud_" + source
        if not report.get(key):
            sid = report["first_local" if source == "obsidian" else "first_notion"]
            t = time.monotonic()
            report[key] = pd.publish(sid, source)
            report[key]["elapsed_seconds"] = round(time.monotonic()-t, 3)
            save()
    if not report.get("second_local"):
        note.write_text("# Proteção\nVersão DOIS.\n", "utf-8")
        m = p.capture_vault(vault, p.HOME / "capture/obsidian", p.read(p.HOME / "capture/obsidian/manifest.json"))
        report["second_local"] = p.commit_capture("obsidian", m)
        save()
    if not report.get("second_notion"):
        blocks = notion.all_children(token, report["source_page"])
        paragraph = next(x for x in blocks if x["type"] == "paragraph")
        notion.request("PATCH", "/blocks/"+paragraph["id"], token, {"paragraph":{"rich_text":notion._rt("Notion: versão DOIS.")}})
        m = pn.capture(token, [parent], nfolder, p.read(nfolder / "manifest.json"), discover=False)
        report["second_notion"] = p.commit_capture("notion", m)
        save()
    if not report.get("local_deleted"):
        note.unlink(missing_ok=True)
        report["local_deleted"] = True
        save()
        m = p.capture_vault(vault, p.HOME / "capture/obsidian", p.read(p.HOME / "capture/obsidian/manifest.json"))
        report["deletion_snapshot"] = p.commit_capture("obsidian", m)
        save()
    recovery = root / "recuperacoes"
    recovery.mkdir(exist_ok=True)
    report["local_recovery"] = p.restore(p.HOME / "repository", report["first_local"], recovery)
    save()
    for source in ("obsidian", "notion"):
        downloaded, catalog = pd.download_repository(report["cloud_"+source]["id"], recovery)
        p.run_restic(downloaded / "repository", "check", "--read-data")
        result = p.restore(downloaded / "repository", catalog["snapshot"], recovery)
        report["drive_recovery_"+source] = {**result,"download":str(downloaded),"objects":len(catalog["objects"])}
        save()
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--folder", default=r"D:\Aplicativos\Lumen-protecao-validacao-20261028")
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run para criar áreas identificadas nas APIs reais.")
    main(Path(args.folder))
