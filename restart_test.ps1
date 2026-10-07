# Stops server/tracer/game, then starts the game. Server and tracer are started separately.
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -match 'tracer.py|login_server.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Stop-Process -Name InfiniteCrisis,InfiniteCrisis_patched -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Set-Location (Split-Path $PSScriptRoot -Parent)
Start-Process python -ArgumentList "login_server.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Sleep -Seconds 2
cmd /c 'start "" /affinity FFFE InfiniteCrisis_patched.exe --loginurl http://127.0.0.1:8888/WebLoginApp-1.3/AuthenticateWS --loginregion NA --reportingurl http://127.0.0.1:8888/WebLoginApp-1.3/Metrics --language en'
Start-Sleep -Seconds 12
Start-Process python -ArgumentList "tracer.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Sleep -Seconds 4
Get-Process InfiniteCrisis_patched | Select-Object Id, Responding
Get-Content (Join-Path $PSScriptRoot "logs\trace.log") -Tail 2
