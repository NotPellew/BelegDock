#ifndef AppVersion
  #error AppVersion fehlt
#endif
#ifndef VersionInfo
  #error VersionInfo fehlt
#endif
#ifndef DistDir
  #error DistDir fehlt
#endif
#ifndef BundleDir
  #define BundleDir DistDir + "\BelegDock"
#endif

[Setup]
AppId={{4F1B9B0E-6C7A-4F2B-9B0E-2E6F0B1A3C41}
AppName=BelegDock
AppVersion={#AppVersion}
AppVerName=BelegDock {#AppVersion}
AppPublisher=BelegDock contributors
VersionInfoVersion={#VersionInfo}
VersionInfoProductName=BelegDock
VersionInfoProductVersion={#VersionInfo}
VersionInfoDescription=BelegDock Desktop-Installation
DefaultDirName={localappdata}\Programs\BelegDock
DefaultGroupName=BelegDock
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0.19045
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
OutputDir={#DistDir}
OutputBaseFilename=BelegDock-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=BelegDock
UninstallDisplayIcon={app}\BelegDock-Desktop.exe

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README-Windows.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\BelegDock"; Filename: "{app}\BelegDock-Desktop.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\README-Windows.txt"; Description: "Windows-Anleitung öffnen"; Flags: shellexec postinstall skipifsilent unchecked

[Code]
const
  EnvironmentKey = 'Environment';

function NeedsAddPath(InstallPath: string): Boolean;
var
  CurrentPath: string;
begin
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', CurrentPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(InstallPath) + ';', ';' + Uppercase(CurrentPath) + ';') = 0;
end;

procedure AddToPath(InstallPath: string);
var
  CurrentPath: string;
begin
  if not NeedsAddPath(InstallPath) then
    exit;
  if RegQueryStringValue(HKCU, EnvironmentKey, 'Path', CurrentPath) then
  begin
    if (CurrentPath <> '') and (CurrentPath[Length(CurrentPath)] <> ';') then
      CurrentPath := CurrentPath + ';';
  end
  else
    CurrentPath := '';
  RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', CurrentPath + InstallPath);
  Log('Benutzer-PATH um das Installationsverzeichnis ergänzt.');
end;

procedure RemoveFromPath(InstallPath: string);
var
  Remaining, Item, Updated: string;
  Position: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Remaining) then
    exit;
  Updated := '';
  while Remaining <> '' do
  begin
    Position := Pos(';', Remaining);
    if Position = 0 then
    begin
      Item := Remaining;
      Remaining := '';
    end
    else
    begin
      Item := Copy(Remaining, 1, Position - 1);
      Remaining := Copy(Remaining, Position + 1, Length(Remaining));
    end;
    if (Item <> '') and (Uppercase(Item) <> Uppercase(InstallPath)) then
    begin
      if Updated <> '' then
        Updated := Updated + ';';
      Updated := Updated + Item;
    end;
  end;
  RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', Updated);
  Log('Benutzer-PATH-Eintrag entfernt.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    AddToPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
