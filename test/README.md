# Tests

Run from the repository root after installing `requirements.txt` in the main
Python virtual environment. Tests live in `test/`; application modules remain
in `src/`. Set `PYTHONPATH` so unittest can import those modules.

PowerShell (UTF-8 log, including stderr and exit status):

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$env:PYTHONPATH = (Resolve-Path .\src).Path
$log = ".\logs\unit-tests-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
python -m unittest discover -s test -p 'test_*.py' -v 2>&1 | Out-File $log -Encoding utf8
$testExitCode = $LASTEXITCODE
"Exit code: $testExitCode" | Out-File $log -Append -Encoding utf8
Write-Host "Test exit code: $testExitCode; log: $log"
```

For a specific module, change the pattern, for example to
`-p 'test_duration_policy.py'`.

Bash:

```bash
mkdir -p logs
PYTHONPATH=src python -m unittest discover -s test -p 'test_*.py' -v > logs/unit-tests.log 2>&1
result=$?
printf '\nExit code: %s\n' "$result" >> logs/unit-tests.log
exit "$result"
```

CI uses the same discovery command and uploads its log even when tests fail.
