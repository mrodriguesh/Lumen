import atexit
import os
import shutil
import tempfile

# Dados do app isolados para os testes (nunca usa o histórico/config reais), apagados ao terminar.
os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-test-")
atexit.register(shutil.rmtree, os.environ["LUMEN_DATA"], ignore_errors=True)
