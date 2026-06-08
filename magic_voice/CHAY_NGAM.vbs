Option Explicit
Dim fso, sh, base, py, logf, cmd, q, wmi, procs, p, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
q = Chr(34)
py = base & "\venv\Scripts\python.exe"
logf = base & "\tool_log.txt"

If Not fso.FileExists(py) Then
    MsgBox "Tool chua duoc cai dat. Hay chay file 1_CAI_DAT.bat truoc.", 48, "Chatterbox TTS"
    WScript.Quit
End If

Function PortReady()
    Dim tmp, ts, content
    tmp = base & "\port_check.tmp"
    sh.Run "cmd /c netstat -ano | findstr :7860 | findstr LISTENING > " & q & tmp & q, 0, True
    PortReady = False
    If fso.FileExists(tmp) Then
        Set ts = fso.OpenTextFile(tmp, 1)
        If Not ts.AtEndOfStream Then content = ts.ReadAll Else content = ""
        ts.Close
        fso.DeleteFile tmp
        If Len(Trim(content)) > 0 Then PortReady = True
    End If
End Function

Sub OpenAppWindow()
    On Error Resume Next
    sh.Run "msedge --app=http://127.0.0.1:7860", 1, False
    If Err.Number <> 0 Then
        Err.Clear
        sh.Run "chrome --app=http://127.0.0.1:7860", 1, False
        If Err.Number <> 0 Then
            Err.Clear
            sh.Run "http://127.0.0.1:7860", 1, False
        End If
    End If
End Sub

If PortReady() Then
    ' Dong co dang chay san -> mo cua so ngay
    OpenAppWindow
    WScript.Quit
End If

' Don tien trinh "xac song" con sot lai (neu co)
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe'")
For Each p In procs
    On Error Resume Next
    If Not IsNull(p.CommandLine) Then
        If InStr(LCase(p.CommandLine), LCase(base)) > 0 Then p.Terminate
    End If
    On Error GoTo 0
Next
WScript.Sleep 2000

' No may dong co (chay ngam)
sh.Environment("Process")("PYTHONUTF8") = "1"
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c " & q & q & py & q & " app.py > " & q & logf & q & " 2>&1" & q
sh.Run cmd, 0, False

' Cho toi da 3 phut, cu 5 giay kiem tra 1 lan, san sang la mo cua so
For i = 1 To 36
    WScript.Sleep 5000
    If PortReady() Then
        OpenAppWindow
        WScript.Quit
    End If
Next

MsgBox "Dong co khoi dong qua lau hoac bi loi." & vbCrLf & "Anh mo file tool_log.txt trong thu muc magic_voice va gui cho nguoi ho tro xem.", 48, "Chatterbox TTS"
