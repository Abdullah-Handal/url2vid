; Inno Setup script for the url2vid installer.
;
; Installs under the user's Documents folder and asks for no administrator
; rights, so it works on a locked-down machine and needs no UAC prompt.
;
; Build with:  ISCC /DAppVersion=0.1.1 packaging\url2vid.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "url2vid"
#define AppExe "url2vid.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Abdullah-Handal
DefaultDirName={userdocs}\{#AppName}
DefaultGroupName={#AppName}
; "lowest" keeps the whole install inside the user's own profile.
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=installer
OutputBaseFilename=url2vid-windows-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the Desktop"; GroupDescription: "Shortcuts:"

[Files]
; The whole PyInstaller folder: the exe cannot run without _internal beside it.
Source: "..\dist\url2vid\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leaves downloaded videos alone; only removes what the install put here.
Type: filesandordirs; Name: "{app}\_internal"
