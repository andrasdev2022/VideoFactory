# Kötelező vizuális supervisor

A supervisor a teljes vizuális tervet ellenőrzi **az első képgenerálás előtt**.
Ez a karakterreferenciákra, jelenetképekre, kézi indításra és `--force`
újragenerálásra is vonatkozik. Hiányzó vagy elavult jóváhagyásnál a képgenerátor
API-hívás nélkül leáll. Nincs kikapcsoló vagy megkerülő CLI-kapcsoló.

## Működés

1. Forgatókönyv, narráció és időzítés készül, majd az összes vizuális és
   karakterreferencia-prompt. Ezek még nem képgenerálások.
2. A supervisor együtt vizsgálja a történetet, karaktereket, stílust, promptokat,
   konfigurációt, videómódot és a kép-/videó-QC utasításait.
3. Minden jelenethez közös specifikáció készül: képkivágás, egyetlen ábrázolt
   pillanat, kötelező/opcionális/tiltott elemek, látható karakterjegyek és a
   képen nem megkövetelt részletek. A karakterreferenciák saját tervet kapnak.
4. Egy külön modellhívás az eredeti bemenetekkel összevetve ellenőrzi a tervet.
   Csak teljes lefedettség, megőrzött történet és üres konfliktuslista mellett
   engedélyezett a generálás. Maximum három tervezési/ellenőrzési kör fut.
5. Az elfogadott kép-, mozgás-, negatív és folytonossági promptok bekerülnek a
   jelenetekbe. A narráció és a kanonikus karakterleírás nem íródik át.
6. A képgenerálás és a kép-/videó-QC ugyanazt a jóváhagyott specifikációt kapja.
   Kézközelinél nem kötelező egy képen kívüli arc vagy szemöldökseb. A látható
   karakterjegyeknek továbbra is illeszkedniük kell a referenciához.

Still-motion esetén a történet időbeli eseményeit a narráció közvetítheti,
a kép egy reprezentatív pillanatot mutat. A videó csak közelítést vagy kitartást
végezhet. Ez nem engedély a történet lényegének elhagyására.

A jóváhagyást a program a bemenetek és a terv SHA-256 lenyomatához köti.
Forgatókönyv-, karakter-, prompt-, stílus-, konfiguráció-, videómód- vagy
QC/generálási szabályváltozás új ellenőrzést igényel. A média létrejötte,
a próbálkozásszámláló és a QC eredménye nem módosítja a tervezési bemeneteket.
Érvényes jóváhagyás ismételt ellenőrzése nem indít új modellhívást.

A jóváhagyás nem matematikai bizonyíték minden ellentmondás hiányára, és nem
jelent garantáltan hibátlan képet. A generálás utáni technikai és tartalmi QC
megmarad. Hibás képnél az újrapróbálkozás megkapja a QC konkrét észrevételeit;
ezek csak a jóváhagyott terv teljesítését segíthetik, nem írhatják át a tervet.

## Indítás és folytatás

A master automatikusan futtatja az ellenőrzést a karakterreferencia-promptok
után, a karakterképek előtt, folytatáskor is. Csak a tervezési kapuig:

```powershell
. .\enter-dev.ps1
$env:VIDEO_PROVIDER = 'still_motion'
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\supervisor-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
python -u .\src\pipeline_orchestrator.py --stop-after visual_supervisor 2>&1 |
    Out-File $log -Encoding utf8
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Encoding utf8 -Append
Get-Content $log -Encoding utf8 -Tail 30
```

Ez a parancs a hiányzó korábbi fázisokat is elvégzi, de képet még nem generál.
Ha már minden prompt kész, csak a supervisor futtatható:

```powershell
python -u .\src\visual_supervisor.py --max-rounds 3 2>&1 |
    Out-File .\logs\visual-supervisor.log -Encoding utf8
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File .\logs\visual-supervisor.log -Encoding utf8 -Append
```

A modell az `OPENAI_SUPERVISOR_MODEL`, ennek hiányában az `OPENAI_MODEL` értéke.
A supervisor szöveges API-hívásai költséggel járhatnak: körönként egy tervezés,
majd szerkezetileg érvényes terv esetén egy külön ellenőrzés.
Hiba/refusal/hiányos válasz esetén a kapu zárva marad.

## Meglévő jobok és mentések

Régi job nem kap automatikus felmentést. Első jóváhagyáskor, illetve új terv
jóváhagyásakor a jelenlegi megvalósítás konzervatívan a **teljes vizuális
médiaállapotot** érvényteleníti: karakterképek, jelenetképek, videók, ezek QC-je,
vágás és a függő összeállítás/export. A képi és videós próbálkozásszámlálók
nullázódnak. A narráció és annak időzítése megmarad. Az audioterv és a generált
zene/SFX cache-e is érvénytelenedik, mert a vizuális terv változhatott.

A meglévő médiafájlokat a supervisor nem törli, de a későbbi generátorok
felülírhatják őket. Folytatás előtt mentsd külön az `output/<job_id>` könyvtárat,
és branchváltás előtt a helyi `jobs/video_job.json` fájlt is. A supervisor CLI
minden új ellenőrzés előtt automatikus JSON-mentést készít a `jobs/history/`
könyvtárba; ez nem médiamentés.

A `visual_supervisor` mező tárolja az eredeti bemeneteket, a körök terveit,
visszautasításait, a konfliktusfeloldásokat és a végső specifikációt. Korábbi
ellenőrzések a `visual_supervisor_history` listába kerülnek. Sikertelen ellenőrzés
után a konkrét konfliktust kell javítani; a `status` kézi átírása nem megoldás.

A fázis a vizuális tervezést és a kép-/videó-QC követelményeit egyezteti.
Nem helyettesít külön hangminőségi vagy audioterv-supervisort.
