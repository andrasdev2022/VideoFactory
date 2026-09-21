# Meglévő videó hangerőegyensúlyának módosítása

Nincs szükség új TTS-, zene- vagy képgenerálásra. A `final_audio_mix.py --force`
a már elkészült feliratos videó narrációját, zenét és effekteket keveri újra.
A `final_qc_export.py --force` utána frissíti a végső videót és exportot.

| Környezeti változó | Alapérték | Javasolt első próba |
| --- | --- | --- |
| `FINAL_MIX_MUSIC_VOLUME` | A job zenéjének `volume` mezője, tipikusan 0.20 | 0.35 |
| `FINAL_MIX_VOICE_VOLUME` | 1.0 | 0.85 |
| `FINAL_MIX_DUCK_RATIO` | 8.0 | 2.0 |

A volume értékek 0–1 közötti lineáris jelszintszorzók, nem érzékelt hangerőszázalékok.
A kisebb duck ratio kevésbé halkítja a zenét narráció alatt; 1.0 kikapcsolja ezt
a kompressziót. A narráció hangerőszorzója nem változtatja meg a ducking érzékelőjét.
A zenei felülírás a jelenetszintű zenékre is vonatkozik; az effektek hangereje
változatlan. A beállítások bekerülnek a mix cache-aláírásába.

A projekt gyökerében, az aktivált fő `.venv`-ből:

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$job = Get-Content .\jobs\video_job.json -Raw -Encoding utf8 | ConvertFrom-Json
Copy-Item .\jobs\video_job.json "..\video_job-before-remix-$stamp.json"
Copy-Item ".\output\$($job.job_id)\final\video.mp4" "..\video-before-remix-$stamp.mp4"

$env:FINAL_MIX_MUSIC_VOLUME = '0.35'
$env:FINAL_MIX_VOICE_VOLUME = '0.85'
$env:FINAL_MIX_DUCK_RATIO = '2.0'
$env:PYTHONIOENCODING = 'utf-8'
$log = ".\logs\remix-$stamp.log"
cmd.exe /d /c ('python -u src\final_audio_mix.py --force > "{0}" 2>&1' -f $log)
$remixExit = $LASTEXITCODE
if ($remixExit -eq 0) {
    cmd.exe /d /c ('python -u src\final_qc_export.py --force >> "{0}" 2>&1' -f $log)
    $remixExit = $LASTEXITCODE
}
"Exit code: $remixExit" | Out-File $log -Append -Encoding utf8
Get-Content $log -Tail 20
```

Az eredmény ismét `output/<job_id>/final/video.mp4`. Ez csak helyi FFmpeg-keverés
és export, nem hív fizetős generáló API-t. A végső hangerőegyensúlyt hallgasd meg:
a nyers zene hangereje és a narráció dinamikája is számít.

A beállítások az aktuális PowerShell-munkamenetben maradnak, nem írják át a job
vagy a YAML eredeti hangerőértékeit. Tartós használathoz az `.env.local` fájlba
is felvehetők. Visszaállítás a munkamenetben:

```powershell
Remove-Item Env:FINAL_MIX_MUSIC_VOLUME -ErrorAction SilentlyContinue
Remove-Item Env:FINAL_MIX_VOICE_VOLUME -ErrorAction SilentlyContinue
Remove-Item Env:FINAL_MIX_DUCK_RATIO -ErrorAction SilentlyContinue
```
