@echo off
rem Makes YerpBiometric.exe from YerpBiometric.cs with the C# compiler that comes with the .NET Framework - nothing is
rem downloaded or installed. The other .bat files call this; "build.bat force" makes it again even if it is there.
setlocal
cd /d "%~dp0"
if /i not "%~1"=="force" if exist "YerpBiometric.exe" exit /b 0
set "CSC="
if exist "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not defined CSC if exist "%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not defined CSC (
  echo This computer does not have the Microsoft .NET Framework 4.5 or newer.
  echo Windows 8, 10 and 11 have it already. On Windows 7 install ".NET Framework 4.8" from microsoft.com,
  echo then run SETUP.bat again.
  exit /b 1
)
"%CSC%" /nologo /target:exe /platform:anycpu /optimize+ /out:YerpBiometric.exe /r:System.Web.Extensions.dll YerpBiometric.cs > build.log 2>&1
if errorlevel 1 (
  type build.log
  echo.
  echo The program could not be made - send build.log to whoever looks after Y ERP.
  exit /b 1
)
del build.log >nul 2>&1
exit /b 0
