@echo off
cd /d %~dp0\api
uvicorn main:app --host 0.0.0.0 --port 8000
