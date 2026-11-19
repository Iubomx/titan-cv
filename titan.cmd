@echo off
rem Atajo de TITAN CV: ejecuta la CLI con el entorno del proyecto, desde cualquier carpeta.
rem Uso:  titan auto  |  titan informe  |  titan informe --historial  |  titan demo <URL>
"%~dp0.venv\Scripts\python.exe" -m cvtitan %*
