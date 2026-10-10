@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Primeira execucao: preparando o Lumen ^(so acontece uma vez^)...
  py -3 -m venv .venv || python -m venv .venv || (
    echo Python 3.11+ nao encontrado. Instale em https://www.python.org/downloads/ e tente de novo.
    pause & exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (
    echo Falha ao instalar dependencias. Verifique a internet e tente de novo.
    pause & exit /b 1
  )
  where nvidia-smi >nul 2>nul && (
    choice /m "GPU NVIDIA detectada. Baixar suporte a GPU (cerca de 1 GB) para transcrever mais rapido"
    if not errorlevel 2 ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-gpu.txt
  )
)

if exist "Lumen.exe" (start "" "Lumen.exe") else (start "" ".venv\Scripts\pythonw.exe" -m lumen)
