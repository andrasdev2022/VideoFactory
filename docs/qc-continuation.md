# QC-hiba utáni célzott folytatás

A képi és videós jelenet-QC négy fázisa támogatott: `image_qc`,
`image_semantic_qc`, `video_qc`, `video_semantic_qc`. Alapértelmezésben egy
első generálás és legfeljebb **három további javítás** engedélyezett médiánként.
A számlálók a jobban maradnak, ezért egy sima újraindítás nem ad új keretet.
A régi `--max-image-attempts` és `--max-video-attempts` teljes generálásszámot
jelent; mindkettő alapértéke 4, megengedett tartománya 1–4.

A keret kimerülésekor a `qc_continuation` tartós pont megőrzi a job/jelenet/fázis
azonosságát, a média metaadatait és SHA-256 lenyomatát, a releváns követelményeket,
a QC teljes eredményét, az okot és a tényleges próbálkozásszámot.
A sima resume ennél megáll, még a szolgáltatás-preflight előtt: nem generál újra.

## A két döntés

```powershell
python src/pipeline_orchestrator.py -OverruleQC
python src/pipeline_orchestrator.py -RetryQC
```

**`-OverruleQC`**: a mentett szemantikai QC-eredmény egyszeri kézi elfogadása.
Az eredeti hibák és megfigyelések megmaradnak; a `status` elfogadottra változik,
és külön dátumozott `manual_override` rögzíti a döntést. Csak ez az egy eredmény
változik. A következő hibás jelenet vagy fázis új megállást és új döntést igényel.
A fájlokat megőrzi, és a pipeline továbbhalad; a még hiányzó további fázisok
normál működése API-költséggel járhat.

Technikai QC-hiba nem fogadható el kézzel. Hiányzó, üres vagy nem dekódolható
média, módosított fájl, eltérő job, megváltozott követelmény vagy QC-metaadat
esetén a felülbírálás elutasításra kerül. Videónál a forráskép lenyomata is
ellenőrzött. A videó olvashatóságát helyi FFmpeg-dekódolás ellenőrzi.

**`-RetryQC`**: új, legfeljebb négy generálást engedő javítási ciklus az érintett
médiafázisnál. A korábbi ciklus és QC a `qc_continuation_history` alatt megmarad.
A már kész többi jelenet, narráció és zenei asset megmarad. Az érintett jelenet
vágása és a függő összeállítás, felirat-render, mix, thumbnail-cache és végső QC
érvénytelenedik. Képhibánál az abból készült jelenetvideó is érvénytelenedik.
Ez fizetős kép-/videógenerálást és szemantikai QC-t is indíthat.
Hiányzó média újragenerálható, de egy meglévő, a pont óta megváltoztatott fájl
nem használható fel a régi döntéshez.

Still-motion videó szemantikai hibájánál a javítás célzott forráskép-szerkesztés
az eredeti QC-megfigyelésekkel, majd új kép-QC és videórender. A változatlan
forráskép ismételt determinisztikus renderelése nem számít javításnak.
A képjavító az érvényes supervisor-szerződésen belüli eltéréseket korrigálja;
a kötelező supervisor-jóváhagyás továbbra is blokkolhatja a képgenerálást.
A képjavításnak saját, legfeljebb három javításos kerete van. Ha ezen belül a
kép-QC áll meg, az új folytatási pont pontosan ezt a képi fázist jelöli.

Mindkét döntés előtt JSON-mentés készül a `jobs/history/before-qc-*.json` alá.
Újragenerálás előtt az érintett meglévő jelenetképek és videók másolata az
`output/<job_id>/history/qc-*/` alá kerül. Az automatikus javítások QC-eredményeit
és médiamentéseit a `qc_repair_history` tárolja. Mentési hiba esetén a művelet
nem folytatódik a generálással.

A kapcsolók egymást kizárják, és `--idea` mellett nem használhatók.
Mentett pont nélkül hibát jeleznek. Új videóhoz továbbra is `--idea` kell.
A régi, folytatási pont nélküli, elakadt job normál resume során kap pontot,
ha az eltárolt QC-hiba elérte a javítási limitet; különben a maradék javítások
futnak. Egy már elkészült jobhoz nem kell egyik kapcsoló sem.
Más munkerek technikai/API/konfigurációs hibái nem szemantikai QC-elutasítások;
ezekre nincs kézi sikeressé nyilvánítás.

## Windows: megőrzés és UTF-8 log

Branchváltás vagy frissítés **előtt** a projekt gyökeréből mentsd a jelenlegi
runtime állapotot és a kész médiát a repón kívülre. A repo-job nem helyettesíti
a Windows gépeden lévő authoritative `jobs/video_job.json` fájlt.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path (Split-Path (Get-Location).Path -Parent) "VideoFactory-backup-$stamp"
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
$job = Get-Content .\jobs\video_job.json -Raw -Encoding utf8 | ConvertFrom-Json
Copy-Item .\jobs\video_job.json (Join-Path $backup 'video_job.json') -ErrorAction Stop
Copy-Item (Join-Path '.\output' $job.job_id) (Join-Path $backup $job.job_id) -Recurse -ErrorAction Stop
"Mentés: $backup"
```

Folytatás csak a QC és a média kézi ellenőrzése után. Példa felülbírálásra:

```powershell
. .\enter-dev.ps1
New-Item -ItemType Directory -Force .\logs | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$log = ".\logs\qc-continue-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('python -u src/pipeline_orchestrator.py -OverruleQC > "{0}" 2>&1' -f $log)
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Encoding utf8
```

Javításhoz ugyanebben a logoló parancsban `-RetryQC` használandó.
A kapcsoló hiányában a megoldatlan pont csak megjelenik, nem fogy el.
