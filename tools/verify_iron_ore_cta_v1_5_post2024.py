from pathlib import Path
import re


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "jq_iron_ore_cta_v1_5_post2024.py"
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
    if 'POST_2024_START = "2024-01-01"' not in source:
        violations.append("post-2024 switch date is not 2024-01-01")
    if "fast_days=10" not in source or "trend_days=40" not in source or "slope_days=5" not in source:
        violations.append("post-2024 fast trend parameters are incomplete")
    if "min_efficiency=0.25" not in source:
        violations.append("efficiency threshold is not 0.25")
    if "max_vol_ratio=1.8" not in source:
        violations.append("volatility ratio threshold is not 1.8")
    if "allow_short=True" not in source or "ALLOW_SHORT = True" not in source:
        violations.append("post-2024 short mode is not enabled")
    for name in (
        "calculate_efficiency_ratio",
        "calculate_volatility_ratio",
        "calculate_adaptive_signal",
        "calculate_regime_risk_multiplier",
    ):
        if name not in source:
            violations.append("missing adaptive helper: {}".format(name))
    if "end_date=signal_date" not in source:
        violations.append("missing signal-date cutoff for market data")
    if "classify_trend_strength" in source:
        violations.append("reintroduces the V1.2 trend-strength classifier")
    if not re.search(r"\^I\\d\{4\}\\\.XDCE\$", source):
        violations.append("does not anchor contract selection to I####.XDCE")
    if "PRE_PARAMS" not in source or "POST_PARAMS" not in source:
        violations.append("missing pre/post parameter sets")

    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V1.5 static audit: 0 violations")


if __name__ == "__main__":
    main()
