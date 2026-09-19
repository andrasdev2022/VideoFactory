# ============================================================
# VIDEO FACTORY - DEVELOPMENT ENVIRONMENT
# ============================================================

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Stop"

# Keep Python/native-process output Unicode-safe when piped through
# Tee-Object or redirected to log files on Windows PowerShell.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# ------------------------------------------------------------
# PROJECT ROOT
# ------------------------------------------------------------

$ProjectRoot = $PSScriptRoot

Set-Location $ProjectRoot

Write-Host ""
Write-Host "============================================================"
Write-Host " VIDEO FACTORY - DEVELOPMENT ENVIRONMENT"
Write-Host "============================================================"
Write-Host ""

Write-Host "Project:"
Write-Host "  $ProjectRoot"
Write-Host ""


# ------------------------------------------------------------
# PYTHON VIRTUAL ENVIRONMENT
# ------------------------------------------------------------

$ActivateScript = Join-Path `
    $ProjectRoot `
    ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $ActivateScript)) {

    Write-Host "ERROR: Python virtual environment not found:"
    Write-Host "  $ActivateScript"

    $ErrorActionPreference = $PreviousErrorActionPreference
    return
}

Write-Host "Activating Python virtual environment..."

. $ActivateScript


# ------------------------------------------------------------
# LOAD .env.local
# ------------------------------------------------------------

$EnvFile = Join-Path `
    $ProjectRoot `
    ".env.local"

if (-not (Test-Path $EnvFile)) {

    Write-Host ""
    Write-Host "ERROR: .env.local not found:"
    Write-Host "  $EnvFile"
    Write-Host ""

    $ErrorActionPreference = $PreviousErrorActionPreference
    return
}

Write-Host "Loading secrets from .env.local..."

Get-Content $EnvFile | ForEach-Object {

    $Line = $_.Trim()

    # Ignore empty lines
    if ([string]::IsNullOrWhiteSpace($Line)) {
        return
    }

    # Ignore comments
    if ($Line.StartsWith("#")) {
        return
    }

    $Parts = $Line -split "=", 2

    if ($Parts.Count -ne 2) {
        return
    }

    $Name = $Parts[0].Trim()
    $Value = $Parts[1].Trim()

    if (
        $Value.StartsWith('"') -and
        $Value.EndsWith('"')
    ) {
        $Value = $Value.Substring(
            1,
            $Value.Length - 2
        )
    }

    [Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        "Process"
    )
}


# ------------------------------------------------------------
# OPENAI TEXT MODEL
# ------------------------------------------------------------

$env:OPENAI_MODEL = "gpt-5.6-luna"


# ------------------------------------------------------------
# OPENAI IMAGE GENERATION
# ------------------------------------------------------------

$env:OPENAI_IMAGE_MODEL = "gpt-image-2.5-flare"

# During development keep this cheap.
$env:OPENAI_IMAGE_QUALITY = "low"

$env:OPENAI_CHARACTER_REFERENCE_SIZE = "1024x1536"

$env:OPENAI_SCENE_IMAGE_SIZE = "1008x1792"


# ------------------------------------------------------------
# OPENAI VISION / SEMANTIC QC
# ------------------------------------------------------------

$env:OPENAI_VISION_MODEL = "gpt-5.6-luna"

$env:OPENAI_VISION_DETAIL = "high"


# ------------------------------------------------------------
# VIDEO PROVIDER
# ------------------------------------------------------------

# Protect Runway credits by default. Set this to "runway" explicitly
# if you intentionally want to use the paid Runway provider.
$env:VIDEO_PROVIDER = "local_ltx"

# Local LTX baseline for RTX 2070 / 8 GB VRAM.
$env:LOCAL_LTX_PYTHON = Join-Path $ProjectRoot ".venv-ltx\Scripts\python.exe"
$env:LOCAL_LTX_WORKER = Join-Path $ProjectRoot "src\local_ltx_worker.py"
$env:LOCAL_LTX_SERVICE = Join-Path $ProjectRoot "src\local_ltx_service.py"
$env:LOCAL_LTX_MODEL_ID = "Lightricks/LTX-Video"
$env:LOCAL_LTX_WIDTH = "512"
$env:LOCAL_LTX_HEIGHT = "896"
$env:LOCAL_LTX_FPS = "24"
$env:LOCAL_LTX_INFERENCE_STEPS = "12"
$env:LOCAL_LTX_GUIDANCE_SCALE = "3.0"
$env:LOCAL_LTX_SEED_BASE = "171198"
$env:LOCAL_LTX_TIMEOUT_SEC = "7200"
$env:LOCAL_LTX_SERVER_START_TIMEOUT_SEC = "300"
$env:LOCAL_LTX_OFFLOAD_MODE = "sequential"


# ------------------------------------------------------------
# RUNWAY VIDEO (explicit opt-in provider)
# ------------------------------------------------------------

$env:RUNWAY_VIDEO_MODEL = "gen4_turbo"

$env:RUNWAY_VIDEO_RATIO = "720:1280"

$env:RUNWAY_TASK_TIMEOUT_SEC = "600"

$env:SCENE_TRIM_DURATION_TOLERANCE_SEC = "0.08"
$env:SCENE_TRIM_CRF = "18"
$env:SCENE_TRIM_PRESET = "medium"

$env:BASE_ASSEMBLY_DURATION_TOLERANCE_SEC = "0.15"
$env:BASE_ASSEMBLY_CRF = "16"
$env:BASE_ASSEMBLY_PRESET = "medium"
$env:BASE_ASSEMBLY_AUDIO_SAMPLE_RATE = "48000"
$env:BASE_ASSEMBLY_AUDIO_BITRATE = "192k"

$env:LOCAL_VIDEO_FALLBACK_WIDTH = "720"
$env:LOCAL_VIDEO_FALLBACK_HEIGHT = "1280"
$env:LOCAL_VIDEO_FALLBACK_FPS = "24"
$env:LOCAL_VIDEO_FALLBACK_CRF = "18"
$env:LOCAL_VIDEO_FALLBACK_PRESET = "medium"
$env:LOCAL_VIDEO_FALLBACK_MAX_ZOOM = "1.025"

$env:SUBTITLE_FONT_SIZE = "72"
$env:SUBTITLE_MARGIN_V = "320"
$env:SUBTITLE_OUTLINE = "4"
$env:SUBTITLE_SHADOW = "1"
$env:SUBTITLE_VIDEO_CRF = "16"
$env:SUBTITLE_VIDEO_PRESET = "medium"
$env:SUBTITLE_DURATION_TOLERANCE_SEC = "0.15"

$env:FINAL_MIX_AUDIO_SAMPLE_RATE = "48000"
$env:FINAL_MIX_AUDIO_BITRATE = "192k"
$env:FINAL_MIX_MUSIC_FADE_SEC = "0.50"
$env:FINAL_MIX_DUCK_THRESHOLD = "0.02"
$env:FINAL_MIX_DUCK_RATIO = "8.0"
$env:FINAL_MIX_DUCK_ATTACK_MS = "20"
$env:FINAL_MIX_DUCK_RELEASE_MS = "250"
$env:FINAL_MIX_DURATION_TOLERANCE_SEC = "0.15"

$env:ELEVENLABS_API_BASE_URL = "https://api.elevenlabs.io"
$env:ELEVENLABS_MUSIC_MODEL = "music_v2_5"
$env:ELEVENLABS_SFX_MODEL = "eleven_text_to_sound_v2"
$env:ELEVENLABS_MUSIC_OUTPUT_FORMAT = "mp3_48000_192"
$env:ELEVENLABS_SFX_OUTPUT_FORMAT = "mp3_44100_128"
$env:ELEVENLABS_HTTP_TIMEOUT_SEC = "300"
$env:ELEVENLABS_SFX_DEFAULT_DURATION_SEC = "1.5"
$env:ELEVENLABS_SFX_PROMPT_INFLUENCE = "0.5"
$env:ELEVENLABS_SFX_MAX_PROMPT_CHARS = "430"

$env:FINAL_QC_FPS_TOLERANCE = "0.05"
$env:FINAL_QC_TARGET_DURATION_TOLERANCE_SEC = "4.0"
$env:FINAL_QC_AUDIO_SAMPLE_RATE = "48000"


# ------------------------------------------------------------
# IMAGE QC
# ------------------------------------------------------------

$env:IMAGE_QC_MIN_FILE_SIZE_BYTES = "20000"

$env:IMAGE_QC_ASPECT_RATIO_TOLERANCE = "0.02"

$env:IMAGE_QC_MIN_LUMINANCE_STDDEV = "2.0"

$env:IMAGE_SEMANTIC_QC_LOW_CONFIDENCE = "0.70"


# ------------------------------------------------------------
# CHECK PYTHON
# ------------------------------------------------------------

Write-Host ""
Write-Host "Checking Python..."

$PythonVersion = python --version

Write-Host "  $PythonVersion"

$PythonPath = (
    where.exe python |
    Select-Object -First 1
)

Write-Host "  $PythonPath"


# ------------------------------------------------------------
# CHECK FFMPEG
# ------------------------------------------------------------

Write-Host ""
Write-Host "Checking FFmpeg..."

$FFmpegCommand = Get-Command `
    ffmpeg `
    -ErrorAction SilentlyContinue

if ($null -eq $FFmpegCommand) {

    Write-Host "  ffmpeg: NOT FOUND"

}
else {

    Write-Host "  ffmpeg: OK"
    Write-Host "  $($FFmpegCommand.Source)"
}


$FFprobeCommand = Get-Command `
    ffprobe `
    -ErrorAction SilentlyContinue

if ($null -eq $FFprobeCommand) {

    Write-Host "  ffprobe: NOT FOUND"

}
else {

    Write-Host "  ffprobe: OK"
    Write-Host "  $($FFprobeCommand.Source)"
}


# ------------------------------------------------------------
# CHECK API KEYS
# ------------------------------------------------------------

Write-Host ""
Write-Host "Checking API configuration..."


if (
    [string]::IsNullOrWhiteSpace(
        $env:OPENAI_API_KEY
    )
) {

    Write-Host "  OPENAI_API_KEY:       MISSING"

}
else {

    Write-Host "  OPENAI_API_KEY:       OK"
}


if (
    [string]::IsNullOrWhiteSpace(
        $env:RUNWAYML_API_SECRET
    )
) {

    Write-Host "  RUNWAYML_API_SECRET:  MISSING"

}
else {

    Write-Host "  RUNWAYML_API_SECRET:  OK"
}


if (
    [string]::IsNullOrWhiteSpace(
        $env:ELEVENLABS_API_KEY
    )
) {

    Write-Host "  ELEVENLABS_API_KEY:   MISSING"

}
else {

    Write-Host "  ELEVENLABS_API_KEY:   OK"
}


# ------------------------------------------------------------
# DISPLAY CONFIGURATION
# ------------------------------------------------------------

Write-Host ""
Write-Host "Configuration:"
Write-Host ""

Write-Host "  Text model:"
Write-Host "    $env:OPENAI_MODEL"

Write-Host ""

Write-Host "  Image model:"
Write-Host "    $env:OPENAI_IMAGE_MODEL"
Write-Host "    quality = $env:OPENAI_IMAGE_QUALITY"

Write-Host ""

Write-Host "  Vision model:"
Write-Host "    $env:OPENAI_VISION_MODEL"
Write-Host "    detail = $env:OPENAI_VISION_DETAIL"

Write-Host ""

Write-Host "  Video provider:"
Write-Host "    $env:VIDEO_PROVIDER"

if ($env:VIDEO_PROVIDER -eq "local_ltx") {
    Write-Host "    model = $env:LOCAL_LTX_MODEL_ID"
    Write-Host "    resolution = $env:LOCAL_LTX_WIDTH x $env:LOCAL_LTX_HEIGHT"
    Write-Host "    fps = $env:LOCAL_LTX_FPS"
    Write-Host "    steps = $env:LOCAL_LTX_INFERENCE_STEPS"
    Write-Host "    offload = $env:LOCAL_LTX_OFFLOAD_MODE"
    Write-Host "    persistent service = enabled by master pipeline"
}
else {
    Write-Host "    model = $env:RUNWAY_VIDEO_MODEL"
    Write-Host "    ratio = $env:RUNWAY_VIDEO_RATIO"
}

# ------------------------------------------------------------
# VIDEO SEMANTIC QC
# ------------------------------------------------------------

$env:OPENAI_VIDEO_QC_MODEL = "gpt-5.6-luna"
$env:OPENAI_VIDEO_QC_DETAIL = "high"

$env:VIDEO_SEMANTIC_QC_FRAME_COUNT = "5"
$env:VIDEO_SEMANTIC_QC_FRAME_WIDTH = "512"
$env:VIDEO_SEMANTIC_QC_LOW_CONFIDENCE = "0.70"

# Audio
$env:OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
$env:OPENAI_TTS_VOICE = "marin"
$env:OPENAI_TTS_FORMAT = "wav"
$env:OPENAI_TTS_SPEED = "1.0"

$env:SCENE_TIMING_HEADROOM_SEC = "0.30"
$env:SCENE_TIMING_MIN_VIDEO_SEC = "2.0"
$env:SCENE_TIMING_MAX_VIDEO_SEC = "10.0"
$env:SCENE_TIMING_TARGET_TOLERANCE_SEC = "4.0"

$env:VOICE_QC_MIN_DURATION_SEC = "0.20"
$env:VOICE_QC_MIN_FILE_SIZE_BYTES = "5000"
$env:VOICE_QC_MIN_SAMPLE_RATE = "22050"

$env:SCRIPT_REWRITE_VOICE_SAFETY_SEC = "0.35"
$env:SCRIPT_REWRITE_MAX_ATTEMPTS = "3"

$env:SCRIPT_DURATION_REWRITE_MAX_ATTEMPTS = "3"
$env:SCRIPT_DURATION_PROTECT_HOOK_MAX_SEC = "3.5"
$env:SCRIPT_DURATION_SHORTEN_TEXT_SAFETY = "0.97"

# ------------------------------------------------------------
# READY
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"
Write-Host " VIDEO FACTORY ENVIRONMENT READY"
Write-Host "============================================================"
Write-Host ""

# This script is dot-sourced. Restore the caller error policy so
# warnings written by native/Python processes are not promoted to
# terminating NativeCommandError exceptions in the interactive shell.
$ErrorActionPreference = $PreviousErrorActionPreference