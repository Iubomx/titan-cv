# Ejecución programada (Windows, Linux y macOS)

> **Aviso:** una tarea programada corre sin supervisión. Actívala solo después de revisar varias misiones manuales
> y con `send_enabled: false` salvo que aceptes que se envíen postulaciones reales sin que las veas.

## Windows
`powershell -ExecutionPolicy Bypass -File .\programar_tarea.ps1` (quitar: `-Quitar`).

## Linux (cron)
```cron
0 8 * * *  cd /ruta/a/titan-cv && .venv/bin/python -m cvtitan auto --linea todas --log data/auto/auto.log
```

## macOS (launchd)
Crea `~/Library/LaunchAgents/com.titancv.auto.plist` con `ProgramArguments` apuntando a
`/ruta/a/titan-cv/.venv/bin/python -m cvtitan auto --linea todas --log data/auto/auto.log`,
`WorkingDirectory` en la carpeta del proyecto y `StartCalendarInterval` (Hour 8, Minute 0).
Luego: `launchctl load ~/Library/LaunchAgents/com.titancv.auto.plist`.
