# Service credit and quota preflight

VideoFactory checks external provider capacity before entering expensive
pipeline stages.

The goal is to avoid starting a long job when a selected external service is
unavailable or demonstrably lacks enough visible quota.

## Status model

Every provider check returns one of:

- `PASS` - visible capacity covers the planned request.
- `WARN` - the account is reachable, but the API cannot prove enough
  capacity for the full retry budget.
- `BLOCK` - the API proves the request cannot proceed safely.
- `UNKNOWN` - authentication works, but the provider does not expose the
  remaining balance required to make a reliable decision.

Only `BLOCK` stops the pipeline automatically.

## Two-stage checks

### Startup gate

Before the first pipeline worker runs:

- OpenAI authentication/availability is checked.
- ElevenLabs authentication and visible subscription quota are checked.
- Runway organization balance is checked only when
  `VIDEO_PROVIDER=runway`.

This gate does not make a billable generation request.

### Stage budget gates

Once the job contains enough planning information, VideoFactory checks again.

Before Runway scene generation:

- pending scene provider durations are calculated;
- the selected model credit rate is applied;
- one-attempt and configured worst-case retry budgets are calculated;
- current organization credit balance and daily generation limits are
  compared with the plan.

Before ElevenLabs audio assets:

- final planned music duration is estimated from timed scenes;
- planned SFX durations are summed;
- estimated credits are compared with visible account quota.

## Runway

The Runway organization API exposes remaining credit balance and model-specific
daily generation limits.

For the current `gen4_turbo` baseline VideoFactory uses 5 credits per
generated second. Pricing changes can be handled without a code change:

```powershell
$env:RUNWAY_PREFLIGHT_CREDITS_PER_SECOND = "5"
```

Capacity policy:

- not enough for one attempt per pending scene -> `BLOCK`;
- enough for one attempt but not the configured retry reserve -> `WARN`;
- enough for the full configured retry reserve -> `PASS`.

## ElevenLabs

The subscription API exposes the visible workspace credit pool and legacy
credit-limit extension settings.

The current planning rates are configurable:

```powershell
$env:ELEVENLABS_MUSIC_CREDITS_PER_MINUTE = "900"
$env:ELEVENLABS_SFX_CREDITS_PER_SECOND = "40"
```

If the API key is valid but its scope does not allow reading subscription
information, VideoFactory reports `WARN` instead of incorrectly treating the
account as out of credits.

Pay As You Go balance is not exposed by the subscription endpoint. Therefore,
when visible quota is insufficient, the default is `WARN`, not `BLOCK`.

If an installation intentionally never uses PAYG, make visible quota strict:

```powershell
$env:ELEVENLABS_PREFLIGHT_ASSUME_NO_PAYG = "1"
```

## OpenAI

The normal OpenAI API key is validated with a non-generation request.

OpenAI's documented API does not expose a reliable remaining prepaid-credit
balance to a normal project API key, so VideoFactory reports balance status as
`UNKNOWN` rather than pretending it can prove sufficient funds.

An optional organization-level monthly spend guard can be enabled with an
OpenAI Admin API key:

```powershell
$env:OPENAI_ADMIN_KEY = "..."
$env:OPENAI_PREFLIGHT_MONTHLY_BUDGET_USD = "25"
```

When configured, current-month organization costs are compared with this
locally configured ceiling. Reaching the ceiling produces `BLOCK`.

## Configuration

Default development configuration:

```powershell
$env:SERVICE_PREFLIGHT_ENABLED = "1"
$env:SERVICE_PREFLIGHT_TIMEOUT_SEC = "10"

$env:ELEVENLABS_MUSIC_CREDITS_PER_MINUTE = "900"
$env:ELEVENLABS_SFX_CREDITS_PER_SECOND = "40"
$env:ELEVENLABS_PREFLIGHT_ASSUME_NO_PAYG = "0"
```

Emergency opt-out:

```powershell
$env:SERVICE_PREFLIGHT_ENABLED = "0"
```

Disabling the preflight is intended only for troubleshooting. It does not
change provider billing behavior.

## Standalone diagnostic

After loading the normal development environment, provider checks can be run
without starting the production pipeline:

```powershell
. .\enter-dev.ps1
python src\service_budget_preflight.py
```

To include estimates for the active `jobs/video_job.json`:

```powershell
python src\service_budget_preflight.py --job-budget
```

These commands perform account/quota reads only; they do not submit media
generation requests.

## Example output

```text
========================================================================
SERVICE ACCOUNT / QUOTA PREFLIGHT
========================================================================
[UNKNOWN] openai: OpenAI authentication is valid...
[PASS] elevenlabs: ElevenLabs account is reachable and has visible quota...

========================================================================
RUNWAY SCENE BUDGET PREFLIGHT
========================================================================
[WARN] runway: Runway can cover one attempt per pending scene but not the
configured worst-case retry budget.
    credit_balance: 140
    base_required_credits: 100
    worst_case_required_credits: 400
```
