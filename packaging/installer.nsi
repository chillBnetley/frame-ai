Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APPNAME "FRAME AI"
!define APPEXE "FRAME AI.exe"
!define APPVERSION "0.2.0"
!define APPPUBLISHER "FRAME AI"
!define SOURCE_DIR "..\dist\FRAME AI"
!define OUTPUT_FILE "..\dist-installer\FRAME-AI-setup.exe"

Name "${APPNAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\FRAME AI"
InstallDirRegKey HKCU "Software\FRAME AI" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ManifestDPIAware true
BrandingText "FRAME AI"

VIProductVersion "0.2.0.0"
VIAddVersionKey "ProductName" "FRAME AI"
VIAddVersionKey "FileDescription" "FRAME AI installer"
VIAddVersionKey "FileVersion" "0.2.0"
VIAddVersionKey "ProductVersion" "0.2.0"
VIAddVersionKey "CompanyName" "FRAME AI"
VIAddVersionKey "LegalCopyright" "FRAME AI"

!define MUI_ABORTWARNING
!define MUI_ICON "assets\frame-ai.ico"
!define MUI_UNICON "assets\frame-ai.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT "运行 FRAME AI"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "FRAME AI" SecMain
    SetShellVarContext current
    SetOutPath "$INSTDIR"
    File /r "${SOURCE_DIR}\*.*"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    CreateDirectory "$SMPROGRAMS\FRAME AI"
    CreateShortcut "$SMPROGRAMS\FRAME AI\FRAME AI.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0
    CreateShortcut "$SMPROGRAMS\FRAME AI\卸载 FRAME AI.lnk" "$INSTDIR\Uninstall.exe"
    CreateShortcut "$DESKTOP\FRAME AI.lnk" "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0

    WriteRegStr HKCU "Software\FRAME AI" "InstallLocation" "$INSTDIR"

    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "DisplayName" "${APPNAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "DisplayVersion" "${APPVERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "Publisher" "${APPPUBLISHER}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "DisplayIcon" "$INSTDIR\${APPEXE}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "NoRepair" 1

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
    SetShellVarContext current

    Delete "$DESKTOP\FRAME AI.lnk"
    Delete "$SMPROGRAMS\FRAME AI\FRAME AI.lnk"
    Delete "$SMPROGRAMS\FRAME AI\卸载 FRAME AI.lnk"
    RMDir "$SMPROGRAMS\FRAME AI"

    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FRAME AI"
    DeleteRegKey HKCU "Software\FRAME AI"

    ; User data lives in %APPDATA%\FRAME AI and is intentionally preserved.
    RMDir /r "$INSTDIR"
SectionEnd
