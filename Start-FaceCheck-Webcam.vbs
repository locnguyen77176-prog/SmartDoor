Option Explicit

Dim shell, fso, projectDir, pythonPath, mainPath, launcherPath

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonPath = fso.BuildPath(projectDir, "venv\Scripts\python.exe")
mainPath = fso.BuildPath(projectDir, "facecheck.py")
launcherPath = fso.BuildPath(projectDir, "Start-FaceCheck-Webcam-Hidden.cmd")

If Not fso.FileExists(pythonPath) Then
    MsgBox "Khong tim thay venv\Scripts\python.exe." & vbCrLf & _
           "Hay tao moi truong ao va cai requirements.txt.", _
           vbCritical, "FaceCheck"
    WScript.Quit 1
End If

If Not fso.FileExists(mainPath) Then
    MsgBox "Khong tim thay facecheck.py trong thu muc du an.", _
           vbCritical, "FaceCheck"
    WScript.Quit 1
End If

If Not fso.FileExists(launcherPath) Then
    MsgBox "Khong tim thay trinh khoi dong FaceCheck.", _
           vbCritical, "FaceCheck"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir

' Window style 0 starts the batch launcher without a console window.
shell.Run Chr(34) & launcherPath & Chr(34), 0, False

