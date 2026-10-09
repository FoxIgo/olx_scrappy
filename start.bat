@echo off
rem olx_scrappy launcher.
rem   start.bat                 -> interactive menu
rem   start.bat <scrappy args>  -> passes args to the CLI, e.g. start.bat offers list gtx-laptops --all
setlocal EnableExtensions

set "ROOT=%~dp0"
set "SERVER=%ROOT%packages\server"

where uv >nul 2>&1
if errorlevel 1 (
    echo [error] uv is not installed or not on PATH. See https://docs.astral.sh/uv/
    exit /b 1
)

rem Settings use relative paths (.env, config\), so run from the server package.
rem Data lives at the repo root so it survives package changes; .env can override it.
if not defined SCRAPPY_DATA_DIR set "SCRAPPY_DATA_DIR=%ROOT%data"
set "PYTHONUTF8=1"

pushd "%SERVER%" || exit /b 1

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [info] Created packages\server\.env from .env.example - set OPENROUTER_API_KEY there for LLM extraction.
)

uv sync --quiet
if errorlevel 1 (
    echo [error] uv sync failed.
    popd & exit /b 1
)

if "%~1"=="" goto menu
uv run scrappy %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:menu
echo.
echo  olx_scrappy   data: %SCRAPPY_DATA_DIR%
echo  ----------------------------------------
echo   1. List saved searches
echo   2. Add a saved search
echo   3. Run a search (inline)
echo   4. List offers of a search
echo   5. Show last runs
echo   6. Start worker (Ctrl+C to stop)
echo   7. Custom command
echo   0. Exit
echo.
set "OPT="
set /p "OPT=Choose: "
rem Empty input (Enter or end of input) exits, so piped input can never loop forever.
if "%OPT%"=="" goto end

if "%OPT%"=="1" uv run scrappy search list <nul & goto menu
if "%OPT%"=="2" goto add
if "%OPT%"=="3" goto run
if "%OPT%"=="4" goto offers
if "%OPT%"=="5" uv run scrappy runs list <nul & goto menu
if "%OPT%"=="6" uv run scrappy worker <nul & goto menu
if "%OPT%"=="7" goto custom
if "%OPT%"=="0" goto end
echo Unknown option.
goto menu

:add
set "NAME=" & set "URL=" & set "CAT="
set /p "NAME=Search name (e.g. gtx-laptops): "
set /p "URL=OLX search URL: "
set /p "CAT=Category [laptop]: "
if "%CAT%"=="" set "CAT=laptop"
uv run scrappy search add "%NAME%" "%URL%" -c "%CAT%" <nul
goto menu

:run
set "NAME="
set /p "NAME=Search name: "
uv run scrappy run "%NAME%" --inline <nul
goto menu

:offers
set "NAME=" & set "WHERE="
set /p "NAME=Search name: "
set /p "WHERE=Attribute filter (optional, e.g. ram_gb>=16): "
if "%WHERE%"=="" (
    uv run scrappy offers list "%NAME%" --all <nul
) else (
    uv run scrappy offers list "%NAME%" --all -w "%WHERE%" <nul
)
goto menu

:custom
set "ARGS="
set /p "ARGS=scrappy "
uv run scrappy %ARGS% <nul
goto menu

:end
popd
endlocal
