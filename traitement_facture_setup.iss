; ============================================================
; Inno Setup — Traitement de factures
; Sédentaire.co
; ============================================================

#define AppName      "Traitement de factures"
#define AppVersion   "2.0"
#define AppPublisher "Sédentaire.co"
#define AppURL       "https://sedentaire.co"
#define AppExeName   "TraitementFactures.exe"
#define AppId        "{{A3F8C2D1-4E7B-4A9F-B3C2-1D5E8F9A0B2C}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL=mailto:info@sedentaire.co
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=no
LicenseFile=
OutputDir=output
OutputBaseFilename=TraitementFactures_Setup_v{#AppVersion}
SetupIconFile=app_icon.ico
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_icon.bmp
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=100
WizardResizable=no
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}.0.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName}
VersionInfoCopyright=Copyright (C) 2026 Sédentaire.co
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
french.WelcomeLabel1=Bienvenue dans l'assistant d'installation
french.WelcomeLabel2=Cet assistant va installer {#AppName} v{#AppVersion} sur votre ordinateur.%n%nCet outil classe automatiquement vos factures PDF par fournisseur et numéro de bon de commande, grâce à l'intelligence artificielle.%n%nFermez toutes les applications avant de continuer.
french.FinishedLabel={#AppName} a été installé avec succès.%n%nL'application est maintenant disponible dans le menu Démarrer.%n%nCliquez sur Terminer pour fermer cet assistant.
french.ClickNext=Suivant >
french.ButtonFinish=Terminer

[Tasks]
Name: "desktopicon";   Description: "Créer un raccourci sur le Bureau";         GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "startmenuicon"; Description: "Créer un raccourci dans le menu Démarrer"; GroupDescription: "Raccourcis :"; Flags: checkedonce

[Files]
Source: "dist\TraitementFactures\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}";      Tasks: startmenuicon
Name: "{userdesktop}\{#AppName}";        Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Lancer {#AppName} maintenant"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function InitializeSetup(): Boolean;
var
  installed: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}_is1',
      'DisplayVersion', installed) then
  begin
    if CompareStr(installed, '{#AppVersion}') > 0 then
    begin
      MsgBox(
        'Une version plus récente (' + installed + ') est déjà installée.' + #13#10 +
        'L''installation a été annulée.',
        mbInformation, MB_OK);
      Result := False;
    end;
  end;
end;
