"""Ein Prüflauf: Bericht + Datenraum -> Ergebnis."""

from __future__ import annotations

from .clauses import apply_clauses, contract_register
from .consistency import check_income_statements, report_conflicts
from .crosscheck import apply_conflicts, find_conflicts
from .dataroom import DataRoom
from .derive import apply_addbacks, apply_derived, check_addbacks
from .gaps import check_gaps
from .render import Run, sha256
from .report import parse_report
from .swiss import apply_rates, swiss_flags
from .verify import ModelVerifier, verify


def run_check(
    report_name: str,
    report_text: str,
    report_bytes: bytes,
    room: DataRoom,
    model: ModelVerifier | None = None,
    model_name: str | None = None,
) -> Run:
    claims = parse_report(report_text)
    findings = verify(claims, room, model)
    addbacks = check_addbacks(findings)
    apply_addbacks(addbacks)
    apply_derived(findings, room, skip={c.total.claim.number for c in addbacks})
    apply_rates(findings)
    register = contract_register(room)
    apply_clauses(findings, room, register)
    conflicts = find_conflicts(room)
    apply_conflicts(findings, conflicts)
    internal = report_conflicts(findings)
    return Run(report_name, sha256(report_bytes), room, findings, model_name if model else None,
               conflicts=conflicts, addbacks=addbacks, gaps=check_gaps(room), contracts=register,
               flags=check_income_statements(room) + swiss_flags(room), internal=internal)
