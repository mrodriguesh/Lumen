"""Processo de voz dos Estudos (D44): o Chatterbox pt-br, num processo à parte, com o Python do ambiente dele
(D:\\Lumen\\voz\\chatterbox), fora do .venv do Lúmen. Não importa nada do app: o ambiente dele só tem o motor.

Protocolo, um JSON por linha:
- a primeira linha da saída é {"ready": true, "sr": 24000} quando o modelo carregou, ou {"fatal": "..."};
- cada pedido na entrada, {"id": 7, "text": "...", "out": "caminho.wav", "seed": 1}, recebe {"id": 7, "ok": true,
  "seconds": 2.4} ou {"id": 7, "error": "..."}. O id volta igual: depois de um cancelamento, o app ignora a resposta
  atrasada do pedido antigo.
Nenhuma voz é clonada: é a voz padrão do modelo (conds.pt do repositório base)."""
import json
import os
import sys
import wave
from pathlib import Path

ROOT = Path(os.environ.get("LUMEN_VOICE_DIR", r"D:\Lumen\voz"))
os.environ.setdefault("HF_HOME", str(ROOT / "hf"))
os.environ.setdefault("TORCH_HOME", str(ROOT / "torch"))
BASE, PTBR = "ResembleAI/chatterbox", "ResembleAI/Chatterbox-Multilingual-pt-br"
# nome que o chatterbox-tts 0.1.7 espera → (repositório, arquivo do finetune brasileiro)
FILES = {"ve.pt": (BASE, "ve.pt"), "conds.pt": (BASE, "conds.pt"),
         "t3_mtl23ls_v2.safetensors": (PTBR, "t3_pt_br.safetensors"), "s3gen.pt": (PTBR, "s3gen_v3.pt"),
         "grapheme_mtl_merged_expanded_v1.json": (PTBR, "grapheme_mtl_merged_expanded_v1.json")}
MAX_CHARS = 600


def load(device="cuda"):
    """O from_local da 0.1.7 com os pesos pt-br. A pasta local liga (link físico) os arquivos do finetune aos nomes do
    modelo v2; o s3gen_v3 não guarda dois valores que o S3Gen recalcula (filtro de mel e janela), e só essa falta é
    aceita."""
    import torch
    from chatterbox import mtl_tts
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    ckpt = ROOT / "chatterbox-ptbr"
    ckpt.mkdir(parents=True, exist_ok=True)
    for name, (repo, file) in FILES.items():
        if not (ckpt / name).exists():
            os.link(Path(hf_hub_download(repo, file)).resolve(), ckpt / name)
    ve = mtl_tts.VoiceEncoder()
    ve.load_state_dict(torch.load(ckpt / "ve.pt", weights_only=True))
    t3 = mtl_tts.T3(mtl_tts.T3Config.multilingual())
    t3.load_state_dict(load_file(str(ckpt / "t3_mtl23ls_v2.safetensors")))
    s3gen = mtl_tts.S3Gen()
    missing, unexpected = s3gen.load_state_dict(torch.load(ckpt / "s3gen.pt", weights_only=True), strict=False)
    if unexpected or set(missing) - {"tokenizer._mel_filters", "tokenizer.window"}:
        raise RuntimeError(f"s3gen_v3 incompatível: faltam {missing}, sobram {unexpected}")
    return mtl_tts.ChatterboxMultilingualTTS(
        t3.to(device).eval(), s3gen.to(device).eval(), ve.to(device).eval(),
        mtl_tts.MTLTokenizer(str(ckpt / "grapheme_mtl_merged_expanded_v1.json")), device,
        conds=mtl_tts.Conditionals.load(ckpt / "conds.pt").to(device))


def write(path, audio, sr):
    """WAV mono de 16 bits; só limita o pico (o volume final é igualado na mixagem)."""
    import numpy as np
    audio = np.asarray(audio, np.float32).ravel()
    audio = audio * min(1.0, 0.98 / max(float(np.abs(audio).max()) if audio.size else 0.0, 1e-9))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((audio * 32767).astype(np.int16).tobytes())


def main():
    out, sys.stdout = sys.stdout, sys.stderr  # o que as bibliotecas imprimirem não suja o protocolo
    try:
        import torch
        model = load()
    except Exception as e:  # noqa: BLE001 — o app mostra o motivo e segue sem voz
        print(json.dumps({"fatal": f"{type(e).__name__}: {e}"[:300]}), file=out, flush=True)
        return 1
    print(json.dumps({"ready": True, "sr": model.sr}), file=out, flush=True)
    for line in sys.stdin:
        req = {}
        try:
            req = json.loads(line)
            torch.manual_seed(int(req.get("seed") or 1))
            with torch.inference_mode():
                wav = model.generate(str(req["text"])[:MAX_CHARS], language_id="pt").squeeze().float().cpu().numpy()
            write(req["out"], wav, model.sr)
            reply = {"ok": True, "seconds": round(len(wav) / model.sr, 2)}
        except Exception as e:  # noqa: BLE001 — uma frase ruim não derruba o processo
            reply = {"error": f"{type(e).__name__}: {e}"[:300]}
        print(json.dumps({"id": req.get("id") if isinstance(req, dict) else None, **reply}), file=out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
