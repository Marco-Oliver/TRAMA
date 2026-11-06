#define MyAppName "TRAMA"
#define MyAppVersion "2.2.0"
#define MyAppExeName "TRAMA.exe"

[Setup]
AppId={{9819EDB4-FC18-4D9E-99F6-8CB6D9914407}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=TRAMA
DefaultDirName={localappdata}\Programs\TRAMA
DefaultGroupName=TRAMA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UninstallDisplayIcon={app}\TRAMA.exe
SetupIconFile=assets\trama.ico
OutputDir=release
OutputBaseFilename=TRAMA_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartIfNeededByRun=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "dist\TRAMA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TRAMA"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\TRAMA"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir TRAMA"; Flags: postinstall nowait skipifsilent
