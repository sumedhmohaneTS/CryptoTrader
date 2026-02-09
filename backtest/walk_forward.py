"""Walk-forward validation engine.

Splits the total date range into rolling train/test windows and runs
a backtest on each test window.  Compares in-sample (train) vs
out-of-sample (test) performance to detect overfitting.

Usage:
    from backtest.walk_forward import WalkForwardEngine
    wf = WalkForwardEngine("2025-06-01", "2026-02-01")
    wf.run()
"""

from dataclasses import dataclass, field
from datetime import datetime

from dateutil.relativedelta import relativedelta

from backtest.engine import BacktestEngine
from backtest.reporter import BacktestReporter


@dataclass
class WindowResult:
    """Metrics for a single train or test window."""
    start: str
    end: str
    total_return_pct: float
    trades: int
    win_rate: float
    max_drawdown_pct: float
    profit_factor: float
    final_balance: float


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward output."""
    windows: list[tuple[WindowResult, WindowResult]] = field(default_factory=list)


class WalkForwardEngine:
    """Rolling-window walk-forward validation.

    Parameters
    ----------
    start : str           Overall start date (YYYY-MM-DD).
    end : str             Overall end date (YYYY-MM-DD).
    train_months : int    Length of each training window in months.
    test_months : int     Length of each testing window in months.
    step_months : int     How far to slide the window each iteration.
    initial_balance : float
    """

    def __init__(
        self,
        start: str,
        end: str,
        train_months: int = 2,
        test_months: int = 1,
        step_months: int = 1,
        initial_balance: float = 100.0,
    ):
        self.start = datetime.strptime(start, "%Y-%m-%d")
        self.end = datetime.strptime(end, "%Y-%m-%d")
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months
        self.initial_balance = initial_balance

    def _generate_windows(self) -> list[tuple[str, str, str, str]]:
        """Generate (train_start, train_end, test_start, test_end) tuples."""
        windows = []
        cursor = self.start

        while True:
            train_start = cursor
            train_end = cursor + relativedelta(months=self.train_months)
            test_start = train_end
            test_end = test_start + relativedelta(months=self.test_months)

            if test_end > self.end:
                break

            windows.append((
                train_start.strftime("%Y-%m-%d"),
                train_end.strftime("%Y-%m-%d"),
                test_start.strftime("%Y-%m-%d"),
                test_end.strftime("%Y-%m-%d"),
            ))
            cursor += relativedelta(months=self.step_months)

        return windows

    @staticmethod
    def _run_window(start: str, end: str, balance: float) -> WindowResult:
        """Run a single backtest window and extract key metrics."""
        engine = BacktestEngine(
            start_date=start,
            end_date=end,
            initial_balance=balance,
        )
        result = engine.run()
        reporter = BacktestReporter(result)

        dd_pct, _ = reporter.max_drawdown()

        return WindowResult(
            start=start,
            end=end,
            total_return_pct=reporter.total_return_pct(),
            trades=len(result.trades),
            win_rate=reporter.win_rate(),
            max_drawdown_pct=dd_pct,
            profit_factor=reporter.profit_factor(),
            final_balance=result.final_balance,
        )

    def run(self) -> WalkForwardResult:
        """Execute walk-forward analysis and print comparison table."""
        windows = self._generate_windows()
        if not windows:
            print("Not enough date range for walk-forward windows.")
            return WalkForwardResult()

        print(f"\nWalk-Forward Validation: {len(windows)} window(s)")
        print(f"Train: {self.train_months}mo | Test: {self.test_months}mo | Step: {self.step_months}mo")
        print()

        wf_result = WalkForwardResult()

        for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows, 1):
            print(f"--- Window {i}/{len(windows)} ---")
            print(f"  Train: {tr_s} -> {tr_e}")
            train_res = self._run_window(tr_s, tr_e, self.initial_balance)

            print(f"  Test:  {te_s} -> {te_e}")
            test_res = self._run_window(te_s, te_e, self.initial_balance)

            wf_result.windows.append((train_res, test_res))
            print()

        # Print comparison table
        self._print_table(wf_result)

        return wf_result

    @staticmethod
    def _print_table(wf_result: WalkForwardResult):
        """Print a per-window comparison table."""
        print("=" * 90)
        print("  WALK-FORWARD COMPARISON")
        print("=" * 90)
        header = (
            f"  {'Window':<8} {'Period':<24} {'Return':>8} {'Trades':>7} "
            f"{'WinRate':>8} {'MaxDD':>8} {'PF':>6}"
        )
        print(header)
        print(f"  {'-'*8} {'-'*24} {'-'*8} {'-'*7} {'-'*8} {'-'*8} {'-'*6}")

        for i, (train, test) in enumerate(wf_result.windows, 1):
            # Train row
            print(
                f"  {'T' + str(i):<8} {train.start + ' -> ' + train.end:<24} "
                f"{train.total_return_pct:>+7.2%} {train.trades:>7} "
                f"{train.win_rate:>7.1%} {train.max_drawdown_pct:>7.2%} "
                f"{train.profit_factor:>6.2f}"
            )
            # Test row
            print(
                f"  {'V' + str(i):<8} {test.start + ' -> ' + test.end:<24} "
                f"{test.total_return_pct:>+7.2%} {test.trades:>7} "
                f"{test.win_rate:>7.1%} {test.max_drawdown_pct:>7.2%} "
                f"{test.profit_factor:>6.2f}"
            )

        # Summary
        train_returns = [t.total_return_pct for t, _ in wf_result.windows]
        test_returns = [t.total_return_pct for _, t in wf_result.windows]
        avg_train = sum(train_returns) / len(train_returns) if train_returns else 0
        avg_test = sum(test_returns) / len(test_returns) if test_returns else 0

        print()
        print(f"  Avg Train Return: {avg_train:+.2%}")
        print(f"  Avg Test Return:  {avg_test:+.2%}")
        if avg_train != 0:
            ratio = avg_test / avg_train
            print(f"  Test/Train Ratio: {ratio:.2f}  (>0.5 = reasonable generalization)")
        print("=" * 90)
