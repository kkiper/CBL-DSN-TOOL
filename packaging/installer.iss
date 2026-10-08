; Inno Setup script: Windows installer with Start menu entry and .cbl file association.
; Build after PyInstaller:  iscc /DAppVersion=0.3.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif

[Setup]
AppId={{6B7E5D0A-2F0C-4C8E-9C41-3D5C1B2A7F10}
AppName=Cable Designer
AppVersion={#AppVersion}
AppPublisher=Cable Designer
DefaultDirName={autopf}\Cable Designer
DefaultGroupName=Cable Designer
OutputDir=..\dist
OutputBaseFilename=CableDesigner-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\CableDesigner.exe
Compression=lzma2
SolidCompression=yes
ChangesAssociations=yes
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\CableDesigner.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Cable Designer"; Filename: "{app}\CableDesigner.exe"
Name: "{autodesktop}\Cable Designer"; Filename: "{app}\CableDesigner.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Registry]
Root: HKA; Subkey: "Software\Classes\.cbl"; ValueType: string; ValueName: ""; ValueData: "CableDesigner.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\CableDesigner.Project"; ValueType: string; ValueName: ""; ValueData: "Cable Designer project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\CableDesigner.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\CableDesigner.exe,0"
Root: HKA; Subkey: "Software\Classes\CableDesigner.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\CableDesigner.exe"" ""%1"""

[Run]
Filename: "{app}\CableDesigner.exe"; Description: "Start Cable Designer"; Flags: nowait postinstall skipifsilent
