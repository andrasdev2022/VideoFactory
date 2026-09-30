# VideoFactory — projektátadó

Frissítve: **2026-09-30**. Ellenőrzött main: `ebe96b155619f7af6af84946eda0b2f6687f1cf3`.
PR #27 merge-elve, a felhasználó törölte a branchet. E dokumentációs PR előtt
nem volt nyitott PR. A Windows runtime job továbbra is authoritative.
Az alábbi aktuális állapot felülírja a későbbi, történeti fejezeteket.

## Új chat indítása

Másolható indítóüzenet:

> Folytassuk a VideoFactory projektet, repo: andrasdev2022/VideoFactory.
> Először olvasd el a docs/project-handoff.md dokumentumot és ellenőrizd a main,
> a nyitott PR-ek és a releváns forrásfájlok aktuális állapotát.
> Feature branch és PR módosítható, de ne merge-elj külön kérésem nélkül.
> A Windows gépemen lévő jobs/video_job.json az authoritative runtime state:
> branchváltás vagy reset előtt meg kell őrizni. A teszt- és futtatási parancsok
> stdout/stderr kimenete UTF-8 logfájlba kerüljön.
> A legutóbbi igazolt job: 20260930-113010, The Grand Crocodile Beach Prank.
> A kész videó 50,033 s, hat jelenet, still_motion, SFX nélkül, export PASS.
> Következő feladat: implementáld az alább dokumentált, elfogadott QC-folytatási
> mechanizmust, pontosan -OverruleQC és -RetryQC kapcsolókkal.
> Ez még nincs implementálva. A kész videót ne regeneráld; fizetős API-hívást
> ne indíts, helyi/mock tesztekkel dolgozz.

## Aktuális állapot és következő fejlesztés — 2026-09-30

### Elfogadott QC-folytatási mechanizmus — még nincs implementálva

A felhasználó elfogadta a koncepciót. A pontos kapcsolónév **`-OverruleQC`**
(egyetlen kötőjel, kis r; nem `-OverRuleQC`). A következő chat feladata az implementáció,
a használati dokumentáció és az érdemi regressziós tesztek elkészítése feature PR-ben.

1. QC-hiba után az eredeti generáláson felül legfeljebb **3 javítási próbálkozás**.
   A számlálók a folytatások között megmaradnak; a jelenlegi eltérő limiteket ehhez
   kell igazítani. Három összes generálás nem azonos három javítással.
2. Sikertelenségnél leállás ELŐTT tartós folytatási pont mentése:
   job ID, scene ID, pontos QC-fázis, érintett fájl és azonosító/lenyomat,
   követelmények/config releváns azonossága, QC-eredmény, indoklás, próbálkozások.
3. `python src/pipeline_orchestrator.py -OverruleQC`: kizárólag a mentett
   jelenet adott QC-eredményét kézzel elfogadottnak jelöli, az elkészült médiát
   megtartja, majd folytatja a pipeline-t. Az eredeti eredmény és a kézi döntés
   dátummal megmarad az előzményekben; mentés készüljön a változtatás előtt.
4. `python src/pipeline_orchestrator.py -RetryQC`: új javítási ciklus az érintett
   jelenet hibás fázisánál. Csak a szükséges függő eredmények érvénytelenedjenek,
   más kész jelenetek maradjanak meg. Teljesen új videó továbbra is `--idea`.
5. Paraméter nélküli resume megoldatlan folytatási pontnál a hibát és a két
   konkrét választható parancsot mutatja; nem bírál felül és nem költ újra magától.
6. A felülbírálás **egyszeri**, nem az egész futásra érvényes QC-kikapcsolás.
   A pont elfogyasztódik. Egy következő jelenet/fázis hibája új pontot hoz létre,
   új felhasználói döntéssel; a CLI-flag nem terjedhet át erre automatikusan.
7. Másik job, megváltozott média vagy elavult pont nem fogadható el a korábbi
   döntéssel. Hiányzó/olvashatatlan fájl és egyéb valódi technikai hiba nem
   minősíthető sikeresnek. Egymást kizáró kapcsolókat és hiányzó pontot ellenőrizni kell.
8. Still-motion esetén ugyanannak a determinisztikus rendernek ismétlése nem
   javítás: érdemi, QC-visszajelzéshez kötött korrekció kell. A megoldás nem
   kerülheti meg a kötelező supervisor-ellenőrzést képgenerálás előtt.
9. A leállási üzenet a tényleges okot és próbálkozásszámot közölje.

Tesztelendő: fázis/jelenet izoláció, egyszeri felhasználás, második QC-hibánál új
megállás, elavult/módosított fájl elutasítása, technikai hibák blokkolása,
3 javítás számlálása, retry célzott invalidálása és előzmények megőrzése.

### A problémát igazoló legutóbbi futás

- Job `20260930-113010`, **The Grand Crocodile Beach Prank**; Cuki (bébi krokodil),
  Pip (remeterák), Grandma Croc. Hat jelenet, animation_3d, still_motion.
- `crocodile-20260930-132956.log`: supervisor APPROVED; az 1. jelenet képét
  célzott javítás után elfogadta a QC. A videó-QC azt állította, hogy a tojás
  alul kilóg az utolsó mintán. A felhasználó videója és a megvizsgált első/végéhez
  közeli képkocka cáfolta ezt: a teljes tojás látható. Téves QC-elutasítás.
- A scene orchestrator egyetlen still_motion render után megállt, de hibásan
  „maximum 4 video attempts” üzenetet adott. Ez nem valós limitkimerülés volt.
- Ideiglenes kézi JSON-felülbírálás történt mentéssel, előzményekkel:
  `visuals.scenes[scene_id=1].video.semantic_qc` status=passed,
  motion_matches_prompt=true, errors/problematic_sample_indices üres,
  manual_override indoklással. A kulcs **visuals**, nem visual.
- `crocodile-resume-20260930-135643.log`: az 1. jelenet médiája megmaradt;
  mind a hat jelenet kész, a 4. kép elhajlott lapátja egy javítást igényelt.
  Végső export **50,033 s**, `Publish ready: True`, `Exit code: 0`.
- Kimenet: `output/20260930-113010/final/video.mp4`; narráció, felirat és zene
  elkészült. SFX a tervben, generálásban és keverésben is 0.
- A teljes kész videót nem vizsgáltuk meg; a sikert a log igazolja.
  A legutolsó teljes Windows job JSON nincs feltöltve; ne helyettesítsd repo-jobbal.

### Azóta elkészült fejlesztések és külön nyitott tételek

- PR #25: kötelező vizuális supervisor a képgenerálás előtt, terv/QC-egyeztetés,
  célzott képjavítás és szelektív invalidálás. Ezt meg kell őrizni.
- PR #26: YAML `audio.sound_effects.enabled: false` tiltja az SFX-et végig,
  meglévő job folytatásakor is.
- PR #27: YAML TTS modell/hang/instrukció/numerikus sebesség/formátum bekötése,
  cache-ellenőrzés és függőségek invalidálása. Dokumentáció: narration-settings.md.
  A nem használt `gender` törölve. A genre_policy többé nem írja át a content.style-t;
  YAML-alapérték: `pacing appropriate to the genre and emotional arc`.
  Korábbi teljes tesztkészlet 326 sikeres teszt, PR CI zöld.
- Külön, még nem implementált bootstrap-javítás: a „Prefer 1–3 characters” puha
  prompt és a kötelező 1–3 validátor eltérése miatt az első krokodilos futás
  megállt (`crocodile-20260930-132610.log`). Pontosan három szereplős ötlettel
  sikerült. Szigorúbb instrukció, korlátos javítás és helyes bootstrap-resume
  üzenet későbbi feladat; nem a most elfogadott QC-folytatás része.
- Második, célzott QC-felülvizsgálat ötlete felmerült, de nem implementált,
  és nem helyettesíti a most elfogadott felhasználói folytatási mechanizmust.

## Repo, környezet és munkaszabályok

- Repo: https://github.com/andrasdev2022/VideoFactory
- Felhasználói gép: Windows 11.
- Projekt: `C:\Users\johnd\Desktop\Content generator\video_factory`.
- Fő Python: `.venv`; a felhasználó korábbi logjában Python 3.14.7.
- Környezet aktiválása és titkok betöltése: `. .\enter-dev.ps1`.
- Local LTX: külön `.venv-ltx`, Python 3.11 (korábbi log: 3.11.9).
- GPU: NVIDIA RTX 2070, 8 GB VRAM. FFmpeg és ffprobe szükséges.
- Beszélgetés és használati útmutatók nyelve magyar.
- Feature branchek és PR-ek közvetlenül módosíthatók. Merge kizárólag külön kérésre.
- Minden repómódosítás után ellenőrizni kell a CI-t.
- A helyi `jobs/video_job.json` megőrzendő; repo-verzióval nem szabad felülírni.
  Branchváltás/reset előtt másold a repón kívülre. Ha a média is fontos,
  az `output/<job_id>` könyvtárat is mentsd külön.
- Futási jobot, generált médiát, titkokat és logokat ne commitolj.
- A felhasználó helyben futtatja az API/GPU E2E teszteket, és feltölti a logokat.
  Logból ne állítsuk, hogy meghallgattuk a hangot vagy megnéztük a teljes videót.
- GitHub Actions: `.github/workflows/tests.yml`, Python 3.12, unittest.
  A tesztlogot artifactként is feltölti. A tesztek a `test/` könyvtárban vannak,
  az alkalmazáskód az azonos szintű `src/` könyvtárban.

## Fő pipeline

Ötlet / új job → forgatókönyv → jelenetenként TTS és időzítés → globális időzítés
→ vizuális és karakterreferencia-promptok → kötelező visual supervisor
→ karakterreferencia-képek → jelenetképek, képi QC, jelenetvideók,
videó-QC és vágás → összeállítás → felirat → audioterv → zene/SFX → hangkeverés
→ thumbnail → végső QC és export.

Belépési pont: `src/pipeline_orchestrator.py`.
`--idea` új jobot készít; nélküle az aktív jobot folytatja.
A már jóváhagyott eredményeket a pipeline státuszok és cache-aláírások alapján
újrahasználja. A régi aktív jobot a bootstrap a `jobs/history/` alá archiválja.
Ez nem jelent teljes több-jobos izolációt vagy párhuzamos futtatási támogatást.

## Videoproviderek

- `VIDEO_PROVIDER=still_motion`: helyi FFmpeg, statikus kép lassú középre zoomolása
  vagy tartása, szereplő- és tárgymozgás nélkül. Megbízható alternatíva ezen a GPU-n.
  A jelenetvideók alapból 720×1280, 24 fps; a végső export 1080×1920, 30 fps.
  `STILL_MOTION_MODE=zoom|hold`, `STILL_MOTION_MAX_ZOOM` alapból 1.05.
- `VIDEO_PROVIDER=local_ltx`: `Lightricks/LTX-Video`, 512×896, 24 fps,
  12 inference step, guidance 3.0, sequential CPU offload.
  A master jelenetgenerálási szakaszában persistent LTX service használható.
  Tokenizer szerinti maximum 120 token; mozgás és folytonosság prioritással.
  A hosszú QC overall_notes nem kerül vissza a Local LTX retry promptjába.
- Runway továbbra is támogatott; thumbnail a providertől függetlenül készül.

A Local LTX technikailag fut, de arc-/test-/ruhamorfózis miatt több régi jelenet
statikus fallbackre jutott. Ezért a still_motion tudatos gyártási opció.
Részletek: [local-ltx.md](local-ltx.md), [still-motion.md](still-motion.md).

## Műfaj, stílus, konfiguráció

A `config/video_spec_v1.yaml` az általános kreatív/technikai specifikáció.
Az új job ezen kívül a `--idea`, a CLI-felülírások és az AI kimenete alapján készül.
A providerek, modellek és más runtime opciók környezeti változókból is származnak.

A PR #21 óta az új job menti a `spec_snapshot` konfigurációt és a
`creative_direction.genre` értéket. Resume ezt használja; későbbi YAML-módosítás
az új videókra vonatkozik. Régi, snapshot nélküli jobok továbbra is YAML-t olvasnak.
Kivétel: az aktuális YAML `audio.sound_effects.enabled: false` értéke meglévő
jobnál is tiltja az SFX-generálást és -keverést. Részletek: [audio-volume.md](audio-volume.md).

- `content.genre` szabad szöveg, nincs `--genre` kapcsoló.
- A műfaji instrukció végigmegy a történeten, scripten, átírásokon, vizuális
  promptokon, képeken, narráción, audioterven és zenén.
- Ismert komédia-alapértékeket nem komikus műfajnál a feloldott konfiguráció
  semlegesít; nincs minden videóra kötelező poén, játékos zene vagy gyors tempó.
- Műfajpéldák és korlátok: [genres.md](genres.md).
- `--visual-style` csak új jobnál, `--idea` mellett használható.
  Választék: `default`, `photorealistic`, `cinematic_realism`, `animation_3d`,
  `cartoon_2d`, `anime`, `watercolor`, `comic`, `storybook`.
- A műfaj és a képi médium külön választás; az anime lehet drámai is.
  Részletek: [visual-styles.md](visual-styles.md).

## Időtartam, thumbnail és service preflight

- A cél és az elfogadott időtartomány a job specifikációjától függ. A régi
  kézi teszt 30 s / 25–35 s értékeket használt; a legutóbbi export 50,033 s.
- Végső QC legfeljebb egy kimeneti képkocka többletet enged encoder-kerekítésre.
- Narrációt természetes tempóval generálunk és mérünk; túl hosszú szöveg átírható.
  A still_motion szükség esetén vizuális tartással is segíthet a minimum elérésén.
- Thumbnail helyi Pillow-generálás, 1080×1920 JPEG, jóváhagyott jelenetképpel és
  címszöveggel. Jelenetválasztás megőrizhető; oldalsó sávok a teljes kép illesztése
  miatt jelenhetnek meg. Providerfüggetlen.
- OpenAI: auth ellenőrzés; megbízható prepaid egyenleg nincs, UNKNOWN nem blokkol.
- ElevenLabs: közvetlen `/v1/user/subscription`; nincs felesleges `/v1/models` hívás.
  `missing_permissions` / `insufficient_permissions` → WARN/UNKNOWN, nem BLOCK.
  A `user_read` hiánya mellett a zene- és SFX-generálás a helyi teszteken működött.
- Runway: credit/daily limit ellenőrzés és scene-budget becslés.
- A becsült kreditek nem ténylegesen kiszámlázott költségek.

Részletek: [duration-range.md](duration-range.md), [thumbnail.md](thumbnail.md),
[service-preflight.md](service-preflight.md).

## Egyetlen jelenet módosítása

`src/scene_editor.py --scene N --patch patch.json`:

- `voiceover`: pontos narrációszöveg;
- `image_prompt`: új képleírás;
- `motion_prompt`: mozgásleírás Local LTX/Runway számára;
- `still_motion`: jelenetszintű `mode` és `max_zoom`;
- `music_prompt`: saját jelenetzenei instrukció.

`--dry-run` csak ellenőriz; `--regenerate` mentés után folytatja a pipeline-t.
Automatikus JSON-mentés készül a `jobs/history/` alá. Ez nem médiamentés.
Az érintett eredmények és próbálkozásszámlálók érvénytelenednek, a többi kész
jelenet médiája megmarad. Ha a szerkesztett narráció miatt a teljes hossz kívül
kerül az elfogadott tartományon, leáll a globális átírás helyett.
A saját jelenetzene csak annak idősávjában váltja fel az alap háttérzenét.
Részletes, logoló Windows-parancsok: [scene-editing.md](scene-editing.md).

## Narráció konfigurálása

A `audio.voiceover` YAML-szekcióban modell, hang, stílus, instrukció, sebesség és
formátum állítható. A környezeti felülírások és a job snapshotjának elsőbbsége,
a támogatott értékek, valamint a meglévő narráció cseréjének menete:
[narration-settings.md](narration-settings.md).

## Hangerő és újrakeverés

A már generált zenét/TTS-t nem szükséges újragenerálni. A
`final_audio_mix.py --force`, majd siker esetén `final_qc_export.py --force`
helyben újrakeveri és exportálja a videót, fizetős generáló API nélkül.

| Változó | Alapérték | Jelentés |
| --- | --- | --- |
| `FINAL_MIX_MUSIC_VOLUME` | mentett zenei volume, tipikusan 0.20 | 0–1 zenei jelszint, jelenetzenére is |
| `FINAL_MIX_VOICE_VOLUME` | 1.0 | 0–1 narrációs jelszint |
| `FINAL_MIX_SFX_VOLUME` | 1.0 | 0–2 szorzó az effektek saját szintjére |
| `FINAL_MIX_DUCK_RATIO` | 8.0 | Beszéd alatti zenehalkítás; 2.0 enyhébb, 1.0 kikapcsolja |

Első próbára javasolt értékek: zene 0.35, narráció 0.85, SFX 0.70, duck ratio 2.0.
Ezek nem felhasználó által már jóváhagyott végleges beállítások. A remix
hallgatási eredménye még nem érkezett vissza ebben a beszélgetésben.
Teljes mentési, logolási és visszaállítási parancsok: [audio-volume.md](audio-volume.md).

## Tesztek és PowerShell-logolás

A PR #21 végső módosítása után 283 helyi teszt sikeres, GitHub CI zöld volt.
A tesztek között valódi FFmpeg-keverési ellenőrzés is szerepel.
Windows alatt a unittest és az argparse várt stderr-kimenete is okozhat
`NativeCommandError` megjelenítést. A csak unittest runner stdout-ra irányítása
nem elég: gyermekfolyamatok is írhatnak stderr-re. Használd a cmd.exe-n belüli
átirányítást, és mindig ellenőrizd az exit code-ot és a tesztösszesítést.

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$env:PYTHONPATH = (Resolve-Path .\src).Path
$env:PYTHONIOENCODING = 'utf-8'
$log = ".\logs\unit-tests-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('python -u -m unittest discover -s test -p "test_*.py" -v > "{0}" 2>&1' -f $log)
$testExitCode = $LASTEXITCODE
"Exit code: $testExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Tail 20
```

Siker: `OK`, `Exit code: 0`. Az `... ok` egyetlen tesztnél nem bizonyítja a teljes
futás sikerét. A `*>` / `Out-File` vegyes kódolásait kerüld; UTF-8-at használj.
Részletek: [test/README.md](../test/README.md).


## Történeti kézi fázisteszt — 2026-09-22

**Archív állapot, nem a következő feladat. Az akkori függő tételeket és
folytatási parancsokat ne kezeld aktuális utasításként.**

A felhasználó célja az egyes fázisok önálló futtatása, a kézi beavatkozás,
a jelenetenkénti újragenerálás és a retry/fallback működésének kipróbálása.
Fázisonként nevezzük meg, mi történik, adjunk UTF-8 logoló PowerShell-parancsot,
és a feltöltött logból ellenőrizzük az eredményt. Ez nem teljesen automatikus
E2E futás; ne ugorjunk át jóváhagyott lépéseken.

**Legutóbbi igazolt job:** `20260922-095059`, **The City Beneath the Moon**.
Ötlet: „Kommandósok megérkeznek egy idegen civilizációba. A holdsütötte városban
mindenhol sötét árnyak vannak.”
Karakterek: Captain Mara Voss, Tarin Holt, The Hollow Child.
A bootstrap logja `Visual style: default` értéket mutat; a tényleges YAML-stílust,
műfajt és a következő videógenerálás providerét a helyi jobból/környezetből kell
ellenőrizni. Ne örökítsük rá a korábbi The Last Watch anime/still_motion beállítását.

### Elvégzett fázisok és önálló belépési pontok

Az alábbiak worker-parancsok; futtatáskor stdout és stderr is UTF-8 logba kerüljön.

| Fázis | Worker | Igazolt eredmény |
| --- | --- | --- |
| 1. Ötletkidolgozás / bootstrap | `python -u src/new_job.py --idea "..."` | Új job, 3 karakter; korábbi `20260921-102547` job archiválva |
| 2. Forgatókönyv | `python -u src/script_generator.py` | Első próbára 5 jelenet, 30 s tervezett hossz |
| 3. Jelenetenkénti narráció, hang-QC, időzítés | `python -u src/voice_orchestrator.py --scene N --max-attempts 3` | Mind az 5 jelenet elkészült; 1–3. jelenetnél rövidítések |
| 3/a. Egy jelenet automatikus rövidítése | `python -u src/script_timing_rewriter.py --scene N` | 2. jelenet: 1 kör; 3. jelenet: 2 kör |
| 3/b. Új hang a rövidítés után | `python -u src/voice_orchestrator.py --scene N --max-attempts 3 --reset-attempts` | Új TTS, QC és mért időzítés |
| 4. Összesített időzítés | `python -u src/scene_timing.py` | 5/5 jelenet PASS, de 41,65 s; globális rövidítés szükséges |
| 4/a. Globális korrekció | `python -u src/script_duration_orchestrator.py --max-iterations 3` | 1 globális kör: 41,65 → 29,60 s; minden jelenet átírva és újramérve |
| 5. Vizuális promptok | `python -u src/visual_prompt_generator.py` | Következő lépés; ehhez a jobhoz még nincs igazolt futás |

A job, forgatókönyv, QC és időzítési állapot a Windows gép
`jobs/video_job.json` fájljában van. A hangok:
`output/20260922-095059/audio/voice/scene_001.wav` … `scene_005.wav`.
A log nem helyettesíti a teljes JSON-t. A teljes aktuális JSON-t nem kaptuk meg.
Kép-, videó-, zene-, felirat- és végső exporteredmény ehhez a jobhoz még nincs igazolva.

### Időzítési eredmények

TTS: `gpt-4o-mini-tts`, hang `marin`, természetes sebesség `1.0`;
a vizsgált WAV-ok mono, 24 kHz PCM. Jelenetenként 0,30 s ráhagyás,
10 s helyi jelenetkorlát. Ezeket a futásokban ellenőriztük, nem univerzális
providerképességként állítjuk.

| Jelenet | Globális korrekció előtt, ráhagyással | Utolsó mért hang | Utolsó jelenethossz |
| --- | --- | --- | --- |
| 1. | 4,85 s | 3,15 s | 3,45 s |
| 2. | 9,35 s | 5,60 s | 5,90 s |
| 3. | 9,00 s | 6,30 s | 6,60 s |
| 4. | 9,80 s | 6,85 s | 7,15 s |
| 5. | 8,65 s | 6,20 s | 6,50 s |
| Összesen | 41,65 s | 28,10 s | **29,60 s** |

A 29,60 s a jelenetidőzítések összege, nem kész videófájl mért hossza.
Utolsó eredmény: `GLOBAL SCRIPT TIMING COMPLETE`,
`Script revision recommended: False`, `Exit code: 0`.
A rövidítő 35 s felső határt célzott; az új TTS tényleges eredménye lett 29,60 s.

- 1. jelenet: eredetileg 5,65 s hang / 5,95 s jelenet. Kézi szövegcserével
  4,55 / 4,85 s lett; ezt a felhasználó kifejezetten elfogadta.
  A globális kör később ezt is átírta, tehát az elfogadás nem automatikusan
  vonatkozik a legutolsó 3,45 s-os változatra.
- 2. jelenet: 13,90 s hang → automatikus rövidítés után 9,05 s hang.
- 3. jelenet: 15,10 s hang → első rövidítés 9,75 s hang + 0,30 s = 10,05 s,
  ezért még FAIL → második rövidítés 8,70 s hang / 9,00 s jelenet, PASS.
- A 4–5. jelenet elkészültét a felhasználó jelezte; időzítésüket a teljes
  összesítő log igazolta. Külön eredeti generálási logjukat nem kaptuk meg.

### Legutolsó, globálisan rövidített narrációk

A `04-global-timing-20260922-145740.log` által igazolt szövegek:

1. “Moonlit shadows turned toward the commandos.”
2. “Silent streets. A shadow reached for Tarin—a child trapped inside.”
3. “Cursed cityfolk, not monsters. The seal could free them—or unleash shadows.”
4. “Mara sent them running, cut the curse in the seal with her blood. Warm light restored them.”
5. “City lived. No shadows beneath them. Four shadows walked away. Would you stay?”

**Nyitott elfogadás:** a globális kör utáni hangok meghallgatását és a fenti
szövegek tartalmi elfogadását a felhasználó még nem igazolta vissza.
A technikai QC nem bizonyítja a természetes megfogalmazást vagy a jelentésmegőrzést.
A 3. jelenetből a helyi rövidítés során eltűnt a testekbe költöző árnyak konkrét
veszélye; a globális körben a torony és a pecsét megtalálása is kiesett.
Az 5. jelenet „City lived.” megfogalmazása távirati.
Ezek észrevételek, nem automatikusan elvégzendő javítások.

### A kézi teszt során feltárt működési korlátok

- Nincs minden fázisra egységes „3 retry, majd fallback” garancia.
  Bootstrap: nincs alkalmazásszintű tartalmi retry/fallback.
  Forgatókönyv: maximum 3 generálási kísérlet validálási visszajelzéssel,
  generálási kivételnél leáll, nincs fallback. A 3 kísérlet nem 3 további retry.
- A voice orchestrator megőrzi a próbálkozásszámot; `--reset-attempts`
  ezt nullázza, nem általános újragenerálási kapcsoló.
  Túl hosszú szövegnél az önálló worker rövidítést kérve megáll.
  A fő pipeline hívja a helyi rövidítőt és indít új mérési kört.
- A helyi rövidítőnek nincs tetszőleges célidőt fogadó CLI-paramétere;
  a mentett timing maximumából számol. A 10 s korlát, 0,30 s ráhagyás és
  0,35 s biztonsági tartalék mellett a narrációs cél 9,35 s volt.
- A `scene_editor.py` létező script- ÉS visual-jelenetet követel meg,
  ezért a vizuális promptok előtti kézi narrációszerkesztésre jelenleg nem alkalmas.
  Az 1. jelenetnél mentés után közvetlen JSON-szövegcserét, az összesített
  `script.voiceover` frissítését, a jelenet `voice`/`timing` és a
  `timing_summary` törlését használtuk, majd új voice/timing futást.
  Ez a korai fázisra szabott megoldás, nem későbbi médiákhoz általános recept.
- A kezdeti script tervezett időtartama nem megbízható beszédhosszbecslés:
  több jelenet jelentősen túlfutott. A rövidítések szó-/karakterkorlátja sem
  garantálja a tényleges TTS-hosszt; ezért szükséges az újramérés.
- Az ismételt rövidítés tartalmi részleteket veszíthet. Nincs a bemutatott
  technikai PASS-szal igazolt automatikus jelentésmegőrzési ellenőrzés.
- A `scene_timing.py` 0-s kilépése önmagában nem bizonyítja, hogy a teljes videó
  belefér a tartományba: 41,65 s-nál is 0 volt, globális revíziós jelzéssel.
- A globális kör mind az öt jelenetet módosította, a korábban elfogadott elsőt is.
  Ez nem jelenetenkénti felhasználói jóváhagyást megőrző zárolási rendszer.

### Mentések, bizonyítékok és következő lépés

A kiadott helyi parancsok JSON- és WAV-mentést készítettek a rövidítések előtt:
`jobs/history/before-scene-001-shortening-<stamp>/`,
`jobs/history/before-scene-00N-rewrite-<stamp>.json` és
`scene_00N-before-<stamp>.wav`, illetve globális korrekció előtt
`jobs/history/before-global-timing-<stamp>/video_job.json` és `voice/`.
A mentések jelenlegi meglétét külön nem ellenőriztük. Ezek a repón belüli mentések
nem helyettesítik a branchváltás/reset előtti repón kívüli mentést.

Fő vizsgált logok (2026-09-22):
`01-new-job-20260922-115041.log`,
`02-script-20260922-120410.log`,
`03-voice-scene-001-shortened-20260922-122611.log`,
`03-voice-scene-002-rewrite-20260922-123331.log`,
`03-voice-scene-003-rewrite-20260922-123812.log` (még FAIL),
`03-voice-scene-003-rewrite-20260922-124038.log` (PASS),
`04-total-timing-20260922-130543.log`,
`04-global-timing-20260922-145740.log`.
A feltöltött logokat elolvastuk; a hangfájlokat nem hallgattuk meg.

Folytatás: az aktuális helyi job és a globális narrációk elfogadásának tisztázása
után **5. fázis, vizuális promptok generálása**. Új PowerShellben először
`. .\\enter-dev.ps1`, majd a projekt gyökeréből:

```powershell
New-Item -ItemType Directory -Force .\\logs | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$log = ".\\logs\\05-visual-prompts-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
cmd.exe /d /c ('python -u src\\visual_prompt_generator.py > "{0}" 2>&1' -f $log)
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Append -Encoding utf8
Get-Content $log -Encoding utf8
```

Ez promptokat készít; önmagában még nem generál jelenetképeket vagy videókat.
Az eredmény a job `visuals` részébe kerül. Egy jelenet célzására `--scene N`,
újragenerálásra `--force`, meglévő visual-jelenet mozgáspromptjához
`--scene N --motion-only` is elérhető; használat előtt a meglévő állapotot ellenőrizd.

## Korábbi teljes helyi E2E — The Last Watch

**The Last Watch**, job `20260921-102547`, 2026-09-21:

- `drama` műfaj, `anime` vizuális stílus, `still_motion` provider.
- Sir Aldren idős lovag, lánya Mira csak emlékképekben jelenik meg.
  A történet veszteségről, bűntudatról és emlékezésről szól.
- Öt jelenet, mindegyik kép és videó első próbálkozásra QC-passed.
- A 3. jelenet helyi szövegrövidítést igényelt. A teljes 36.3 s-ot egy globális
  átírás 32.9 s-ra csökkentette. Végső média: 32.933 s.
- Zene, három SFX, felirat, thumbnail, végső QC/export elkészült.
- `Publish ready: True`, `Exit code: 0`.
- Eredmény: `output/20260921-102547/final/video.mp4`.
- Vizsgált log: `anime-20260921-122532.log`.
- A felhasználó szerint minden jó, kivéve a hangerőegyensúlyt. Ez indította a
  külön zene-/narráció-/SFX-szabályzók hozzáadását.

Korábbi referenciák: `20260920-075808` (Paws & Relax, LTX/fallback),
`20260920-200833` (The Last Croissant, cinematic_realism, 28.1 s).
A legutóbbi ismert job nem feltétlenül a jelenlegi aktív job: ezt a helyi JSON
alapján kell ellenőrizni. Az assistant workspace repo-jobja nem bizonyíték rá.

## Történeti GitHub-állapot és korábbi lehetséges feladatok

Az alábbi lista szeptember 27-i archívum; az aktuális állapot a dokumentum elején van.

2026-09-27-én ellenőrizve, e frissítés PR-jének megnyitása előtt:

- `main`: `6415ac8`; #22 (az első projektátadó) merge-elve.
- Nincs nyitott PR. A távoli branchlista: `main`, `feature/multi-job-isolation-reuse`.

- #21 merge-elve: műfaj, snapshot, jelenetszerkesztés, zene/narráció/SFX hangerő.
- #19 merge-elve: tesztek külön `test/` könyvtárban.
- #20 korábbi, csak műfajdokumentációs javaslatát #21 tartalmilag kiváltotta.
  Nem kell külön merge-elni. A nyitott PR-keresés nem adott találatot.
- `fix/local-ltx-prompt-budget`: a mostani távoli branchlistában már nem szerepel.
- `feature/multi-job-isolation-reuse`: a szeptember 22-i, #22 előtti összehasonlítás
  szerint 1 saját commit, 93 commit lemaradás; ez nem a mai ahead/behind érték. A külön commit egy 214 soros `src/job_context.py` fájlt ad hozzá.
  Megőrzendő az érdemi összehasonlításig; nincs igazolt kész több-jobos integráció.

Nyitott minőségi észrevételek, még nem implementált javításként kezelendők:

1. Still-motion mellett az audioterv kard lehelyezésének hangját kérte, pedig
   nincs szereplőmozgás. Az akció-SFX és kamera-only jelenet kapcsolatát javítani kell.
2. A zenei terv kórust kért, a zenegeneráló instrumentális/no-vocals instrukciót:
   a két szakasz között ellentmondás maradt.
3. Az 5. jelenet QC-je festményszerűbb képet jelzett a kért anime-vonalrajznál.
   A felhasználó a kész videó látványát elfogadta; nem indok automatikus újragenerálásra.
4. A hangerő-remix meghallgatása és a jelenetszerkesztő valódi helyi E2E-je
   még nem kapott visszaigazolást; ezekre unit/FFmpeg-tesztek állnak rendelkezésre.
5. Későbbi LTX motion/retry optimalizálás és a régi multi-job branch áttekintése
   lehetséges, de nem automatikusan elkezdendő feladat.

Új munkamenetben először a felhasználó aktuális célját és helyi állapotát kövesd;
ne regeneráld vagy írd felül a már elfogadott videót pusztán a fenti lista miatt.
