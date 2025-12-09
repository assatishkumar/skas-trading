from datetime import datetime
import pandas as pd
from core.utils import format_inr
import skas_data

class ShopStrategy:
    def __init__(self, universe, initial_capital=500000, capital_parts=40, 
                 new_buy_drop_threshold=0.10, avg_buy_drop_threshold=0.05,
                 profit_target=0.03, max_new_buys_per_day=3, max_avg_buys_per_day=1,
                 verbose=False):
        
        self.universe = universe
        self.initial_capital = initial_capital
        self.capital_parts = capital_parts
        self.new_buy_drop_threshold = new_buy_drop_threshold
        self.avg_buy_drop_threshold = avg_buy_drop_threshold
        self.profit_target = profit_target
        self.max_new_buys_per_day = max_new_buys_per_day
        self.max_avg_buys_per_day = max_avg_buys_per_day
        self.verbose = verbose

        # State Variables
        self.cash = initial_capital
        self.portfolio = {} # {ticker: [ {price: float, date: datetime, units: int} ]} (LIFO Stack)
        self.transactions = [] # List of executed trades
        self.history = [] # Daily portfolio snapshot

        self.allocation_amount = initial_capital / capital_parts
        
        # Data
        self.market_data = {} # {ticker: dataframe}
        self.unified_dates = []

    def load_data(self, sd, start_date, end_date):
        """
        Fetch data for all stocks in the universe and align dates.
        """
        print("Fetching market data...")
        all_dates = set()
        
        for ticker in self.universe:
            df = sd.get_prices(symbol=ticker, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                # Ensure date column is datetime
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                self.market_data[ticker] = df
                all_dates.update(df.index.tolist())
            else:
                if self.verbose:
                    print(f"Warning: No data for {ticker}")
        
        self.unified_dates = sorted(list(all_dates))
        print(f"Data loaded for {len(self.market_data)} symbols. Total trading days: {len(self.unified_dates)}")

    def run(self):
        print("Running strategy simulation...")
        
        for current_date in self.unified_dates:
            self._process_day(current_date)
        
        print("Simulation complete.")

    def _process_day(self, date):
        daily_candidates = [] # For New Buys
        stocks_averaged_today = False # Constraint: Global check for averaging
        
        # --- Step A: Market Scan ---
        # We need to know the state of every stock for this date
        market_snapshot = {}
        
        for ticker in self.universe:
            if ticker not in self.market_data:
                continue
                
            df = self.market_data[ticker]
            if date not in df.index:
                continue
            
            row = df.loc[date]
            current_close = row['close']
            
            # Previous Close (for Red/Green candle check)
            # Find the location of current date
            loc = df.index.get_loc(date)
            if loc > 0:
                prev_close = df.iloc[loc-1]['close']
                is_green = current_close > prev_close
                is_red = current_close < prev_close
            else:
                # First day, assume neutral/skip logic dependent on candle color
                prev_close = current_close
                is_green = False
                is_red = False
            
            # 52 Week High Logic
            # Look back 252 trading days (or less if not enough history)
            # Efficient way: Expanding window max up to this point if we iterate chronologically?
            # Or just slice: df.iloc[max(0, loc-252):loc+1]
            start_loc = max(0, loc - 252)
            recent_window = df.iloc[start_loc : loc + 1]
            high_52w = recent_window['close'].max() # Using Close for 52W High as per common backtest simplicity, or High if available? Requirement says "Calculate 52_Week_High". Usually implies High column, but if we only have Close, we use Close. `skas_data` returns close. Let's assume Close for now based on typical casual data sources, or check if 'high' is in data. 
            # Looking at PKP code, it only used 'close'. Checking shop.txt... it just says "skas-data utils for stock / ETF price". PKP used only close. I will stick to Close max.
            
            market_snapshot[ticker] = {
                'close': current_close,
                'prev_close': prev_close,
                'is_green': is_green,
                'is_red': is_red,
                'high_52w': high_52w
            }

        # --- Step B: Sell Logic (Exits) ---
        # Free up cash first
        # Iterate snapshot of keys to allow modification of dictionary
        for ticker in list(self.portfolio.keys()):
            if ticker not in market_snapshot:
                continue
                
            data = market_snapshot[ticker]
            packets = self.portfolio[ticker]
            
            if not packets:
                continue
                
            # LIFO: Check last packet
            last_packet = packets[-1]
            buy_price = last_packet['price']
            current_close = data['close']
            
            pnl_pct = (current_close - buy_price) / buy_price
            
            # Sell Condition: >= Target Profit AND Red Candle
            if pnl_pct >= self.profit_target and data['is_red']:
                # Sell!
                revenue = last_packet['units'] * current_close
                profit = revenue - (last_packet['units'] * buy_price)
                
                self.cash += revenue
                self.portfolio[ticker].pop() # Remove last packet
                
                # Cleanup if empty
                if not self.portfolio[ticker]:
                    del self.portfolio[ticker]
                
                self.log_transaction(date, ticker, "SELL", last_packet['units'], current_close, profit, pnl_pct)

        # --- Step C: Averaging Logic (Re-Entry) ---
        # Priority over new buys
        # Limit 1 avg buy per day across ENTIRE portfolio? 
        # Req: "Check Global Constraint: Has an averaging trade already happened today? If yes, Stop Averaging." => YES, global limit.
        # Req: "Iterate through all stocks currently in the Portfolio."
        
        avg_candidates = []
        
        if not stocks_averaged_today:
            for ticker in list(self.portfolio.keys()):
                if ticker not in market_snapshot:
                    continue
                    
                data = market_snapshot[ticker]
                packets = self.portfolio[ticker]
                if not packets: continue
                
                last_packet = packets[-1]
                buy_price = last_packet['price']
                current_close = data['close']
                
                # Buy Condition: Drop > Thresh AND Green Candle
                drop_price = buy_price * (1 - self.avg_buy_drop_threshold)
                if current_close < drop_price and data['is_green']:
                    # Candidate for averaging
                    # If multiple qualify, which one to pick? Requirement doesn't specify sort order for Averaging, just "Iterate".
                    # Usually we pick the first one we find or the "best" one. 
                    # Let's collect them and maybe pick the deepest drop? Or just first one as per loop?
                    # "Iterate through all stocks... Check Global Constraint... If yes, Stop." implies strict order of iteration matters OR we process one and break.
                    # Since dictionary order is insertion order in py3.7+, this is deterministic.
                    # I will execute the first one found to satisfy strict "Stop Averaging".
                    
                    if self.cash > self.allocation_amount:
                        units = int(self.allocation_amount // current_close)
                        if units > 0:
                            cost = units * current_close
                            self.cash -= cost
                            self.portfolio[ticker].append({
                                'price': current_close,
                                'date': date,
                                'units': units
                            })
                            
                            self.log_transaction(date, ticker, "AVG_BUY", units, current_close, 0, 0)
                            stocks_averaged_today = True
                            break # Global constraint reached
        
        
        # --- Step D: New Buy Logic (Fresh Entry) ---
        # Only if Averaging_Done_Today is False
        if not stocks_averaged_today:
             # Identify candidates
             candidates = []
             
             for ticker in self.universe:
                 # Skip if already in portfolio
                 if ticker in self.portfolio:
                     continue
                 
                 if ticker not in market_snapshot:
                     continue
                     
                 data = market_snapshot[ticker]
                 
                 # Conditions
                 # 1. Close < 52W High * (1 - New_Buy_Drop)
                 # 2. Green Candle
                 
                 target_price = data['high_52w'] * (1 - self.new_buy_drop_threshold)
                 if data['close'] < target_price and data['is_green']:
                     drop_pct = (data['high_52w'] - data['close']) / data['high_52w']
                     candidates.append({
                         'ticker': ticker,
                         'drop_pct': drop_pct,
                         'close': data['close']
                     })
             
             # Ranking: Sort by percentage drop (deepest discount first) DESC
             candidates.sort(key=lambda x: x['drop_pct'], reverse=True)
             
             # Execute Top N
             buys_executed = 0
             for cand in candidates:
                 if buys_executed >= self.max_new_buys_per_day:
                     break
                 
                 if self.cash < self.allocation_amount:
                     break # Stop if no cash
                     
                 ticker = cand['ticker']
                 price = cand['close']
                 units = int(self.allocation_amount // price)
                 
                 if units > 0:
                     self.cash -= (units * price)
                     if ticker not in self.portfolio:
                         self.portfolio[ticker] = []
                     
                     self.portfolio[ticker].append({
                         'price': price,
                         'date': date,
                         'units': units
                     })
                     
                     self.log_transaction(date, ticker, "NEW_BUY", units, price, 0, 0)
                     buys_executed += 1
        
        # Record Daily History
        self.record_history(date)

    def log_transaction(self, date, ticker, action, units, price, profit, pnl_pct):
        self.transactions.append({
            'date': date,
            'ticker': ticker,
            'action': action,
            'units': units,
            'price': price,
            'amount': units * price,
            'profit': profit,
            'pnl_pct': pnl_pct
        })
        if self.verbose:
            print(f"{date.date()} | {ticker:<10} | {action:<8} | {units} @ {price:.2f}")

    def record_history(self, date):
        # Calculate Total Portfolio Value and Cost Basis
        holdings_value = 0
        invested_capital = 0
        
        for ticker, packets in self.portfolio.items():
            if ticker in self.market_data and date in self.market_data[ticker].index:
                price = self.market_data[ticker].loc[date]['close']
                qty = sum(p['units'] for p in packets)
                holdings_value += (qty * price)
            
            # Sum cost basis for all packets
            for p in packets:
                invested_capital += (p['units'] * p['price'])
        
        self.history.append({
            'date': date,
            'cash': self.cash,
            'holdings_value': holdings_value,
            'invested_capital': invested_capital,
            'total_equity': self.cash + holdings_value
        })

    def get_metrics(self):
        if not self.history:
            return {}

        final = self.history[-1]
        
        # --- Overall Metrics ---
        # CAGR
        start_date = self.history[0]['date']
        end_date = final['date']
        years = (end_date - start_date).days / 365.25
        final_equity = final['total_equity']
        
        overall_cagr = 0
        if years > 0 and final_equity > 0:
            overall_cagr = (final_equity / self.initial_capital) ** (1 / years) - 1
            
        # Max Drawdown & Max Invested Capital
        high_water_mark = 0
        max_dd = 0
        max_invested_capital = 0
        
        for day in self.history:
            # Drawdown
            eq = day['total_equity']
            if eq > high_water_mark:
                high_water_mark = eq
            
            dd = (high_water_mark - eq) / high_water_mark if high_water_mark > 0 else 0
            if dd > max_dd:
                max_dd = dd
                
            # Max Invested Capital (Peak Cost Basis)
            # Use .get() for backward compatibility if history didn't have this key before fix
            invested = day.get('invested_capital', 0)
            if invested > max_invested_capital:
                max_invested_capital = invested

        # Win Rate
        closed_trades = [t for t in self.transactions if t['action'] == 'SELL']
        wins = len([t for t in closed_trades if t['profit'] > 0])
        total_trades = len(closed_trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        # --- Yearly Breakdown ---
        # Group history by year
        daily_df = pd.DataFrame(self.history)
        daily_df['year'] = daily_df['date'].dt.year
        
        yearly_metrics = {}
        unique_years = sorted(daily_df['year'].unique())
        
        for year in unique_years:
            ydf = daily_df[daily_df['year'] == year]
            
            # Start/End Equity for the year
            if year == unique_years[0]:
                start_eq = self.initial_capital
            else:
                prev_year_days = daily_df[daily_df['year'] == year - 1]
                if not prev_year_days.empty:
                    start_eq = prev_year_days.iloc[-1]['total_equity']
                else:
                    start_eq = self.initial_capital
            
            end_eq = ydf.iloc[-1]['total_equity']
            abs_return_val = end_eq - start_eq
            abs_return_pct = (abs_return_val / start_eq * 100) if start_eq > 0 else 0
            
            # Max Drawdown in Year
            y_max_dd = 0
            y_hwm = start_eq
            
            for eq in ydf['total_equity']:
                if eq > y_hwm:
                    y_hwm = eq
                dd = (y_hwm - eq) / y_hwm if y_hwm > 0 else 0
                if dd > y_max_dd:
                    y_max_dd = dd
                    
            # Max Invested Capital in Year
            y_max_cap_used = 0
            if 'invested_capital' in ydf.columns:
                y_max_cap_used = ydf['invested_capital'].max()
            
            yearly_metrics[year] = {
                'Return (Abs)': abs_return_val,
                'Return (%)': abs_return_pct,
                'Max Drawdown (%)': y_max_dd * 100,
                'Max Capital Used': y_max_cap_used
            }
        
        return {
            'Total Return %': total_return,
            'CAGR %': overall_cagr * 100,
            'Final Equity': final_equity,
            'Max Drawdown %': max_dd * 100,
            'Max Capital Used': max_invested_capital,
            'Total Trades': total_trades,
            'Win Rate %': win_rate,
            'Cash Balance': self.cash,
            'Yearly Breakdown': yearly_metrics
        }

    def print_trade_log(self):
        print("\n" + "="*80)
        print("TRADE LOG")
        print("="*80)
        print(f"{'Date':<12} | {'Ticker':<12} | {'Action':<10} | {'Price':<10} | {'PnL':<10} | {'PnL %'}")
        print("-" * 80)
        
        for t in self.transactions:
            date_str = t['date'].strftime('%Y-%m-%d')
            pnl_str = f"{t['profit']:.2f}" if t['action'] == 'SELL' else "-"
            pct_str = f"{t['pnl_pct']*100:.2f}%" if t['action'] == 'SELL' else "-"
            
            print(f"{date_str:<12} | {t['ticker']:<12} | {t['action']:<10} | {t['price']:<10.2f} | {pnl_str:<10} | {pct_str}")

    def save_trade_log(self, filename):
        if not self.transactions:
            print("No transactions to save.")
            return
            
        df = pd.DataFrame(self.transactions)
        # Format columns for CSV
        # We might want to keep raw numbers or format them? Usually raw numbers are better for CSV analysis.
        # But 'date' should be readable.
        
        # Create a copy for export to avoid modifying internal state if we were doing inplace changes (we aren't but good practice)
        export_df = df.copy()
        
        # Select and Rename columns if needed
        cols = ['date', 'ticker', 'action', 'units', 'price', 'amount', 'profit', 'pnl_pct']
        export_df = export_df[cols]
        
        export_df.to_csv(filename, index=False)
        print(f"Trade log saved to: {filename}")
