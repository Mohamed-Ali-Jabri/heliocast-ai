# Exemple : schedule du job quotidien sous Windows (sans Docker).
# A executer UNE FOIS dans PowerShell (administrateur) pour creer la tache,
# ou adapter la ligne Action au Planificateur de taches (GUI).

$py = "C:\Program Files\Python314\python.exe"
$proj = "C:\Système intelligent de prévision de la production photovoltaïque\Système intelligent de prévision de la production photovoltaïque"

$action   = New-ScheduledTaskAction -Execute $py -Argument "-m deploy.app.forecast_job --days 7" -WorkingDirectory $proj
$trigger  = New-ScheduledTaskTrigger -Daily -At 00:05
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "HelioCast_DailyForecast" -Action $action -Trigger $trigger -Settings $settings -Description "STEG HelioCast AI - prevision PV quotidienne" -Force

# Verification : Get-ScheduledTask -TaskName "HelioCast_DailyForecast"
# Lancement immediat (test) : Start-ScheduledTask -TaskName "HelioCast_DailyForecast"