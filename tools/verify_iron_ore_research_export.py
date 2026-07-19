from pathlib import Path
import re


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "jq_research_export_iron_ore_v1_6.py"
)


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    violations = []
    if "get_bars(" in source:
        violations.append("research exporter uses get_bars")
    if not re.search(r"get_all_securities\(\[\"futures\"\],\s*date=", source):
        violations.append("futures metadata call is not date-scoped")
    if "end_date=_format_date(end_date)" not in source:
        violations.append("price query is missing an explicit end_date")
    if "I8888.XDCE" not in source:
        violations.append("main signal contract is missing")
    if 'IRON_ORE_CODE_RE = re.compile(r"^I\\d{4}\\.XDCE$"' not in source:
        violations.append("contract code regex is not anchored to I####.XDCE")
    for filename in (
        "iron_ore_main_daily.csv",
        "iron_ore_contract_daily.csv",
        "iron_ore_contracts.csv",
        "iron_ore_universe_daily.csv",
        "manifest.json",
    ):
        if filename not in source:
            violations.append(f"missing export file: {filename}")
    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore research exporter static audit: 0 violations")


if __name__ == "__main__":
    main()
