@echo off
rem Launch the Orihon virtual printer uninstaller with administrator rights.
setlocal
set "PS1=%~dp0Uninstall-OrihonPrinter.ps1"
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','\"%PS1%\"'"
endlocal
