@echo off
echo ========================================
echo Building Standalone Debug EXE
echo ========================================
echo.

set "PIP_CACHE_DIR=%CD%\.pip-cache"
set "NUITKA_CACHE_DIR=%CD%\.nuitka-cache"
set "OUTPUT_DIR=SugoiHook_debug_builds"
set "DIST_DIR=%OUTPUT_DIR%\SugoiHook_gui.dist"
set "PRESERVE_DIR=.build-preserve\debug"

echo Preserving runtime *_config.json files from %DIST_DIR%...
if exist "%PRESERVE_DIR%" rmdir /s /q "%PRESERVE_DIR%"
mkdir "%PRESERVE_DIR%" >nul 2>&1
if exist "%DIST_DIR%\*_config.json" copy /y "%DIST_DIR%\*_config.json" "%PRESERVE_DIR%\" >nul

echo Cleaning previous debug build artifacts...
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"

echo Installing pinned runtime and build dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo Failed to install pinned dependencies.
    if /I not "%NO_PAUSE%"=="1" pause
    exit /b 1
)
echo.

echo Starting standalone debug build...
echo.

python -m nuitka ^
    --mode=standalone ^
    --include-raw-dir=luna_builds=luna_builds ^
    --include-raw-dir=dictionaries=dictionaries ^
    --include-raw-dir=deep_translator=deep_translator ^
    --include-raw-dir=plugins=plugins ^
    --include-data-files=logo.webp=logo.webp ^
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
    --windows-console-mode=attach ^
    --output-dir=%OUTPUT_DIR% ^
    --company-name="Sugoi Toolkit Inc." ^
    --product-name="Sugoi Hook" ^
    --file-version=2.0.1 ^
    --product-version=2.0.1 ^
    --file-description="Modern Hooking Interface (Debug)" ^
    --output-filename=SugoiHook_debug.exe ^
    SugoiHook_gui.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo Debug Build Failed!
    echo ========================================
    echo.
    if /I not "%NO_PAUSE%"=="1" pause
    exit /b 1
)

if exist "%PRESERVE_DIR%\*_config.json" (
    echo Restoring preserved runtime config files...
    copy /y "%PRESERVE_DIR%\*_config.json" "%DIST_DIR%\" >nul
)

echo.
echo ========================================
echo Debug Build Complete!
echo ========================================
echo.
echo Executable created: %DIST_DIR%\SugoiHook_debug.exe
if /I not "%NO_PAUSE%"=="1" pause
