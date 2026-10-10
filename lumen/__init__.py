"""Lumen — transforma aulas em vídeo em páginas de estudo no Notion."""


class AppError(Exception):
    """Erro mostrado ao usuário: o que aconteceu + a próxima ação."""

    def __init__(self, message, action=""):
        super().__init__(message)
        self.action = action


class Cancelled(Exception):
    pass
