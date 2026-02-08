@echo off
echo Stopping CryptoTrader bot...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq *run_forever*" >nul 2>&1
:: Kill any python processes running main.py or run_forever.py from our directory
for /f "tokens=2" %%i in ('wmic process where "CommandLine like '%%CryptoTrader%%run_forever%%'" get ProcessId /format:list 2^>nul ^| findstr ProcessId') do taskkill /f /pid %%i >nul 2>&1
for /f "tokens=2" %%i in ('wmic process where "CommandLine like '%%CryptoTrader%%main.py%%'" get ProcessId /format:list 2^>nul ^| findstr ProcessId') do taskkill /f /pid %%i >nul 2>&1
echo CryptoTrader bot stopped.
pause
