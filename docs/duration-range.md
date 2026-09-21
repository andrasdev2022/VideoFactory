# Accepted video duration

`config/video_spec_v1.yaml` is the shared source for timing and final QC:

```yaml
video:
  target_duration_sec: 30
  min_duration_sec: 25
  max_duration_sec: 35
```

The inclusive 25–35 second range accepts a measured 25.25 second job without
rewriting speech or adding holds. Thirty seconds remains the creative target.
The old scene/final target-tolerance environment variables no longer decide
acceptance; change the YAML minimum and maximum instead.

Below the minimum, still-motion can add visual holds up to 25 seconds without
changing speech. Other providers use the existing expansion flow. Above the
maximum, the rewrite planner aims at 35 seconds rather than 30; measured TTS
must then pass the same range. No audio is cut or accelerated. Rewrite validation
can still reject generated text; this change does not guarantee every API reply
will meet its text budget.

Resume recalculates the timing summary from saved scene timings before deciding
whether rewriting is needed, including exhausted jobs now inside the range.
Pending voice remeasurement remains required. Existing asset files are preserved.
Final export validates the measured media duration against these same bounds, allowing at most one output frame above the maximum
for encoder rounding (about 0.033 seconds at 30 fps).

From the main activated virtual environment, resume without creating a new job:

```powershell
$env:VIDEO_PROVIDER = 'still_motion'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force .\logs | Out-Null
$log = ".\logs\duration-range-resume-$stamp.log"
python -u .\src\pipeline_orchestrator.py 2>&1 | Out-File $log -Encoding utf8
$pipelineExit = $LASTEXITCODE
"Exit code: $pipelineExit" | Out-File $log -Encoding utf8 -Append
```

Always preserve `jobs/video_job.json` before switching branches. Do not pass
`--idea` or `--visual-style` when resuming the existing cinematic-realism job.
