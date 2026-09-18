#!/usr/bin/env python3
"""Core CR triage routing and action-plan logic."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orbit_client import DEFAULT_AUTH_FILE, OrbitApi

DEBUG_TAGS = {"debug_info_available", "debug_info_needed"}
DECISIONS = {"debug_info_available", "debug_info_needed"}
CLOSED_STATUSES = {"closed", "cannot duplicate", "duplicate", "withdrawn"}


@dataclass(frozen=True)
class TeamRoute:
    functionality: str
    team: str
    folder: str

    @property
    def key(self) -> str:
        return self.functionality.casefold()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, sort_keys=True, default=str)


def get_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(flatten_text(v) for v in value)
    return str(value)


def parse_tags(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        raw = []
        for item in value:
            if isinstance(item, dict):
                raw.append(scalar(item.get("Name") or item.get("Text") or item.get("Value")))
            else:
                raw.append(scalar(item))
    else:
        raw = re.split(r"[,;\s]+", scalar(value))
    return {tag.strip().casefold() for tag in raw if tag and tag.strip()}


def load_functionality_map(root: Path) -> dict[str, TeamRoute]:
    path = root / "functionality-map.md"
    routes: dict[str, TeamRoute] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "`tech-teams/" not in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        functionality, team, folder = cells[:3]
        routes[functionality.casefold()] = TeamRoute(functionality, team, folder.rstrip("/"))
    return routes


def team_metadata(root: Path, route: TeamRoute) -> dict[str, Any]:
    folder = root / route.folder
    readme = folder / "README.md"
    skill = folder / "SKILL.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    placeholder = "status: placeholder" in text[:200].casefold() or "placeholder" in text[:800].casefold()
    return {
        "team": route.team,
        "folder": route.folder,
        "skill": str(skill.relative_to(root)) if skill.exists() else None,
        "rules": str(readme.relative_to(root)) if readme.exists() else None,
        "placeholder": placeholder,
    }


def cr_number(row: dict[str, Any]) -> str:
    return scalar(get_value(row, "ChangeRequestNumber", "changeRequestNumber", "crId", "id")).strip()


def functionality(row: dict[str, Any], details: dict[str, Any] | None = None) -> str:
    direct = get_value(
        row,
        "ChangeRequestParticipant.Functionality",
        "Functionality",
        "functionality",
    )
    if direct:
        return scalar(direct).strip()
    if details:
        participants = details.get("Participants")
        if isinstance(participants, list):
            primary = next((p for p in participants if isinstance(p, dict) and p.get("IsPrimary") is True), None)
            participant = primary or next((p for p in participants if isinstance(p, dict)), None)
            if isinstance(participant, dict):
                return scalar(participant.get("FunctionalityName") or participant.get("Functionality")).strip()
    return ""


def is_open(row: dict[str, Any], details: dict[str, Any] | None = None) -> bool:
    status = scalar(get_value(row, "Status", "status") or (details or {}).get("Status")).strip()
    return status.casefold() not in CLOSED_STATUSES


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        number = cr_number(row)
        if number and number not in deduped:
            deduped[number] = row
    return list(deduped.values())


def route_cr(row: dict[str, Any], root: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    routes = load_functionality_map(root)
    func = functionality(row, details)
    route = routes.get(func.casefold())
    if not route:
        return {
            "cr": cr_number(row),
            "functionality": func,
            "status": "unmapped_functionality",
            "reason": "No exact functionality mapping found.",
        }
    meta = team_metadata(root, route)
    return {
        "cr": cr_number(row),
        "functionality": func,
        "status": "routed",
        "team": route.team,
        "team_folder": route.folder,
        "team_skill": meta["skill"],
        "team_rules": meta["rules"],
        "team_rules_placeholder": meta["placeholder"],
    }


def list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("missingItems must be an array when provided")
    return [scalar(item).strip() for item in value if scalar(item).strip()]


def assessment_result(value: Any) -> tuple[str, list[str], str | None, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("review mode requires object argument: assessment when requesting an action plan")

    missing = list_of_strings(
        get_value(value, "missingItems", "missing_items", "missing", "neededInfo", "needed_info")
    )
    decision = scalar(get_value(value, "decision", "status") or "").strip()
    if not decision:
        decision = "debug_info_needed" if missing else "debug_info_available"
    if decision not in DECISIONS:
        raise ValueError(f"Unsupported assessment decision: {decision}")
    if decision == "debug_info_needed" and not missing:
        raise ValueError("debug_info_needed assessments must include missingItems")

    criteria_source = scalar(get_value(value, "criteriaSource", "criteria_source") or "").strip() or None
    rationale = list_of_strings(get_value(value, "rationale", "reasons", "evidence"))
    return decision, missing, criteria_source, rationale


def action_plan(number: str, reporter: str, decision: str, missing: list[str]) -> list[dict[str, Any]]:
    if decision == "debug_info_available":
        return [
            {
                "operation": "add_tags",
                "transport": "orbit_web_api",
                "arguments": {"crId": number, "tags": ["debug_info_available"]},
            }
        ]

    comment = (
        "Root-cause analysis is blocked pending additional debug information.\n\n"
        "Please retrieve the following from the customer:\n"
        + "\n".join(f"- {item}" for item in missing)
    )
    return [
        {
            "operation": "add_tags",
            "transport": "orbit_web_api",
            "arguments": {"crId": number, "tags": ["debug_info_needed"]},
        },
        {
            "operation": "edit_cr_details",
            "transport": "orbit_web_api",
            "arguments": {
                "crId": number,
                "assignee": reporter,
                "justification": "Reassigned to reporter because additional debug information is required from the customer to proceed with root-cause analysis.",
            },
        },
        {
            "operation": "add_cr_comment",
            "transport": "orbit_web_api",
            "arguments": {"changeRequestNumber": number, "commentText": comment},
        },
    ]


def orbit_options(payload: dict[str, Any]) -> dict[str, Any]:
    auth_file = payload.get("authFile") or payload.get("auth_file")
    return {
        "server": scalar(payload.get("server") or "orbit-sd"),
        "auth_file": Path(scalar(auth_file)) if auth_file else DEFAULT_AUTH_FILE,
        "renew_krb_token": bool(payload.get("renewKrb", payload.get("renew_krb", True))),
        "timeout": int(payload.get("timeout") or 120),
        "page_size": int(payload.get("pageSize") or payload.get("page_size") or 100000),
    }


def orbit_api(payload: dict[str, Any]) -> OrbitApi:
    opts = orbit_options(payload)
    return OrbitApi(
        server=opts["server"],
        auth_file=opts["auth_file"],
        renew_krb_token=opts["renew_krb_token"],
    )


def saved_query_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "rows" in payload:
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            raise ValueError("rows must be an array when provided")
        return [row for row in rows if isinstance(row, dict)]

    if not bool(payload.get("fetchOrbit", payload.get("fetch_orbit", True))):
        raise ValueError("rows are required when fetchOrbit is false")

    opts = orbit_options(payload)
    query_id = scalar(payload.get("queryId") or "37070")
    api = orbit_api(payload)
    response = api.run_saved_query(query_id, page_size=opts["page_size"], timeout=opts["timeout"])
    rows = response.get("Results") or []
    total = response.get("Total")
    if isinstance(total, int) and total > len(rows):
        response = api.run_saved_query(query_id, page_size=total, timeout=opts["timeout"])
        rows = response.get("Results") or []
    if not isinstance(rows, list):
        raise RuntimeError("Orbit saved-query response does not contain a Results list")
    return [row for row in rows if isinstance(row, dict)]


def cr_context(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[Any], list[str]]:
    warnings = []
    row = payload.get("cr") or {}
    cr_id = scalar(payload.get("crNumber") or payload.get("crId") or cr_number(row)).strip()
    if not isinstance(row, dict):
        raise ValueError("review mode requires object argument: cr")
    if not row and cr_id:
        row = {"ChangeRequestNumber": cr_id}

    details = payload.get("details")
    comments = payload.get("comments")
    fetch_orbit = bool(payload.get("fetchOrbit", payload.get("fetch_orbit", True)))
    timeout = orbit_options(payload)["timeout"]
    api: OrbitApi | None = None

    if fetch_orbit and cr_id and details is None:
        api = api or orbit_api(payload)
        details = api.get_cr_details(cr_id, timeout=timeout)
    if fetch_orbit and cr_id and comments is None and bool(payload.get("fetchComments", True)):
        api = api or orbit_api(payload)
        try:
            comments = api.get_cr_comments(cr_id, timeout=timeout)
        except Exception as exc:
            comments = []
            warnings.append(f"Unable to fetch Orbit comments for {cr_id}: {exc}")

    details = details or {}
    comments = comments or []
    if not isinstance(details, dict):
        raise ValueError("details must be an object when provided")
    if not isinstance(comments, list):
        raise ValueError("comments must be an array when provided")
    return row, details, comments, warnings


def apply_action(api: OrbitApi, action: dict[str, Any], timeout: int) -> dict[str, Any]:
    operation = scalar(action.get("operation"))
    args = action.get("arguments") or {}
    if not isinstance(args, dict):
        raise ValueError("action arguments must be an object")

    if operation == "add_tags":
        result = api.add_tags(scalar(args.get("crId")), [scalar(t) for t in args.get("tags", [])], timeout=timeout)
    elif operation == "edit_cr_details":
        fields = {}
        if args.get("assignee"):
            fields["Assignee"] = scalar(args.get("assignee"))
        if args.get("justification"):
            fields["Justification"] = scalar(args.get("justification"))
        result = api.update_cr_details(scalar(args.get("crId")), fields, timeout=timeout)
    elif operation == "add_cr_comment":
        result = api.add_cr_comment(
            scalar(args.get("changeRequestNumber") or args.get("crId")),
            scalar(args.get("commentText")),
            timeout=timeout,
        )
    else:
        raise ValueError(f"Unsupported Orbit Web API operation: {operation}")
    return {"operation": operation, "status": "applied", "result": result}


def apply_actions(payload: dict[str, Any], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not bool(payload.get("applyUpdates", payload.get("apply_updates", False))):
        return []
    api = orbit_api(payload)
    timeout = orbit_options(payload)["timeout"]
    applied = []
    for action in actions:
        applied.append(apply_action(api, action, timeout))
    return applied


def review_cr(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    row, details, comments, retrieval_warnings = cr_context(payload)

    number = cr_number(row)
    open_state = is_open(row, details)
    if open_state is False:
        return {
            "cr": number,
            "decision": "skipped",
            "skip_reason": "closed",
            "actions": [],
            "retrieval_warnings": retrieval_warnings,
        }

    route = route_cr(row, root, details)
    if route["status"] != "routed":
        return {"cr": number, "decision": "skipped", "skip_reason": route["status"], "route": route, "actions": []}

    assessment = payload.get("assessment")
    if assessment is None:
        return {
            "cr": number,
            "decision": "needs_team_review",
            "route": route,
            "team_review_request": {
                "skill": route["team_skill"],
                "rules": route["team_rules"],
                "rules_placeholder": route["team_rules_placeholder"],
                "input": {
                    "cr": row,
                    "details": details,
                    "comments": comments,
                },
                "expected_assessment_schema": {
                    "decision": "debug_info_available | debug_info_needed",
                    "missingItems": ["required only when decision is debug_info_needed"],
                    "criteriaSource": "team README path or placeholder baseline",
                    "rationale": ["optional short reasons"],
                },
            },
            "actions": [],
            "retrieval_warnings": retrieval_warnings,
        }

    decision, missing, criteria_source, rationale = assessment_result(assessment)
    reporter = scalar(get_value(row, "Reporter", "reporter") or details.get("Reporter")).strip()
    actions = action_plan(number, reporter, decision, missing)
    return {
        "cr": number,
        "decision": decision,
        "route": route,
        "criteria_source": criteria_source or route["team_rules"],
        "rationale": rationale,
        "missing": missing,
        "actions": actions,
        "applied_actions": apply_actions(payload, actions),
        "retrieval_warnings": retrieval_warnings,
    }


def route_rows(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    rows = saved_query_rows(payload)
    force = bool(payload.get("force", False))
    groups: dict[str, list[dict[str, Any]]] = {}
    skipped: list[dict[str, Any]] = []
    routed: list[dict[str, Any]] = []
    unique_rows = dedupe_rows([r for r in rows if isinstance(r, dict)])

    for row in unique_rows:
        number = cr_number(row)
        open_state = is_open(row)
        if open_state is False:
            skipped.append({"cr": number, "reason": "closed"})
            continue
        tags = parse_tags(get_value(row, "Tags", "tags"))
        if not force and tags.intersection(DEBUG_TAGS):
            skipped.append({"cr": number, "reason": "already_reviewed", "tags": sorted(tags.intersection(DEBUG_TAGS))})
            continue
        route = route_cr(row, root)
        if route["status"] != "routed":
            skipped.append({"cr": number, "reason": route["status"], "functionality": route.get("functionality")})
            continue
        routed.append(route)
        groups.setdefault(route["team"], []).append({"cr": number, "functionality": route["functionality"]})

    return {
        "queryId": scalar(payload.get("queryId") or "37070"),
        "force": force,
        "counts": {
            "input_rows": len(rows),
            "unique_crs": len(unique_rows),
            "routed": len(routed),
            "skipped": len(skipped),
        },
        "team_groups": groups,
        "routed": routed,
        "skipped": skipped,
    }


def batch_plan(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    rows = saved_query_rows(payload)
    resolved_payload = {**payload, "rows": rows}
    plan = route_rows(resolved_payload, root)
    details_by_cr = payload.get("detailsByCr") or {}
    comments_by_cr = payload.get("commentsByCr") or {}
    assessments_by_cr = payload.get("assessmentsByCr") or payload.get("assessmentByCr") or {}
    rows_by_cr = {cr_number(r): r for r in dedupe_rows(rows)}
    reviews = []
    for route in plan["routed"]:
        number = route["cr"]
        has_context = number in details_by_cr or number in comments_by_cr or bool(payload.get("fetchOrbit", True))
        has_assessment = number in assessments_by_cr
        if not has_context and not has_assessment:
            reviews.append(
                {
                    "cr": number,
                    "decision": "needs_context",
                    "route": route,
                    "required_context": ["Orbit CR details", "Orbit CR comments"],
                }
            )
            continue
        reviews.append(
            review_cr(
                {
                    "cr": rows_by_cr[number],
                    "details": details_by_cr.get(number) if number in details_by_cr else None,
                    "comments": comments_by_cr.get(number) if number in comments_by_cr else None,
                    "assessment": assessments_by_cr.get(number),
                    "server": payload.get("server"),
                    "authFile": payload.get("authFile") or payload.get("auth_file"),
                    "renewKrb": payload.get("renewKrb", payload.get("renew_krb", True)),
                    "timeout": payload.get("timeout"),
                    "fetchOrbit": payload.get("fetchOrbit", True),
                    "fetchComments": payload.get("fetchComments", True),
                    "applyUpdates": payload.get("applyUpdates", payload.get("apply_updates", False)),
                },
                root,
            )
        )
    plan["reviews"] = reviews
    plan["summary"] = {
        "debug_info_available": sum(1 for r in reviews if r.get("decision") == "debug_info_available"),
        "debug_info_needed": sum(1 for r in reviews if r.get("decision") == "debug_info_needed"),
        "needs_context": sum(1 for r in reviews if r.get("decision") == "needs_context"),
        "needs_team_review": sum(1 for r in reviews if r.get("decision") == "needs_team_review"),
        "skipped_closed": sum(1 for r in plan["skipped"] if r.get("reason") == "closed"),
        "skipped_already_reviewed": sum(1 for r in plan["skipped"] if r.get("reason") == "already_reviewed"),
        "skipped_unmapped_or_unclear": sum(
            1 for r in plan["skipped"] if r.get("reason") == "unmapped_functionality"
        ),
    }
    return plan


def run(arguments: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parent.parent
    return batch_plan(arguments, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the core CR triage batch plan.")
    parser.add_argument("--input", help="Optional JSON object containing script arguments, or '-' for stdin.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    if args.input:
        payload_text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = json.loads(payload_text)
    else:
        payload = {}
    print(json.dumps(run(payload, args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
