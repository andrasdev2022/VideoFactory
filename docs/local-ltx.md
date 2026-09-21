# Local LTX video provider

VideoFactory can generate scene videos locally with LTX-Video instead of
using paid Runway generations.

The first target is a conservative NVIDIA RTX 2070 / 8 GB VRAM baseline.
This is intentionally optimized for memory first, not speed.

## Architecture

The main VideoFactory environment stays lightweight:

```text
.venv/
    VideoFactory orchestration
    OpenAI / ElevenLabs / Runway clients
```

Local LTX runs in a separate CUDA/PyTorch environment:

```text
.venv-ltx/
    PyTorch CUDA
    Diffusers
    Transformers
    Accelerate
    LTX model runtime
```

The Local LTX CUDA runtime remains isolated from the main environment.

Two execution modes are supported:

- benchmark/manual single-scene runs use `src/local_ltx_worker.py` as a
  one-shot subprocess
- the master pipeline starts `src/local_ltx_service.py` once for the
  scene-generation stage and reuses the already-loaded LTX pipeline across
  scene subprocesses through localhost TCP

This keeps the CUDA dependency stack isolated while avoiding repeated model
loads during a full multi-scene job.

## Provider selection

`enter-dev.ps1` defaults to:

```powershell
$env:VIDEO_PROVIDER = "local_ltx"
```

This is intentional so development cannot silently consume Runway credits.

To explicitly use Runway for a session:

```powershell
$env:VIDEO_PROVIDER = "runway"
```

## RTX 2070 baseline

Default Local LTX settings:

```text
model        Lightricks/LTX-Video
resolution   512x896
fps          24
steps        12
guidance     3.0
offload      sequential
dtype        FP16
VAE tiling   enabled
```

Sequential CPU offload is the selected RTX 2070 baseline. Local benchmarking
showed that model offload did not improve end-to-end time and used much more
CUDA memory.

The 12-step baseline was selected after comparing 20, 12, and 8 inference
steps on the target RTX 2070. Eight steps produced unacceptable temporal
breakdown, while 12 steps retained useful visual quality with materially
lower generation time than 20 steps.

## Setup

The setup requires a local Python 3.11 installation and an NVIDIA driver
that supports the selected PyTorch CUDA wheel.

From the repository root:

```powershell
git pull
.\setup-local-ltx.ps1
```

The script:

1. checks `nvidia-smi`
2. creates `.venv-ltx`
3. installs CUDA-enabled PyTorch
4. installs `requirements-ltx.txt`
5. runs a CUDA/dependency preflight

The PyTorch wheel index can be overridden:

```powershell
.\setup-local-ltx.ps1 -TorchIndexUrl "https://download.pytorch.org/whl/cu126"
```

## Non-destructive benchmark

Do not begin with the full pipeline.

Load the normal VideoFactory environment:

```powershell
. .\enter-dev.ps1
```

Check the isolated worker:

```powershell
python src\local_ltx_benchmark.py --preflight
```

Then benchmark one existing scene:

```powershell
python src\local_ltx_benchmark.py --scene 1
```

The benchmark reads the active job but does not modify
`jobs/video_job.json`.

Output:

```text
output/<job_id>/benchmarks/local_ltx_scene_001.mp4
```

For an even shorter first GPU test:

```powershell
python src\local_ltx_benchmark.py --scene 1 --duration 2
```

## First model download

The first real generation downloads the LTX model and its text-encoder
dependencies from Hugging Face. The download is large and model loading
can require substantially more system RAM than GPU VRAM because CPU
offload is enabled.

This benchmark must pass on the target machine before enabling Local LTX
for a complete new job.

## Pipeline integration

After the benchmark is accepted:

```powershell
$env:VIDEO_PROVIDER = "local_ltx"
python src\image_to_video_generator.py --scene 1 --force
```

or run a new full job through the master orchestrator.

For a full master-pipeline run, the orchestrator automatically starts the
persistent Local LTX service before scene generation, waits until the model
is loaded, passes the service endpoint to the scene subprocesses, and shuts
the service down after the scene stage. Manual/benchmark runs fall back to
the one-shot worker when no service endpoint is present.

Provider identity is stored in scene video metadata. A cached Runway
artifact is therefore not reused as a Local LTX cache hit, and vice versa.

Semantic QC retries stay local when `VIDEO_PROVIDER=local_ltx`.

## Prompt token budget

The current Diffusers LTX image-to-video pipeline uses a 128-token prompt
limit. VideoFactory keeps a small safety margin and compacts Local LTX prompts
to at most 120 tokenizer tokens before calling Diffusers.

Initial attempts retain the authored motion followed by continuity notes.
Local LTX retry plans replace the failed action rather than append corrections.
Verbose semantic-QC `overall_notes` and old action-bearing continuity notes
are not copied back into retry prompts. The 120-token worker limit still
applies to both one-shot and persistent-service generation.

## Local LTX motion policy

New visual prompts and `--motion-only` prompts receive Local LTX-specific
instructions: locked camera, one small visible action by one subject, stable
props, and no animated foreground steam/mist. The story's main gag should be
readable in the source image. Existing authored prompts are not silently
rewritten on their initial attempt.

The existing orchestrator attempt budget and fallback sequence are preserved:

| Attempt | Local LTX motion plan |
| --- | --- |
| Initial | Authored motion |
| First semantic retry: motion mismatch only | One small head tilt by the first listed known character |
| First semantic retry: identity, anatomy, visibility, cut, or continuity failure | Small visible breathing movement in place |
| Safe-motion attempt after another failure | Compact minimal-motion plan with a fresh seed |
| Safe-motion attempt fails | Existing deterministic static fallback |

For scenes without a known character, retries request a small in-place subject
movement without assuming human/animal anatomy. These recovery plans prioritize
stable visible characters over reproducing the original complex action; they
can reduce story-specific motion and still require visual review.

Video metadata records `motion_policy_version`, `motion_policy_stage`,
`effective_motion_prompt`, and `requested_prompt` (before worker token fitting).
Semantic QC uses the effective motion for that artifact. Motion, identity,
anatomy, source continuity, and scene-cut failures still fail QC; these generated
retries do not receive the deterministic fallback's `static_hold` waiver.
Runway retains its existing prompt and correction behavior.

Changing a motion-only prompt clears the previous fallback policy and preserves
the approved image. A changed prompt cannot inherit a static-hold QC waiver.

## Retry seeds

The first Local LTX generation uses a deterministic seed derived from the
scene ID. A Local LTX retry increments the previous seed by one. This
makes retries reproducible while still allowing a different generated
motion sample. The last successful Local LTX seed is also stored at scene level,
so safe-motion fallback and motion-only edits can invalidate the video without
resetting the seed sequence. Existing jobs without this field use the seed from
their current Local LTX video when available.

## Validate against an existing job

The baseline `20260920-075808` log reported steam/occlusion in scenes 2 and 3,
and character deformation in scene 5. It also contains token-truncation warnings;
it is not evidence of performance after the prompt-budget fix. Unit tests cannot
establish GPU image quality or guarantee a lower fallback rate.

Before branch changes, back up the authoritative local `jobs/video_job.json`.
Before re-rendering, also copy `output/<job_id>` outside the working output tree
to retain the old videos for comparison. Do not restore a repository job over
the local runtime job.

Run offline tests from the project root in the main `.venv`:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s test -p "test_local_ltx*.py" -v 2>&1 | Out-File .\logs\local-ltx-tests.log -Encoding utf8
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s test -p "test_*.py" -v 2>&1 | Out-File .\logs\unit-tests.log -Encoding utf8
```

Then test one previously failed scene with the real local job and approved image:

```powershell
. .\enter-dev.ps1
$env:VIDEO_PROVIDER = "local_ltx"
python src\visual_prompt_generator.py --scene 2 --motion-only --force
python src\scene_orchestrator.py --scene 2 --reset-attempts --max-video-attempts 3
```

Only run the second command if motion generation succeeds. These commands call
OpenAI for prompt/QC work and generate video on the local GPU. A standalone
scene run uses the one-shot LTX worker unless a persistent service endpoint is
already configured; the master pipeline still owns its persistent service.
Reset attempts only for an intentional new comparison run, not ordinary resume.
Start with scene 2, then repeat for 3 and 5 if the result warrants it. Compare
character visibility, distortion, actual motion, attempt count, and fallback
usage, not just final technical PASS. Keep 512x896, 24 fps, 12 steps, guidance
3.0 and sequential offload fixed for that comparison.

## Failure behavior

Dependency errors, CUDA errors, and out-of-memory errors are not blindly
retried by the provider adapter. They stop the scene so configuration can
be corrected instead of repeating an identical expensive local failure.

A successfully generated video still goes through the existing technical
and semantic QC pipeline.
