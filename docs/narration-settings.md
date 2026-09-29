# Narráció beállításai

A VideoFactory az OpenAI Speech API-val készíti a jelenetenkénti narrációt.
A fő beállítások a `config/video_spec_v1.yaml` fájlban találhatók:

```yaml
audio:
  voiceover:
    required: true
    gender: "any"
    model: "gpt-4o-mini-tts"
    voice: "marin"
    style: "warm, gentle and intimate storytelling"
    instructions: >-
      Use subtle affection and soft expressive intonation.
      Keep clear articulation and natural pauses.
      Avoid theatrical exaggeration.
    speed: 1.0
    response_format: "wav"
```

## Értékek és hatásuk

| Mező | Érték / alapérték | Hatás |
| --- | --- | --- |
| `model` | `gpt-4o-mini-tts` (alap), `gpt-4o-mini-tts-2025-12-15`, `tts-1`, `tts-1-hd` | Beszédgeneráló modell. Az instrukcióvezérléshez GPT-4o mini TTS kell. |
| `voice` | Alap: `marin`; a hanglista lent | A narrátor alaphangja. Nem a történetbeli karakter neve. |
| `style` | Szabad szöveg; hiányában `energetic` | Általános előadásmód; pl. `calm documentary narration`, `warm storytelling`, `dramatic and restrained`. A műfaji szabályok is bekerülnek az instrukcióba. |
| `instructions` | Szabad szöveg, alap: üres | Kiegészítő előadói instrukciók: tónus, érzelem, akcentus, hangsúly, szünetek, suttogás. Nem felolvasandó szöveg. |
| `speed` | Szám **0.25–4.0**, alap: **1.0** | 1.0 normál, 0.9 lassabb, 1.1 gyorsabb. A régi `"natural"` érték továbbra is 1.0-t jelent. Nem pontos videóhossz-előírás. |
| `response_format` | `wav` (alap), `mp3`, `opus`, `aac`, `flac` | A jelenetenként mentett hang formátuma. A WAV egyszerű, tömörítetlen munkaforrás. |
| `gender` | Meglévő kompatibilitási mező | Nem választ hangot; nincs ilyen külön Speech API-paraméter. A `voice` és a hangminták alapján válassz. |
| `required` | Maradjon `true` | A jelenlegi pipeline narrációra és annak mért időzítésére épül. A narráció nélküli pipeline nincs ezzel a változtatással megvalósítva. |

A nyelvet a `video.language` adja, például `en` vagy `hu`. A felolvasott szöveg
legyen azonos nyelvű. Az instrukció nem fordítja át a narrációt.

Az API nyers `pcm` kimenetet is támogat, de ez a pipeline nem engedi: a fejléc
nélküli hanghoz külön formátumleírás kellene az automatikus QC és időmérés során.
Ismeretlen modell/hang, nem megfelelő modell–hang párosítás, hibás sebesség vagy
túl hosszú instrukció esetén a program a beszédgenerálási API-hívás előtt leáll.
A teljes összeállított instrukció legfeljebb 4096 karakter lehet.

## Hangok és modellek

GPT-4o mini TTS hangok:

`alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`,
`shimmer`, `verse`, `marin`, `cedar`.

Az OpenAI minőségi ajánlása `marin` vagy `cedar`. A megfelelő hangot érdemes
meghallgatni; a program nem rendel automatikusan nemet a hangnevekhez.

A `tts-1` és `tts-1-hd` támogatott hangjai:
`alloy`, `ash`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`.
Ezeknél az `instructions` legyen üres, különben a program hibát jelez. A `style`
és a műfaji előadói instrukció nem kerül továbbításra ezeknek a modelleknek.
A `gpt-4o-mini-tts-2025-12-15` dátumozott modellváltozat; az elérhetőséget az
API-fiók és a szolgáltató aktuális modellkínálata is meghatározza.

Saját feltöltött hang / hangklónozás nincs bekötve. Jelenleg minden jelenet
ugyanazt a narrátort használja; szereplőnként eltérő dialógushang nincs.

## Elsőbbség és mentett konfiguráció

A modell, hang és fájlformátum feloldási sorrendje:

1. Nem üres környezeti változó: `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`, `OPENAI_TTS_FORMAT`.
2. A job konfigurációjának megfelelő YAML-mezője.
3. A fenti alapérték.

A sebességhez nincs környezeti felülírás. Ha teljesen YAML-ból szeretnéd vezérelni
a narrációt, az `.env.local` megfelelő felülírásait töröld vagy hagyd üresen.
Az `enter-dev.ps1` betöltheti ezeket, ezért a környezeti beállításokat utána vizsgáld.

Új job a YAML-t a `spec_snapshot` mezőbe menti. Meglévő job a snapshotját használja;
a YAML későbbi változása nem módosítja automatikusan a kész videó narrációját.
Snapshot nélküli régi job az aktuális YAML-ra támaszkodik. Ez eltér az SFX-kapcsoló
külön dokumentált, élő YAML-tiltásától.

## Meglévő videó narrációjának módosítása

Előbb mentsd a `jobs/video_job.json` fájlt és az `output/<job_id>` mappát.
A mentett job `spec_snapshot.audio.voiceover` részében változtasd a kívánt
beállítást. Az `audio.voiceover` összesítő vagy a jelenetek `voice` eredményeinek
kézi átírása önmagában nem állítja át a generátort. A korábbi eredményeket ne
jelöld át kézzel sikeresre.

Ezután a master `--idea` nélkül folytatható, UTF-8 naplózással:

```powershell
. .\enter-dev.ps1
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\narration-resume-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
python -u .\src\pipeline_orchestrator.py 2>&1 |
    Out-File $log -Encoding utf8
$runExitCode = $LASTEXITCODE
"Exit code: $runExitCode" | Out-File $log -Encoding utf8 -Append
Get-Content $log -Encoding utf8 -Tail 40
```

A cache a modellt, hangot, sebességet, formátumot, tényleges instrukciókat és
felolvasandó szöveget is összehasonlítja. Változáskor új TTS-hívás történik;
az új hangot QC és időmérés követi. A már elfogyott narrációs próbálkozási keret
nem nullázódik automatikusan. Ilyenkor az adott jelenetre futtasd a
`voice_orchestrator.py --scene N --reset-attempts` parancsot azonos naplózással,
majd folytasd a mastert. Ne használj `--idea` kapcsolót, mert az új jobot indít.

Az új narráció miatt az érintett jelenet videója és a függő összeállítás,
felirat, audioterv, mix és export új feldolgozást igényel. A kép megmarad,
ha a supervisor jóváhagyása és a vizuális követelmények ezt lehetővé teszik.
Ez nem csupán helyi hangerő-remix: új narráció és esetleg további generálás is
API-költséggel járhat. A pipeline nem gyorsítja automatikusan a hangot a
határidő kedvéért; a kiválasztott sebességnél mért hossz alapján dönt a szöveg
rövidítéséről vagy a vizuális kitartásról.

## Példák

- Romantikus: `style: "warm, intimate, tender storytelling"`, `speed: 0.95`.
- Ismeretterjesztő: `style: "clear, calm documentary narration"`, `speed: 1.0`.
- Lendületes: `style: "bright, upbeat and engaging"`, `speed: 1.05`.

Az instrukciók modellnek adott iránymutatások, nem garantált akusztikai értékek.
A tempót és érzelmi intenzitást hallgasd meg; új TTS-futásnál a pontos hossz is
változhat. A hangmagassághoz nincs külön numerikus paraméter.

## Hivatalos források

Ellenőrizve: 2026-09-29.

- [OpenAI Text to speech útmutató és hangminták](https://developers.openai.com/api/docs/guides/text-to-speech)
- [Speech API-paraméterek](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
