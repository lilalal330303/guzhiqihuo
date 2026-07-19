from pathlib import Path
import re


SCRIPT = Path(__file__).resolve().parents[1] / "reports" / "jq_iron_ore_cta_v1_2_balance.py"


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    violations = []
    if re.search(r"(?m)^\s*(from|import)\s+reports", source):
        violations.append("contains a local reports package import")
    if "get_bars(" in source:
        violations.append("uses get_bars without an explicit point-in-time guard")
    if "max_margin_usage\": 0.70" in source or "max_margin_usage = 0.70" in source:
        violations.append("retains the old 70% margin budget")
    if re.search(r"get_all_securities\(\s*\[\s*[\"']futures[\"']\s*\]\s*\)", source):
        violations.append("futures metadata is requested without a date")
    if "from __future__" in source:
        violations.append("contains a future import incompatible with older JoinQuant runtimes")
    if not re.search(r"\^I\\d\{4\}\\\.XDCE\$", source):
        violations.append("does not anchor contract selection to I####.XDCE")
    if "end_date=signal_date" not in source:
        violations.append("missing signal-date cutoff for market data")
    if "ALLOW_SHORT = False" not in source:
        violations.append("short mode is not disabled by default")
    if '"target_annual_vol": 0.22' not in source:
        violations.append("V1.2 target volatility is not 22%")
    if '"max_leverage": 2.5' not in source:
        violations.append("V1.2 max leverage is not 2.5")
    if '"max_margin_usage": 0.45' not in source:
        violations.append("V1.2 max margin usage is not 45%")
    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V1.2 static audit: 0 violations")


if __name__ == "__main__":
    main()
