; Inno Setup script - makes dist\installer\WanderPin-Setup-<version>.exe
; Change the name/version here AND in product.json when you rebrand.
#define AppName "WanderPin"
#define AppVersion "1.0.0"
#define AppPublisher "WanderPin"
#define AppExe "WanderPin.exe"

[Setup]
AppId={{6F2C9A4E-3B7D-4E1A-9C55-7A1D2B8E4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\EULA.txt
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup
SetupIconFile=..\static\img\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
