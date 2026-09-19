# ============================================================
# VIDEO FACTORY - DEVELOPMENT ENVIRONMENT
# ============================================================

$ErrorActionPreference = "Stop"

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
# RUNWAY VIDEO
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

Write-Host "  Video model:"
Write-Host "    $env:RUNWAY_VIDEO_MODEL"
Write-Host "    ratio = $env:RUNWAY_VIDEO_RATIO"

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