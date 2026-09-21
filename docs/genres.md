# Műfaj és a teljes videó hangvétele

A `config/video_spec_v1.yaml` fájlban a `content.genre` határozza meg az új videó
műfaját. Szabad szöveges mező; nincs `--genre` CLI-kapcsoló.

```yaml
content:
  genre: "tragedy"
```

A műfaji instrukciót megkapja a történetgeneráló, a forgatókönyvíró, az időzítés
miatti szövegátírók, a vizuális és karakterprompt-generáló, a képgeneráló,
a narrációgeneráló, a zenei tervező és a zenegeneráló. A hangeffektek instrukciója
műfajsemleges, a tervezésük az adott történethez igazodik.

A kód nem ír elő minden történetre poént, gyors tempót vagy játékos zenét.
A nem komikus műfajoknál a régi YAML ismert komédia-alapértékei (fast_paced,
abszurd escalation/punchline, colorful surreal comedy, energetic narráció)
a job létrehozásakor műfajhoz illő általános instrukcióvá alakulnak. Az eredeti
YAML fájl nem módosul. A régi `core_joke` mező kompatibilitási okból megmarad,
nem komikus műfajnál üres. A hashtag-kiegészítés nem erőltet `#funny` címkét.

## Értékek

| Érték | Beépített műfaji irány |
| --- | --- |
| `absurd_comedy` | Abszurd fokozás, poén, játékos zene |
| `comedy` | Karakterekből fakadó humor |
| `romantic_comedy` | Romantika könnyed humorral |
| `romance` | Őszinte érzelmi kapcsolat, gyengéd zene, erőltetett poén nélkül |
| `drama` | Komoly konfliktus és érzelmi következmények |
| `melancholic_drama` | Emlékek, veszteség, visszafogott, keserédes hangulat |
| `tragedy` | Visszafordíthatatlan veszteség, komor narráció és zene, komikus feloldás nélkül |
| `horror` | Félelem és baljós atmoszféra |
| `thriller` | Fokozódó feszültség és suspense |
| `dark_fantasy` | Komor fantasztikus történet |

Más érték is használható, például `fantasy`, `adventure`, `mystery`,
`science_fiction`, `historical_fiction`, `slice_of_life`, `inspirational`.
Ezeknél a modell a műfaj nevét kapja meg, közös instrukcióval a következetes
hangvételre. Angol megnevezés ajánlott. A felsorolt irányok kreatív instrukciók,
nem garantálják minden generált válasz művészi minőségét.

## Műfaj és vizuális stílus

A `--visual-style anime` a rajzi megjelenést, a `genre: tragedy` a történet és
hangulat jellegét szabályozza. Együtt is használhatók. Egy explicit vizuális
preset felülírja a YAML képi médiumra vonatkozó alapleírását, de nem a műfajt.
A stílusleírásba konkrét képi jellemzőket írj, például:

```yaml
visual:
  style:
    style_description: >
      somber cinematic imagery, muted colors, restrained expressions,
      dramatic shadows, rain-soaked environments
```

Lásd: [visual-styles.md](visual-styles.md).

## Mentett konfiguráció és folytatás

Az új job `creative_direction.genre` mezője és `spec_snapshot` konfigurációja
rögzíti a választást. A `job.idea.genre` a konfigurált műfajjal egyezik.
A későbbi gyártási lépések és a folytatás a mentett konfigurációt használják:
a YAML átírása a következő új videóra vonatkozik. Az API-kulcsok, providerek és
modellek környezeti változói nem részei a snapshotnak.

Régi, snapshot nélküli jobok továbbra is a YAML-t olvassák; meglévő médiát nem
migrálunk vagy generálunk újra automatikusan. Teljes műfajváltáshoz új jobot
indíts `--idea` használatával, az aktív job előzetes mentése után.

Egyetlen jelenet módosításához: [scene-editing.md](scene-editing.md).
