import argparse
import pandas as pd
from datetime import datetime, date
from strategies.pkp.strategy import PKPStrategy
from core.utils import format_inr
import skas_data

def run_strategy_for_symbol(symbol, args, sd, start_dt, end_dt):
    print(f"Processing {symbol}...")
    
    # Fetch Data
    df = sd.get_prices(symbol=symbol, start_date=start_dt, end_date=end_dt)
    
    if df is None or df.empty:
        print(f"No data found for {symbol}")
        return None

    # Convert Data
    data = []
    for index, row in df.iterrows():
        raw_date = row['date']
        if isinstance(raw_date, str):
            dt = datetime.strptime(raw_date, '%Y-%m-%d')
        elif isinstance(raw_date, date):
            dt = datetime.combine(raw_date, datetime.min.time())
        else:
            dt = pd.to_datetime(raw_date)
        
        data.append({
            'date': dt,
            'close': float(row['close'])
        })
    data.sort(key=lambda x: x['date'])

    # Initialize Strategy
    strategy = PKPStrategy(
        ticker=symbol,
        base_sip=args.sip,
        min_profit_booking_amount=args.min_profit,
        bid_multiplier=args.bid_mult,
        bid_trigger_drop=args.bid_drop,
        verbose=False, # Suppress daily logs
        show_notes=False,
        initial_lumpsum=args.lumpsum
    )
    
    # Run Strategy
    strategy.run(data)
    
    return strategy.get_metrics()

def main():
    parser = argparse.ArgumentParser(description='Run PKP Strategy Batch')
    parser.add_argument('symbols', type=str, help='Comma-separated list of symbols (e.g., BAJFINANCE,ITC)')
    parser.add_argument('--sip', type=float, default=100000, help='Base SIP Amount (default: 100000)')
    parser.add_argument('--min-profit', type=float, default=10000, help='Min Profit Booking Amount (default: 10000)')
    parser.add_argument('--bid-mult', type=float, default=0.5, help='BID Multiplier (default: 0.5)')
    parser.add_argument('--bid-drop', type=float, default=0.02, help='BID Trigger Drop %% (default: 0.02)')
    parser.add_argument('--start-date', type=str, default='2010-01-01', help='Start Date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None, help='End Date (YYYY-MM-DD), default is Today')
    parser.add_argument('--lumpsum', type=float, default=0, help='Initial Lumpsum Investment (default: 0)')
    
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
    
    # Initialize Data Provider
    sd = skas_data.SkasData(cache_only=True)
    
    results = []
    for symbol in symbol_list:
        metrics = run_strategy_for_symbol(symbol, args, sd, start_dt, end_dt)
        if metrics:
            results.append(metrics)
            
    if not results:
        print("No results generated.")
        return

    # Create DataFrame for Table Display
    df_results = pd.DataFrame(results)
    
    # Calculate Derived Metrics
    df_results['total_value'] = df_results['market_value'] + df_results['cash_balance']
    
    def calc_pkp_returns(row):
        if row['actual_invested'] <= 0:
            return "Inf"
        return (row['total_value'] - row['actual_invested']) / row['actual_invested'] * 100

    def calc_reg_returns(row):
        if row['invested_reg_sip'] <= 0:
            return 0.0
        return (row['market_value_reg_sip'] - row['invested_reg_sip']) / row['invested_reg_sip'] * 100

    df_results['pkp_abs_pct'] = df_results.apply(calc_pkp_returns, axis=1)
    df_results['reg_abs_pct'] = df_results.apply(calc_reg_returns, axis=1)

    # Rename columns for display
    display_cols = {
        'symbol': 'Symbol',
        'sip_years': 'SIP Years',
        'max_actual_invested': 'Max Invested',
        'actual_invested': 'Invested',
        'market_value': 'Mkt Val',
        'cash_balance': 'Cash Bal',
        'total_value': 'Total Value',
        'pkp_abs_pct': 'PKP Abs %',
        'break_even_date': 'BE Date',
        'time_to_break_even': 'Time to BE',
        'avg_monthly_profit_pre_be': 'Avg Prof(Pre)',
        'avg_monthly_profit_post_be': 'Avg Prof(Post)',
        'invested_reg_sip': 'Reg SIP Inv',
        'market_value_reg_sip': 'Reg SIP Val',
        'reg_abs_pct': 'Reg Abs %'
    }
    
    # Reorder columns
    cols_order = ['Symbol', 'SIP Years', 'Max Invested', 'Invested', 'Mkt Val', 'Cash Bal', 'Total Value', 'PKP Abs %', 'BE Date', 'Time to BE', 'Avg Prof(Pre)', 'Avg Prof(Post)', 'Reg SIP Inv', 'Reg SIP Val', 'Reg Abs %']
    
    # Ensure all columns exist (some might be missing if results list was empty, but we check that earlier)
    # Map internal names to display names
    df_display = pd.DataFrame()
    for col in cols_order:
        # Find the key in display_cols that maps to this col
        key = [k for k, v in display_cols.items() if v == col][0]
        df_display[col] = df_results[key]
    
    # Format Currency Columns
    currency_cols = ['Max Invested', 'Invested', 'Mkt Val', 'Cash Bal', 'Total Value', 'Avg Prof(Pre)', 'Avg Prof(Post)', 'Reg SIP Inv', 'Reg SIP Val']
    for col in currency_cols:
        df_display[col] = df_display[col].apply(lambda x: format_inr(x, decimals=0))
        
    # Format Percentage Columns
    pct_cols = ['PKP Abs %', 'Reg Abs %']
    for col in pct_cols:
        df_display[col] = df_display[col].apply(lambda x: f"{x:.2f}%" if isinstance(x, (int, float)) else x)
        
    # Print Table with Custom Formatting
    print("\n" + "="*160)
    print("PKP STRATEGY BATCH SUMMARY")
    print("="*160)
    
    print_formatted_table(df_display, currency_cols + ['SIP Years'])
    
    # --- Yearly Profits Table ---
    print("\n" + "="*160)
    print("YEARLY PROFITS SUMMARY")
    print("="*160)
    
    # Extract all years
    all_years = set()
    for res in results:
        all_years.update(res['yearly_profits'].keys())
    sorted_years = sorted(list(all_years))
    
    yearly_data = []
    yearly_totals = {year: 0 for year in sorted_years}
    
    for res in results:
        row = {'Symbol': res['symbol']}
        for year in sorted_years:
            profit = res['yearly_profits'].get(year, 0)
            row[year] = profit
            yearly_totals[year] += profit
        yearly_data.append(row)
        
    # Add Total Row
    total_row = {'Symbol': 'TOTAL'}
    for year in sorted_years:
        total_row[year] = yearly_totals[year]
    yearly_data.append(total_row)
        
    df_yearly = pd.DataFrame(yearly_data)
    
    # Format Currency for Yearly Profits
    for year in sorted_years:
        df_yearly[year] = df_yearly[year].apply(lambda x: format_inr(x, decimals=0))
        
    print_formatted_table(df_yearly, sorted_years)


def print_formatted_table(df, right_align_cols):
    # Calculate column widths
    col_widths = {}
    for col in df.columns:
        # Convert all to string to measure length
        max_len = max(df[col].astype(str).apply(len).max(), len(str(col)))
        col_widths[col] = max_len + 2 # Add padding

    # Create Header
    header = "|"
    separator = "+"
    for col in df.columns:
        width = col_widths[col]
        header += f" {str(col):<{width-1}}|"
        separator += "-" * (width + 1) + "+"
    
    print(separator)
    print(header)
    print(separator)
    
    # Print Rows
    for _, row in df.iterrows():
        line = "|"
        for col in df.columns:
            width = col_widths[col]
            val = str(row[col])
            # Right align numbers/currency, left align others
            if col in right_align_cols:
                line += f" {val:>{width-1}}|"
            else:
                line += f" {val:<{width-1}}|"
        print(line)
    
    print(separator)

if __name__ == "__main__":
    main()
