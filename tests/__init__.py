import os
import tempfile

# Dados do app isolados para os testes (nunca usa o histórico/config reais).
os.environ["LUMEN_DATA"] = tempfile.mkdtemp(prefix="lumen-test-")
