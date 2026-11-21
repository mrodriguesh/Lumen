import atexit
import os
import shutil
import tempfile

# Dados do app isolados para os testes (nunca usa o histórico/config reais), apagados ao terminar.
os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-test-")
atexit.register(shutil.rmtree, os.environ["LUMEN_DATA"], ignore_errors=True)

# O cofre do Windows nunca é lido, gravado nem apagado por um teste: todo o `keyring` cai num cofre em memória, trocado a cada
# execução. (Os testes que precisam de credenciais as põem aqui; os do Drive e do Notion usam o mesmo cofre falso.)
import keyring  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402
from keyring.errors import PasswordDeleteError  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.items = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.items:
            raise PasswordDeleteError("Entrada inexistente.")
        del self.items[(service, username)]


VAULT = MemoryKeyring()
keyring.set_keyring(VAULT)

# A visualização 3D fica ligada (como no app), mas desenhada pequena e com poucos quadros: os testes de tamanho real
# (960 × 540, peso, quadros) voltam aos valores de verdade em tests/test_visual3d.py.
from lumen import visual3d  # noqa: E402

REAL_VISUAL = {"W": visual3d.W, "H": visual3d.H, "ATTEMPTS": visual3d.ATTEMPTS}
visual3d.W, visual3d.H, visual3d.ATTEMPTS = 320, 180, ((320, 180, 6),)

# O Voice Studio do estudante nunca sobe, abre nem responde num teste (D53): os caminhos dele apontam para uma pasta
# vazia e o endereço padrão é uma porta fechada. Os testes da voz usam o falso (tests/fake_voicestudio.py).
from pathlib import Path  # noqa: E402

from lumen import voicestudio  # noqa: E402

_NO_VS = Path(os.environ["LUMEN_DATA"]) / "sem-voicestudio"
voicestudio.APP, voicestudio.USER_DATA = _NO_VS / "Programs", _NO_VS / "Roaming"
voicestudio.EXE, voicestudio.PROJECT = _NO_VS / "Programs" / "VoiceStudio.exe", _NO_VS / "Roaming" / "runtime" / "project"
voicestudio.PYTHON = voicestudio.PROJECT / ".venv" / "Scripts" / "python.exe"
os.environ.setdefault("LUMEN_VOICESTUDIO_URL", "http://127.0.0.1:9")
