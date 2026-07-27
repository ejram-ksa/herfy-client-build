#define AppName "Herfy Client"
#define AppPublisher "Herfy"
#define AppExeName "HerfyClient.exe"
#define AppUserModelID "Herfy.HerfyClient"
#ifndef SourceDir
  #define SourceDir "..\dist\HerfyClient"
#endif
#ifndef OutputDir
  #define OutputDir "output"
#endif
#ifndef SetupVersion
  #define SetupVersion "2.18.1"
#endif

[Setup]
AppId={{A7D1C18E-780D-4E64-9E2D-21F674000001}
AppName={#AppName}
AppVersion={#SetupVersion}
AppVerName={#AppName} {#SetupVersion}
AppPublisher={#AppPublisher}
AppMutex=Herfy.HerfyClient
VersionInfoVersion={#SetupVersion}.0
VersionInfoProductVersion={#SetupVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\Herfy Client
DefaultGroupName=Herfy Client
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\..\runtime\resources\images\app_icon.ico
WizardStyle=modern
WizardImageFile=assets\wizard_side.bmp
WizardSmallImageFile=assets\wizard_header.bmp
LicenseFile=terms_and_conditions.txt
InfoBeforeFile=app_about.txt
OutputDir={#OutputDir}
OutputBaseFilename=HerfyClientSetup-{#SetupVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
CloseApplications=yes
CloseApplicationsFilter=HerfyClient.exe,HerfyClientUpdateAgent.exe
RestartApplications=no
DirExistsWarning=no
AllowNoIcons=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
DisableWelcomePage=no
DisableReadyPage=no
DisableFinishedPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app_about.txt"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "terms_and_conditions.txt"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\Herfy Client"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\Uninstall Herfy Client"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Herfy Client"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "{#AppUserModelID}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Herfy Client"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExeName}"; Flags: nowait; Check: ShouldAutoRestartApplication

[UninstallDelete]
Type: files; Name: "{app}\installer_defaults.ini"
Type: dirifempty; Name: "{app}\installer"

[Code]
var
  SettingsPage: TWizardPage;
  LangEnglishRadio: TNewRadioButton;
  LangArabicRadio: TNewRadioButton;
  EnableAlertsCheck: TNewCheckBox;
  EnableDesktopNotificationsCheck: TNewCheckBox;
  EnableSoundsCheck: TNewCheckBox;
  CheckUpdatesCheck: TNewCheckBox;
  ImmediateSyncCheck: TNewCheckBox;
  StartWithWindowsCheck: TNewCheckBox;
  ExistingInstallation: Boolean;

function ShouldAutoRestartApplication(): Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:AUTORESTARTAPP|0}') = '1');
end;

function BoolText(Value: Boolean): String;
begin
  if Value then
    Result := 'True'
  else
    Result := 'False';
end;

function SelectedLanguage(): String;
begin
  if LangArabicRadio.Checked then
    Result := 'ar'
  else
    Result := 'en';
end;

procedure AddSectionText(ParentPage: TWizardPage; Text: String; TopValue: Integer; Bold: Boolean);
var
  LabelControl: TNewStaticText;
begin
  LabelControl := TNewStaticText.Create(WizardForm);
  LabelControl.Parent := ParentPage.Surface;
  LabelControl.Left := ScaleX(0);
  LabelControl.Top := ScaleY(TopValue);
  LabelControl.Width := ParentPage.SurfaceWidth;
  LabelControl.Height := ScaleY(24);
  LabelControl.AutoSize := False;
  LabelControl.WordWrap := True;
  LabelControl.Caption := Text;
  LabelControl.Font.Style := [];
  if Bold then
    LabelControl.Font.Style := [fsBold];
end;

procedure InitializeWizard();
var
  IntroText: TNewStaticText;
begin
  SettingsPage := CreateCustomPage(wpSelectDir, 'Initial Settings / الإعدادات', 'Choose startup defaults before installation. You can change them later inside the application.');

  IntroText := TNewStaticText.Create(WizardForm);
  IntroText.Parent := SettingsPage.Surface;
  IntroText.Left := ScaleX(0);
  IntroText.Top := ScaleY(0);
  IntroText.Width := SettingsPage.SurfaceWidth;
  IntroText.Height := ScaleY(36);
  IntroText.AutoSize := False;
  IntroText.WordWrap := True;
  IntroText.Caption := 'These options write safe local defaults only. Server permissions and update validation remain controlled by Herfy server policies.';

  AddSectionText(SettingsPage, 'Language / اللغة', 44, True);
  LangEnglishRadio := TNewRadioButton.Create(WizardForm);
  LangEnglishRadio.Parent := SettingsPage.Surface;
  LangEnglishRadio.Left := ScaleX(16);
  LangEnglishRadio.Top := ScaleY(72);
  LangEnglishRadio.Width := ScaleX(220);
  LangEnglishRadio.Caption := 'English';
  LangEnglishRadio.Checked := False;

  LangArabicRadio := TNewRadioButton.Create(WizardForm);
  LangArabicRadio.Parent := SettingsPage.Surface;
  LangArabicRadio.Left := ScaleX(250);
  LangArabicRadio.Top := ScaleY(72);
  LangArabicRadio.Width := ScaleX(220);
  LangArabicRadio.Caption := 'العربية';
  LangArabicRadio.Checked := True;

  AddSectionText(SettingsPage, 'Notifications / التنبيهات', 104, True);
  EnableAlertsCheck := TNewCheckBox.Create(WizardForm);
  EnableAlertsCheck.Parent := SettingsPage.Surface;
  EnableAlertsCheck.Left := ScaleX(16);
  EnableAlertsCheck.Top := ScaleY(132);
  EnableAlertsCheck.Width := ScaleX(220);
  EnableAlertsCheck.Caption := 'Enable smart alerts';
  EnableAlertsCheck.Checked := True;

  EnableDesktopNotificationsCheck := TNewCheckBox.Create(WizardForm);
  EnableDesktopNotificationsCheck.Parent := SettingsPage.Surface;
  EnableDesktopNotificationsCheck.Left := ScaleX(270);
  EnableDesktopNotificationsCheck.Top := ScaleY(132);
  EnableDesktopNotificationsCheck.Width := ScaleX(220);
  EnableDesktopNotificationsCheck.Caption := 'Desktop notifications';
  EnableDesktopNotificationsCheck.Checked := True;

  EnableSoundsCheck := TNewCheckBox.Create(WizardForm);
  EnableSoundsCheck.Parent := SettingsPage.Surface;
  EnableSoundsCheck.Left := ScaleX(16);
  EnableSoundsCheck.Top := ScaleY(158);
  EnableSoundsCheck.Width := ScaleX(220);
  EnableSoundsCheck.Caption := 'Sound alerts';
  EnableSoundsCheck.Checked := True;

  AddSectionText(SettingsPage, 'Runtime / التشغيل', 192, True);
  CheckUpdatesCheck := TNewCheckBox.Create(WizardForm);
  CheckUpdatesCheck.Parent := SettingsPage.Surface;
  CheckUpdatesCheck.Left := ScaleX(270);
  CheckUpdatesCheck.Top := ScaleY(220);
  CheckUpdatesCheck.Width := ScaleX(220);
  CheckUpdatesCheck.Caption := 'Check updates on startup';
  CheckUpdatesCheck.Checked := True;

  ImmediateSyncCheck := TNewCheckBox.Create(WizardForm);
  ImmediateSyncCheck.Parent := SettingsPage.Surface;
  ImmediateSyncCheck.Left := ScaleX(16);
  ImmediateSyncCheck.Top := ScaleY(246);
  ImmediateSyncCheck.Width := ScaleX(220);
  ImmediateSyncCheck.Caption := 'Immediate server sync after startup';
  ImmediateSyncCheck.Checked := True;

  StartWithWindowsCheck := TNewCheckBox.Create(WizardForm);
  StartWithWindowsCheck.Parent := SettingsPage.Surface;
  StartWithWindowsCheck.Left := ScaleX(270);
  StartWithWindowsCheck.Top := ScaleY(246);
  StartWithWindowsCheck.Width := ScaleX(220);
  StartWithWindowsCheck.Caption := 'Start with Windows';
  StartWithWindowsCheck.Checked := False;

  ExistingInstallation := False;
end;

procedure WriteInstallerDefaults();
var
  Content: String;
begin
  Content :=
    '# Generated by Herfy Client installer' + #13#10 +
    'language=' + SelectedLanguage() + #13#10 +
    'enable_alerts=' + BoolText(EnableAlertsCheck.Checked) + #13#10 +
    'enable_smart_notifications=' + BoolText(EnableAlertsCheck.Checked) + #13#10 +
    'enable_desktop_notifications=' + BoolText(EnableDesktopNotificationsCheck.Checked) + #13#10 +
    'enable_sounds=' + BoolText(EnableSoundsCheck.Checked) + #13#10 +
    'enable_tray_background=True' + #13#10 +
    'check_updates_on_startup=' + BoolText(CheckUpdatesCheck.Checked) + #13#10 +
    'refresh_remote_ui_on_startup=True' + #13#10 +
    'immediate_server_sync=' + BoolText(ImmediateSyncCheck.Checked) + #13#10 +
    'start_with_windows=' + BoolText(StartWithWindowsCheck.Checked) + #13#10 +
    'tray_show_message_on_minimize=False' + #13#10 +
    'notification_once_per_day=True' + #13#10 +
    'notification_repeat_interval_minutes=240' + #13#10 +
    'notification_duration_seconds=8' + #13#10 +
    'notification_max_per_cycle=5' + #13#10 +
    'notification_summary_threshold=3' + #13#10 +
    'monitoring_active_check_interval_minutes=15' + #13#10 +
    'monitoring_background_check_interval_minutes=30' + #13#10;
  SaveStringToFile(ExpandConstant('{app}\installer_defaults.ini'), Content, False);
end;

procedure ApplyStartupRegistry();
var
  CommandLine: String;
begin
  if StartWithWindowsCheck.Checked then
  begin
    CommandLine := '"' + ExpandConstant('{app}\{#AppExeName}') + '"';
    RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'HerfyClient', CommandLine);
  end
  else
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'HerfyClient');
end;


function SettingsSummaryLine(Name: String; Value: String): String;
begin
  Result := '  ' + Name + ': ' + Value + #13#10;
end;

function EnabledText(Value: Boolean): String;
begin
  if Value then
    Result := 'Enabled'
  else
    Result := 'Disabled';
end;

function UpdateReadyMemo(
  Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Summary: String;
begin
  Summary := MemoDirInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then
    Summary := Summary + MemoTasksInfo + NewLine + NewLine;
  Summary := Summary + 'Initial settings / الإعدادات:' + NewLine;
  Summary := Summary + SettingsSummaryLine('Language', SelectedLanguage());
  Summary := Summary + SettingsSummaryLine('Smart alerts', EnabledText(EnableAlertsCheck.Checked));
  Summary := Summary + SettingsSummaryLine('Desktop notifications', EnabledText(EnableDesktopNotificationsCheck.Checked));
  Summary := Summary + SettingsSummaryLine('Sound alerts', EnabledText(EnableSoundsCheck.Checked));
  Summary := Summary + SettingsSummaryLine('Background monitoring', 'Enabled');
  Summary := Summary + SettingsSummaryLine('Startup update check', EnabledText(CheckUpdatesCheck.Checked));
  Summary := Summary + SettingsSummaryLine('Immediate server sync', EnabledText(ImmediateSyncCheck.Checked));
  Summary := Summary + SettingsSummaryLine('Start with Windows', EnabledText(StartWithWindowsCheck.Checked));
  Result := Summary;
end;


function IsSafeRuntimeRelativePath(Value: String): Boolean;
begin
  if Value = '' then
  begin
    Result := False;
    Exit;
  end;
  Result :=
    (Pos('..', Value) = 0) and
    (Pos(':', Value) = 0) and
    (Value[1] <> '\') and
    (Value[1] <> '/');
end;

procedure DeletePreviousRuntimeManifestFiles();
var
  ManifestPath: String;
  Lines: TArrayOfString;
  I: Integer;
  RelativePath: String;
  TargetPath: String;
begin
  ManifestPath := ExpandConstant('{app}\runtime_files.txt');
  if not FileExists(ManifestPath) then
    Exit;
  if not LoadStringsFromFile(ManifestPath, Lines) then
    RaiseException('Unable to read the previous runtime manifest.');
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    RelativePath := Trim(Lines[I]);
    StringChangeEx(RelativePath, '/', '\', True);
    if not IsSafeRuntimeRelativePath(RelativePath) then
      RaiseException('Unsafe runtime manifest entry: ' + RelativePath);
    TargetPath := AddBackslash(ExpandConstant('{app}')) + RelativePath;
    if FileExists(TargetPath) then
      DeleteFile(TargetPath);
  end;
end;

procedure CleanupPreviousRuntime();
var
  AppRoot: String;
begin
  AppRoot := ExpandConstant('{app}');
  if not DirExists(AppRoot) then
    Exit;

  DeletePreviousRuntimeManifestFiles();

  { Remove every known obsolete source-code layout.  Source files beside the
    frozen executable can override PyInstaller modules and must never survive
    an upgrade. }
  DelTree(AppRoot + '\app', True, True, True);
  DelTree(AppRoot + '\application', True, True, True);
  DelTree(AppRoot + '\bootstrap', True, True, True);
  DelTree(AppRoot + '\core', True, True, True);
  DelTree(AppRoot + '\data', True, True, True);
  DelTree(AppRoot + '\domain', True, True, True);
  DelTree(AppRoot + '\presentation', True, True, True);
  DelTree(AppRoot + '\remote', True, True, True);
  DelTree(AppRoot + '\services', True, True, True);
  DelTree(AppRoot + '\settings', True, True, True);
  DelTree(AppRoot + '\ui', True, True, True);
  DelTree(AppRoot + '\__pycache__', True, True, True);

  { Remove old frozen runtime containers before the new complete runtime is
    copied. Installer-owned files, defaults and uninstaller files are kept. }
  DelTree(AppRoot + '\_internal', True, True, True);
  DelTree(AppRoot + '\resources', True, True, True);
  DelTree(AppRoot + '\*.py', False, True, False);
  DelTree(AppRoot + '\*.pyc', False, True, False);
  DelTree(AppRoot + '\*.pyo', False, True, False);
  DelTree(AppRoot + '\*.pyd', False, True, False);
  DelTree(AppRoot + '\*.dll', False, True, False);
  DeleteFile(AppRoot + '\base_library.zip');
  DeleteFile(AppRoot + '\HerfyClient.exe');
  DeleteFile(AppRoot + '\HerfyClientUpdateAgent.exe');
  DeleteFile(AppRoot + '\version.json');
  DeleteFile(AppRoot + '\runtime_files.txt');
  DeleteFile(AppRoot + '\shell_cloud.py');
  DeleteFile(AppRoot + '\shell.py');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    ExistingInstallation := FileExists(ExpandConstant('{app}\{#AppExeName}'));
    CleanupPreviousRuntime();
  end;

  if (CurStep = ssPostInstall) and (not WizardSilent) and (not ExistingInstallation) then
  begin
    { Write installer defaults and startup registration only for a fresh install.
      Interactive and silent upgrades preserve the user's existing choices. }
    WriteInstallerDefaults();
    ApplyStartupRegistry();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'HerfyClient');
end;
