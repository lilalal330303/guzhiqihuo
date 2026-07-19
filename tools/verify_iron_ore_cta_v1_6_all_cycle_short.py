from pathlib import Path
import re


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "jq_iron_ore_cta_v1_6_all_cycle_short.py"
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
    for fragment in (
        "fast_days=10",
        "trend_days=40",
        "slope_days=5",
        "dual_speed=True",
        "min_efficiency=0.25",
        "min_consistency=0.60",
        "max_vol_ratio=1.8",
        "allow_short=True",
        "ALLOW_SHORT = True",
    ):
        if fragment not in source:
            violations.append("missing required V1.6 parameter: {}".format(fragment))
    for name in (
        "calculate_direction_consistency",
        "calculate_dual_speed_signal",
        "calculate_efficiency_ratio",
        "calculate_volatility_ratio",
        "calculate_adaptive_signal",
        "calculate_regime_risk_multiplier",
        "should_trigger_trailing_stop",
    ):
        if name not in source:
            violations.append("missing V1.6 helper: {}".format(name))
    if "end_date=signal_date" not in source:
        violations.append("missing signal-date cutoff for market data")
    if not re.search(r"\^I\\d\{4\}\\\.XDCE\$", source):
        violations.append("does not anchor contract selection to I####.XDCE")
    if "PRE_PARAMS" not in source or "POST_PARAMS" not in source:
        violations.append("missing pre/post parameter sets")
    if "g.best_close" not in source:
        violations.append("missing persistent trailing-stop state")

    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V1.6 static audit: 0 violations")


if __name__ == "__main__":
    main()
