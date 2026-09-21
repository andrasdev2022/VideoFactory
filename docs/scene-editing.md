# Egyetlen jelenet szerkesztése és újragenerálása

A `src/scene_editor.py` az aktív `jobs/video_job.json` egy jelenetét módosítja.
A jelenetnek már rendelkeznie kell script- és vizuális promptbejegyzéssel.
Nem hoz létre új jobot, és nem cseréli ki a többi jelenet szereplőit vagy promptjait.

A parancs egy UTF-8 JSON patch fájlból olvassa a pontos csereértékeket:

| Mező | Hatás |
| --- | --- |
| `voiceover` | Új narrációszöveg; az adott jelenet TTS, időzítés és videó újragenerálása |
| `image_prompt` | Új képleírás; az adott kép, kép-QC és videó újragenerálása |
| `motion_prompt` | Új mozgásleírás Local LTX/Runway számára; a kép megmarad |
| `still_motion` | Jelenetszintű `mode` (`zoom` vagy `hold`) és `max_zoom` (1.0–1.08); a kép megmarad |
| `music_prompt` | Saját zenei instrukció erre a jelenetre; a kép, videó és narráció megmarad |

Csak a módosítani kívánt mezőket add meg. A `voiceover` pontos narrációszöveg,
nem történetgenerálási instrukció. Új történés esetén a kép-/mozgásleírást is
igazítsd hozzá. A már jóváhagyott szereplők azonosítói és globális történet nem
változnak. A narrációfeliratot a `voiceover` alapján generálja.

A still_motion provider szabad szövegből nem animál szereplőket vagy kamerát.
Ennél a `still_motion` objektummal állítsd a kamerahatást; a `motion_prompt`
önmagában nem módosítja a renderelt mozgást.

## Példa: a 4. jelenet képe és zenéje

A projekt gyökerében, az aktivált fő `.venv` környezetben:

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
@'
{
  "image_prompt": "The same elderly knight and spectral squire in the ruined castle, wide composition, all characters and the entire sword inside generous margins. Preserve approved identities and clothing. Somber rain and restrained expressions.",
  "music_prompt": "Sparse mournful cello and distant low strings, no playful motifs, no vocals."
}
'@ | Out-File .\logs\scene-4-edit.json -Encoding utf8

$env:VIDEO_PROVIDER = 'still_motion'
$env:PYTHONIOENCODING = 'utf-8'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = ".\logs\scene-4-edit-$stamp.log"
$command = 'python -u src\scene_editor.py --scene 4 --patch logs\scene-4-edit.json --regenerate > "{0}" 2>&1' -f $log
cmd.exe /d /c $command
$pipelineExit = $LASTEXITCODE
"Exit code: $pipelineExit" | Out-File $log -Append -Encoding utf8
Get-Content $log -Tail 25
```

Ez API-hívásokat indíthat. Ellenőrzéshez a `--regenerate` helyett `--dry-run`
kapcsolót adj meg: ekkor nem ír jobot és nem generál semmit. Kapcsoló nélkül
csak ment; utána a master pipeline sima folytatása elvégzi a szükséges lépéseket.

A mentés előtt automatikus job-mentés készül a `jobs/history/` könyvtárba.
Ez JSON-mentés, nem teljes médiamentés: ha a régi képet/videót is meg akarod
őrizni, előbb másold ki az adott `output/<job_id>` könyvtárat.

Másik patch példa kizárólag a kamera visszafogott zoomjára:

```json
{"still_motion": {"mode": "zoom", "max_zoom": 1.025}}
```

## Újragenerálási határok

A szerkesztő csak a megváltozott mezőktől függő eredményeket érvényteleníti,
és az érintett kép-/videó-/hangpróbálkozás számlálóját indítja újra. Az azonos
értékek ismételt megadása nem érvénytelenít semmit. `--regenerate` mellett az
azonos patch a korábban megszakadt futást is folytatja.

A végső összeállítás, felirat, hangkeverés és export szükség szerint újraépül.
A QC továbbra is érvényesül. Kép/mozgás módosításakor az audioterv is újrakészülhet,
így az effektek az új látványhoz igazodnak. A master a még befejezetlen egyéb
jeleneteket is befejezi; a már kész jelenetek médiáját megtartja.

Narrációmódosításnál az adott jelenet hangja és időzítése változhat. Ha emiatt a
teljes videó kikerül az elfogadott időtartományból, a master leáll és az érintett
szöveg javítását kéri; nem írja át automatikusan a többi jelenetet. Az adott
jelenet saját hosszkorlátja miatt helyi szövegrövidítés továbbra is történhet.

## Jelenetszintű zene

A jelenet saját zenéje a `visuals.scenes[].music_override` mezőbe kerül. Külön
ElevenLabs-generálás készül `audio/generated/music/scene_NNN.mp3` fájlba az adott
jelenet tényleges hosszára. Csak az adott idősávban némítjuk az alap háttérzenét;
a jelenetzene rövid be-/kiúszást és narráció alatti hangerőcsökkentést kap.
A többi jelenet továbbra is az alap zenét használja. A rövidebb forrást a keverő
csenddel kitölti, a hosszabbat a jelenet végén levágja. A preflight becslés
figyelembe veszi a jelenetzenék hosszát is.

A műfaj a jelenet saját zenéjéhez is kontextust ad, de a kifejezetten megadott
helyi zenei instrukció elsőbbséget kap az általános hangulati alapértékekkel
szemben. A teljes videó műfaját nem változtatja meg a patch; ehhez új job szükséges.
