# Enregistre une tâche planifiée Windows qui lance arpej_watch.py toutes les N minutes.
# Usage :  powershell -ExecutionPolicy Bypass -File install_task.ps1
#          powershell -ExecutionPolicy Bypass -File install_task.ps1 -IntervalMinutes 10
#          powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove

param(
    [int]$IntervalMinutes = 15,
    [switch]$Remove
)

$TaskName = "ARPEJ-Palaiseau-Watch"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ScriptDir "arpej_watch.py"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Tache '$TaskName' supprimee."
    exit 0
}

# pythonw.exe = pas de fenetre console qui clignote a chaque execution
$Python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Write-Error "Python introuvable dans le PATH."; exit 1 }

if (-not (Test-Path (Join-Path $ScriptDir "config.json"))) {
    Write-Warning "config.json absent : cree-le a partir de config.example.json avant que la tache ne serve a quelque chose."
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$ScriptPath`"" -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Verifie les logements disponibles sur les residences ARPEJ de Palaiseau et envoie un mail." | Out-Null

Write-Host "Tache '$TaskName' enregistree : verification toutes les $IntervalMinutes minutes."
Write-Host "Python  : $Python"
Write-Host "Script  : $ScriptPath"
Write-Host "Logs    : $(Join-Path $ScriptDir 'watch.log')"
Write-Host ""
Write-Host "Lancer tout de suite :  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Supprimer            :  powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove"
