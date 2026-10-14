@echo off
chcp 65001 >nul
set "VENV=C:/Users/wuyijun/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"%VENV%" "%~dp0prompt_pusher\cli.py" %*
pause
