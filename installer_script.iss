[Setup]
AppId={{8B6E32A0-6A2B-4A88-B932-9F1F3507B280}}
AppName=OPS ROOM
AppVersion=0.25.50
AppVerName=OPS ROOM 0.25.50
AppPublisher=Exzonom
AppPublisherURL=https://opsroom.live
AppSupportURL=https://opsroom.live/support
AppUpdatesURL=https://opsroom.live
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
DefaultDirName={autopf}\OPS ROOM
DefaultGroupName=OPS ROOM
DisableDirPage=no
DisableProgramGroupPage=no
LicenseFile=PRIVACY_NOTICE.txt
UninstallDisplayIcon={app}\OPS ROOM.exe
SetupIconFile=app\static\opsroom.ico
OutputDir=dist_installer
OutputBaseFilename=OPS_ROOM_Setup_0.25.50
WizardSmallImageFile=app\assets\brand\installer.png
WizardImageFile=app\assets\brand\installer.png
WizardImageStretch=no
WizardImageBackColor=$141619
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardResizable=yes
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\OPS ROOM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OPS ROOM"; Filename: "{app}\OPS ROOM.exe"
Name: "{group}\{cm:UninstallProgram,OPS ROOM}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OPS ROOM"; Filename: "{app}\OPS ROOM.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OPS ROOM.exe"; Description: "{cm:LaunchProgram,OPS ROOM}"; Flags: nowait postinstall skipifsilent

[Code]
var
  CoffeeLabel: TLabel;

procedure CoffeeLabelClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://buymeacoffee.com/exzonom', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure InitializeWizard();
begin
  CoffeeLabel := TLabel.Create(WizardForm);
  CoffeeLabel.Parent := WizardForm;
  CoffeeLabel.Left := ScaleX(16);
  CoffeeLabel.Top := WizardForm.CancelButton.Top + ScaleY(4);
  CoffeeLabel.Caption := '☕ Support Project (Buy me a coffee)';
  CoffeeLabel.Font.Color := $D07000;
  CoffeeLabel.Font.Style := [fsUnderline];
  CoffeeLabel.Cursor := crHand;
  CoffeeLabel.OnClick := @CoffeeLabelClick;
end;
