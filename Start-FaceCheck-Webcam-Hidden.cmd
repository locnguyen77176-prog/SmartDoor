@echo off
setlocal
pushd "%~dp0"

if not exist "data" mkdir "data"
"venv\Scripts\python.exe" "facecheck.py" webcam --camera-index 0 >> "data\facecheck-server.log" 2>&1

popd
endlocal

