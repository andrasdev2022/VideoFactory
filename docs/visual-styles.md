# Visual style presets

Use `--visual-style NAME` with `--idea` in `pipeline_orchestrator.py` or `new_job.py`.
The preset is saved in `job.style.preset` and applied to bootstrap, character
reference prompts, scene prompts, and actual image generation requests. It is
independent of `VIDEO_PROVIDER`: Runway, Local LTX and still-motion use the same
image-style selection. Thumbnail rendering reuses the styled source image.

| Name | Appearance |
| --- | --- |
| `default` (or omitted) | Existing spec and idea-driven behavior |
| `photorealistic` | Natural photography, realistic skin/materials and proportions |
| `cinematic_realism` | Live-action film still, natural proportions, cinematic light |
| `animation_3d` | Stylized dimensional animated-film rendering |
| `cartoon_2d` | Clean outlines, simplified shapes and flat colors |
| `anime` | Anime linework, cel shading and painted backgrounds |
| `watercolor` | Translucent washes, paper texture and soft edges |
| `comic` | Bold ink, graphic shadows; no lettering or speech bubbles |
| `storybook` | Detailed painted storybook illustration |

These are prompt presets, not separate image models or guaranteed styles.
The explicit preset takes priority over conflicting visual-medium/realism words
in the idea and shared YAML defaults. Lighting, palette, and story details can
still be specified in the idea. No celebrity/content rules are changed.

Resume without `--idea` uses the saved style. Supplying `--visual-style` during
resume is rejected before running the pipeline to avoid mixing existing assets
with a new style. Existing jobs without a preset keep legacy behavior. Changing
an existing video's style is not supported by this option: start a new job,
which requires fresh character and scene image generation.

## New cinematic-realism video (PowerShell)

From the repo root, with the main `.venv` activated and API configuration loaded:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\jobs\video_job.json "..\video_job-before-style-$stamp.json"
$env:VIDEO_PROVIDER = 'still_motion'
$env:STILL_MOTION_MODE = 'zoom'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\cinematic-realism-$stamp.log"
python -u .\src\pipeline_orchestrator.py --visual-style cinematic_realism --idea "Two adults meet over the last croissant in a Parisian cafe. Warm, understated romance, natural faces, amber cafe light and blue rainy streets." 2>&1 | Out-File $log -Encoding utf8
$pipelineExit = $LASTEXITCODE
"Exit code: $pipelineExit" | Out-File $log -Encoding utf8 -Append
```

For a script-stage review, use `--stop-after script` on the master pipeline.
To resume the new job, omit both `--idea` and `--visual-style`.

## Tests

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s test -p 'test_*.py' -v 2>&1 | Out-File .\logs\visual-style-tests.log -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; see logs\visual-style-tests.log' }
```
