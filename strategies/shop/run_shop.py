import argparse
import sys
import os
import pandas as pd
from datetime import datetime, date

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from strategies.shop.strategy import ShopStrategy
from core.utils import format_inr
import skas_data

def main():
    parser = argparse.ArgumentParser(description='Run Shop Strategy Backtest')
    parser.add_argument('symbols', type=str, help='Comma-separated list of symbols (e.g., RELIANCE,TCS)')
    parser.add_argument('--capital', type=float, default=500000, help='Initial Capital (default: 500000)')
    parser.add_argument('--parts', type=int, default=40, help='Capital Parts (default: 40)')
    parser.add_argument('--new-drop', type=float, default=0.10, help='New Buy Drop %% (default: 0.10)')
    parser.add_argument('--avg-drop', type=float, default=0.05, help='Avg Buy Drop %% (default: 0.05)')
    parser.add_argument('--target', type=float, default=0.03, help='Profit Target %% (default: 0.03)')
    parser.add_argument('--start-date', type=str, default='2020-01-01', help='Start Date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None, help='End Date (YYYY-MM-DD), default is Today')
    parser.add_argument('--csv', nargs='?', const='auto', default=None, help='Export Trade Log to CSV. Optional filename.')
    parser.add_argument('--verbose', action='store_true', help='Verbose Output')
    
    args = parser.parse_args()
    
    symbol_list = [s.strip() for s in args.symbols.split(',')]
    
    # Parse Dates
    try:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    except ValueError:
        print("Invalid start date format. Use YYYY-MM-DD")
        return

    if args.end_date:
        try:
            end_dt = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            print("Invalid end date format. Use YYYY-MM-DD")
            return
    else:
        end_dt = date.today()
    
    print(f"Backtesting Shop Strategy on {len(symbol_list)} symbols from {start_dt} to {end_dt}")
    
    # Initialize Data Provider
    sd = skas_data.SkasData(cache_only=True)
    
    # Initialize Strategy
    strategy = ShopStrategy(
        universe=symbol_list,
        initial_capital=args.capital,
        capital_parts=args.parts,
        new_buy_drop_threshold=args.new_drop,
        avg_buy_drop_threshold=args.avg_drop,
        profit_target=args.target,
        verbose=args.verbose
    )
    
    # Load Data
    strategy.load_data(sd, start_dt, end_dt)
    
    # Run
    strategy.run()
    
    # Report
    metrics = strategy.get_metrics()
    strategy.print_trade_log()
    
    print("\n" + "="*40)
    print("PERFORMANCE SUMMARY")
    print("="*40)
    
    # Yearly Breakdown first (if exists) before summary
    yearly = metrics.pop('Yearly Breakdown', None)
    
    if yearly:
        print("YEARLY BREAKDOWN:")
        print(f"{'Year':<6} | {'Return':<12} | {'Return %':<10} | {'Max DD %':<10} | {'Max Cap Used'}")
        print("-" * 65)
        for year, data in yearly.items():
            print(f"{year:<6} | {format_inr(data['Return (Abs)']):<12} | {data['Return (%)']:<9.2f}% | {data['Max Drawdown (%)']:<9.2f}% | {format_inr(data['Max Capital Used'])}")
        print("-" * 65)
        print("")

    for k, v in metrics.items():
        if "CAGR" in k or "Return" in k or "Drawdown" in k or "Win Rate" in k:
             print(f"{k:<20}: {v:.2f}%")
        elif "Equity" in k or "Cash" in k or "Capital" in k:
             print(f"{k:<20}: {format_inr(v)}")
        else:
             print(f"{k:<20}: {v}")
    print("="*40)

    # Export CSV if requested
    if args.csv:
        filename = args.csv
        if filename == 'auto':
            # Generate default filename: shop_trade_log_YYYYMMDD_HHMMSS.csv
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"shop_trade_log_{timestamp}.csv"
        
        strategy.save_trade_log(filename)

if __name__ == "__main__":
    main()
