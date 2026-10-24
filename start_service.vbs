' 静默启动本地字幕服务：双击本文件即可，不弹任何窗口。
' 想开机自启，运行一次 install_autostart.bat。
'
' 实际启动的是同目录的 start_service.bat，由它拉起 python.exe。
' 这里只负责“把窗口藏起来”，因为 .bat 自己没法不显示控制台。
Option Explicit

Dim fso, sh, base, bat
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
bat = base & "\start_service.bat"

If Not fso.FileExists(bat) Then
    MsgBox "start_service.bat not found next to this file:" & vbCrLf & vbCrLf & _
           base, 16, "TCM Captions"
    WScript.Quit 1
End If

sh.CurrentDirectory = base
sh.Run """" & bat & """", 0, False
