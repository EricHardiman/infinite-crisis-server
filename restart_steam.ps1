# Like restart_test.ps1, but the GAME is launched by the user from Steam (non-Steam shortcut to
# InfiniteCrisis_patched.exe, so Steam's overlay / game recording work). This script stops the old
# server/tracer/game, starts the server, waits for the game to appear, then applies the same CPU
# affinity as restart_test.ps1 and starts the tracer.
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -match 'tracer.py|login_server.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Stop-Process -Name InfiniteCrisis,InfiniteCrisis_patched -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Process python -ArgumentList "login_server.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Write-Output "server started - launch Infinite Crisis from Steam now (waiting up to 5 minutes)"
$game = $null
for ($i = 0; $i -lt 300 -and -not $game; $i++) {
    Start-Sleep -Seconds 1
    $game = Get-Process InfiniteCrisis_patched -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $game) { Write-Output "game did not start"; exit 1 }
try { $game.ProcessorAffinity = [IntPtr]0xFFFE } catch { Write-Output "could not set affinity: $_" }
Start-Sleep -Seconds 12
Start-Process python -ArgumentList "tracer.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Sleep -Seconds 4
Get-Process InfiniteCrisis_patched | Select-Object Id, Responding
Get-Content (Join-Path $PSScriptRoot "logs\trace.log") -Tail 2
