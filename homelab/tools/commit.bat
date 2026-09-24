@echo off
setlocal
cd /d "%~dp0" || exit /b 1

if "%*"=="" (set "MSG=commit %DATE% %TIME%") else (set "MSG=%* - %DATE% %TIME%")

git add -A || exit /b 1

git diff --cached --quiet
if %ERRORLEVEL%==0 (
  echo Nothing to commit.
) else (
  git commit -m "%MSG%" || exit /b 1
)

git push || exit /b 1
git status -sb

echo.
pause