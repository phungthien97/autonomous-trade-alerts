@echo off
title Live Bot Status
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\ibgateway\check_bot.ps1"
