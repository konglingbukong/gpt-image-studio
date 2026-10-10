@echo off
rem GPT Image Studio - start the local workbench in the background (no console window).
rem If it's already running, this just opens the page.
start "" pythonw "%~dp0web\server.py"
