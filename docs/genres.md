# Műfajok (genre)

## Mit fogad el a program?

A `config/video_spec_v1.yaml` fájl `content.genre` mezője jelenleg **szabad
szöveges instrukció**, nem előre definiált preset vagy enum. Nincs zárt lista
az engedélyezett értékekről. Az alapérték `absurd_comedy`.

A `src/new_job.py` a `content` konfigurációt átadja a történetgeneráló modellnek.
Az általa visszaadott `IdeaBlueprint.genre` típusa `str`; a generált érték a
`jobs/video_job.json` fájl `idea.genre` mezőjébe kerül. Ez nem garantáltan a YAML
értékének szó szerinti másolata. A forgatókönyvíró is megkapja a `content`
konfigurációt; a zenegenerálás a mentett `idea.genre` értékét használja kontextusként.

Nincs `--genre` CLI-kapcsoló. A műfajt a YAML-ban, új job indítása előtt lehet
megadni. Angol, egyértelmű megnevezés vagy rövid angol leírás ajánlott.

## Példák megadható értékekre

Az alábbiak **javasolt promptértékek, nem implementált vagy külön tesztelt
műfajpresetek**. Más megnevezés is használható.

| Érték | Jelentés / történetirány |
| --- | --- |
| `absurd_comedy` | Abszurd humor, képtelen helyzetek, váratlan poén |
| `comedy` | Könnyed, humoros történet |
| `romantic_comedy` | Romantikus közeledés humoros konfliktussal |
| `romance` | Érzelmi kapcsolat, gyengéd vagy megható történet |
| `drama` | Komoly konfliktus és érzelmi következmények |
| `melancholic_drama` | Emlékek, veszteség, visszafogott szomorúság |
| `fantasy` | Kitalált világ, mágia, természetfeletti elemek |
| `dark_fantasy` | Komor fantasy, baljós világ és hangulat |
| `adventure` | Felfedezés, akadályok és rövid kaland |
| `mystery` | Rejtély és annak feloldása |
| `thriller` | Feszültség, fenyegetés, fordulat |
| `horror` | Félelemkeltő történet és atmoszféra |
| `science_fiction` | Technológiai vagy futurisztikus alapötlet |
| `historical_fiction` | Történelmi környezetű fikció; nem tényellenőrzés |
| `slice_of_life` | Hétköznapi élethelyzet, apró emberi pillanat |
| `inspirational` | Bátorító történet, kitartás vagy remény |

## Műfaj és képi stílus

A két beállítás külön célt szolgál:

- `content.genre`: miről és milyen történetként mesélünk.
- `--visual-style`: hogyan nézzenek ki a szereplők és a jelenetek.

Például a `melancholic_drama` műfaj használható `anime` vagy
`cinematic_realism` vizuális presettel is. Az `anime` önmagában nem írja felül
az `absurd_comedy` történetirányt. A vizuális preseteket a
[visual-styles.md](visual-styles.md) dokumentálja.

## Jelenlegi korlátok

A pipeline több része még a rövid, humoros videókhoz igazodik:

- A YAML `content.style` alapértéke `fast_paced`; az escalation célja
  `increase absurdity/conflict`, a payoff célja `unexpected ending or punchline`.
- Az alap vizuális leírás `colorful surreal comedy, exaggerated expressions`.
  Egy explicit vizuális preset a képi stílust felülírja.
- Az alap narrációstílus `energetic`.
- A `src/new_job.py` történetsémájában kötelező a `core_joke` mező.
- A `src/script_generator.py` rendszerpromptja a core joke megőrzését, gyors
  tempót és payoff/punchline lezárást kér.
- A `src/audio_asset_generator.py` zenei promptja rögzítetten tartalmazza a
  `light, playful, polished` instrukciót. Hiányzó műfajnál a fallback
  `short-form comedy`.
- A bootstrap hashtag-kiegészítése szükség esetén `#funny` címkét is használ.

Ezért a műfaj átírása befolyásolja a generálást, de **nem garantál teljes
műfajváltást a pipeline minden szakaszában**. A komoly drámai történetek
következetes támogatásához későbbi, műfajfüggő promptkezelés szükséges.

## Példa: az esőben álló idős lovag

Új job előtt a meglévő YAML megfelelő mezőit lehet például így módosítani
(ez részlet, nem a teljes konfiguráció helyettesítője):

```yaml
content:
  genre: "melancholic_drama"
  style: "reflective, restrained, emotionally grounded"
  structure:
    escalation:
      duration_sec: 12
      purpose: "deepen the emotional conflict through memories"
    payoff:
      duration_sec: 6
      purpose: "resolve the emotional arc with a quiet moment of hope"

audio:
  voiceover:
    style: "calm, reflective"
```

A többi meglévő kulcsot őrizd meg. Az ötlet is legyen összhangban a műfajjal,
például: “An elderly knight stands in the rain atop a ruined castle, remembering
lost companions. A solemn, bittersweet story ending in quiet hope; no comedy.”
Az `anime` vizuális preset ettől függetlenül választható. A fenti rögzített
promptkorlátok ennél a példánál is érvényesek.

A már létrehozott jobot a YAML átírása nem alakítja át visszamenőleg:
a korábban generált történet, szöveg és média megmarad. Egyes későbbi szakaszok
újraolvassák a konfigurációt, ezért futó job közben ne válts műfajt. Előbb fejezd
be a jobot, majd készíts mentést az authoritative `jobs/video_job.json` fájlról,
és az új beállítással indíts új jobot `--idea` használatával.
