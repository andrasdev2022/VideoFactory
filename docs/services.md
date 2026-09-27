# A VideoFactory által használt szolgáltatások

A folyamatot helyben futó Python-programok vezérlik. Egyes fázisok internetes API-t hívnak, mások a számítógépre telepített alkalmazásokat és Python-csomagokat használják.

## Fázisonkénti áttekintés

| Fázis | Szolgáltató vagy helyi eszköz | Feladat |
| --- | --- | --- |
| Indulási ellenőrzés (preflight) | OpenAI, ElevenLabs; Runway, ha azt választottuk | API-hozzáférés, illetve az elérhető keretadatok ellenőrzése. |
| Forgatókönyv és szükséges szövegjavítások | OpenAI szöveges API | Az ötletből narráció és jelenetterv készítése, szükség esetén a szöveg hosszának javítása. |
| Narráció | OpenAI TTS | A narráció szövegének beszédhanggá alakítása. |
| Narráció ellenőrzése és jelenetidőzítés | Helyi Python és ffprobe | A hang technikai vizsgálata és a jelenethosszak kiszámítása. |
| Kép-, mozgás- és karakterreferencia-promptok | OpenAI szöveges API | A képgeneráláshoz és a jelenetek mozgatásához szükséges leírások elkészítése. |
| Karakterreferenciák és jelenetképek | OpenAI Images API | A képek generálása. |
| Képek technikai és tartalmi ellenőrzése | Helyi Pillow; OpenAI képfelismerés | A Pillow ellenőrzi a képfájlt és méreteit; az OpenAI a jelenet tartalmát és vizuális megfelelőségét. |
| Jelenetvideók készítése | A választott videómód, lásd alább | Az állóképekből videók készítése. |
| Videók technikai és tartalmi ellenőrzése | ffprobe, FFmpeg; OpenAI képfelismerés | Technikai adatok vizsgálata, mintaképkockák kinyerése és tartalmi ellenőrzése. |
| Vágás és alapvideó összeállítása | Helyi FFmpeg és ffprobe | Jelenetek hosszának igazítása, összefűzés és a narráció hozzáadása. |
| Feliratok | Helyi Python és FFmpeg | SRT/ASS felirat készítése, majd beégetése. Az időzítés szövegalapú becslés; ehhez nincs külön beszédfelismerő szolgáltatás. |
| Zene- és hangeffektterv | OpenAI szöveges API | A zenei hangulat és a hangeffektek megtervezése. |
| Zene és hangeffektek generálása | ElevenLabs API | Háttérzene, hangeffektek és bekapcsolás esetén jelenetenkénti zene készítése. |
| Végső hangkeverés | Helyi FFmpeg és ffprobe | Narráció, zene és effektek keverése, hangerők és átmenetek kezelése. |
| Borítókép (thumbnail) | Helyi Pillow és telepített betűkészlet | Meglévő jelenetképből feliratos borító készítése. |
| Végső ellenőrzés és export | Helyi Python és ffprobe | A kész videó ellenőrzése és az exportfájlok összeállítása. Ez nem jelent automatikus közzétételt. |

## Választható videómódok

A módot a `VIDEO_PROVIDER` környezeti változó választja ki.

| Érték | Hol fut, mit igényel? | Működés |
| --- | --- | --- |
| `still_motion` | Helyben, FFmpeg segítségével | Állóképből finom közelítést vagy kitartott képet készít. Ehhez a fázishoz nem kell Runway vagy LTX. |
| `local_ltx` | Helyben, külön `.venv-ltx` környezetben; NVIDIA GPU, megfelelő driver, CUDA-képes PyTorch, Diffusers és Transformers | A Lightricks LTX-Video modell generál mozgást. Az első generáláskor a modell és függőségei a Hugging Face-ről töltődnek le. A teljes pipeline a helyi LTX-szolgáltatást automatikusan indítja és állítja le. |
| `runway` | Runway felhőszolgáltatás, API-kulcs és kredit | A jelenetvideót a Runway API generálja. |

Az `enter-dev.ps1` jelenleg `local_ltx` értéket állít be, ha a `VIDEO_PROVIDER` még nincs megadva. A still motion módhoz az indító betöltése után add ki:

```powershell
$env:VIDEO_PROVIDER = "still_motion"
```

A `still_motion` csak a jelenetvideók készítését teszi helyivé. A teljes generálás többi fázisa továbbra is használ OpenAI- és ElevenLabs-szolgáltatásokat.

## Szükséges hozzáférések és telepítések

- **OpenAI:** `OPENAI_API_KEY` a szöveg-, kép-, beszédgeneráláshoz és tartalmi ellenőrzéshez.
- **ElevenLabs:** `ELEVENLABS_API_KEY` a zene és hangeffektek generálásához.
- **Runway:** `RUNWAYML_API_SECRET`, csak a Runway videómódhoz.
- **Helyi alapkörnyezet:** Python virtuális környezet (`.venv`), a [requirements.txt](../requirements.txt) csomagjai, valamint elérhető `ffmpeg` és `ffprobe`. A feliratbeégetéshez ASS/libass-támogatású FFmpeg és megfelelő betűkészlet szükséges.
- **Csak helyi LTX esetén:** a [setup-local-ltx.ps1](../setup-local-ltx.ps1) által létrehozott külön környezet és a [requirements-ltx.txt](../requirements-ltx.txt) csomagjai.

A kulcsokat az `enter-dev.ps1` a helyi `.env.local` fájlból tölti be. A szolgáltatások modelljeit és további beállításait az indító és a megfelelő Python-modulok környezeti változói szabályozzák. Az API-hívások szolgáltatói díjjal vagy kreditfogyasztással járhatnak; az újragenerálások és ellenőrzési ismétlések további hívásokat indíthatnak.

Részletek: [Still motion](still-motion.md), [Local LTX](local-ltx.md), [szolgáltatási preflight](service-preflight.md).
