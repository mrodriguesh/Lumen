"""Grava o som do PC sem o app de música (filtro de música externa, passo 1: isolar a fonte).

O Windows 10 2004+/11 permite capturar o som de todos os processos menos uma árvore de processos (“process
loopback”, AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK). Se o Spotify (ou outro app de música) estiver aberto, a
música dele nem entra na gravação e a aula chega limpa, sem precisar separar nada. A captura em si é a do
soundcard (o mesmo gravador de lumen/record.py); aqui só muda como o cliente de áudio é aberto.

Música tocando no mesmo navegador da aula não dá para isolar assim: fica para o detector (lumen/music.py)."""
import ctypes
import uuid
from ctypes import POINTER, Structure, WINFUNCTYPE, byref, c_long, c_ulong, c_ushort, c_void_p, wintypes

# Apps só de música (nome do executável em minúsculas → nome mostrado). Players que também tocam vídeo (VLC,
# Media Player) ficam de fora: a aula pode estar neles.
MUSIC_APPS = {
    "spotify.exe": "Spotify", "deezer.exe": "Deezer", "tidal.exe": "TIDAL", "applemusic.exe": "Apple Music",
    "itunes.exe": "iTunes", "amazon music.exe": "Amazon Music", "amazonmusic.exe": "Amazon Music",
    "youtube music.exe": "YouTube Music", "youtube-music-desktop-app.exe": "YouTube Music", "qobuz.exe": "Qobuz",
    "music.ui.exe": "Groove Música", "foobar2000.exe": "foobar2000", "musicbee.exe": "MusicBee", "aimp.exe": "AIMP",
    "winamp.exe": "Winamp", "soundcloud.exe": "SoundCloud", "pandora.exe": "Pandora",
}


class _Entry(Structure):  # PROCESSENTRY32W
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def music_app():
    """(pid da raiz, nome) do primeiro app de música aberto, ou None."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return None
    procs = {}
    try:
        e = _Entry(dwSize=ctypes.sizeof(_Entry))
        ok = k32.Process32FirstW(snap, byref(e))
        while ok:
            procs[e.th32ProcessID] = (e.szExeFile.lower(), e.th32ParentProcessID)
            ok = k32.Process32NextW(snap, byref(e))
    finally:
        k32.CloseHandle(snap)
    for pid, (exe, parent) in sorted(procs.items()):
        # o Spotify abre vários processos filhos com o mesmo nome; a raiz é a que exclui a árvore toda
        if exe in MUSIC_APPS and procs.get(parent, ("",))[0] != exe:
            return pid, MUSIC_APPS[exe]
    return None


class _GUID(Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]


def _guid(s):
    return _GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


class _LoopbackParams(Structure):  # AUDIOCLIENT_ACTIVATION_PARAMS com AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS
    _fields_ = [("ActivationType", c_long), ("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_long)]


class _Blob(Structure):  # PROPVARIANT com VT_BLOB
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("cbSize", c_ulong), ("pBlobData", c_void_p)]


_QI = WINFUNCTYPE(c_long, c_void_p, POINTER(_GUID), POINTER(c_void_p))
_REF = WINFUNCTYPE(c_ulong, c_void_p)
_DONE = WINFUNCTYPE(c_long, c_void_p, c_void_p)


class _Vtbl(Structure):  # IActivateAudioInterfaceCompletionHandler
    _fields_ = [("QueryInterface", _QI), ("AddRef", _REF), ("Release", _REF), ("ActivateCompleted", _DONE)]


class _Handler(Structure):
    _fields_ = [("lpVtbl", POINTER(_Vtbl))]


_IIDS = {bytes(_guid(s).b) for s in ("00000000-0000-0000-C000-000000000046",    # IUnknown
                                     "41D949AB-9862-444A-80F6-C261334DA5EB",    # o handler
                                     "94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")}   # IAgileObject (exigido)
_IID_AUDIO_CLIENT = _guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")


def _call(ptr, index, *types):
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    return WINFUNCTYPE(c_long, c_void_p, *types)(vtbl[index])


def _activate(pid, timeout=5):
    """IAudioClient (endereço) que grava tudo menos a árvore de processos `pid`."""
    import threading
    done = threading.Event()

    def qi(this, iid, out):
        if bytes(iid.contents.b) in _IIDS:
            out[0] = this
            return 0
        out[0] = None
        return -2147467262  # E_NOINTERFACE

    def completed(this, op):
        done.set()
        return 0
    vt = _Vtbl(_QI(qi), _REF(lambda this: 1), _REF(lambda this: 1), _DONE(completed))  # objeto estático: sem contagem
    handler = _Handler(ctypes.pointer(vt))
    params = _LoopbackParams(1, pid, 1)  # PROCESS_LOOPBACK, EXCLUDE_TARGET_PROCESS_TREE
    blob = _Blob(vt=65, cbSize=ctypes.sizeof(params), pBlobData=ctypes.cast(byref(params), c_void_p))
    op = c_void_p()
    mmdev = ctypes.WinDLL("Mmdevapi")
    mmdev.ActivateAudioInterfaceAsync.restype = c_long
    hr = mmdev.ActivateAudioInterfaceAsync(ctypes.c_wchar_p("VAD\\Process_Loopback"), byref(_IID_AUDIO_CLIENT),
                                           byref(blob), byref(handler), byref(op))
    if hr < 0:
        raise OSError(f"ActivateAudioInterfaceAsync 0x{hr & 0xFFFFFFFF:08X}")
    try:
        if not done.wait(timeout):
            raise OSError("a ativação do áudio não respondeu")
        result, unk = c_long(), c_void_p()
        hr = _call(op, 3, POINTER(c_long), POINTER(c_void_p))(op, byref(result), byref(unk))  # GetActivateResult
        if hr < 0 or result.value < 0 or not unk:
            raise OSError(f"process loopback 0x{(result.value if hr >= 0 else hr) & 0xFFFFFFFF:08X}")
        client = c_void_p()
        hr = _call(unk, 0, POINTER(_GUID), POINTER(c_void_p))(unk, byref(_IID_AUDIO_CLIENT), byref(client))
        _call(unk, 2)(unk)
        if hr < 0 or not client:
            raise OSError(f"IAudioClient 0x{hr & 0xFFFFFFFF:08X}")
        return client.value
    finally:
        _call(op, 2)(op)  # Release
        _keep.append((vt, handler))  # o Windows pode chamar o handler depois do tempo esgotado


_keep = []


def _float_recorder(ptr, samplerate, channels, flags):
    """Gravador do soundcard (mesma interface de record()) com formato fixo float32 e sem GetMixFormat: o Windows
    converte o formato do aparelho (AUTOCONVERTPCM)."""
    from soundcard import mediafoundation as mf

    class _Recorder(mf._Recorder):
        def __init__(self):
            self._ptr, self.channelmap, self.samplerate, self._idle_start_time = ptr, list(range(channels)), samplerate, None
            fmt = mf._ffi.new("WAVEFORMATEXTENSIBLE*")
            f = fmt[0].Format
            f.wFormatTag, f.nChannels, f.nSamplesPerSec, f.wBitsPerSample, f.cbSize = 3, channels, samplerate, 32, 0
            f.nBlockAlign = channels * 4
            f.nAvgBytesPerSec = samplerate * channels * 4
            mf._com.check_error(ptr[0][0].lpVtbl.Initialize(ptr[0], 0, flags, 5_000_000, 0, fmt, mf._ffi.NULL))

        @property
        def deviceperiod(self):  # o process loopback não informa; 10 ms é o período típico do Windows
            return 0.01, 0.003

    try:
        return _Recorder()
    except Exception:
        mf._com.release(ptr)
        raise


def recorder(pid, samplerate, channels):
    """Gravador sobre o cliente de process loopback (não tem GetMixFormat)."""
    from soundcard import mediafoundation as mf
    ptr = mf._ffi.new("IAudioClient**")
    ptr[0] = mf._ffi.cast("IAudioClient*", _activate(pid))
    # loopback | autoconvert (outras flags dão AUDCLNT_E_INVALID_STREAM_FLAG)
    return _float_recorder(ptr, samplerate, channels, 0x00020000 | 0x80000000)


def _ensure_com():
    """O COM do Windows (MediaFoundation / WASAPI) é por thread: garante inicialização antes de abrir microfone ou saída."""
    import os
    if os.name == "nt":
        ctypes.windll.ole32.CoInitializeEx(None, 0)


def microphones():
    """Lista os microfones do Windows sem abrir fluxo nem gravar nada (só enumera os aparelhos)."""
    try:
        import soundcard as sc
        _ensure_com()
        default = sc.default_microphone()
        def_id = str(default.id) if default else ""
        return [{"id": str(m.id), "name": str(m.name), "default": str(m.id) == def_id}
                for m in sc.all_microphones(include_loopback=False)]
    except Exception:  # noqa: BLE001 — PC sem microfone ligado ou serviço de áudio parado
        return []


def microphone(samplerate, channels, mic_id=""):
    """O microfone escolhido (ou o padrão do Windows). O recorder() do soundcard exige que o aparelho informe o formato
    "extensible"; microfones USB mono (o USB AUDIO do estudante) informam PCM simples e ele falha num assert (02/11)."""
    import soundcard as sc
    _ensure_com()
    dev = None
    if mic_id:
        try:
            dev = sc.get_microphone(mic_id, include_loopback=False)
        except Exception:  # noqa: BLE001 — aparelho desligado: volta para o padrão do sistema
            dev = None
    dev = dev or sc.default_microphone()
    # autoconvert | conversão de taxa com a qualidade padrão do Windows
    return _float_recorder(dev._audio_client(), samplerate, channels, 0x80000000 | 0x08000000)


def _float_player(ptr, samplerate, channels, flags, buffer_ms=80):
    """Saída de áudio do soundcard com formato fixo float32 e sem GetMixFormat (a mesma proteção do microfone contra
    aparelhos USB que informam PCM simples). O buffer curto (~80 ms) deixa a interrupção imediata."""
    from soundcard import mediafoundation as mf

    class _Player(mf._Player):
        def __init__(self, ch):
            self._ptr, self.channelmap, self.samplerate, self._idle_start_time = ptr, list(range(ch)), samplerate, None
            fmt = mf._ffi.new("WAVEFORMATEXTENSIBLE*")
            f = fmt[0].Format
            f.wFormatTag, f.nChannels, f.nSamplesPerSec, f.wBitsPerSample, f.cbSize = 3, ch, samplerate, 32, 0
            f.nBlockAlign = ch * 4
            f.nAvgBytesPerSec = samplerate * ch * 4
            dur = max(200_000, int(buffer_ms * 10_000))  # unidades de 100 ns
            mf._com.check_error(ptr[0][0].lpVtbl.Initialize(ptr[0], 0, flags, dur, 0, fmt, mf._ffi.NULL))

        def flush(self):
            """Descarta o que ainda estava na fila da placa depois da descida suave."""
            try:
                self._ptr[0][0].lpVtbl.Stop(self._ptr[0])
                self._ptr[0][0].lpVtbl.Reset(self._ptr[0])
                self._ptr[0][0].lpVtbl.Start(self._ptr[0])
            except Exception:  # noqa: BLE001
                pass

    try:
        return _Player(channels)
    except Exception:
        mf._com.release(ptr)
        raise


def speaker(samplerate=24000, channels=1, buffer_ms=80):
    """A saída padrão do Windows (fone ou caixa de som), em float32, para a conversa por voz."""
    import soundcard as sc
    _ensure_com()
    flags = 0x80000000 | 0x08000000 | 0x00080000  # autoconvert | SRC qualidade padrão | nopersist
    spk = sc.default_speaker()
    try:
        return _float_player(spk._audio_client(), samplerate, channels, flags, buffer_ms)
    except Exception:
        if channels != 1:
            raise
        # alguns drivers só aceitam estéreo mesmo com AUTOCONVERTPCM; o play() duplica o canal mono
        return _float_player(spk._audio_client(), samplerate, 2, flags, buffer_ms)
