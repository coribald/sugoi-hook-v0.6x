@echo off
echo ========================================
echo Building Single EXE with Nuitka (Fixed)
echo ========================================
echo.

set "PIP_CACHE_DIR=%CD%\.pip-cache"
set "NUITKA_CACHE_DIR=%CD%\.nuitka-cache"
set "OUTPUT_DIR=SugoiHook_builds"
set "PRESERVE_DIR=.build-preserve\release"

echo Preserving runtime *_config.json files from %OUTPUT_DIR%...
if exist "%PRESERVE_DIR%" rmdir /s /q "%PRESERVE_DIR%"
mkdir "%PRESERVE_DIR%" >nul 2>&1
if exist "%OUTPUT_DIR%\*_config.json" copy /y "%OUTPUT_DIR%\*_config.json" "%PRESERVE_DIR%\" >nul

echo Cleaning previous release build artifacts...
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"

echo Installing pinned runtime and build dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo Failed to install pinned dependencies.
    if /I not "%NO_PAUSE%"=="1" pause
    exit /b 1
)
echo.

echo Starting Nuitka compilation...
echo This creates a SINGLE EXE file with ALL runtime assets bundled
echo May take 10-15 minutes on first run...
echo.

REM Build with Nuitka - Single file mode with raw runtime assets included
REM Avoid forced stdout/stderr redirection here; in onefile mode it causes
REM an early native APPCRASH before Python startup on some Windows systems.
python -m nuitka ^
    --onefile ^
    --include-raw-dir=luna_builds=luna_builds ^
    --include-raw-dir=deep_translator=deep_translator ^
    --include-raw-dir=plugins=plugins ^
    --include-data-files=logo.webp=logo.webp ^
    --include-data-files=logo.ico=logo.ico ^
    --windows-icon-from-ico=logo.ico ^
    --enable-plugin=tk-inter ^
    --include-module=dictionary_backend ^
    --include-module=tkinter.font ^
    --include-package=pystray ^
    --include-package=PIL ^
    --include-package=psutil ^
    --include-package=requests ^
    --include-package=bs4 ^
    --include-package=win32gui ^
    --include-package=win32ui ^
    --include-package=win32con ^
    --include-package=win32process ^
    --follow-imports ^
    --assume-yes-for-downloads ^
    --windows-console-mode=disable ^
    --output-dir=%OUTPUT_DIR% ^
    --company-name="Sugoi Toolkit Inc." ^
    --product-name="Sugoi Hook" ^
    --file-version=2.0.1 ^
    --product-version=2.0.1 ^
    --file-description="Modern Hooking Interface" ^
    --output-filename=SugoiHook.exe ^
    SugoiHook_gui.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo Build Failed!
    echo ========================================
    echo.
    if /I not "%NO_PAUSE%"=="1" pause
    exit /b 1
)

if exist "%PRESERVE_DIR%\*_config.json" (
    echo Restoring preserved runtime config files...
    copy /y "%PRESERVE_DIR%\*_config.json" "%OUTPUT_DIR%\" >nul
)

echo Copying dictionaries beside the onefile build...
xcopy /e /i /y "dictionaries" "%OUTPUT_DIR%\dictionaries\" >nul

echo Creating desktop-style launch shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$shell = New-Object -ComObject WScript.Shell; " ^
    "$outputDir = (Resolve-Path '%OUTPUT_DIR%').Path; " ^
    "$exePath = Join-Path $outputDir 'SugoiHook.exe'; " ^
    "$plainShortcut = Join-Path $outputDir 'SugoiHook v0.6x.lnk'; " ^
    "$debugShortcut = Join-Path $outputDir 'SugoiHook v0.6x (debug).lnk'; " ^
    "$plain = $shell.CreateShortcut($plainShortcut); " ^
    "$plain.TargetPath = $exePath; " ^
    "$plain.WorkingDirectory = $outputDir; " ^
    "$plain.IconLocation = $exePath + ',0'; " ^
    "$plain.Save(); " ^
    "$debug = $shell.CreateShortcut($debugShortcut); " ^
    "$debug.TargetPath = $exePath; " ^
    "$debug.Arguments = '--debug'; " ^
    "$debug.WorkingDirectory = $outputDir; " ^
    "$debug.IconLocation = $exePath + ',0'; " ^
    "$debug.Save()"

if /I not "%KEEP_BUILD_ARTIFACTS%"=="1" (
    echo Cleaning release build artifacts...
    if exist "%OUTPUT_DIR%\SugoiHook_gui.build" rmdir /s /q "%OUTPUT_DIR%\SugoiHook_gui.build"
    if exist "%OUTPUT_DIR%\SugoiHook_gui.dist" rmdir /s /q "%OUTPUT_DIR%\SugoiHook_gui.dist"
    if exist "%OUTPUT_DIR%\SugoiHook_gui.onefile-build" rmdir /s /q "%OUTPUT_DIR%\SugoiHook_gui.onefile-build"
)

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Executable created: %OUTPUT_DIR%\SugoiHook.exe
echo.
if /I not "%NO_PAUSE%"=="1" pause
