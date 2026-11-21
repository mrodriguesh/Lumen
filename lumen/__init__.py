"""Lúmen — base local de conhecimento para um segundo cérebro e ferramentas de estudo."""
import os

# O OpenBLAS do numpy reserva ~30 MB por thread lógica ao carregar (12 neste i5-11400F: ~350 MB de memória
# comprometida), e as contas do Lúmen com ele são pequenas (busca, voz, 3D): 1 thread basta. Vale só para o Lúmen e os
# processos dele; o que o usuário já definiu prevalece, e os programas de terceiros (Voice Studio, Open Notebook,
# instaladores) recebem o ambiente sem estes valores.
OWN_ENV = {k: v for k, v in {"OPENBLAS_NUM_THREADS": "1"}.items() if k not in os.environ}
os.environ.update(OWN_ENV)


class AppError(Exception):
    """Erro mostrado ao usuário: o que aconteceu + a próxima ação."""

    def __init__(self, message, action=""):
        super().__init__(message)
        self.action = action


class Cancelled(Exception):
    pass
