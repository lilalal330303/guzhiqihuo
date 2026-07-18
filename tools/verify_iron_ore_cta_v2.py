"""静态审计铁矿石 CTA V2 的关键安全约束。"""

from pathlib import Path
import re


SCRIPT = Path(__file__).resolve().parents[1] / "reports" / "jq_iron_ore_cta_v2.py"


def audit_script(text):
    violations = []
    if "get_bars(" in text:
        violations.append("script must not use get_bars; use point-in-time get_price")
    if "g.flag = 1" in text or "g.flag=1" in text:
        violations.append("script must not mark a position full without actual-fill reconciliation")
    if "get_all_securities([\"futures\"], date=" not in text:
        violations.append("futures metadata must be queried with a signal date")
    if 'set_option("avoid_future_data", True)' not in text:
        violations.append("avoid_future_data must be enabled")
    if re.search(r"order_target\([^\n]*IC\d{4}\.CCFX", text, flags=re.IGNORECASE):
        violations.append("trade executor must not contain IC equity-index contracts")
    if 're.match(r"^I\\d{4}\\.XDCE$"' not in text:
        violations.append("contract selection must enforce I####.XDCE")
    return violations


def main():
    violations = audit_script(SCRIPT.read_text(encoding="utf-8"))
    if violations:
        for item in violations:
            print("VIOLATION:", item)
        raise SystemExit(1)
    print("iron ore CTA V2 static audit: 0 violations")


if __name__ == "__main__":
    main()
