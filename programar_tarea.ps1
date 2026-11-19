# Programa el piloto automático de CV TITAN: todos los días a las 8:00, oculto y con prioridad baja.
# Uso (PowerShell, en esta carpeta):   powershell -ExecutionPolicy Bypass -File .\programar_tarea.ps1
# Para quitarla:                       powershell -ExecutionPolicy Bypass -File .\programar_tarea.ps1 -Quitar
param([switch]$Quitar, [string]$Hora = "8:00")

$name = "CV TITAN - postulacion automatica"
if ($Quitar) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Tarea eliminada."
    exit
}
$root = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\pythonw.exe" `
    -Argument "-m cvtitan auto --linea todas --log data\auto\auto.log" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Hora
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -Priority 7 -MultipleInstances IgnoreNew -DontStopOnIdleEnd
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "Busca vacantes y postula a las que cumplen config\auto.yaml. Registro: data\auto\auto.log" | Out-Null
$next = (Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo).NextRunTime
Write-Host "Listo. CV TITAN postulará solo todos los días a las $Hora. Próxima ejecución: $next"
Write-Host "Registro de cada ejecución: $root\data\auto\auto.log"
