"""Gerador de imagens local para as capas (stable-diffusion.cpp + modelo aberto, sem chave e sem nuvem).

Os arquivos ficam em `config["image_dir"]` (padrão: pasta de dados do Lumen) e só são baixados com o clique do
usuário. Sem eles, a capa volta a ser desenhada com emojis (lumen/cover.py).
"""
import os
import re
import threading
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import AppError, store

HF = "https://huggingface.co"
SD_RELEASE = "master-945-a1ded76"
SD_ZIP = (f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{SD_RELEASE}/"
          f"sd-master-a1ded76-bin-win-vulkan-x64.zip")
# Escolhido por comparação lado a lado com o FLUX.2 [klein] 4B (mesmos temas e semente; docs/DECISOES.md):
# o Z-Image-Turbo teve ilustrações mais bonitas e não desenhou texto deformado. Tempo medido na RTX 3060 a partir
# do SSD: ≈ 33 s por capa 1536×640 (Vulkan); do HD a leitura de 6 GB levava ~100 s a mais.
ENGINES = {
    "z-image": {
        "label": "Z-Image-Turbo", "license": "Apache 2.0 (Alibaba Tongyi)", "size": "≈ 6,7 GB",
        "files": {
            "model": ("zimage/z_image_turbo-Q4_K.gguf", f"{HF}/leejet/Z-Image-Turbo-GGUF/resolve/main/z_image_turbo-Q4_K.gguf"),
            "llm": ("zimage/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                    f"{HF}/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
            "vae": ("zimage/ae.safetensors", f"{HF}/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"),
        },
        "args": ["--cfg-scale", "1.0", "--steps", "8"],
    },
}
DEFAULT_ENGINE = "z-image"
STYLE = (", wide cinematic full-bleed composition that fills the whole frame, main subject in the center, soft studio "
         "lighting, vibrant harmonious colors, clean modern 3D illustration, high detail, no text, no letters, no words")
# Palavras que fazem o modelo desenhar texto ilegível ou molduras (visto no teste); saem do pedido da IA de texto.
_RISKY = re.compile(r"\b(interfaces?|screens?|monitors?|displays?|dashboards?|ui|code|coding|text|letters?|words?|"
                    r"documents?|papers?|signs?|posters?|banners?|labels?|charts?|graphs?|book pages?|blueprints?)\b", re.I)


def clean_prompt(prompt):
    """Tira do pedido o que costuma virar texto falso ou moldura na imagem."""
    s = re.sub(r"\s{2,}", " ", _RISKY.sub("", prompt or ""))
    return re.sub(r"\s+([,.])", r"\1", s).strip(" ,.")


def folder():
    return Path(store.load_config().get("image_dir") or store.DATA / "imagem")


def _exe():
    return folder() / "bin" / "vulkan" / "sd-cli.exe"


def ready(engine=DEFAULT_ENGINE):
    f = folder()
    return _exe().is_file() and all((f / rel).is_file() for rel, _ in ENGINES[engine]["files"].values())


def download(engine, progress, check):
    """Baixa o programa e os pesos (pedido explícito do usuário). Retoma arquivos pela metade."""
    f = folder()
    if shutil.disk_usage(f.anchor if f.exists() else f.parent.anchor).free < 9e9:
        raise AppError("Pouco espaço em disco para o gerador de capas (≈ 6,7 GB).",
                       "Libere espaço no disco do Lumen (de preferência um SSD) e tente de novo.")
    jobs = [(rel, url) for rel, url in ENGINES[engine]["files"].values() if not (f / rel).is_file()]
    if not _exe().is_file():
        jobs.insert(0, ("bin/sd.zip", SD_ZIP))
    for i, (rel, url) in enumerate(jobs):
        dest = f / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if have else "wb") as out:
            total = have + int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(1 << 20):
                check()
                out.write(chunk)
                have += len(chunk)
                progress((i + have / max(total, 1)) / len(jobs), None)
        part.replace(dest)
        if rel == "bin/sd.zip":
            with zipfile.ZipFile(dest) as z:
                z.extractall(f / "bin" / "vulkan")
            dest.unlink()


_lock = threading.Lock()  # duas gerações ao mesmo tempo disputariam a VRAM


def generate(prompt, engine=DEFAULT_ENGINE, width=1536, height=640, seed=-1, timeout=240, *, check=lambda: None):
    """PNG (bytes) gerado localmente na GPU (Vulkan) ou CPU. None se o gerador não estiver instalado."""
    if engine not in ENGINES or not isinstance(prompt, str) or not prompt.strip():
        raise AppError("Descreva a imagem e escolha um gerador disponível.")
    if any(type(n) is not int or n < 256 or n > 1536 or n % 64 for n in (width, height)) or width * height > 1048576:
        raise AppError("Proporção de imagem inválida.")
    if not ready(engine):
        return None
    while not _lock.acquire(timeout=0.2):
        check()
    try:
        check()
        return _generate(prompt, engine, width, height, seed, timeout, check)
    finally:
        _lock.release()


def _generate(prompt, engine, width, height, seed, timeout, check):
    e, f = ENGINES[engine], folder()
    with tempfile.TemporaryDirectory(prefix="lumen-img-", dir=f, ignore_cleanup_errors=True) as tmp:
        out = Path(tmp) / "capa.png"
        cmd = [str(_exe()), "--diffusion-model", str(f / e["files"]["model"][0]), "--llm", str(f / e["files"]["llm"][0]),
               "--vae", str(f / e["files"]["vae"][0]), "-p", clean_prompt(prompt)[:1500] +
               (STYLE if width > height else STYLE.replace("wide cinematic", "balanced")), "-W", str(width), "-H", str(height),
               "-s", str(seed), "--diffusion-fa", "-o", str(out), *e["args"]]
        # sem --offload-to-cpu/--vae-tiling: com folga de VRAM o sd.cpp decide sozinho onde pôr cada parte
        # (backend_fit); com as duas opções ligadas a geração passou de 4 minutos no teste
        try:
            with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  cwd=str(_exe().parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
                until = time.monotonic() + timeout
                try:
                    while proc.poll() is None:
                        check()
                        if time.monotonic() >= until:
                            raise subprocess.TimeoutExpired(cmd, timeout)
                        time.sleep(0.2)
                    check()
                    if proc.returncode:
                        return None
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
        except (OSError, subprocess.SubprocessError):
            return None
        return out.read_bytes() if out.exists() and out.stat().st_size > 1000 else None
