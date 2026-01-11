#define MyAppName "CaffeinatedWin"
#define MyAppVersion "1.0.0"
#define MyAppExeName "CaffeinatedWin.exe"

[Setup]
AppId={{9A38D2A6-76E8-4F2C-9C0D-0E5F2E7E3A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist-installer
OutputBaseFilename={#MyAppName}-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"
Name: "startup"; Description: "Run {#MyAppName} when I log in"; GroupDescription: "Startup:"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F >nul 2>&1"; Flags: runhidden
