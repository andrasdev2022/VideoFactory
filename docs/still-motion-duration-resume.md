# Still-motion hosszkorlát és a krokodilos job folytatása

2026-10-01: a `20261001-121737` job 3. jelenete 11,712 s-nál megállt.
Az időzítésben már 24 s volt engedélyezve, de a közös videógenerátor minden
providerre fix 2–10 s korlátot alkalmazott. A javítás still-motion esetén a
jóváhagyott jelenet `timing.min_video_duration_sec` és `max_video_duration_sec`
értékeit használja. Régi, határok nélküli timing esetén 2–10 s marad a fallback.
Érvénytelen/nem véges határ vagy időtartam továbbra is hiba. Runway és Local LTX
korlátja változatlan. A végső frame kerekítés továbbra is a provider feladata.

Ez nem módosít narrációt, időzítést, képet, QC-eredményt vagy retry-számlálót.
Az időzítés korlátját továbbra is `SCENE_TIMING_MAX_VIDEO_SEC` szabályozza,
nem automatikusan a YAML. Ebben a jobban 24 s a megfelelő beállítás.
Az `enter-dev.ps1` jelenleg 10-re állítja: utána kell a 24-et megadni.

## Igazolt állapot a 19:42-es log alapján

- Teljes tervezett hossz 50 s, globális időzítés elfogadva; supervisor APPROVED.
- 1–2. jelenet kész, vágással és QC-vel; 3. kép és képi QC kész.
- 3. videó generálása konfigurációs hibával megállt, egy videókísérlet fogyott.
- Sima resume a 3. videónál folytat; nem kell `-OverruleQC`, `-RetryQC`,
  `--reset-attempts`, új ötlet vagy JSON-szerkesztés.
- A későbbi QC-k továbbra is megállíthatják a futást. Végső export még nincs igazolva.

## Célzott átvétel, branchváltás és runtime-job csere nélkül

Álló pipeline mellett, a projekt gyökeréből, az eddig használt PowerShellben.
A parancs csak a javított generátort veszi át a feature branchről; a teljes PR
merge-elése továbbra is külön felhasználói döntés. Meglévő helyi generátorváltozat,
job, YAML és a job teljes médiakönyvtára előbb repón kívüli mentést kap.

```powershell
$ErrorActionPreference = 'Stop'
$job = Get-Content .\jobs\video_job.json -Raw -Encoding UTF8 | ConvertFrom-Json
if ($job.job_id -ne '20261001-121737') { throw 'Másik aktív job: ne folytasd ezzel a paranccsal.' }
$backup = Join-Path (Split-Path (Get-Location).Path -Parent) ('vf-duration-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item .\jobs\video_job.json $backup
Copy-Item .\config\video_spec_v1.yaml $backup
Copy-Item .\src\image_to_video_generator.py $backup
Copy-Item ".\output\$($job.job_id)" $backup -Recurse

git fetch origin feature/scoped-qc-continuation
if ($LASTEXITCODE -ne 0) { throw 'Git fetch sikertelen.' }
git restore --source=origin/feature/scoped-qc-continuation -- src/image_to_video_generator.py
if ($LASTEXITCODE -ne 0) { throw 'A generátor átvétele sikertelen.' }

$env:VIDEO_PROVIDER = 'still_motion'
$env:SCENE_TIMING_MAX_VIDEO_SEC = '24'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\crocodile-resume-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('".venv\Scripts\python.exe" -u src\pipeline_orchestrator.py > "{0}" 2>&1' -f $log)
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Encoding utf8
```

A futás kimenete közvetlenül UTF-8 logba kerül; a konzolon a végén jelenik meg.
Másik ablakban `Get-Content <logfájl> -Encoding utf8 -Wait` követheti élőben.
Ne futtasd újra az `enter-dev.ps1`-et a felülírások és az indítás között.
A javítás átvételekor a runtime job és a kész médiák nem változnak; resume során
a pipeline a hiányzó eredményeket készíti el, ami további API-költséggel járhat.
