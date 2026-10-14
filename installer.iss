[Setup]
#ifdef ValidationBuild
AppId={{BA7DEAF2-B3B0-4B71-90F0-5E171AF7FD20}
Uninstallable=no
#else
AppId={{4F6AB230-8EBE-4D52-A6B2-EF6F61C21B24}
#endif
AppName=PaperTag Local
AppVersion=0.7.10
AppPublisher=PaperTag Local contributors
DefaultDirName={localappdata}\Programs\ResearchLiteratureLibrary
DefaultGroupName=垃圾桶科研文献库
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
#ifdef ValidationBuild
OutputDir=tmp
OutputBaseFilename=validation-setup
#else
OutputDir=release
OutputBaseFilename=PaperTagLocal-Setup-0.7.10
#endif
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LiteratureLibrary.exe
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "dist\LiteratureLibrary\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
#ifndef ValidationBuild
Name: "{group}\垃圾桶科研文献库"; Filename: "{app}\LiteratureLibrary.exe"
Name: "{autodesktop}\垃圾桶科研文献库"; Filename: "{app}\LiteratureLibrary.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\LiteratureLibrary.exe"; Description: "启动垃圾桶科研文献库"; Flags: nowait postinstall skipifsilent

; The user's database is under LOCALAPPDATA, outside {app}.
; Uninstall deliberately preserves it, and preserves every original PDF.
