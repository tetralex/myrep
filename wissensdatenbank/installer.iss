; Inno-Setup-Skript für einen Windows-Installer.
; Wird von build.bat automatisch aufgerufen, wenn Inno Setup 6 installiert ist.
; Name/Version kommen per /D-Parameter aus app/config.py.

#ifndef MyAppName
  #define MyAppName "KälteWiki"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "KaelteWiki.exe"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E0B-9C1A-5D2E7B4A9C10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=Setup_{#MyAppName}_{#MyAppVersion}
SetupIconFile=app\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Zusätzliche Verknüpfungen:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} jetzt starten"; Flags: nowait postinstall skipifsilent

; Benutzerdaten (%APPDATA%) bleiben bei der Deinstallation absichtlich erhalten.
