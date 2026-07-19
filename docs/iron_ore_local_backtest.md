# 铁矿石 CTA V1.6 本地数据与回测

研究端导出函数会同时生成目录和同名 ZIP 文件，例如：

~~~text
iron_ore_v1_6_export/
iron_ore_v1_6_export.zip
~~~

正式下载时只需要下载 ZIP。本地导入命令的 --input 参数同时支持目录和 ZIP：

~~~powershell
.\.venv\Scripts\python.exe tools/import_iron_ore_v1_6.py --input .\iron_ore_v1_6_export.zip --db .\data\market.duckdb
~~~

## 一、需要从聚宽研究端下载什么

首版日频本地回测需要四类数据：

1. **I8888.XDCE 主连日线**：用于 V1.6 信号和 ATR/波动率计算。
2. **所有实际铁矿石合约 I####.XDCE 日线**：用于下一交易日开盘成交、持仓估值和换月。
3. **合约元数据**：合约上市日和到期日。
4. **点时合约宇宙**：每个 asof_date 当天聚宽可见的铁矿石合约列表，防止本地回测使用未来合约。

日线字段为：

~~~text
symbol, trade_date, open, high, low, close, volume, amount, open_interest
~~~

其中 amount 在聚宽研究端由 money 字段标准化而来。分钟线不是 V1.6 首版必需数据；如果后续要尽量复现聚宽 09:05 的成交，另行下载目标合约 1 分钟线。

## 二、在聚宽研究环境导出

把下面脚本复制到聚宽“研究”环境运行，不要放到策略编辑器：

~~~text
reports/jq_research_export_iron_ore_v1_6.py
~~~

研究环境中执行：

~~~python
manifest = export_iron_ore_v16_bundle(
    start_date="2018-01-01",
    end_date="2026-07-18",
    output_dir="iron_ore_v1_6_export",
    metadata_stride=1,
)
manifest
~~~

metadata_stride=1 表示每个交易日导出一次点时合约宇宙，最严格但查询较多。先验证流程时可以使用 metadata_stride=5，正式回测建议恢复为 1。

将研究目录中的以下五个文件下载到本地同一目录：

~~~text
iron_ore_main_daily.csv
iron_ore_contract_daily.csv
iron_ore_contracts.csv
iron_ore_universe_daily.csv
manifest.json
~~~

## 三、导入本地 DuckDB

在项目根目录执行：

~~~powershell
.\.venv\Scripts\python.exe tools/import_iron_ore_v1_6.py --input-dir .\iron_ore_v1_6_export --db .\data\market.duckdb
~~~

导入器会创建或更新：

~~~text
iron_ore_main_daily
iron_ore_contract_daily
iron_ore_contracts
iron_ore_universe_daily
~~~

导入过程会拒绝重复主键、非法合约代码、非正 OHLC 和非法上市/到期日。重复导入同一批数据是幂等的。

## 四、运行本地 V1.6 回测

~~~powershell
.\.venv\Scripts\python.exe tools/run_iron_ore_v1_6_local.py --db .\data\market.duckdb --start 2018-01-01 --end 2026-07-18 --initial-cash 1000000 --output-dir .\reports\iron_ore_v1_6_local_backtest
~~~

结果文件：

~~~text
signals.csv
trades.csv
equity_curve.csv
metrics.json
~~~

本地回测采用“信号日 T、下一交易日 T+1 开盘执行”，是对聚宽分钟回测的透明日频近似，不应直接要求收益曲线逐笔一致。建议分三段比较：

~~~text
2018-01-01 至 2023-12-31
2024-01-01 至最近日期
2018-01-01 至最近日期
~~~

重点核对：空头成交数量、换月日期、最大回撤、2024 年后的空头贡献、以及本地与聚宽的手续费/滑点差异。
