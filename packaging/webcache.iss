; packaging/webcache.iss -- the Windows installer (Inno Setup 6).
;
; Installs for the current user by default, with no administrator rights,
; or for every user of the machine when run as administrator or with
; /ALLUSERS. The "installed" marker beside the program tells it to keep
; its case files and settings in the examiner's own profile
; (%LOCALAPPDATA%\WebCacheAnalyzer) instead of beside the executable,
; which an all-users install cannot write to. Uninstalling removes the
; program only: case files (tags and comments on an exhibit) are the
; examiner's work and are never deleted by it.
;
; Built by .github/workflows/release.yml:
;   ISCC /DAppVersion=5.0.0 /DSourceDir=dist\WebCacheAnalyzer packaging\webcache.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\WebCacheAnalyzer"
#endif
#define AppName "WebCache Forensic Analyzer"
#define AppExe "WebCacheAnalyzer.exe"

[Setup]
AppId={{6E4C2B1A-5F3D-4C8E-9A7B-2D1E0F3C4B5A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Akhil Dara
AppPublisherURL=https://github.com/akhil-dara/WebCache-Forensic-Analyzer
AppSupportURL=https://github.com/akhil-dara/WebCache-Forensic-Analyzer/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=webcache.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=WebCacheAnalyzer-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the bundled runtime whole, never mixing two versions.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
