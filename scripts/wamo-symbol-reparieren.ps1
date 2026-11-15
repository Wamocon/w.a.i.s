<#
.SYNOPSIS
  Taskleisten-Symbol von W.A.I.S. reparieren: Explorer beenden, den App-Zwischenspeicher der Shell löschen, Explorer starten.

.DESCRIPTION
  Befund 14.11.2026: Nach einem Update zeigte die Taskleiste für das Fenster von W.A.I.S. ein leeres Datei-Symbol, obwohl EXE,
  Verknüpfung im Startmenü und Fenster das richtige Symbol hatten. Der Zustand hing an der App-Kennung de.wamocon.wamo und
  überstand Neustarts des Explorers. Geholfen hat nur: Explorer beenden, die Dateien *.db in
  %LOCALAPPDATA%\Microsoft\Windows\Caches löschen (App-Zwischenspeicher der Shell, Windows legt sie beim nächsten Start neu an)
  und den Explorer starten. Genau das macht dieses Skript, nur für den angemeldeten Benutzer und nur nach Bestätigung.

  Ablauf: Der Explorer wird zuerst geordnet beendet (wie "Explorer beenden" im Kontextmenü der Taskleiste, dann startet Windows
  ihn nicht von selbst neu), nach 10 Sekunden notfalls hart. Danach werden nur die Dateien *.db direkt im Ordner Caches gelöscht,
  nichts in Unterordnern und keine anderen Dateien. Zum Schluss startet der Explorer wieder, falls er nicht schon läuft. Die
  Taskleiste verschwindet für einige Sekunden, offene Explorer-Fenster schließen sich. Die letzte Zeile der Ausgabe ist das
  Ergebnis als JSON (für die Desktop-App).

  Aufruf von Hand:  powershell -NoProfile -ExecutionPolicy Bypass -File wamo-symbol-reparieren.ps1
  Die Desktop-App ruft das Skript über den Tray-Eintrag "Taskleisten-Symbol reparieren" mit -Bestaetigt auf, nachdem sie selbst
  nachgefragt hat.

.PARAMETER Bestaetigt
  Ohne Rückfrage ausführen (die Desktop-App fragt vorher selbst).
.PARAMETER Trocken
  Nur anzeigen, was gelöscht würde. Ändert nichts und fasst den Explorer nicht an.
.PARAMETER CacheOrdner
  Nur für Tests: anderer Ordner. Er muss Caches heißen.
.PARAMETER ExplorerLassen
  Nur für Tests: den Explorer weder beenden noch starten.
#>
[CmdletBinding()]
param(
  [switch]$Bestaetigt,
  [switch]$Trocken,
  [string]$CacheOrdner = "",
  [switch]$ExplorerLassen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($CacheOrdner -eq "") { $CacheOrdner = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Caches" }
if ((Split-Path -Leaf $CacheOrdner) -ne "Caches") { throw "Der Ordner muss Caches heißen: $CacheOrdner" }

function Ergebnis([string]$ergebnis, [string[]]$geloescht, [string[]]$gesperrt, [string]$explorer) {
  [pscustomobject]@{
    ergebnis  = $ergebnis
    geloescht = [string[]]@($geloescht)
    gesperrt  = [string[]]@($gesperrt)
    explorer  = $explorer
  } | ConvertTo-Json -Compress
}

# Nur Dateien *.db direkt im Ordner, keine Unterordner
$dateien = @()
if (Test-Path -LiteralPath $CacheOrdner -PathType Container) {
  $dateien = @(Get-ChildItem -LiteralPath $CacheOrdner -File -Force | Where-Object { $_.Extension -eq ".db" })
}

if ($Trocken) {
  Write-Output "Probelauf: würde in $CacheOrdner löschen: $(($dateien | ForEach-Object Name) -join ', ')"
  Ergebnis "trocken" ([string[]]@($dateien | ForEach-Object Name)) @() "nicht angefasst"
  exit 0
}

if (-not $Bestaetigt) {
  Write-Output "Der Explorer wird beendet und neu gestartet, die Taskleiste verschwindet für einige Sekunden."
  Write-Output "Gelöscht werden nur die Dateien *.db in $CacheOrdner."
  $antwort = Read-Host "Fortfahren? (ja/nein)"
  if ($antwort -ne "ja") {
    Ergebnis "abgebrochen" @() @() "nicht angefasst"
    exit 1
  }
}

$sitzung = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
function Explorer-Prozesse { @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $sitzung }) }

$explorerStand = "nicht angefasst"
$geloescht = New-Object System.Collections.Generic.List[string]
$gesperrt = New-Object System.Collections.Generic.List[string]
try {
  if (-not $ExplorerLassen) {
    Add-Type -Namespace WamoSymbol -Name Shell -MemberDefinition @'
[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindow(string klasse, string titel);
[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr fenster, uint nachricht, IntPtr w, IntPtr l);
'@
    # Geordnet beenden: Nachricht 0x5B4 (WM_USER + 436) an die Taskleiste, wie "Explorer beenden" in ihrem Kontextmenü
    $taskleiste = [WamoSymbol.Shell]::FindWindow("Shell_TrayWnd", $null)
    if ($taskleiste -ne [IntPtr]::Zero) { [void][WamoSymbol.Shell]::PostMessage($taskleiste, 0x5B4, [IntPtr]::Zero, [IntPtr]::Zero) }
    $bis = (Get-Date).AddSeconds(10)
    while ((Explorer-Prozesse).Count -gt 0 -and (Get-Date) -lt $bis) { Start-Sleep -Milliseconds 250 }
    $rest = Explorer-Prozesse
    if ($rest.Count -gt 0) {
      $rest | Stop-Process -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 500
    }
    $explorerStand = "neu gestartet"
  }

  foreach ($d in $dateien) {
    $weg = $false
    for ($versuch = 0; $versuch -lt 10 -and -not $weg; $versuch++) {
      try {
        Remove-Item -LiteralPath $d.FullName -Force -ErrorAction Stop
        $weg = $true
      } catch {
        Start-Sleep -Milliseconds 500
      }
    }
    if ($weg) { $geloescht.Add($d.Name) } else { $gesperrt.Add($d.Name) }
  }
} finally {
  # Auch nach einem Fehler: Ohne laufenden Explorer gäbe es keine Taskleiste mehr
  if (-not $ExplorerLassen -and (Explorer-Prozesse).Count -eq 0) {
    # Der neue Explorer erbt die Umgebung dieses Prozesses: Variablen der Desktop-App gehören nicht dazu
    Get-ChildItem Env: | Where-Object { $_.Name -match '^(ELECTRON_|CHROME_|WAMO_|NODE_OPTIONS$)' } | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }
    Start-Process -FilePath (Join-Path $env:SystemRoot "explorer.exe")
  }
}

$stand = if ($gesperrt.Count -eq 0) { "repariert" } else { "teilweise" }
Write-Output "Gelöscht: $($geloescht.Count), gesperrt: $($gesperrt.Count), Explorer: $explorerStand"
Ergebnis $stand $geloescht.ToArray() $gesperrt.ToArray() $explorerStand
if ($gesperrt.Count -gt 0) { exit 2 }
exit 0
