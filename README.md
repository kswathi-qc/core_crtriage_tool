# CR Debug Info Review Tool

This package provides `core_crtriage_tool` as a standalone script. The script
owns common CR mechanics:

- de-duplicate rows from Orbit saved query `37070`
- skip closed CRs
- skip already-reviewed CRs unless `force` is set
- treat only `Closed`, `Cannot Duplicate`, `Duplicate`, and `Withdrawn` as
  closed statuses; all other statuses proceed as open
- route each CR by `ChangeRequestParticipant.Functionality`
- authenticate to Orbit Web API using `auth/orbit_auth.txt`
- fetch saved-query rows, CR details, and CR comments directly from Orbit
- package routed CR context for the owning tech-team skill
- convert a tech-team assessment into direct Orbit Web API updates for
  `debug_info_available` or `debug_info_needed`

The tech-team skill owns the decision about whether the CR has the debug and
root-cause information required by that team.

Run the orchestration logic directly with `scripts/core_crtriage_tool.py`.

## Plugin Layout

- `.codex-plugin/plugin.json` - plugin metadata
- `auth/orbit_auth.txt` - local Orbit Web API service-account auth file
- `requirements.txt` - Python packages needed for live Orbit Web API calls
- `scripts/core_crtriage_tool.py` - review/routing/action-plan logic
- `scripts/orbit_client.py` - Kerberos-backed Orbit Web API client
- `functionality-map.md` - Orbit functionality to tech-team mapping
- `tech-teams/<team>/SKILL.md` - team skill entry points
- `tech-teams/<team>/README.md` - team-specific debug-info criteria

## Script Invocation

Run from this directory:

```bash
python3 scripts/core_crtriage_tool.py
python3 scripts/core_crtriage_tool.py --input payload.json
```

When `--input` is omitted, the script uses default arguments. It fetches Orbit
saved query `37070` from `orbit-sd` using `auth/orbit_auth.txt`. Use
`--input -` to read a JSON object from stdin when overrides are needed.

## Batch Plan

`core_crtriage_tool` runs one default workflow: fetch saved-query `37070`
unless `rows` are supplied, skip terminal-status CRs, route open CRs, and return
per-CR review requests or action plans when tech-team assessments are supplied.

By default the script previews the update plan. Set `applyUpdates: true` to apply
the tag, reassignment, and comment updates directly through Orbit Web API. This
keeps Orbit updates self-contained in the standalone script.

## Team Assessment Contract

After a CR is routed, the corresponding `tech-teams/<team>/SKILL.md` decides
whether debug info is sufficient. The skill returns an assessment object to the
script:

```json
{
  "decision": "debug_info_available",
  "missingItems": [],
  "criteriaSource": "tech-teams/kernel/README.md",
  "rationale": ["short reason"]
}
```

When the team skill or team README has no approved criteria yet, use the blank
template in `assessment-template.json` and keep the decision as
`debug_info_needed`. Do not mark a CR as `debug_info_available` without defined
criteria.

Use `debug_info_needed` and a non-empty `missingItems` list when the team
criteria are not satisfied. The generic script does not infer this from keywords;
it only validates the assessment and formats/applies the Orbit Web API tag,
reassignment, and comment updates.

## Orbit Authentication

The auth flow is self-contained:

1. Read a TIP-format auth file.
2. Run `/usr/bin/kinit <user>@<realm>` with the password from that file.
3. Call `https://<server>/api/...` with Kerberos `Authorization: Negotiate`,
   `ApplicationSource`, and optional `ImpersonatedUserName` headers.

The default server is `orbit-sd`. The default auth file is
`auth/orbit_auth.txt`; callers can override it with `authFile`.

Install the live Orbit dependencies in the runtime environment if they are not
already present:

```bash
python3 -m pip install -r requirements.txt
```

## Extending Routing

Add new exact, case-insensitive `Functionality` mappings to
`functionality-map.md`. If a functionality is missing, the script skips write
actions for that CR and reports it as unmapped.
