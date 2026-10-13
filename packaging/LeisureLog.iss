#ifndef AppVersion
  #define AppVersion "0.4.0b1"
#endif

[Setup]
AppId={{8BC287AC-41B7-4A14-9665-E67353CEB533}
AppName=LeisureLog
AppVersion={#AppVersion}
AppVerName=LeisureLog {#AppVersion} 本机试用版
AppPublisher=LeisureLog
AppPublisherURL=https://github.com/jinzhengwang60-del/LeisureLog
DefaultDirName={localappdata}\Programs\LeisureLog
DefaultGroupName=LeisureLog
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\releases
OutputBaseFilename=LeisureLog-{#AppVersion}-Windows-x64-Setup
SetupIconFile=..\build\desktop-resources\LeisureLog.ico
UninstallDisplayIcon={app}\LeisureLog.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=LeisureLogDesktop
CloseApplications=no
RestartApplications=no
Uninstallable=yes
VersionInfoVersion=0.4.0.0
InfoBeforeFile=..\build\desktop-resources\installer-notice.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "..\dist\LeisureLog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LeisureLog"; Filename: "{app}\LeisureLog.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 LeisureLog"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LeisureLog"; Filename: "{app}\LeisureLog.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\LeisureLog.exe"; Description: "打开 LeisureLog 并完成首次设置"; Flags: nowait postinstall skipifsilent

; No user-data deletion entry: updates and uninstall preserve the separate personal data directory.
