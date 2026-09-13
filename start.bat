@echo off
setlocal EnableExtensions
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Network Inspector yonetici yetkisi istiyor...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

where py >nul 2>&1
if not "%errorlevel%"=="0" (
  echo HATA: Python 3.12 veya daha yenisi gerekli.
  pause
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
if not "%errorlevel%"=="0" (
  echo HATA: Python 3.12 veya daha yenisi bulunamadi.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Ilk kurulum yapiliyor. Bu islem birkac dakika surebilir...
  py -3 -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

echo CA sertifikasi kontrol ediliyor...
".venv\Scripts\python.exe" -m backend.cert.bootstrap
if not "%errorlevel%"=="0" goto :certificate_error

where npm >nul 2>&1
if errorlevel 1 (
  echo HATA: Frontend build icin Node.js ve npm gerekli.
  pause
  exit /b 1
)
echo Frontend hazirlaniyor...
pushd frontend
call npm ci || goto :error_popd
call npm run build || goto :error_popd
popd

echo Stale ag durumu temizleniyor...
".venv\Scripts\python.exe" -m backend.net.cleanup --runtime-dir "%CD%\.runtime"

echo Network Inspector baslatiliyor: http://127.0.0.1:43110
start "" powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(45); while((Get-Date) -lt $deadline){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:43110/api/health | Out-Null; Start-Process http://127.0.0.1:43110; break}catch{Start-Sleep -Milliseconds 400}}"
".venv\Scripts\python.exe" -m backend.main
goto :cleanup

:error_popd
popd
:error
echo Kurulum basarisiz oldu. Yukaridaki hatayi inceleyin.
pause
exit /b 1

:certificate_error
echo.
echo CA sertifikasi kurulmadan Network Inspector baslatilmadi.
echo start.bat dosyasini tekrar calistirarak kurulumu yeniden deneyebilirsiniz.
pause
exit /b 1

:cleanup
echo Guvenli kapatma kontrolu yapiliyor...
".venv\Scripts\python.exe" -m backend.net.cleanup --runtime-dir "%CD%\.runtime"
pause
