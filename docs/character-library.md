# Új történet meglévő karakterekkel

A `character_library/` helyi karaktertár, nem kerül Gitbe. Az import és a katalógus
nem használ API-t, nem módosítja az aktív jobot vagy a korábbi médiákat.
A könyvtárat a projekt többi helyi médiájával együtt érdemes menteni.

## 1. Meglévő karakterek importálása

A projekt gyökerében, az aktivált `.venv` környezetben:

```powershell
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\character-import-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('python -u src\character_library.py import > "{0}" 2>&1' -f $log)
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Encoding utf8
Start-Process ".\character_library\catalog.html"
```

Források: `jobs/video_job.json` és `jobs/history/**/*.json`, a bennük hivatkozott
referenciaképekkel. A régi `output` könyvtáraknak az első importkor még meg kell
lenniük. Hiányzó/sérült kép vagy hiányos karakter esetén az import figyelmeztet,
és a többi karakterrel folytatódik. Pusztán a jelenetképekből nem rekonstruál
karaktert. A képeket és leírásokat külön bemásolja, ezért később a forrásvideó
eltávolítható anélkül, hogy a karaktertár sérülne.

Az import megismételhető, új videók után ismét futtatandó. Azonos név, leírás,
személyiség és képtartalom ugyanaz az elem; eltérő megjelenés külön azonosítót kap.
A történeten belüli `char-001` önmagában nem globális azonosító.

## 2. Kiválasztás

A katalógus a böngészőben helyben megnyitható, nincs szerver. Név, leírás és
forrásvideó alapján kereshető. Jelölj ki 1–3 szereplőt, majd másold ki a megjelenő
`--characters "..."` kapcsolót. Különböző videók szereplői is kombinálhatók.

A katalógus újraépítése: `python -u src/character_library.py catalog`.
Szűkített katalógus: `python -u src/character_library.py catalog --search Pip`.
Ezek kimenetét is az importnál bemutatott UTF-8 logolással rögzítsd.

## 3. Első teszt: csak a forgatókönyvig

Az alábbi `$cast` értékét cseréld a katalógus tényleges azonosítóira. Az ötlet
illeszkedjen hozzájuk; a szereplők nevét érdemes kifejezetten megadni.

```powershell
$env:PYTHONUTF8 = '1'
$cast = 'AZONOSITO1,AZONOSITO2,AZONOSITO3'
$idea = 'A kiválasztott három szereplő együtt kincset keres a kertben. Write the English narration in natural rhyming couplets; keep complete couplets within each scene.'
$log = ".\logs\character-story-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('python -u src\pipeline_orchestrator.py --idea "{0}" --characters "{1}" --stop-after script > "{2}" 2>&1' -f $idea, $cast, $log)
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Encoding utf8
```

Ebben a `cmd.exe` példában a változók szövegébe ne írj dupla idézőjelet vagy
shellvezérlő karaktert. A normál CLI közvetlenül is használható. A saját YAML
style_description megőrzéséhez hagyd el a `--visual-style` kapcsolót.

A kiválasztott nevek/leírások/személyiségek már a bootstrap modell kérésében
szerepelnek, és változatlanul kerülnek a jobba. A szerep az új történethez igazodhat.
A faj, életkor, megjelenés, ruha és kiegészítők rögzítettek. A teljes szereplőgárda
a kijelölt lista: ez a változat nem kever újonnan kitalált és importált karaktereket.

A kiválasztás helyi hibái preflight előtt megállítják a master pipeline-t.
Az ötlet/stílus kompatibilitását külön szöveges AI-ellenőrzés nézi bootstrap előtt,
majd az elkészült blueprintet újra ellenőrzi. Ez két további szöveges modellhívás;
a szemantikai ellenőrzés nem tévedhetetlen. Hiba vagy modellkiesés esetén a régi
aktív job nincs archiválva/felülírva. A bootstrap karakteradatait determinisztikusan
is ellenőrizzük; ha átnevezi vagy átírja őket, hibát adunk, nem cseréljük le csendben.

Siker esetén az új job önálló képmásolatokat és eredetadatokat kap. A katalógus
későbbi változtatása vagy törlése nem módosítja a megkezdett videót. Hiányzó/sérült
job-referencia esetén hiba jön; nincs automatikus újrarajzolás. A `--force` sem
rajzolhatja újra az importált karaktert. A vizuális supervisor továbbra is kötelező,
de a meglévő karakterképeket nem érvénytelenítheti, a jelenetképi QC pedig aktív marad.
Eltérő ruha vagy új megjelenés később külön karakterváltozat lehet; variánsgenerátor
még nincs ebben a változatban.

## 4. Folytatás

Az ellenőrzött forgatókönyv után ugyanaz a naplózási minta, de a parancs:

```powershell
python -u src\pipeline_orchestrator.py
```

A folytatásban nincs `--idea`, `--characters` vagy `--stop-after script`.
A master tiltja a `--characters` kapcsolót új ötlet nélkül, így nem lehet egy aktív
videó szereplőit véletlenül lecserélni.

## Fejlesztői ellenőrzés

A `test/test_character_library.py` izolált PNG-fixture-ökkel és mock modellekkel
ellenőrzi az ismételt importot, forrásfüggetlen másolatokat, sérülést, útvonalhatárokat,
katalógus-escape-et, tényleges bootstrap requestet, konfliktus miatti megállást,
sikeres új-job mentést és archiválást, illetve a supervisor és képgenerátor
referenciamegőrzését. Fizetős generálás a helyi tesztben nem történik.
