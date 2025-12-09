from core.utils import format_inr
from datetime import datetime

class PKPStrategy:
    def __init__(self, ticker, base_sip=100000, min_profit_booking_amount=10000, 
                 bid_multiplier=0.5, bid_trigger_drop=0.02, verbose=False, show_notes=False,
                 initial_lumpsum=0):
        self.ticker = ticker
        self.base_sip = base_sip
        self.min_profit_booking_amount = min_profit_booking_amount
        self.verbose = verbose
        self.show_notes = show_notes
        self.initial_lumpsum = initial_lumpsum
        
        # Strategy Parameters
        self.bid_multiplier = bid_multiplier
        self.bid_trigger_drop = bid_trigger_drop
        
        # State Variables
        self.total_units = 0
        self.bia = 0.0 # Base Investment Amount (Total Cost Basis)
        self.pap = 0.0 # Portfolio Average Price
        self.profit_reserve = 0.0 # Realized Profit Reserve (Cash)
        self.actual_invested = 0.0 # "Out of Pocket" Investment (Fresh Capital)
        
        self.transactions = []
        self.portfolio_history = []
        
        # BID State
        self.current_bid_stage = 0 # 0=Wait for 1x, 1=Wait for 2x, ... 9=Wait for 10x
        self.bids_executed_count = 0
        
        # SIP State
        self.current_sip_amount = base_sip
        
        # Metrics Tracking
        self.initial_breakeven_date = None
        self.sustained_breakeven_date = None
        self.monthly_profits = {} # Key: Year-Month, Value: Profit Amount
        self.has_invested = False # Track if we have ever invested capital
        self.max_actual_invested = 0.0
        self.max_actual_invested_date = None
        
        # Benchmark State (Regular SIP)
        self.benchmark_units = 0
        self.benchmark_invested = 0.0

    def log_transaction(self, date, type, units, price, amount, actual_invested, notes=""):
        current_market_value = self.total_units * price
        
        # Calculate PnL %: (Market Value - BIA) / BIA
        pnl_pct = 0.0
        if self.bia > 0:
            pnl_pct = (current_market_value - self.bia) / self.bia
        
        self.transactions.append({
            'date': date,
            'type': type,
            'units': units,
            'price': price,
            'amount': amount,
            'total_units': self.total_units,
            'pap': self.pap,
            'bia': self.bia,
            'actual_invested': actual_invested,
            'current_market_value': current_market_value,
            'pnl_pct': pnl_pct,
            'profit_reserve': self.profit_reserve,
            'notes': notes
        })

    def run(self, data):
        """
        Run the strategy on the provided data.
        
        Args:
            data: List of dictionaries with 'date' (datetime) and 'close' (float) keys.
        """
        prev_month = None
        
        if self.verbose:
            print(f"\n{'Date':<12} | {'Close':<10} | {'Units':<6} | {'BIA':<12} | {'Mkt Val':<12} | {'PnL %':<8} | {'Stage':<5} | {'Action'}")
            print("-" * 90)

        for i, row in enumerate(data):
            date = row['date']
            close_price = row['close']
            
            # --- Initial Lumpsum Execution ---
            if i == 0 and self.initial_lumpsum > 0:
                units_to_buy = int(self.initial_lumpsum / close_price)
                if units_to_buy > 0:
                    cost = units_to_buy * close_price
                    
                    self.bia += cost
                    self.total_units += units_to_buy
                    self.pap = self.bia / self.total_units
                    
                    self.actual_invested += cost
                    self.has_invested = True
                    
                    # Track Max Invested
                    if self.actual_invested > self.max_actual_invested:
                        self.max_actual_invested = self.actual_invested
                        self.max_actual_invested_date = date
                        
                    # Benchmark Lumpsum
                    self.benchmark_invested += cost
                    self.benchmark_units += units_to_buy
                    
                    self.log_transaction(date, "LUMPSUM", units_to_buy, close_price, cost, self.actual_invested, "Initial Investment")
            
            current_month = date.month
            is_sip_day = False
            action_taken = ""
            
            # REQ-N1: Atomicity & SIP Precedence
            # Check for SIP Day (1st trading day of the month)
            if prev_month is not None and current_month != prev_month:
                is_sip_day = True
            
            prev_month = current_month
            
            # --- REQ-F1 & REQ-F2: SIP Execution ---
            if is_sip_day:
                # --- Benchmark: Regular SIP ---
                bench_units = int(self.base_sip / close_price)
                if bench_units > 0:
                    self.benchmark_invested += (bench_units * close_price)
                    self.benchmark_units += bench_units
                
                # REQ-F1: Fixed SIP Amount
                self.current_sip_amount = self.base_sip
                
                # REQ-F2: Execute SIP
                units_to_buy = int(self.current_sip_amount / close_price) # REQ-N2: Round down
                
                if units_to_buy > 0:
                    cost = units_to_buy * close_price
                    
                    # Update BIA and PAP
                    self.bia += cost
                    self.total_units += units_to_buy
                    self.pap = self.bia / self.total_units
                    
                    # Funding Logic: Reserve First
                    amount_from_reserve = min(cost, self.profit_reserve)
                    self.profit_reserve -= amount_from_reserve
                    
                    # Shortfall increases Actual Invested
                    fresh_capital = cost - amount_from_reserve
                    if fresh_capital > 0:
                        self.actual_invested += fresh_capital
                        self.has_invested = True
                        
                        # Track Max Invested
                        if self.actual_invested > self.max_actual_invested:
                            self.max_actual_invested = self.actual_invested
                            self.max_actual_invested_date = date
                    
                    self.log_transaction(date, "SIP", units_to_buy, close_price, cost, self.actual_invested, f"Reserve used: {amount_from_reserve:.2f}")
                    action_taken = "SIP"
                
                # Skip other rules for the day (REQ-N1)
                self.record_history(date, close_price)
                if self.verbose: self.log_daily(date, close_price, action_taken)
                continue

            # --- REQ-F3: Tactical Buy-on-Dip (BID) ---
            if self.total_units > 0:
                base_bid_amt_X = self.bid_multiplier * self.base_sip
                
                # Check drop conditions using PAP
                drop_pct = (self.pap - close_price) / self.pap
                
                bid_multiplier_factor = 0
                
                # Dynamic Strict Incremental Logic (1x -> 10x)
                if self.current_bid_stage < 10:
                    next_multiplier = self.current_bid_stage + 1
                    required_drop = next_multiplier * self.bid_trigger_drop
                    
                    if drop_pct >= required_drop:
                        bid_multiplier_factor = next_multiplier
                
                if bid_multiplier_factor > 0:
                    invest_amt = bid_multiplier_factor * base_bid_amt_X
                    units_to_buy = int(invest_amt / close_price)
                    
                    if units_to_buy > 0:
                        cost = units_to_buy * close_price
                        
                        # Update BIA and PAP
                        self.bia += cost
                        self.total_units += units_to_buy
                        self.pap = self.bia / self.total_units
                        
                        # Funding Logic: Reserve First
                        amount_from_reserve = min(cost, self.profit_reserve)
                        self.profit_reserve -= amount_from_reserve
                        
                        # Shortfall increases Actual Invested
                        fresh_capital = cost - amount_from_reserve
                        if fresh_capital > 0:
                            self.actual_invested += fresh_capital
                            self.has_invested = True
                            
                            # Track Max Invested
                            if self.actual_invested > self.max_actual_invested:
                                self.max_actual_invested = self.actual_invested
                                self.max_actual_invested_date = date
                        
                        self.bids_executed_count += 1
                        self.current_bid_stage += 1 # Increment stage
                        
                        self.log_transaction(date, f"BID-{bid_multiplier_factor}x", units_to_buy, close_price, cost, self.actual_invested, f"Drop: {drop_pct*100:.2f}% | Reserve used: {amount_from_reserve:.2f}")
                        action_taken = f"BID-{bid_multiplier_factor}x"
                        
                        self.record_history(date, close_price)
                        if self.verbose: self.log_daily(date, close_price, action_taken)
                        continue

            # --- REQ-F4: Profit Harvesting (Sell) ---
            if self.total_units > 0:
                current_value = self.total_units * close_price
                
                # Profit Calculation based on BIA (PAP)
                # Profit = Current Value - Base Investment Amount
                profit_val = current_value - self.bia
                
                # Target Sell Amount: Max(10000, 1% of Portfolio Value)
                target_threshold = max(self.min_profit_booking_amount, 0.01 * current_value)
                
                # Trigger: Only sell if we have enough profit to cover the sell amount
                if profit_val >= target_threshold:
                    # Calculate Units to Sell
                    units_calc = int((target_threshold + close_price - 1) // close_price)
                    
                    # Cap at total units held
                    if units_calc > self.total_units:
                        units_calc = self.total_units
                    
                    if units_calc > 0:
                        sale_value = units_calc * close_price
                        
                        # Update Units
                        self.total_units -= units_calc
                        
                        # IMPORTANT: BIA does NOT change on sell.
                        # PAP increases because BIA is spread over fewer units.
                        if self.total_units > 0:
                            self.pap = self.bia / self.total_units
                        else:
                            self.pap = 0 # Should not happen if we cap units, but for safety
                        
                        # Capital Recovery Logic: Reduce Actual Invested First
                        invested_reduction = min(sale_value, self.actual_invested)
                        self.actual_invested -= invested_reduction
                        
                        # Remaining goes to Reserve
                        reserve_addition = sale_value - invested_reduction
                        self.profit_reserve += reserve_addition
                        
                        # Track Monthly Profit
                        ym_key = date.strftime('%Y-%m')
                        self.monthly_profits[ym_key] = self.monthly_profits.get(ym_key, 0) + sale_value
                        
                        # Reset BID Stage on Sell
                        self.current_bid_stage = 0
                        
                        gain_pct = (close_price - self.pap) / self.pap if self.pap > 0 else 0
                        self.log_transaction(date, "SELL", -units_calc, close_price, sale_value, self.actual_invested, f"Gain: {gain_pct*100:.2f}% | Profit: {profit_val:.2f} | Recov: {invested_reduction:.2f}")
                        action_taken = "SELL"

            self.record_history(date, close_price)
            if self.verbose: self.log_daily(date, close_price, action_taken)

    def log_daily(self, date, close_price, action):
        mkt_val = self.total_units * close_price
        pnl_pct = 0.0
        if self.bia > 0:
            pnl_pct = (mkt_val - self.bia) / self.bia * 100
        
        date_str = date.strftime('%Y-%m-%d')
        print(f"{date_str:<12} | {close_price:<10.2f} | {self.total_units:<6} | {format_inr(self.bia):<12} | {format_inr(mkt_val):<12} | {pnl_pct:<7.2f}% | {self.current_bid_stage:<5} | {action}")

    def record_history(self, date, current_price):
        portfolio_value = self.total_units * current_price
        total_equity = portfolio_value + self.profit_reserve
        
        # Breakeven Tracking
        if self.has_invested and self.actual_invested <= 0:
            if self.initial_breakeven_date is None:
                self.initial_breakeven_date = date
            
            # Check if this is the start of sustained breakeven
            # We can only know "sustained" by looking forward, or by updating it continuously 
            # and invalidating if it goes positive again.
            # Simple approach: If currently 0, update sustained candidate.
            # If it goes positive later, we'll have to reset/check.
            # Better approach for "Sustained": Calculate at the end of run.
            pass

        self.portfolio_history.append({
            'date': date,
            'units': self.total_units,
            'pap': self.pap,
            'price': current_price,
            'portfolio_value': portfolio_value,
            'profit_reserve': self.profit_reserve,
            'total_equity': total_equity,
            'actual_invested': self.actual_invested
        })

    def generate_report(self):
        if not self.portfolio_history:
            print("No history to report.")
            return

        final_state = self.portfolio_history[-1]
        
        # Calculate Sustained Breakeven
        # Find the last date where actual_invested > 0. The day after is sustained breakeven.
        last_positive_date = None
        for record in self.portfolio_history:
            if record['actual_invested'] > 1.0: # Tolerance for float
                last_positive_date = record['date']
        
        if last_positive_date:
            # Check if there are records after last_positive_date
            if last_positive_date < final_state['date']:
                # Find the first record after last_positive_date
                for record in self.portfolio_history:
                    if record['date'] > last_positive_date:
                        self.sustained_breakeven_date = record['date']
                        break
        elif self.portfolio_history and self.portfolio_history[0]['actual_invested'] <= 0:
             # Started at 0? Unlikely but possible if first action is not a buy
             # With has_invested check, this shouldn't happen unless we never invested.
             pass

        # Calculate Avg Monthly Profits
        pre_be_profits = []
        post_be_profits = []
        
        be_date = self.sustained_breakeven_date if self.sustained_breakeven_date else final_state['date']
        
        for ym, profit in self.monthly_profits.items():
            # Convert YM to date (1st of month) for comparison
            y, m = map(int, ym.split('-'))
            d = datetime(y, m, 1)
            # Approximate comparison
            if d.date() < be_date.date():
                pre_be_profits.append(profit)
            else:
                post_be_profits.append(profit)
                
        avg_pre_be = sum(pre_be_profits) / len(pre_be_profits) if pre_be_profits else 0
        avg_post_be = sum(post_be_profits) / len(post_be_profits) if post_be_profits else 0
        
        # Transaction Log
        print("\nTransaction Log:")
        if self.show_notes:
            print(f"{'Date':<12} | {'Type':<10} | {'Units':<6} | {'Price':<10} | {'Amount':<12} | {'PAP':<10} | {'BIA (Inv)':<12} | {'Act. Inv.':<12} | {'Mkt Value':<12} | {'PnL %':<8} | {'Reserve':<12} | {'Profit':<12} | {'Notes'}")
            print("-" * 170)
        else:
            print(f"{'Date':<12} | {'Type':<10} | {'Units':<6} | {'Price':<10} | {'Amount':<12} | {'PAP':<10} | {'BIA (Inv)':<12} | {'Act. Inv.':<12} | {'Mkt Value':<12} | {'PnL %':<8} | {'Reserve':<12} | {'Profit':<12}")
            print("-" * 145)

        for t in self.transactions:
            date_str = t['date'].strftime('%Y-%m-%d')
            pnl_str = f"{t['pnl_pct']*100:.2f}%"
            profit_display = format_inr(t['amount']) if t['type'] == 'SELL' else "0.00"
            
            base_row = f"{date_str:<12} | {t['type']:<10} | {t['units']:<6} | {t['price']:<10.2f} | {format_inr(t['amount']):<12} | {format_inr(t['pap']):<10} | {format_inr(t['bia']):<12} | {format_inr(t['actual_invested']):<12} | {format_inr(t['current_market_value']):<12} | {pnl_str:<8} | {format_inr(t['profit_reserve']):<12} | {profit_display:<12}"
            
            if self.show_notes:
                print(f"{base_row} | {t['notes']}")
            else:
                print(base_row)
        
        if self.show_notes:
            print("-" * 170)
        else:
            print("-" * 145)

        print("\n" + "="*40)
        print(f"PKP Strategy Backtest Report: {self.ticker}")
        print("="*40)
        print(f"Final Date: {final_state['date'].date()}")
        print(f"Total Units Held: {final_state['units']}")
        print(f"PKP Avg Price (PAP): {format_inr(final_state['pap'])}")
        print(f"Current Market Price: {format_inr(final_state['price'])}")
        print(f"Portfolio Value (Assets): {format_inr(final_state['portfolio_value'], decimals=0)}")
        print(f"Profit Reserve (Cash): {format_inr(final_state['profit_reserve'], decimals=0)}")
        print(f"Total Equity: {format_inr(final_state['total_equity'], decimals=0)}")
        print(f"Total BIDs Executed: {self.bids_executed_count}")
        print("-" * 40)
        
        # Calculate Invested Amount (approximate from transactions)
        total_invested = 0
        for t in self.transactions:
            if t['type'] in ['SIP'] or t['type'].startswith('BID'):
                total_invested += t['amount']
        
        print(f"Total Capital Deployed (Cumulative): {format_inr(total_invested, decimals=0)}")
        print(f"Current Base Investment Amount (BIA): {format_inr(self.bia, decimals=0)}")
        print(f"Total Actual Invested (Fresh Capital): {format_inr(self.actual_invested, decimals=0)}")
        
        # Breakeven Metrics
        print("-" * 40)
        print("Breakeven Analysis:")
        init_be_str = self.initial_breakeven_date.strftime('%Y-%m-%d') if self.initial_breakeven_date else "Not Reached"
        sust_be_str = self.sustained_breakeven_date.strftime('%Y-%m-%d') if self.sustained_breakeven_date else "Not Reached"
        max_inv_date_str = self.max_actual_invested_date.strftime('%Y-%m-%d') if self.max_actual_invested_date else "N/A"
        
        years_to_be = "N/A"
        if self.sustained_breakeven_date:
            start_date = self.portfolio_history[0]['date']
            days = (self.sustained_breakeven_date - start_date).days
            years_to_be = f"{days/365.25:.1f} Years"

        print(f"Initial Breakeven Date: {init_be_str}")
        print(f"Sustained Breakeven Date: {sust_be_str}")
        print(f"Time to Sustained Breakeven: {years_to_be}")
        print(f"Max Actual Invested: {format_inr(self.max_actual_invested, decimals=0)} (on {max_inv_date_str})")
        print(f"Avg Monthly Profit (Pre-BE): {format_inr(avg_pre_be, decimals=0)}")
        print(f"Avg Monthly Profit (Post-BE): {format_inr(avg_post_be, decimals=0)}")
        
        # Transaction Summary
        sips = len([t for t in self.transactions if t['type'] == 'SIP'])
        bids = len([t for t in self.transactions if t['type'].startswith('BID')])
        sells = len([t for t in self.transactions if t['type'] == 'SELL'])
        
        print("-" * 40)
        print(f"Transactions: {sips} SIPs, {bids} BIDs, {sells} Sells")
        
        # Benchmark Comparison
        bench_mkt_val = self.benchmark_units * final_state['price']
        bench_pnl = (bench_mkt_val - self.benchmark_invested) / self.benchmark_invested * 100 if self.benchmark_invested > 0 else 0
        
        pkp_mkt_val = final_state['portfolio_value'] + final_state['profit_reserve'] # Total Equity
        pkp_invested = self.actual_invested # Compare with Fresh Capital
        
        pkp_pnl_str = "Inf"
        if pkp_invested > 0:
            pkp_pnl = (pkp_mkt_val - pkp_invested) / pkp_invested * 100
            pkp_pnl_str = f"{pkp_pnl:.2f}%"
        elif pkp_invested <= 0 and pkp_mkt_val > 0:
            pkp_pnl_str = "Infinite"
        else:
            pkp_pnl_str = "0.00%"

        print("="*40)
        print("STRATEGY COMPARISON:")
        print(f"{'Metric':<20} | {'Regular SIP':<15} | {'PKP Strategy':<15}")
        print("-" * 56)
        print(f"{'Invested (Pocket)':<20} | {format_inr(self.benchmark_invested, decimals=0):<15} | {format_inr(pkp_invested, decimals=0):<15}")
        print(f"{'Final Value':<20} | {format_inr(bench_mkt_val, decimals=0):<15} | {format_inr(pkp_mkt_val, decimals=0):<15}")
        print(f"{'Returns (Abs %)':<20} | {bench_pnl:<15.2f}% | {pkp_pnl_str:<15}")
        print("="*40)

    def get_metrics(self):
        if not self.portfolio_history:
            return {}

        final_state = self.portfolio_history[-1]
        
        # Calculate Sustained Breakeven (Logic duplicated from generate_report for independence)
        sustained_breakeven_date = None
        last_positive_date = None
        for record in self.portfolio_history:
            if record['actual_invested'] > 1.0:
                last_positive_date = record['date']
        
        if last_positive_date:
            if last_positive_date < final_state['date']:
                for record in self.portfolio_history:
                    if record['date'] > last_positive_date:
                        sustained_breakeven_date = record['date']
                        break
        elif self.portfolio_history and self.portfolio_history[0]['actual_invested'] <= 0:
             sustained_breakeven_date = self.portfolio_history[0]['date']

        # Calculate Avg Monthly Profits
        pre_be_profits = []
        post_be_profits = []
        be_date = sustained_breakeven_date if sustained_breakeven_date else final_state['date']
        
        for ym, profit in self.monthly_profits.items():
            y, m = map(int, ym.split('-'))
            d = datetime(y, m, 1)
            if d.date() < be_date.date():
                pre_be_profits.append(profit)
            else:
                post_be_profits.append(profit)
                
        avg_pre_be = sum(pre_be_profits) / len(pre_be_profits) if pre_be_profits else 0
        avg_post_be = sum(post_be_profits) / len(post_be_profits) if post_be_profits else 0
        
        # SIP Years
        start_date = self.portfolio_history[0]['date']
        end_date = final_state['date']
        sip_years = (end_date - start_date).days / 365.25
        
        # Time to Breakeven
        time_to_be = "N/A"
        if sustained_breakeven_date:
            days = (sustained_breakeven_date - start_date).days
            time_to_be = f"{days/365.25:.1f} Yrs"
            
        # Yearly Profits
        yearly_profits = {}
        for ym, profit in self.monthly_profits.items():
            year = ym.split('-')[0]
            yearly_profits[year] = yearly_profits.get(year, 0) + profit
            
        return {
            'symbol': self.ticker,
            'sip_years': f"{sip_years:.1f}",
            'base_inv_amt': self.bia,
            'max_actual_invested': self.max_actual_invested,
            'actual_invested': self.actual_invested,
            'market_value': final_state['portfolio_value'],
            'cash_balance': final_state['profit_reserve'],
            'break_even_date': sustained_breakeven_date.strftime('%Y-%m-%d') if sustained_breakeven_date else "Not Reached",
            'time_to_break_even': time_to_be,
            'avg_monthly_profit_pre_be': avg_pre_be,
            'avg_monthly_profit_post_be': avg_post_be,
            'invested_reg_sip': self.benchmark_invested,
            'market_value_reg_sip': self.benchmark_units * final_state['price'],
            'yearly_profits': yearly_profits
        }
