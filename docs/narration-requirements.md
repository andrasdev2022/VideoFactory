# Narration requirements

The original `--idea` is saved in `job.seed.text`. The generated `job.idea` is a
story blueprint and may omit writing requirements. All three text workers now
send the unabridged original request as `original_user_request`:

- `script_generator.py`
- `script_timing_rewriter.py` (one scene)
- `script_duration_rewriter.py` (global timing correction)

The common writer instruction explicitly preserves requested language, verse,
rhyme scheme, complete in-scene couplets and whole-video word budgets. Verse uses
line breaks. These requirements override generic prose preferences, but do not
bypass existing technical limits, output schemas or a rewriter's scene scope.
Both `{ "seed": { "text": "..." } }` and legacy string seeds are supported.
No seed migration or runtime-file editing is required.

## Validation before saving

After deterministic validation passes, a separate structured AI review checks the
candidate narration against the original brief. It uses the worker's existing
`OPENAI_MODEL`; it adds one text-model request per deterministically valid candidate
when a nonempty original request exists. Legacy jobs without a seed skip this check.

Full-script and global reviews see all scene narration and deterministic per-scene
and total spoken word counts. The reviewer interprets the author's word-budget
qualifiers, rhyme scheme, language and explicit story requirements. It must not
invent rhyme requirements for ordinary prose jobs. Local reviews see surrounding
scenes for continuity but may reject only the changed scene, not unrelated older
problems or the entire video's word count.

Concrete review failures feed into the existing bounded retry loop. Logs show
`Narration requirements: PASS/FAIL (AI review)` and rejected-candidate reasons.
A missing/invalid review result or API exception stops the worker. An unaccepted
candidate never replaces the script or invalidates audio/media. TTS starts only
after the script worker succeeds. Rewrites still require new TTS duration checks.

AI review is not a mathematical guarantee of rhyme or poetic quality. The local
regression suite mocks model replies; real verse quality must be assessed on a
user-run generation. Neither the measured duration bounds nor the existing
word/character budgets have been relaxed. Targeted repairs for tiny budget
excesses are outside this change.

## Trying the new behavior

Start a new job with the original idea plus the verse requirements. Add
`--stop-after script` to the master command to inspect `script.scenes[].voiceover`
in `jobs/video_job.json` before spending on speech and images. The usual UTF-8
stdout/stderr logging applies. After accepting the script, resume without `--idea`.

A plain resume does not retroactively regenerate an already accepted prose script.
Do not re-run a script worker on a completed job just to test this feature; retain
the existing job/media and start the intended new job through the master.
