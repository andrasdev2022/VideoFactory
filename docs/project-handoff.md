# VideoFactory — projektátadó

Frissítve: **2026-09-22**. Ellenőrzött kiinduló `main` commit:
`aadcc4ab70c170c043c045af184efdc719980bcd` (PR #21 merge).
Ez állapotfelvétel; új munkamenet elején ellenőrizd az aktuális repót és a helyi
runtime jobot. A dokumentum nem helyettesíti a Windows gépen lévő futási állapotot.

## Új chat indítása

Másolható indítóüzenet:

> Folytassuk a VideoFactory projektet, repo: andrasdev2022/VideoFactory.
> Először olvasd el a docs/project-handoff.md dokumentumot és ellenőrizd a main,
> a nyitott PR-ek és a releváns forrásfájlok aktuális állapotát.
> Feature branch és PR módosítható, de ne merge-elj külön kérésem nélkül.
> A Windows gépemen lévő jobs/video_job.json az authoritative runtime state:
> branchváltás vagy reset előtt meg kell őrizni. A teszt- és futtatási parancsok
> stdout/stderr kimenete UTF-8 logfájlba kerüljön. A következő feladat: …

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
→ vizuális promptok és karakterreferenciák → jelenetképek, képi QC, jelenetvideók,
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

- Cél 30 s, elfogadott tartomány 25–35 s. Nem szükséges pontosan 30 másodperc.
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

## Legutóbbi ismert helyi E2E

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

## GitHub-állapot és következő lehetséges feladatok

2026-09-22-én ellenőrizve, e dokumentum PR-jének megnyitása előtt:

- #21 merge-elve: műfaj, snapshot, jelenetszerkesztés, zene/narráció/SFX hangerő.
- #19 merge-elve: tesztek külön `test/` könyvtárban.
- #20 korábbi, csak műfajdokumentációs javaslatát #21 tartalmilag kiváltotta.
  Nem kell külön merge-elni. A nyitott PR-keresés nem adott találatot.
- `fix/local-ltx-prompt-budget`: a korábbi összehasonlítás szerint nincs a
  mainből hiányzó commitja, törölhető volt; törlését nem igazoltuk vissza.
- `feature/multi-job-isolation-reuse`: mainhez képest 1 saját commit, 93 commit
  lemaradás. A külön commit egy 214 soros `src/job_context.py` fájlt ad hozzá.
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
