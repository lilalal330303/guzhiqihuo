# Size-Style Rotation V3.0 Original-Replica Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver an independent JoinQuant Python 3 script whose default behavior reproduces the supplied V2.0 strategy, while providing a narrowly scoped STRICT_ASOF comparison mode and only the compatibility fixes needed for current JoinQuant pandas/JQData responses.

**Architecture:** Keep the strategy in one self-contained file under reports/, because JoinQuant requires a single copy-pasteable script. Retain the original schedule, candidate rules, style ratio, branch direction, and order path; isolate run-mode date semantics and price-frame compatibility in small helpers. Local tests import the script under an empty jqdata stub and exercise pure logic without claiming a cloud backtest result.

**Tech Stack:** Python 3, JoinQuant jqdata, pandas/numpy in the JoinQuant runtime, pytest, and Python AST checks.

## Global Constraints

- RUN_MODE = "ORIGINAL_REPLICA" is the default; STRICT_ASOF changes only fundamental and index-constituent dates.
- Preserve benchmark 000985.XSHG, use_real_price=True, avoid_future_data=True, zero slippage, original stock costs, stock count 5, monthly day-1 rebalance, and 09:05/14:00/14:30 schedules.
- Preserve the original SMALL and BIG candidate rules, including BIG's use of the broad stocks pool rather than silently replacing it with choice.
- Preserve mean_2000 / mean_500 > 1.2 -> BIG, otherwise SMALL, including the original variable/index mapping.
- Do not add V2.1/V2.2 trend confirmation, volatility normalization, risk-off cash, hysteresis, candidate buffers, market guards, winsorization, or forced holding preservation.
- Do not modify the user-provided original source outside this repository.
- Never use pivot_table(sort=...); the reported JoinQuant runtime rejects that keyword.
- Compatibility fallbacks may accept long/wide get_price responses but must not add a signal filter or change the 20-day/40-day windows.
- ORIGINAL_REPLICA is a research/backtest replication mode and must be documented as not proving live no-lookahead behavior.

## File Map

- Create reports/joinquant_size_style_rotation_v30_original_replica.py: the independent copy-pasteable JoinQuant strategy.
- Create reports/joinquant_size_style_rotation_v30_original_replica_readme.md: run modes, preserved behavior, rejected paths, and validation checklist.
- Create tests/test_joinquant_size_style_rotation_v30_original_replica.py: local import, pure-function, compatibility, and AST guard tests.
- Preserve reports/joinquant_size_style_rotation_v21.py, reports/joinquant_size_style_rotation_v22_original_compatible.py, and the original source.

## Stable Interfaces

The script must expose these names for tests and later tasks:

    RUN_MODE = "ORIGINAL_REPLICA"

    def fundamental_date(context):
        """None in ORIGINAL_REPLICA; previous_date in STRICT_ASOF."""

    def constituent_date(context):
        """current_dt in ORIGINAL_REPLICA; previous_date in STRICT_ASOF."""

    def select_style_branch(mean_2000, mean_500, ratio_threshold=1.2):
        """BIG, SMALL, or None for an unusable ratio."""

    def safe_close_frame(raw_prices):
        """A date-indexed wide close DataFrame or None."""

    def select_target_list(context, branch):
        """The original-ranked SMALL or BIG target list."""

### Task 1: Add failing local tests for the baseline contracts

Files:
- Create tests/test_joinquant_size_style_rotation_v30_original_replica.py
- Test target: reports/joinquant_size_style_rotation_v30_original_replica.py

Interfaces:
- Consumes the stable interfaces above.
- Produces executable tests that fail before the script exists and prevent the known no-trade and unsupported-pandas regressions.

- [ ] Step 1: Write the import fixture and failing contract tests.

Create a loader that inserts an empty jqdata module into sys.modules, loads the target file with importlib.util.spec_from_file_location, and resets module.RUN_MODE to ORIGINAL_REPLICA after each test. Add tests with these assertions:

    def test_default_mode_and_date_semantics(module):
        context = SimpleNamespace(
            previous_date=date(2020, 1, 1),
            current_dt=datetime(2020, 1, 2, 9, 30),
        )
        assert module.RUN_MODE == "ORIGINAL_REPLICA"
        assert module.fundamental_date(context) is None
        assert module.constituent_date(context) == context.current_dt

    def test_strict_asof_changes_only_the_two_date_adapters(module):
        context = SimpleNamespace(
            previous_date=date(2020, 1, 1),
            current_dt=datetime(2020, 1, 2, 9, 30),
        )
        module.RUN_MODE = "STRICT_ASOF"
        assert module.fundamental_date(context) == context.previous_date
        assert module.constituent_date(context) == context.previous_date

    def test_original_branch_direction_and_zero_denominator(module):
        assert module.select_style_branch(30.0, 20.0) == "BIG"
        assert module.select_style_branch(20.0, 30.0) == "SMALL"
        assert module.select_style_branch(1.0, 0.0) is None

    def test_price_normalizer_accepts_long_multiindex_without_sort_keyword(module):
        index = pd.MultiIndex.from_tuples(
            [(date(2020, 1, 1), "000001.XSHE"),
             (date(2020, 1, 2), "000001.XSHE")],
            names=["time", "code"],
        )
        raw = pd.DataFrame({"close": [10.0, 11.0]}, index=index)
        result = module.safe_close_frame(raw)
        assert list(result.columns) == ["000001.XSHE"]
        assert result["000001.XSHE"].tolist() == [10.0, 11.0]

- [ ] Step 2: Run the focused tests to verify the intended failure.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q

Expected: collection fails because the target script does not yet exist. No existing strategy file may be changed to make the tests collect.

- [ ] Step 3: Commit the failing-test scaffold.

    git add -- tests/test_joinquant_size_style_rotation_v30_original_replica.py
    git commit -m "test: specify v3 original replica contracts"

### Task 2: Implement date-mode adapters and price compatibility

Files:
- Create reports/joinquant_size_style_rotation_v30_original_replica.py
- Test tests/test_joinquant_size_style_rotation_v30_original_replica.py

Interfaces:
- Consumes Task 1 tests.
- Produces RUN_MODE, fundamental_date, constituent_date, select_style_branch, safe_close_frame, and a valid jqdata import surface.

- [ ] Step 1: Add the minimal header and pure helpers.

Start the script with a docstring stating that the default mode intentionally reproduces the original backtest date semantics. Define:

    RUN_MODE = "ORIGINAL_REPLICA"
    INDEX_2000 = "399303.XSHE"
    INDEX_500 = "399905.XSHE"
    MARKET_INDEX = "000985.XSHG"

    def fundamental_date(context):
        return context.previous_date if RUN_MODE == "STRICT_ASOF" else None

    def constituent_date(context):
        return context.previous_date if RUN_MODE == "STRICT_ASOF" else context.current_dt

    def select_style_branch(mean_2000, mean_500, ratio_threshold=1.2):
        try:
            numerator = float(mean_2000)
            denominator = float(mean_500)
            threshold = float(ratio_threshold)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(numerator) or not np.isfinite(denominator):
            return None
        if abs(denominator) <= 1e-12:
            return None
        return "BIG" if numerator / denominator > threshold else "SMALL"

Implement safe_close_frame(raw_prices) for a wide frame, a long frame with code and close, and a two-level MultiIndex with date/time and code. Use pivot_table(index=..., columns=..., values=..., aggfunc="last") only; convert close with pd.to_numeric, drop invalid dates, and sort the resulting date index. Do not add minimum-sample, winsorization, or risk guards.

- [ ] Step 2: Run the focused tests and fix only minimal failures.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q

Expected: all four contract tests pass. If the empty jqdata stub cannot support wildcard import, adjust only the test loader or import guard; do not add a strategy readiness gate.

- [ ] Step 3: Commit the adapter implementation.

    git add -- reports/joinquant_size_style_rotation_v30_original_replica.py tests/test_joinquant_size_style_rotation_v30_original_replica.py
    git commit -m "feat: add v3 run modes and price compatibility"

### Task 3: Port original candidate and rebalance behavior without new filters

Files:
- Modify reports/joinquant_size_style_rotation_v30_original_replica.py
- Test tests/test_joinquant_size_style_rotation_v30_original_replica.py

Interfaces:
- Consumes Task 2 date adapters and safe_close_frame.
- Produces initialize, prepare_stock_list, SMALL, BIG, select_target_list, weekly_adjustment, order_target_value_, open_position, close_position, and the original filters.

- [ ] Step 1: Add failing tests for target mechanics.

Add pure tests for exclude_recent_limit_up_holdings(ranked, holdings, recent_limit_ups):

    def test_recent_limit_up_blacklist_removes_only_held_recent_limit_up(module):
        assert module.exclude_recent_limit_up_holdings(
            ["A", "B", "C"], ["A", "C"], ["A"]
        ) == ["B", "C"]

    def test_target_selection_does_not_keep_non_target_holdings(module):
        assert module.rebalance_lists(
            holdings=["OLD"], target=["NEW"], protected=[]
        ) == (["OLD"], ["NEW"])

    def test_target_selection_keeps_protected_yesterday_limit_up(module):
        assert module.rebalance_lists(
            holdings=["OLD"], target=["NEW"], protected=["OLD"]
        ) == ([], ["NEW"])

rebalance_lists returns (sell_list, buy_list) and represents original behavior: sell every current holding absent from target unless protected; buy target symbols not currently held. It must not merge all holdings into the target or allocate a candidate buffer.

- [ ] Step 2: Run the new tests and confirm they fail before implementation.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q

Expected: the three new tests fail because the helper functions do not yet exist.

- [ ] Step 3: Port the original functions with exact rules.

1. initialize sets benchmark/options, FixedSlippage(0), original OrderCost, order log level, g.stock_num = 5, g.hold_list, g.yesterday_HL_list, and schedules prepare_stock_list at 09:05, weekly_adjustment monthly day 1 at 09:30, check_limit_up at 14:00, and close_account at 14:30.
2. prepare_stock_list derives current holdings and checks yesterday close == high_limit; accept a code column or a MultiIndex/one-security response.
3. Keep filter_kcbj_stock, filter_st_stock, filter_paused_stock, filter_new_stock, filter_limitup_stock, filter_limitdown_stock, and filter_highprice_stock equivalent to the original. filter_highprice_stock keeps held stocks and admits only last-minute close below 10.
4. get_peg uses get_fundamentals(quality_query, date=fundamental_date(context)) and a market-cap ascending query using the same adapter. Default therefore passes date=None; strict mode passes previous_date.
5. SMALL uses all stocks available as of previous_date, applies original filters, calls get_peg, removes held symbols in the recent 40-day limit-up list, and returns the first five remaining symbols.
6. BIG constructs the original filtered choice but intentionally uses broad stocks in the fundamental query, with the original valuation/indicator filters, descending market cap, and limit 5. Pass date=fundamental_date(context).
7. select_target_list dispatches only BIG or SMALL; there is no risk-off branch.
8. rebalance_lists and weekly_adjustment sell non-target/non-protected positions, then divide available cash by missing target positions and call open_position in target order until filled. Do not preserve non-target holdings because of a buffer.

- [ ] Step 4: Run target tests and syntax check.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q
    python -m py_compile reports/joinquant_size_style_rotation_v30_original_replica.py

Expected: focused tests pass and py_compile exits 0.

- [ ] Step 5: Commit the original candidate/rebalance port.

    git add -- reports/joinquant_size_style_rotation_v30_original_replica.py tests/test_joinquant_size_style_rotation_v30_original_replica.py
    git commit -m "feat: restore original candidate and rebalance path"

### Task 4: Port style signal, order safeguards, and schedules without changing signals

Files:
- Modify reports/joinquant_size_style_rotation_v30_original_replica.py
- Test tests/test_joinquant_size_style_rotation_v30_original_replica.py

Interfaces:
- Consumes Task 3 candidates and date adapters.
- Produces a complete copy-pasteable strategy with runtime logging and no known no-trade failure from pivot_table(sort=...).

- [ ] Step 1: Add failing AST/source tests for known regressions.

Parse the target script and assert:

    source = Path(SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "pivot_table(sort=" not in source
    assert "risk_off" not in source
    assert "candidate_buffer" not in source
    assert "winsorize" not in source

Also assert the source contains date=constituent_date(context), count=20, and a style signal unavailable keep-hold log.

- [ ] Step 2: Run the AST tests and confirm the expected failures.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q

Expected: source-level checks fail until the complete runtime is added, and identify a missing function or substring rather than an unrelated repository failure.

- [ ] Step 3: Implement the style and order runtime.

Implement weekly_adjustment with this sequence:

    yesterday = context.previous_date
    stock_list_2000 = get_index_stocks(INDEX_2000, date=constituent_date(context))
    stock_list_500 = get_index_stocks(INDEX_500, date=constituent_date(context))
    mean_2000 = cross_sectional_mean_return(
        get_price(stock_list_2000, end_date=yesterday, frequency="1d",
                  fields=["close"], count=20),
    )
    mean_500 = cross_sectional_mean_return(
        get_price(stock_list_500, end_date=yesterday, frequency="1d",
                  fields=["close"], count=20),
    )
    branch = select_style_branch(mean_2000, mean_500)
    if branch is None:
        log.warn("style signal unavailable; keep current holdings")
        return
    target_list = select_target_list(context, branch)
    sell_list, buy_list = rebalance_lists(
        g.hold_list, target_list, g.yesterday_HL_list
    )

cross_sectional_mean_return uses first/last rows of the normalized close matrix, calculates (last - first) / first * 100, and takes the arithmetic mean. It may return None only for empty or unusable data; it must not winsorize, normalize by volatility, require a new sample rule, or compare a moving average.

Implement check_limit_up with the original 1-minute close/high-limit check, order_target_value_, open_position, close_position, and close_account. Order failures are logged and skipped, not converted into a global no-trade state. Keep the original protected yesterday-limit-up behavior.

- [ ] Step 4: Run all focused tests and compile the final script.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q
    python -m py_compile reports/joinquant_size_style_rotation_v30_original_replica.py

Expected: all focused tests pass and compilation succeeds.

- [ ] Step 5: Commit the complete runtime.

    git add -- reports/joinquant_size_style_rotation_v30_original_replica.py tests/test_joinquant_size_style_rotation_v30_original_replica.py
    git commit -m "feat: complete v3 original replica runtime"

### Task 5: Add user-facing run instructions and experiment separation

Files:
- Create reports/joinquant_size_style_rotation_v30_original_replica_readme.md
- Modify the script only if documentation comments are missing

Interfaces:
- Consumes the complete Task 4 script.
- Produces unambiguous operating instructions for default replication and later experiments.

- [ ] Step 1: Write the README with exact run instructions.

Include:

    1. Copy reports/joinquant_size_style_rotation_v30_original_replica.py into a JoinQuant Python3 strategy.
    2. Leave RUN_MODE = "ORIGINAL_REPLICA" for the first comparison.
    3. Use the original screenshot/backtest date range, cash, benchmark, and minute frequency.
    4. Compare monthly branch, target list, trade count, and fills before comparing return.
    5. Only after baseline alignment, change RUN_MODE to "STRICT_ASOF" as E1.

Document that ORIGINAL_REPLICA intentionally retains date=None fundamentals and current-time constituent lookup for backtest comparability, while STRICT_ASOF is the safer research comparator. List rejected V2.1/V2.2 paths and E1-E4 one-variable experiment order. Do not claim a cloud return number until the user runs the script.

- [ ] Step 2: Validate references and commit.

Run:
    rg -n "ORIGINAL_REPLICA|STRICT_ASOF|E1|E2|E3|E4|candidate_buffer|risk-off|pivot_table" reports/joinquant_size_style_rotation_v30_original_replica_readme.md

Expected: every required mode and rejected path is present.

    git add -- reports/joinquant_size_style_rotation_v30_original_replica_readme.md
    git commit -m "docs: explain v3 original replica usage"

### Task 6: Run final local verification and prepare the handoff

Files:
- Verify the three V3 deliverables.
- Do not stage or modify unrelated dirty files.

Interfaces:
- Consumes Tasks 1-5.
- Produces evidence-backed local verification and a concise JoinQuant handoff.

- [ ] Step 1: Run the focused suite, compile check, and whitespace check.

Run:
    pytest tests/test_joinquant_size_style_rotation_v30_original_replica.py -q
    python -m py_compile reports/joinquant_size_style_rotation_v30_original_replica.py
    git diff --check HEAD~5..HEAD -- reports/joinquant_size_style_rotation_v30_original_replica.py reports/joinquant_size_style_rotation_v30_original_replica_readme.md tests/test_joinquant_size_style_rotation_v30_original_replica.py

Expected: focused tests pass, compilation succeeds, and diff check prints no errors.

- [ ] Step 2: Audit known regressions.

Run:
    rg -n "pivot_table\\([^\\n]*sort=|risk_off|candidate_buffer|winsorize|market_guard|hysteresis|PriceRelatedSlippage|style signal unavailable" reports/joinquant_size_style_rotation_v30_original_replica.py

Expected: no forbidden optimization terms; the only permitted match is the explicit style signal unavailable keep-hold log.

- [ ] Step 3: Inspect final diff and status.

Run:
    git status --short
    git log --oneline -6 -- reports/joinquant_size_style_rotation_v30_original_replica.py reports/joinquant_size_style_rotation_v30_original_replica_readme.md tests/test_joinquant_size_style_rotation_v30_original_replica.py

Expected: only the three new deliverables are in the V3 commits; unrelated user files remain unstaged and unchanged.

- [ ] Step 4: Report JoinQuant validation procedure without inventing results.

The handoff links the script and README, states local tests cover pure logic only, and instructs ORIGINAL_REPLICA first. Request first six monthly style logs, target lists, filled orders, total trades, return, annualized return, maximum drawdown, Sharpe, plus 2020-2021, 2022-2023, and 2024-2026 windows. Do not present screenshot metrics as new-script results.

## Self-Review Checklist

- Spec coverage: Sections 1-3 map to Tasks 2-4; compatibility boundaries map to Tasks 2 and 4; single-variable experiments/logging map to Task 5; validation/handoff map to Task 6.
- Placeholder scan: the plan contains no unresolved placeholder markers or unnamed edge-case work; every task names files, commands, and expected outcomes.
- Type consistency: fundamental_date, constituent_date, select_style_branch, safe_close_frame, select_target_list, rebalance_lists, and exclude_recent_limit_up_holdings are defined before later tasks consume them.
- Scope safety: the original source and unrelated dirty files remain outside staging commands.
