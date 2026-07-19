from pathlib import Path
import re


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "jq_iron_ore_cta_v1_4_aggressive.py"
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
    if '"target_annual_vol": 0.30' not in source:
        violations.append("target annual volatility is not the C-tier default")
    if '"max_margin_usage": 0.60' not in source:
        violations.append("maximum margin usage is not capped at 60%")
    if '"max_leverage": 3.5' not in source:
        violations.append("maximum leverage is not capped at 3.5")
    if '"max_risk_multiplier": 1.25' not in source:
        violations.append("trend boost cap is not 1.25")
    if "calculate_trend_quality_multiplier" not in source:
        violations.append("missing conditional trend quality multiplier")
    if "slow_slope" not in source:
        violations.append("missing point-in-time slow trend slope")
    if "drawdown < 0.15" not in source or "drawdown < 0.20" not in source or "drawdown < 0.25" not in source:
        violations.append("aggressive drawdown bands are incomplete")
    if "classify_trend_strength" in source:
        violations.append("reintroduces the V1.2 trend-strength classifier")
    if "end_date=signal_date" not in source:
        violations.append("missing signal-date cutoff for market data")
    if "ALLOW_SHORT = False" not in source:
        violations.append("short mode is not disabled by default")
    if not re.search(r"\^I\\d\{4\}\\\.XDCE\$", source):
        violations.append("does not anchor contract selection to I####.XDCE")

    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V1.4 static audit: 0 violations")


if __name__ == "__main__":
    main()
