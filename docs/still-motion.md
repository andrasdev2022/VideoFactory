# Still-motion video provider

Set `VIDEO_PROVIDER=still_motion` to render scene videos from their approved
images with CPU FFmpeg. No Local LTX service, GPU, LTX environment or Runway
generation is used. OpenAI image/text/voice/QC and ElevenLabs music/SFX stages
still run normally and can incur API charges.

Options (set after `enter-dev.ps1`):

```powershell
$env:VIDEO_PROVIDER = "still_motion"
$env:STILL_MOTION_MODE = "zoom"       # zoom (default) or hold
$env:STILL_MOTION_MAX_ZOOM = "1.05"   # 1.0 through 1.08; ignored in hold mode
```

Output is H.264, 720x1280, 24 fps. Duration is rounded up to a whole frame.
Zoom is centered and linear, starting at 1.0x. The image is scaled to cover the
portrait canvas without stretching. Non-matching aspect ratios are cropped.
New image prompts request edge margin, but this is not a guarantee: QC still
checks faces and subject visibility. Pan is intentionally not offered yet.

This provider is deliberate camera-only animation, not a failure fallback.
QC uses the effective camera-motion prompt. Zoom still requires a motion match;
hold permits a static frame sequence. Independent character action is never
required. Anatomy, identity and composition checks remain enabled. A failed
semantic check stops the scene for review instead of rerendering the same
deterministic clip. Each scene writes `scene_NNN.still-motion.log` alongside its
video. A failed render does not replace the previous video.

## New end-to-end job

Before changing branches, preserve the authoritative local `jobs/video_job.json`
outside the repository. Never force a checkout or reset over local changes.
Keep that backup even though `new_job` also archives the previous active job.

After loading `enter-dev.ps1` and setting the three variables above:

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$pipelineLog = ".\logs\still-motion-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
python -u .\src\pipeline_orchestrator.py --idea "A tiny puppy tries to run a luxury spa for a grumpy kitten." 2>&1 |
    Out-File -FilePath $pipelineLog -Encoding utf8
$pipelineExit = $LASTEXITCODE
"Exit code: $pipelineExit" | Out-File $pipelineLog -Encoding utf8 -Append
Write-Host "Exit code: $pipelineExit; log: $pipelineLog"
```

This creates a NEW job, not a rerender of the old job. To resume an interrupted
still-motion job, use the same provider/settings and omit `--idea`. Switching
providers on an already-completed job is not an automatic migration: existing
stage-completion markers may skip work. Use a new job for this first E2E test.

Return to LTX with `$env:VIDEO_PROVIDER = "local_ltx"` before starting another
new job. The environment loader preserves an explicitly selected provider.

## Offline tests

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s test -p "test_still_motion_provider.py" -v 2>&1 |
    Out-File .\logs\still-motion-unit.log -Encoding utf8
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s test -p "test_*.py" -v 2>&1 |
    Out-File .\logs\all-unit-tests.log -Encoding utf8
```

The renderer integration test uses synthetic images and real FFmpeg/ffprobe
when installed. It calls no AI APIs. A complete live E2E still needs to run
on the configured Windows machine.

## Narration shorter than the accepted minimum

Still-motion jobs with approved voice QC can reach the configured minimum duration
using visual holds after narration. The existing audio, text, and speaking speed
are preserved; the assembler pads the voice track with silence while background
music continues. Extra time is distributed equally across scenes, redistributing
any excess when a scene reaches its configured maximum duration.

This recovery also runs for an existing job whose global rewrite attempts are
exhausted. It does not reset that counter or call text/TTS services. Resume the
master pipeline without `--idea`. Other providers retain their existing rewrite
policy. Long narration, incomplete/stale timing, pending voice remeasurement,
insufficient scene capacity, and jobs with generated scene videos are not padded.
Final duration can differ by frame rounding.

PowerShell resume, with consistent UTF-8 logging (main `.venv`, repository root):

```powershell
$env:VIDEO_PROVIDER = 'still_motion'
New-Item -ItemType Directory -Force .\logs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = ".\logs\still-motion-resume-$stamp.log"
python -u .\src\pipeline_orchestrator.py 2>&1 | Out-File $log -Encoding utf8
$pipelineExit = $LASTEXITCODE
"Exit code: $pipelineExit" | Out-File $log -Encoding utf8 -Append
```
