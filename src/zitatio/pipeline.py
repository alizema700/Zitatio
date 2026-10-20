"""Ein Prüflauf: Bericht + Datenraum -> Ergebnis."""

from __future__ import annotations

from .clauses import apply_clauses, contract_register
from .consistency import check_income_statements, report_conflicts
from .crosscheck import apply_conflicts, find_conflicts
from .dataroom import DataRoom
from .derive import apply_addbacks, apply_derived, check_addbacks
from .gaps import check_gaps
from .minutes import check_minutes
from .netdebt import apply_netdebt, net_debt, netdebt_flags
from .references import missing_amendments
from .render import Run, sha256
from .report import parse_report
from .swiss import _latest_statement, apply_rates, swiss_flags
from .terms import closing_list
from .valuation import apply_valuation, value_bridge
from .verify import ModelVerifier, verify
from .versions import carry_decisions, compare


def run_check(
    report_name: str,
    report_text: str,
    report_bytes: bytes,
    room: DataRoom,
    model: ModelVerifier | None = None,
    model_name: str | None = None,
    previous: tuple[str, str] | None = None,
    decisions: dict | None = None,
    spa: tuple[str, str] | None = None,
) -> Run:
    """previous: Name und Text der Vorversion des Berichts; decisions: Entscheide aus deren CSV;
    spa: Name und Text des Kaufvertragsentwurfs, dessen Garantien mit den Befunden abgeglichen werden."""
    findings, conflicts, register, addbacks, internal, debt, valuation = _check(report_text, room, model)
    diff = None
    if previous is not None:
        old_findings = _check(previous[1], room, model)[0]
        diff = compare(old_findings, findings, previous[0])
    terms, closing = closing_list(register)
    latest = _latest_statement(room)
    revenue = (latest[1], latest[2]["umsatz"][0]) if latest and "umsatz" in latest[2] else None
    flags = (check_income_statements(room) + swiss_flags(room) + netdebt_flags(debt) + check_minutes(room, report_text)
             + missing_amendments(room))
    flags.sort(key=lambda fl: ("warnung", "hinweis", "ok").index(fl.level))
    carried = carry_decisions(findings, decisions, diff) if decisions else {}
    run = Run(report_name, sha256(report_bytes), room, findings, model_name if model else None,
               conflicts=conflicts, addbacks=addbacks, gaps=check_gaps(room), contracts=register,
               flags=flags, internal=internal,
               netdebt=debt, valuation=valuation, terms=terms, closing=closing, revenue=revenue, diff=diff, decisions=carried)
    if spa is not None:
        from .spa import check_warranties

        run.spa_name = spa[0]
        run.warranties = check_warranties(spa[1], run)
    return run


def _check(report_text: str, room: DataRoom, model: ModelVerifier | None):
    claims = parse_report(report_text)
    findings = verify(claims, room, model)
    addbacks = check_addbacks(findings)
    apply_addbacks(addbacks)
    apply_derived(findings, room, skip={c.total.claim.number for c in addbacks})
    apply_rates(findings)
    register = contract_register(room)
    apply_clauses(findings, room, register)
    debt = net_debt(room, register)
    apply_netdebt(findings, debt)
    valuation = value_bridge(report_text, addbacks, debt)
    apply_valuation(findings, valuation)
    conflicts = find_conflicts(room)
    apply_conflicts(findings, conflicts)
    internal = report_conflicts(findings)
    return findings, conflicts, register, addbacks, internal, debt, valuation
