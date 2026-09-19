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

## Retry seeds

The first Local LTX generation uses a deterministic seed derived from the
scene ID. A Local LTX retry increments the previous seed by one. This
makes retries reproducible while still allowing a different generated
motion sample.

## Failure behavior

Dependency errors, CUDA errors, and out-of-memory errors are not blindly
retried by the provider adapter. They stop the scene so configuration can
be corrected instead of repeating an identical expensive local failure.

A successfully generated video still goes through the existing technical
and semantic QC pipeline.
