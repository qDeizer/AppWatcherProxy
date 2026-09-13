@echo off
setlocal EnableExtensions
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

if exist ".runtime\state.json" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$state = Get-Content -Raw -LiteralPath '.runtime\state.json' | ConvertFrom-Json; foreach($id in @($state.main_pid,$state.watchdog_pid)){if($id){Stop-Process -Id $id -Force -ErrorAction SilentlyContinue}}"
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m backend.net.cleanup --runtime-dir "%CD%\.runtime"
) else (
  netsh advfirewall firewall delete rule name="NetworkInspector-Block-QUIC" >nul 2>&1
  echo Python ortami yok; bilinen firewall kurali dogrudan temizlendi.
)

echo Temizlik tamamlandi. Sistem proxy ayarlari bu uygulama tarafindan degistirilmedi.
pause

