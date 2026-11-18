"""scripts/trivy_gate.py: what blocks, what is accepted, and the rules of the ignore file.

The reports below have the shapes Trivy 0.76.1 writes: `trivy image --show-suppressed` for images,
`trivy convert --show-suppressed` over `trivy config` for Terraform.
"""

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "trivy_gate", Path(__file__).resolve().parents[1] / "scripts" / "trivy_gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

TODAY = datetime.datetime.now(datetime.UTC).date()


def days(n: int) -> str:
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def vuln(cve, severity="HIGH", fixed="2.0", pkg="libfoo"):
    return {
        "VulnerabilityID": cve,
        "PkgName": pkg,
        "InstalledVersion": "1.0",
        "FixedVersion": fixed,
        "Severity": severity,
        "Title": "a flaw",
    }


def image_report(vulns=(), suppressed=()):
    return {
        "ArtifactName": "image:ci",
        "Results": [
            {
                "Target": "image (debian 12)",
                "Class": "os-pkgs",
                "Vulnerabilities": list(vulns),
                "ExperimentalModifiedFindings": [
                    {"Type": "vulnerability", "Status": "ignored", "Finding": vuln(cve)}
                    for cve in suppressed
                ],
            }
        ],
    }


def check(check_id, severity="HIGH", target="modules/net/main.tf"):
    return target, {
        "ID": check_id,
        "Severity": severity,
        "Status": "FAIL",
        "Title": "a misconfiguration",
        "CauseMetadata": {"Resource": "aws_thing.x", "StartLine": 7},
    }


def config_report(failed=(), suppressed=()):
    results = {}
    for target, m in failed:
        results.setdefault(target, []).append(m)
    return {
        "ArtifactName": "infra",
        "Results": [
            {"Target": t, "Class": "config", "Misconfigurations": ms} for t, ms in results.items()
        ]
        + [
            {
                "Target": "envs/dev",
                "Class": "config",
                "Misconfigurations": [],
                "ExperimentalModifiedFindings": [
                    {
                        "Type": "misconfiguration",
                        "Status": "ignored",
                        "Finding": check(i)[1] | {"Status": "ignored"},
                    }
                    for i in suppressed
                ],
            }
        ],
    }


def entry(section, ident, scope, expires=None, statement="Not reachable here."):
    key, item = ("purls", scope) if section == "vulnerabilities" else ("paths", f'"{scope}"')
    lines = [f"  - id: {ident}", f"    {key}:", f"      - {item}"]
    if statement is not None:
        lines.append(f'    statement: "{statement}"')
    if expires is not False:
        lines.append(f"    expired_at: {expires or days(90)}")
    return lines


def run(tmp_path, capsys, monkeypatch, ignore_lines, *reports, strict=False):
    ignore = tmp_path / "ignore.yaml"
    ignore.write_text("\n".join(["# test"] + ignore_lines) + "\n")
    args = []
    for i, report in enumerate(reports):
        path = tmp_path / f"report{i}.json"
        path.write_text(json.dumps(report))
        args.append(f"Report {i}={path}")
    monkeypatch.setattr(
        "sys.argv", ["trivy_gate.py", *(["--strict"] if strict else []), str(ignore), *args]
    )
    code = gate.main()
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_fixable_high_vulnerability_blocks(tmp_path, capsys, monkeypatch):
    code, out, _ = run(tmp_path, capsys, monkeypatch, [], image_report([vuln("CVE-1")]))
    assert code == 1 and "CVE-1" in out


def test_unfixed_and_medium_vulnerabilities_do_not_block(tmp_path, capsys, monkeypatch):
    report = image_report([vuln("CVE-1", fixed=""), vuln("CVE-2", severity="MEDIUM")])
    code, out, _ = run(tmp_path, capsys, monkeypatch, [], report)
    assert code == 0 and "0 blocking" in out


def test_an_accepted_vulnerability_passes(tmp_path, capsys, monkeypatch):
    ignore = ["vulnerabilities:", *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/libfoo")]
    code, _, err = run(tmp_path, capsys, monkeypatch, ignore, image_report(suppressed=["CVE-1"]))
    assert code == 0 and err == ""


def test_a_failed_high_terraform_check_blocks(tmp_path, capsys, monkeypatch):
    code, out, _ = run(tmp_path, capsys, monkeypatch, [], config_report([check("AWS-0095")]))
    assert code == 1 and "AWS-0095" in out and "modules/net/main.tf:7" in out


def test_a_failed_medium_terraform_check_does_not_block(tmp_path, capsys, monkeypatch):
    report = config_report([check("AWS-0178", severity="MEDIUM")])
    code, out, _ = run(tmp_path, capsys, monkeypatch, [], report)
    assert code == 0 and "| MEDIUM | 1 |" in out


def test_an_accepted_terraform_check_passes(tmp_path, capsys, monkeypatch):
    ignore = ["misconfigurations:", *entry("misconfigurations", "AWS-0104", "**/network.tf")]
    code, _, err = run(
        tmp_path, capsys, monkeypatch, ignore, config_report(suppressed=["AWS-0104"])
    )
    assert code == 0 and err == ""


def test_an_entry_matching_nothing_warns_and_fails_only_with_strict(tmp_path, capsys, monkeypatch):
    ignore = ["vulnerabilities:", *entry("vulnerabilities", "CVE-9", "pkg:deb/debian/libfoo")]
    code, _, err = run(tmp_path, capsys, monkeypatch, ignore, image_report())
    assert code == 0 and "CVE-9 matches nothing" in err
    code, _, _ = run(tmp_path, capsys, monkeypatch, ignore, image_report(), strict=True)
    assert code == 1


def test_an_entry_expiring_soon_warns(tmp_path, capsys, monkeypatch):
    ignore = [
        "vulnerabilities:",
        *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/libfoo", days(10)),
    ]
    code, _, err = run(tmp_path, capsys, monkeypatch, ignore, image_report(suppressed=["CVE-1"]))
    assert code == 0 and "CVE-1 expires on" in err


def test_an_expired_entry_is_reported(tmp_path, capsys, monkeypatch):
    # Trivy no longer applies an expired entry, so the finding is back in the report.
    ignore = [
        "vulnerabilities:",
        *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/libfoo", days(-1)),
    ]
    code, _, err = run(tmp_path, capsys, monkeypatch, ignore, image_report([vuln("CVE-1")]))
    assert code == 1 and "CVE-1 expired on" in err


@pytest.mark.parametrize(
    ("ignore", "message"),
    [
        (
            [
                "vulnerabilities:",
                *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/x", statement=None),
            ],
            "no statement",
        ),
        (
            [
                "vulnerabilities:",
                *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/x", expires=False),
            ],
            "no expired_at",
        ),
        (
            ["vulnerabilities:", *entry("vulnerabilities", "CVE-1", "pkg:deb/debian/x", days(200))],
            "more than 180 days away",
        ),
        (
            [
                "vulnerabilities:",
                "  - id: CVE-1",
                '    statement: "x"',
                f"    expired_at: {days(9)}",
            ],
            "no purls",
        ),
        (
            ["misconfigurations:", "  - id: AWS-1", "    purls:", "      - pkg:deb/debian/x"],
            "scoped by paths, not purls",
        ),
        (["vulnerabilities:", "  - id: CVE-1", "    paths: [x]"], "unexpected line"),
    ],
)
def test_the_ignore_file_keeps_its_rules(tmp_path, capsys, monkeypatch, ignore, message):
    code, _, err = run(tmp_path, capsys, monkeypatch, ignore, image_report())
    assert code == 1 and message in err
