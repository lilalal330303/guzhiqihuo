# Fusion ETF Rotation Design

## Decision

Build a single fused ETF rotation strategy with the latest JoinQuant Wufu script as the base:

- Base script: `reports/jq_wufu_fixed_pool_v12c_ultra_split.py`
- Local strategy layer: `src/quant_lab/strategies/wufu_etf_rotation.py`
- Output JoinQuant script: `reports/jq_fusion_etf_rotation_v1.py`

The fused strategy keeps Wufu V12C as the primary engine. Qixing is not kept as an independent strategy. Its useful ideas are folded into Wufu as optional candidate-pool and scoring enhancements.

## Goals

- Remove unused small-cap, blue-chip, and multi-strategy account logic from the old three-in-one script.
- Preserve Wufu V12C behavior as the baseline unless a Qixing enhancement is explicitly enabled.
- Fuse Qixing and Wufu into one target-generation pipeline, one holding set, and one order path.
- Avoid ownership conflicts by removing strategy IDs, virtual sub-accounts, and parallel schedulers.
- Keep the local version testable and reusable by the quant research workbench.
- Produce a clean JoinQuant script that can run as a standalone ETF strategy.

## Non-Goals

- Do not preserve small-cap stock selection, white-horse stock selection, or the old ETF rebound strategy.
- Do not implement live trading outside JoinQuant's normal order APIs.
- Do not weaken the T-day signal and T+1 execution contract in local backtests.
- Do not add Streamlit UI changes in this pass.

## Architecture

### Local Strategy Module

Extend the existing Wufu strategy module with a fusion configuration and target generator:

- `FusionEtfRotationConfig`
- `QixingEnhancementConfig`
- `generate_fusion_etf_targets()`

The local fusion target generator will reuse the existing Wufu primitives where possible:

- Wufu fixed ETF pools.
- Dynamic ETF pool snapshots.
- JoinQuant-style liquidity thresholds.
- Weak-state generation.
- Wufu momentum scoring: weighted log-price regression annualized return multiplied by R-squared.
- Defensive ETF fallback.

Qixing enhancement inputs are folded into the same candidate records rather than producing a second target list.

### JoinQuant Script

Create a new clean script derived from `jq_wufu_fixed_pool_v12c_ultra_split.py`.

The script keeps Wufu V12C's core schedule:

- Morning state and pool preparation around 09:40.
- Signal calculation around 13:10.
- Unified execution around 13:11.
- Pending buy trend checks at 13:40, 14:10, and 14:30.
- Force-buy fallback at the V12C configured force-buy time.
- Capacity split processing on each bar when enabled.
- Minute stop loss.
- Daily reset.

It removes:

- Small-cap strategy code.
- Blue-chip strategy code.
- Qixing standalone scheduler.
- Virtual sub-account logic.
- `stock_strategy` ownership routing.
- Repeated `make_record` / `print_summary` style registrations from the old combined script.

## Fusion Logic

The fused ETF universe is:

1. Wufu V12C baseline fixed pool.
2. Wufu dynamic pool when available.
3. Qixing selected ETF pool, deduplicated into the same universe.
4. Defensive ETF.

Weak-market handling remains Wufu-led. When Wufu V12C marks the market weak, the pool is narrowed using the Wufu weak-market logic first. Qixing symbols may only participate if they survive that same weak-market policy.

Each candidate has one unified score:

```text
fusion_score = wufu_score + qixing_bonus - qixing_penalties
```

Default behavior keeps `qixing_bonus = 0`, so the first implementation can prove baseline compatibility. Enhancements can then be enabled through config without changing the order path.

Qixing-derived enhancements:

- Preferred-pool bonus for symbols in the Qixing ETF pool.
- Short-momentum confirmation.
- Liquidity floor.
- Volume spike veto.
- Premium-rate veto where data is available.
- Optional profit-protection style exit flag for current holdings.

## Conflict Prevention

There is exactly one target list and one set of current holdings.

The implementation must not use:

- Strategy IDs.
- Per-strategy virtual cash accounts.
- Separate Qixing and Wufu order functions.
- Separate sell/buy schedules for Qixing and Wufu.
- Ownership maps such as `stock_strategy`.

If an ETF appears in both Wufu and Qixing pools, it appears once in the fused pool with metadata showing both sources.

## Parameters

Keep Wufu V12C parameters that affect:

- ETF pools.
- Weak-state logic.
- Momentum scoring.
- Candidate filtering.
- Signal timing.
- Execution buffer.
- Round-lot handling.
- Capacity split.
- Stop loss.
- Defensive fallback.

Remove parameters that only serve:

- Small-cap strategy.
- Blue-chip strategy.
- Old ETF rebound strategy.
- Multi-strategy portfolio allocation.
- Strategy ownership routing.
- Duplicated summary schedules.

Qixing parameters are reduced to an enhancement block:

- `enabled`
- `pool`
- `preferred_pool_bonus`
- `short_lookback_days`
- `short_momentum_min`
- `liquidity_lookback_days`
- `liquidity_threshold`
- `volume_lookback_days`
- `volume_threshold`
- `premium_threshold`

## Data Flow

Local:

1. Load ETF prices and optional metadata from DuckDB.
2. Generate weak states using Wufu-compatible logic or supplied states.
3. Generate dynamic pool snapshots if metadata is available.
4. Build the fused pool for each date.
5. Score and filter candidates once.
6. Emit one target row per trade date.
7. Backtest uses T-day target and T+1 execution through existing backtest modules.

JoinQuant:

1. Morning routine prepares weak state and pool.
2. Signal routine ranks fused candidates and writes one intended target.
3. Execute routine sells non-target holdings and buys the target through the single order path.
4. Capacity split and pending-buy checks operate on the same target.
5. Stop-loss and reset routines update one strategy state.

## Testing

Add tests before implementation for:

- Duplicate symbols from Wufu and Qixing appear once in the fused universe.
- With Qixing disabled, fusion targets match Wufu baseline targets on a controlled dataset.
- With Qixing bonus enabled, a Qixing symbol can outrank an otherwise close Wufu candidate.
- Weak-market mode applies Wufu weak-pool constraints before Qixing enhancement.
- No candidate falls back to the defensive ETF.
- The exported JoinQuant script does not contain small-cap, blue-chip, virtual sub-account, `portfolio_value_proportion`, or `stock_strategy` logic.

## Verification

Run focused tests:

```powershell
python -m pytest tests/test_wufu_etf_rotation.py tests/test_fusion_etf_rotation.py -q
```

Run full tests if focused tests pass:

```powershell
python -m pytest -q
```

Static-check the generated JoinQuant script:

```powershell
python -m py_compile reports/jq_fusion_etf_rotation_v1.py
```

## Open Risk

The latest Wufu V12C script is a standalone JoinQuant script while the local workbench has a cleaner reusable module. The implementation should avoid copying the whole script into the strategy module. Instead, local code should express the shared decision logic and the exported JoinQuant script should remain the platform adapter.
