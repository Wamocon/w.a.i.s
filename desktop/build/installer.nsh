; Zusätze zum Installer (electron-builder, NSIS, pro Benutzer, ohne Adminrechte).
;
; Deinstallation und Aktualisierung: Die geplante Aufgabe "WAMO Tunnel" (Host und SSH-Rücktunnel) läuft aus dem
; Installationsordner. Vorher beenden und entfernen, sonst halten laufende Programme Dateien fest. Nach einer
; Aktualisierung legt die Geräteeinrichtung der App die Aufgabe bei der nächsten Anmeldung wieder an.
; Schlüssel, Token und Gerätedaten (%LOCALAPPDATA%\WAMO, %USERPROFILE%\.ssh) bleiben bewusst stehen.
; Der Deinstaller ist ein 32-Bit-Programm: ohne Abschalten der Umleitung liefe eine 32-Bit-PowerShell (SysWOW64).
!include "x64.nsh"
; Sandbox-Zugriff auf den Installationsordner: Im Ordner Programs eines Benutzers tragen oft einzelne Windows-App-Pakete
; Rechte (S-1-15-2-...), aber nicht "ALLE ANWENDUNGSPAKETE". Dann verweigert Windows dem Sandbox-Prozess von Electron das
; Lesen, und die App bricht beim Start mit einem Fatal-Fehler ab (install_dir_access.cc). Der Benutzer ist Besitzer seines
; Ordners, deshalb braucht das keine Adminrechte. Nur dieser Ordner, nur Lesen und Ausführen.
; Symbol nach einem Update: Beim Update behält electron-builder die Verknüpfung im Startmenü (--keep-shortcuts) und tauscht nur
; die EXE. Dann liest Windows den Eintrag der App-Kennung im App-Zwischenspeicher der Shell nicht neu (am 14.11.2026 nachgestellt:
; neu gelesen wurde er nur bei einer umbenannten Verknüpfung), und ein dort hängengebliebenes leeres Symbol bliebe stehen.
; Deshalb die Verknüpfung neu schreiben (dieselbe Kennung, Ziel und Symbol bleiben), Verknüpfung und EXE als geändert melden
; (SHCNE_UPDATEITEM) und danach neue Symbole (SHCNE_ASSOCCHANGED). SHCNF_FLUSH (0x1000) wartet, bis die Shell die Meldung hat.
; customInstall läuft vor dem Start der App (runAfterFinish). Gemessen schreibt die Shell den neu gelesenen Eintrag rund 2,2 s nach
; der neuen Verknüpfung; ohne Wartezeit startete die App 1,1 s davor. Deshalb 3 s warten, dann startet die App. electron-builder meldet neue
; Symbole sonst nur beim Anlegen einer Desktop-Verknüpfung, die es hier nicht gibt (createDesktopShortcut: false).
; Kein Löschen von Dateien der Shell und kein Neustart des Explorers im Installer: Das macht nur das Reparaturwerkzeug
; (scripts\wamo-symbol-reparieren.ps1, Tray "Taskleisten-Symbol reparieren"), und nur nach Rückfrage.
!macro customInstall
  nsExec::Exec '"$SYSDIR\icacls.exe" "$INSTDIR" /grant *S-1-15-2-1:(OI)(CI)(RX)'
  Pop $0
  ${If} ${FileExists} "$newStartMenuLink"
    WinShell::SetLnkAUMI "$newStartMenuLink" "${APP_ID}"
    System::Call 'shell32::SHChangeNotify(i 0x00002000, i 0x1005, w "$newStartMenuLink", p 0)'
  ${EndIf}
  System::Call 'shell32::SHChangeNotify(i 0x00002000, i 0x1005, w "$appExe", p 0)'
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0x1000, p 0, p 0)'
  Sleep 3000
!macroend

!macro customUnInstall
  ${DisableX64FSRedirection}
  IfFileExists "$INSTDIR\resources\scripts\wamo-tunnel-entfernen.ps1" 0 +2
  nsExec::Exec '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\scripts\wamo-tunnel-entfernen.ps1"'
  ${EnableX64FSRedirection}
!macroend
