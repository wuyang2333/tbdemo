' hidden_launch.vbs - Start taobao workbench services without any console window.
' Usage: wscript hidden_launch.vbs backend | wscript hidden_launch.vbs frontend
Option Explicit
Dim args, ws, cmd
Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 1
Set ws = CreateObject("WScript.Shell")

If args(0) = "backend" Then
    cmd = "cmd /c cd /d D:\demo && C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 >> D:\demo\logs\backend.log 2>&1"
ElseIf args(0) = "frontend" Then
    cmd = "cmd /c cd /d D:\demo\frontend && npm run dev >> D:\demo\logs\frontend.log 2>&1"
Else
    WScript.Quit 2
End If

' 0 = hide window, False = do not wait
ws.Run cmd, 0, False
WScript.Quit 0
