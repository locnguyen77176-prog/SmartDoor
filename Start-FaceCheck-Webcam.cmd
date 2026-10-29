@echo off
setlocal
chcp 65001 >nul
title FaceCheck Server

pushd "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [LOI] Khong tim thay venv\Scripts\python.exe
    echo Hay tao moi truong ao va cai requirements.txt truoc khi khoi dong.
    echo.
    pause
    popd
    exit /b 1
)

if not exist "facecheck.py" (
    echo [LOI] Khong tim thay facecheck.py trong thu muc du an.
    echo.
    pause
    popd
    exit /b 1
)

echo Dang khoi dong FaceCheck voi webcam 0...
echo Khong dong cua so nay trong khi dang su dung he thong.
echo.

"venv\Scripts\python.exe" "facecheck.py" webcam --camera-index 0
set "FACECHECK_EXIT=%ERRORLEVEL%"

if not "%FACECHECK_EXIT%"=="0" (
    echo.
    echo [LOI] FaceCheck da dung voi ma loi %FACECHECK_EXIT%.
    echo Xem thong bao phia tren de xac dinh nguyen nhan.
    pause
)

popd
exit /b %FACECHECK_EXIT%
