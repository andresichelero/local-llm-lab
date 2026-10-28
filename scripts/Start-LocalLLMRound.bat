@echo off
setlocal
set "ROUND_ACTION=--prepare"
set "ROUND_MODULE=benchmark.practical_review_replay"
set "ROUND_OUTPUT=/home/foxtrot/local-llm-benchmark/results/practical-agent-limits-skills-v9-m1-independent"
set "ROUND_RECOVERY="
set "ROUND_MODE=benchmark"
if /I "%~1"=="--execute" set "ROUND_ACTION=--execute"
if /I "%~1"=="--replay-review" (
  set "ROUND_ACTION=--execute"
  set "ROUND_MODULE=benchmark.practical_review_replay"
  set "ROUND_OUTPUT=/home/foxtrot/local-llm-benchmark/results/practical-agent-limits-skills-v9-m1-independent"
)
if /I "%~1"=="--operational-prepare" set "ROUND_MODE=operational"
if /I "%~1"=="--operational-execute" (
  set "ROUND_MODE=operational"
  set "ROUND_ACTION=--execute"
)
set "ROUND_EXTRA="
if /I "%~1"=="--retry-blocked" set "ROUND_ACTION=--execute"
if /I "%~2"=="--retry-blocked" set "ROUND_EXTRA=--retry-blocked"
if /I "%~1"=="--retry-blocked" set "ROUND_EXTRA=--retry-blocked"
if /I "%ROUND_MODE%"=="operational" (
  set "ROUND_OUTPUT=/home/foxtrot/local-llm-benchmark/results/practical-agent-limits-skills-v9-m1-independent-operational"
  set "ROUND_RECOVERY="
)
if not "%~1"=="" if /I not "%~1"=="--prepare" if /I not "%~1"=="--execute" if /I not "%~1"=="--replay-review" if /I not "%~1"=="--operational-prepare" if /I not "%~1"=="--operational-execute" if /I not "%~1"=="--retry-blocked" (
  echo Usage: Start-LocalLLMRound.bat [--prepare ^| --execute ^| --retry-blocked ^| --operational-prepare ^| --operational-execute]
  exit /b 2
)
if not "%~2"=="" if /I not "%~2"=="--retry-blocked" (
  echo Usage: Start-LocalLLMRound.bat [action] [--retry-blocked]
  exit /b 2
)
for /f "delims=" %%P in ('wsl.exe -d Ubuntu-24.04 -- wslpath -u "%~dp0.."') do set "ROUND_ROOT=%%P"
if not defined ROUND_ROOT exit /b 2
echo Local LLM round: %ROUND_ACTION%
set "ROUND_CONTINUE="
if /I "%ROUND_ACTION%"=="--execute" set "ROUND_CONTINUE=--continue-model-blocks"
echo Ctrl+C interrupts this foreground run; use --execute again to resume.
wsl.exe -d Ubuntu-24.04 --cd "%ROUND_ROOT%" -- /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m %ROUND_MODULE% %ROUND_ACTION% --mode %ROUND_MODE% --output %ROUND_OUTPUT% %ROUND_RECOVERY% %ROUND_EXTRA% %ROUND_CONTINUE%
exit /b %errorlevel%
