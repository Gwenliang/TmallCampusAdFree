@echo off
REM ============================================================
REM TmallCampusAdFree.dylib 一键编译（Windows，无需 macOS / theos）
REM
REM 依赖：本目录上一级的 toolchain\llvm 里的 clang + ld64.lld
REM 用法：双击或在 cmd 里执行 build.bat
REM ============================================================
setlocal
set ROOT=%~dp0
set LLVM=%ROOT%..\toolchain\llvm\clang+llvm-18.1.8-x86_64-pc-windows-msvc
set CLANG=%LLVM%\bin\clang.exe

if not exist "%CLANG%" (
  echo [ERROR] 找不到 clang: %CLANG%
  echo         请先运行 toolchain\install-toolchain.bat
  exit /b 1
)

if not exist "%ROOT%tmp" mkdir "%ROOT%tmp"
set TMP=%ROOT%tmp
set TEMP=%ROOT%tmp

echo [1/2] 编译 arm64 dylib ...
"%CLANG%" -target arm64-apple-ios12.0 -dynamiclib -nostdlib -fuse-ld=lld ^
  -fno-objc-arc -O2 -Wno-unused-function ^
  -Wl,-undefined,dynamic_lookup ^
  -Wl,-install_name,@rpath/TmallCampusAdFree.dylib ^
  -o "%ROOT%TmallCampusAdFree.dylib" "%ROOT%TmallCampusAdFree.m"
if errorlevel 1 (
  echo [ERROR] 编译失败
  exit /b 1
)

echo [2/2] 检查产物 ...
"%LLVM%\bin\llvm-otool.exe" -h "%ROOT%TmallCampusAdFree.dylib"
echo.
echo 完成: %ROOT%TmallCampusAdFree.dylib
endlocal

