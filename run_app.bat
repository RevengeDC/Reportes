@echo off
title CPNB-ZULIA Monitor
echo.
echo  Instalando dependencias...
pip install fastapi uvicorn aiofiles --quiet
echo.
echo  Iniciando servidor...
echo.
python app.py
pause
