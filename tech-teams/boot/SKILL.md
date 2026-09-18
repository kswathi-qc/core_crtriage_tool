---
name: cr-debug-info-boot
description: Apply Boot-team debug-info requirements to CRs routed by the core_crtriage_tool script.
---

# Boot CR Debug Info Review

Use when `core_crtriage_tool` routes a CR to Boot.

Read `README.md` in this folder for the current Boot criteria. If the README
is blank or still has `status: placeholder`, treat the team criteria as
undefined. In that case, use the blank template from `assessment-template.json`
and set `criteriaSource` to `tech-teams/boot/README.md (blank criteria)`.

Assess the CR context returned by the `core_crtriage_tool` script and produce
an assessment object for the generic script:

```json
{
  "decision": "debug_info_available | debug_info_needed",
  "missingItems": ["required when decision is debug_info_needed"],
  "criteriaSource": "tech-teams/boot/README.md",
  "rationale": ["brief reason"]
}
```

Do not create Orbit tags, assignee changes, or comments directly from this
skill. Pass the assessment back to the generic script so it can build the action
plan consistently.
