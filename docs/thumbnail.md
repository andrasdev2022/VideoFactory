# Local thumbnail generation

The master pipeline creates a portrait 1080×1920 JPEG cover before final QC. It uses the first scene image that passed technical and semantic image QC, with `metadata.thumbnail.text` (or the title) in a separate headline panel. The complete source image is fitted without cropping. This stage uses Pillow locally: no image API request, LTX, or GPU is needed.

The output is `output/<job_id>/thumbnails/thumbnail.jpg`. Final export copies it to `output/<job_id>/final/thumbnail.jpg` and includes `thumbnail_file` in `metadata.json`. This is a generic portrait cover; platform-specific upload/crop handling is outside this stage.

## Complete an existing video

Activate the main `.venv` and run from the repository root. Preserve your local `jobs/video_job.json` before changing branches. No scene video or audio regeneration is needed:

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
python -u .\src\thumbnail_generator.py *> ".\logs\thumbnail-$stamp.log"
if ($LASTEXITCODE -ne 0) { throw "Thumbnail failed; see logs\thumbnail-$stamp.log" }
python -u .\src\final_qc_export.py *> ".\logs\thumbnail-export-$stamp.log"
if ($LASTEXITCODE -ne 0) { throw "Export failed; see logs\thumbnail-export-$stamp.log" }
```

Choose a different approved scene with `--scene 2`; `--force` replaces an existing thumbnail. The selected scene is remembered. Normal resume skips an unchanged valid cover; source-image, headline, or font changes regenerate generated covers. Existing valid custom thumbnails are preserved unless explicitly replaced. Optional thumbnails (`required: false`) are skipped by default; `--scene` or `--force` explicitly generates one.

`THUMBNAIL_FONT` can specify a TrueType font path. Default: bold Arial on Windows, bold DejaVu Sans on Linux. A missing font, empty/oversized headline, or missing approved image fails explicitly.

New full pipeline runs include this step automatically, regardless of video provider. `--stop-after thumbnail` stops before final export. A missing or corrupt required thumbnail keeps `publish_ready` false, even when video QC passes. Readiness is a technical check; inspect the cover before publishing.

## Regression tests

```powershell
New-Item -ItemType Directory -Force .\logs | Out-Null
python -m unittest discover -s src -p 'test_*.py' -v *> .\logs\thumbnail-unit-tests.log
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed; see logs\thumbnail-unit-tests.log' }
```
