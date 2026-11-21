@echo off
setlocal
cd /d "%~dp0"

rem O marcador so e criado depois que todas as dependencias instalaram; se algo falhar, a proxima abertura tenta de novo.
if not exist ".venv\.instalado" (
  echo Preparando o Lumen ^(so acontece na primeira vez^)...
  if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv || python -m venv .venv || (
      echo Python 3.11+ nao encontrado. Instale em https://www.python.org/downloads/ e tente de novo.
      pause & exit /b 1
    )
  )
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (
    echo Falha ao instalar dependencias. Verifique a internet e abra o Lumen de novo.
    pause & exit /b 1
  )
  where nvidia-smi >nul 2>nul && (
    choice /m "GPU NVIDIA detectada. Baixar suporte a GPU (cerca de 1 GB) para transcrever mais rapido"
    if not errorlevel 2 (
      ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-gpu.txt
      rem filtro de musica na GPU: o onnxruntime-directml ocupa o lugar do onnxruntime de CPU (mesmo modulo)
      ".venv\Scripts\python.exe" -m pip uninstall --disable-pip-version-check -q -y onnxruntime
      ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q onnxruntime-directml==1.24.4 || ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q onnxruntime
    )
  )
  echo ok> ".venv\.instalado"
)

rem Dependencias que entraram depois da primeira instalacao (Pillow: visualizacao 3D). So instala o que falta.
".venv\Scripts\python.exe" -c "import PIL" 2>nul || ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pillow==12.3.0

if exist "Lumen.exe" (start "" "Lumen.exe") else (start "" ".venv\Scripts\pythonw.exe" -m lumen)
