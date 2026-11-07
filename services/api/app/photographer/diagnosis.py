from __future__ import annotations

from dataclasses import dataclass

from app.ai.contracts import Severity
from app.models.analysis_report import AnalysisReport
from app.models.photographer import (
    CreativeChoice,
    CreativeChoiceType,
    CreativeDirection,
    DiagnosisItem,
    DiagnosisResult,
)
from app.photographer.rules import (
    clamp,
    creative_choices,
    evidence_refs_for_issue,
    has_conflicting_issues,
    is_creative_sensitive_issue,
    round2,
)

_CONFIRMED_CONFIDENCE = 0.55
_DIAGNOSIS_LIMIT = 10
_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
_SEVERITY_WEIGHT = {Severity.HIGH: 1.0, Severity.MEDIUM: 0.8, Severity.LOW: 0.6}


@dataclass(frozen=True, slots=True)
class AnalysisAdvice:
    diagnosis: DiagnosisResult
    direction: CreativeDirection


def diagnose(report: AnalysisReport) -> DiagnosisResult:
    """Layer Stage 3 findings into confirmed, possible, and creative choices.

    Stage 3 issues are measurements-driven; this layer decides whether an
    apparent defect is well-supported enough to treat, or whether it may be an
    intentional creative choice and should stay advisory.
    """
    ordered = sorted(
        report.issues,
        key=lambda issue: (
            _SEVERITY_RANK[issue.severity],
            -issue.confidence,
            issue.id,
        ),
    )
    conflicting = has_conflicting_issues(report)
    confirmed: list[DiagnosisItem] = []
    possible: list[DiagnosisItem] = []

    for issue in ordered:
        item = DiagnosisItem(
            issue_id=issue.id,
            type=issue.type,
            severity=issue.severity,
            confidence=issue.confidence,
            evidence=issue.evidence,
            evidence_refs=evidence_refs_for_issue(issue),
        )
        deferred = (
            issue.confidence < _CONFIRMED_CONFIDENCE
            or conflicting
            or is_creative_sensitive_issue(issue, report)
        )
        if deferred:
            possible.append(item)
        else:
            confirmed.append(item)

    choices = creative_choices(report)
    return DiagnosisResult(
        confirmed=tuple(confirmed[:_DIAGNOSIS_LIMIT]),
        possible=tuple(possible[:_DIAGNOSIS_LIMIT]),
        creative_choices=choices,
        confidence=_confidence(confirmed, possible, choices),
    )


def _confidence(
    confirmed: list[DiagnosisItem],
    possible: list[DiagnosisItem],
    choices: tuple[CreativeChoice, ...],
) -> float:
    if confirmed:
        weight = sum(_SEVERITY_WEIGHT[item.severity] for item in confirmed)
        value = (
            sum(item.confidence * _SEVERITY_WEIGHT[item.severity] for item in confirmed) / weight
        )
    elif possible:
        value = sum(item.confidence for item in possible) / len(possible) * 0.55
    elif any(choice.type is CreativeChoiceType.ALREADY_EDITED for choice in choices):
        value = 0.55
    else:
        value = 0.45
    return round2(clamp(value, 0.0, 1.0))


__all__ = ["AnalysisAdvice", "diagnose"]
