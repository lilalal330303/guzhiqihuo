from pathlib import Path
import re


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "jq_iron_ore_cta_v1_3_risk.py"
)


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    violations = []

    if re.search(r"^\s*(?:from|import)\s+reports(?:\.|\s)", source, re.MULTILINE):
        violations.append("contains a local reports package import")
    if re.search(r"^\s*from\s+__future__\s+import\s+", source, re.MULTILINE):
        violations.append("contains a future import incompatible with older JoinQuant runtimes")
    if "get_bars(" in source:
        violations.append("uses get_bars without an explicit point-in-time guard")
    if re.search(
        r"get_all_securities\(\s*\[\s*[\"']futures[\"']\s*\]\s*\)",
        source,
    ):
        violations.append("futures metadata is requested without a date")
    if '"target_annual_vol": 0.20' not in source:
        violations.append("target annual volatility is not the V1.3 default")
    if '"max_margin_usage": 0.40' not in source:
        violations.append("maximum margin usage is not capped at 40%")
    if '"max_leverage": 2.5' not in source:
        violations.append("maximum leverage is not capped at 2.5")
    if '"max_margin_usage": 0.70' in source:
        violations.append("retains the old 70% margin budget")
    if "end_date=signal_date" not in source:
        violations.append("missing signal-date cutoff for market data")
    if "calculate_drawdown_multiplier" not in source:
        violations.append("missing drawdown risk overlay")
    if "classify_trend_strength" in source:
        violations.append("reintroduces the V1.2 trend-strength classifier")
    if "ALLOW_SHORT = False" not in source:
        violations.append("short mode is not disabled by default")
    if not re.search(r"\^I\\d\{4\}\\\.XDCE\$", source):
        violations.append("does not anchor contract selection to I####.XDCE")

    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V1.3 static audit: 0 violations")


if __name__ == "__main__":
    main()
