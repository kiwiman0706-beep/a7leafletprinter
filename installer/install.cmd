@echo off
rem Launch the Orihon virtual printer installer with administrator rights.
setlocal
set "PS1=%~dp0Install-OrihonPrinter.ps1"
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','\"%PS1%\"'"
endlocal
