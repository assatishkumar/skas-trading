import argparse
import pandas as pd
from datetime import datetime
import duckdb
from skas_data import SkasData
from strategies.pkp.strategy import PKPStrategy

def main():
    parser = argparse.ArgumentParser(description='Backtest PKP Strategy')
    parser.add_argument('ticker', type=str, help='Ticker symbol (e.g., NIFTY, ITC)')
    parser.add_argument('--sip', type=float, default=100000, help='Base SIP Amount (default: 100000)')
    parser.add_argument('--min-profit', type=float, default=10000, help='Min Profit Booking Amount (default: 10000)')
    parser.add_argument('--bid-mult', type=float, default=0.5, help='BID Multiplier (default: 0.5)')
    parser.add_argument('--bid-drop', type=float, default=0.02, help='BID Trigger Drop %% (default: 0.02)')
    parser.add_argument('--verbose', action='store_true', help='Enable daily verbose logging')
    parser.add_argument('--show-notes', action='store_true', help='Show Notes column in transaction log')
    parser.add_argument('--lumpsum', type=float, default=0, help='Initial Lumpsum Investment (default: 0)')
    
    args = parser.parse_args()

    # Initialize Data Provider
    # Note: We assume asset_type='stock' for now.
    import skas_data
    sd = SkasData(cache_only=True)
    
    from datetime import date
    start_dt = date(2010, 1, 1)
    end_dt = date.today()
    df = sd.get_prices(symbol=args.ticker, start_date=start_dt, end_date=end_dt)
    
    if df is None or df.empty:
        print(f"No data found for {args.ticker}")
        return

    # Convert DataFrame to list of dicts expected by PKPStrategy
    # Expected format: {'date': datetime, 'close': float}
    # skas-data returns a DataFrame with a DatetimeIndex and 'close' column (among others)
    
    data = []
    for index, row in df.iterrows():
        # Ensure date is datetime object
        # skas-data returns 'date' column which might be datetime.date or string
        raw_date = row['date']
        if isinstance(raw_date, str):
            dt = datetime.strptime(raw_date, '%Y-%m-%d')
        elif isinstance(raw_date, date): # datetime.date
            dt = datetime.combine(raw_date, datetime.min.time())
        else:
            dt = pd.to_datetime(raw_date)
        
        data.append({
            'date': dt,
            'close': float(row['close'])
        })
    
    # Sort by date just in case
    data.sort(key=lambda x: x['date'])
    
    print(f"Loaded {len(data)} records.")

    # Initialize Strategy
    strategy = PKPStrategy(
        ticker=args.ticker,
        base_sip=args.sip,
        min_profit_booking_amount=args.min_profit,
        bid_multiplier=args.bid_mult,
        bid_trigger_drop=args.bid_drop,
        verbose=args.verbose,
        show_notes=args.show_notes,
        initial_lumpsum=args.lumpsum
    )
    
    # Run Strategy
    strategy.run(data)
    
    # Generate Report
    strategy.generate_report()

if __name__ == "__main__":
    main()
