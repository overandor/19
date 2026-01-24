import ccxt
import time
import threading
import numpy as np
import functools
import os
import random
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

console = Console()

# Use environment variables for API keys (Required for real trading)
GATE_API_KEY = os.getenv("GATE_API_KEY", "YOUR_GATE_API_KEY")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "YOUR_GATE_API_SECRET")


# === HYDRA SETTINGS ===
DRY_RUN = True           # Dry run mode - set to False for real trading
SIMULATE_FILLS = True    # Simulate random fills in dry run mode
TAKER_FEE = 0.0006       # Estimated taker fee (0.06%)
INITIAL_DEPOSIT = 200.0  # Total deposit in USDT
NUM_GRID_CIRCLES = 9     # Number of grid price levels
MAX_SYMBOLS = 3          # Number of trading pairs to target
LEVERAGE = 50            # Maximum leverage (50x on Gate.io)
GRID_SPACING_PERCENT = 0.3  # Grid spacing in percentage

# Rate control - $0.01 per second target (1 cent/sec)
TARGET_CPS = 1.0  # cents per second target
PROFIT_THRESHOLD = 0.007  # Minimum profit target per grid level
STOP_LOSS_THRESHOLD = -0.002  # Maximum loss per grid level

# Volatility settings
MAX_VOLATILITY_THRESHOLD = 0.05  # Max acceptable volatility
MIN_VOLATILITY_THRESHOLD = 0.003  # Min required volatility

# Concurrency control
thread_lock = threading.Lock()
emergency_stop = False
active_grids = {}
symbol_data = {}
total_profit = 0.0
total_trades = 0
profit_rate = 0.0
start_time = None

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        raise e
                    sleep = (backoff_in_seconds * 2 ** x)
                    time.sleep(sleep)
                    x += 1
        return wrapper
    return decorator

def emergency_liquidation(ex):
    global emergency_stop
    # Capture symbols before clearing
    with thread_lock:
        emergency_stop = True
        symbols_to_clean = list(active_grids.keys())
        active_grids.clear()

    console.print("[bold red]EMERGENCY LIQUIDATION TRIGGERED!")

    try:
        # Cancel orders for active symbols
        for symbol in symbols_to_clean:
            try:
                ex.cancel_all_orders(symbol)
                console.print(f"[yellow]Cancelled all orders for {symbol}")
            except Exception as e:
                console.print(f"[red]Error cancelling orders for {symbol}: {e}")

        # Close all positions
        positions = ex.fetch_positions()
        for pos in positions:
            contracts = float(pos['contracts'])
            if contracts > 0:
                side = 'sell' if pos['side'] == 'long' else 'buy'
                symbol = pos['symbol']
                console.print(f"[red]Closing position: {symbol} {side} {contracts}")
                ex.create_market_order(symbol, side, contracts)
    except Exception as e:
        console.print(f"[red]Error during liquidation: {e}")

def check_account_health(ex):
    if DRY_RUN:
        return True
    try:
        balance = ex.fetch_balance()
        equity = balance['total'].get('USDT', 0)
        if equity > 0 and equity < INITIAL_DEPOSIT * 0.8: # 20% drawdown
             console.print(f"[bold red]Critical drawdown: Equity ${equity:.2f} < 80% of Initial")
             return False
        return True
    except Exception as e:
        console.print(f"[red]Error checking account health: {e}")
        return True

def safe_create_limit_order(ex, symbol, side, amount, price, params={}):
    # Apply precision
    try:
        amount = float(ex.amount_to_precision(symbol, amount))
        price = float(ex.price_to_precision(symbol, price))
    except Exception as e:
        console.print(f"[yellow]Precision adjustment failed for {symbol}: {e}")

    if DRY_RUN:
        # Generate a fake order ID for dry run
        fake_id = f"dry_{int(time.time()*1000)}"
        console.print(f"[yellow][DRY RUN] Would place {side} order for {amount} {symbol} at {price}")
        return {'id': fake_id, 'status': 'open'}

    return retry_with_backoff()(ex.create_limit_order)(symbol, side, amount, price, params)

def create_exchange():
    return ccxt.gateio({
        'apiKey': GATE_API_KEY,
        'secret': GATE_API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
            'defaultSettle': 'usdt',
        }
    })

def get_symbol_volatility(symbol, ex, timeframe='5m', lookback=12):
    """Calculate symbol volatility over specified lookback period"""
    try:
        ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=lookback)
        if not ohlcv or len(ohlcv) < lookback:
            return None

        closes = np.array([candle[4] for candle in ohlcv])
        returns = np.diff(np.log(closes))
        volatility = np.std(returns) * np.sqrt(288)  # Scale to daily volatility (288 5-min periods)
        return volatility
    except Exception as e:
        console.print(f"[red]Error calculating volatility for {symbol}: {e}")
        return None

def get_best_symbols(ex, max_symbols=3):
    """Find the best symbols for grid trading based on volatility and spread"""
    symbols = []
    try:
        markets = ex.load_markets()
        usdtm_symbols = [s for s in markets.keys() if s.endswith('/USDT:USDT') and markets[s]['active']]

        # Get top traded symbols by volume
        tickers = ex.fetch_tickers(usdtm_symbols[:30])  # Limit to top 30 to reduce API calls

        candidates = []
        for symbol, ticker in tickers.items():
            # Skip symbols with extreme prices
            if ticker['last'] < 0.0001 or ticker['last'] > 50000:
                continue

            # Calculate spread
            spread = (ticker['ask'] - ticker['bid']) / ticker['last'] if ticker['last'] > 0 else float('inf')

            # Calculate volatility
            volatility = get_symbol_volatility(symbol, ex)
            if volatility is None:
                continue

            # Calculate volume in USD
            volume_usd = ticker['quoteVolume'] if 'quoteVolume' in ticker else 0

            # Skip low volume symbols
            if volume_usd < 100000:  # Minimum $100k daily volume
                continue

            # Score based on volatility and spread
            if MIN_VOLATILITY_THRESHOLD <= volatility <= MAX_VOLATILITY_THRESHOLD and spread < 0.003:
                candidates.append({
                    'symbol': symbol,
                    'volatility': volatility,
                    'spread': spread,
                    'volume': volume_usd,
                    'last': ticker['last'],
                    # Combined score with preference for higher volatility within bounds
                    'score': (volatility / MAX_VOLATILITY_THRESHOLD) * (1 - (spread * 200))
                })

        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)

        # Return top symbols
        symbols = [c['symbol'] for c in candidates[:max_symbols]]

        # Store symbol data
        for candidate in candidates[:max_symbols]:
            symbol_data[candidate['symbol']] = {
                'volatility': candidate['volatility'],
                'price': candidate['last'],
                'spread': candidate['spread'],
                'volume': candidate['volume']
            }

    except Exception as e:
        console.print(f"[red]Error finding best symbols: {e}")

    return symbols

def calculate_grid_levels(symbol, current_price, num_levels=9, spacing_percent=0.3):
    """Calculate grid price levels around current price"""
    half_levels = num_levels // 2
    grid_levels = []

    # Calculate price levels above and below current price
    for i in range(-half_levels, half_levels + 1):
        level_price = current_price * (1 + (i * spacing_percent / 100))
        grid_levels.append(level_price)

    return sorted(grid_levels)

def place_grid_orders(ex, symbol, grid_levels, position_size_usd, leverage):
    """Place grid orders for a symbol"""
    orders = []

    try:
        ticker = ex.fetch_ticker(symbol)
        current_price = ticker['last']

        # Set leverage (clamp to market max)
        try:
            market = ex.market(symbol)
            max_leverage = market['info'].get('leverage_max', leverage)
            target_leverage = min(int(float(max_leverage)), leverage)
            if not DRY_RUN:
                ex.set_leverage(target_leverage, symbol)
        except Exception as e:
            console.print(f"[yellow]Warning setting leverage for {symbol}: {e}")

        # Position size per grid level
        size_per_level = position_size_usd / len(grid_levels) / current_price

        for price in grid_levels:
            # Place buy orders below market and sell orders above
            if price < current_price:
                side = 'buy'
            elif price > current_price:
                side = 'sell'
            else:
                continue # Skip exactly at market price

            # Calculate order amount with leverage
            amount = size_per_level * leverage

            # Create limit order
            try:
                order = safe_create_limit_order(
                    ex,
                    symbol,
                    side,
                    amount,
                    price,
                    {'timeInForce': 'GTC', 'marginMode': 'cross'}
                )
                orders.append({
                    'id': order['id'],
                    'price': price,
                    'amount': amount,
                    'side': side,
                    'status': 'open',
                    'filled': 0
                })

                console.print(f"[green]Placed {side} order for {amount} {symbol} at {price}")

            except Exception as e:
                console.print(f"[red]Error placing order: {e}")

    except Exception as e:
        console.print(f"[red]Error in grid setup: {e}")

    return orders

def monitor_grid(ex, symbol, grid_orders, position_size_usd):
    """Monitor and manage grid orders"""
    global total_profit, total_trades, profit_rate

    grid_profit = 0.0
    trade_count = 0
    grid_start_time = time.time()

    with thread_lock:
        active_grids[symbol] = {
            'orders': grid_orders,
            'profit': 0.0,
            'trades': 0
        }

    while symbol in active_grids:
        if emergency_stop:
            break
        try:
            # Check open orders
            if DRY_RUN:
                time.sleep(5)
                # Filter locally tracked open orders
                current_open = [o for o in grid_orders if o['status'] == 'open']

                # Optionally simulate a fill
                if SIMULATE_FILLS and current_open and random.random() < 0.3:
                    filled_order = random.choice(current_open)
                    open_order_ids = [o['id'] for o in current_open if o['id'] != filled_order['id']]
                else:
                    open_order_ids = [o['id'] for o in current_open]
            else:
                open_orders = ex.fetch_open_orders(symbol)
                open_order_ids = [order['id'] for order in open_orders]

            # Check filled orders
            for order in grid_orders:
                if order['status'] == 'open' and order['id'] not in open_order_ids:
                    # Order was filled
                    order['status'] = 'filled'
                    order['filled'] = order['amount']

                    # Place opposite order
                    new_side = 'sell' if order['side'] == 'buy' else 'buy'
                    new_price = order['price'] * (1 + PROFIT_THRESHOLD) if new_side == 'sell' else order['price'] * (1 - PROFIT_THRESHOLD)

                    try:
                        new_order = safe_create_limit_order(
                            ex,
                            symbol,
                            new_side,
                            order['amount'],
                            new_price,
                            {'timeInForce': 'GTC', 'marginMode': 'cross'}
                        )

                        # Add new order to tracking
                        grid_orders.append({
                            'id': new_order['id'],
                            'price': new_price,
                            'amount': order['amount'],
                            'side': new_side,
                            'status': 'open',
                            'filled': 0,
                            'parent': order['id']
                        })

                        # Calculate profit from the trade (subtracting estimated fees)
                        gross_profit = order['amount'] * abs(new_price - order['price'])
                        fees = (order['amount'] * order['price'] * TAKER_FEE) + (order['amount'] * new_price * TAKER_FEE)
                        trade_profit = gross_profit - fees

                        grid_profit += trade_profit
                        trade_count += 1

                        with thread_lock:
                            total_profit += trade_profit
                            total_trades += 1
                            elapsed = time.time() - start_time
                            profit_rate = (total_profit * 100) / max(elapsed, 1)  # cents per second

                            if symbol in active_grids:
                                active_grids[symbol]['profit'] = grid_profit
                                active_grids[symbol]['trades'] = trade_count

                        console.print(f"[bold green]Trade completed on {symbol}: {order['side']} -> {new_side}, profit: ${trade_profit:.4f}")

                    except Exception as e:
                        console.print(f"[red]Error placing counter-order: {e}")

            # Check if we need to rebalance the grid
            current_price = ex.fetch_ticker(symbol)['last']
            grid_min = min(order['price'] for order in grid_orders if order['status'] == 'open')
            grid_max = max(order['price'] for order in grid_orders if order['status'] == 'open')

            # If price is outside the grid, rebalance
            if current_price < grid_min * 0.95 or current_price > grid_max * 1.05:
                console.print(f"[yellow]Rebalancing grid for {symbol} - price outside range")

                # Cancel all open orders
                for order in grid_orders:
                    if order['status'] == 'open':
                        try:
                            ex.cancel_order(order['id'], symbol)
                        except Exception:
                            pass

                # Calculate new grid levels
                new_levels = calculate_grid_levels(symbol, current_price, NUM_GRID_CIRCLES, GRID_SPACING_PERCENT)

                # Place new grid orders
                grid_orders = place_grid_orders(ex, symbol, new_levels, position_size_usd, LEVERAGE)

                with thread_lock:
                    active_grids[symbol]['orders'] = grid_orders

            # Check if profit rate is meeting target
            elapsed = time.time() - grid_start_time
            grid_profit_rate = (grid_profit * 100) / max(elapsed, 1)  # cents per second

            if elapsed > 3600:  # Check after one hour
                if grid_profit_rate < TARGET_CPS / MAX_SYMBOLS / 2:
                    console.print(f"[yellow]Grid for {symbol} underperforming. Profit rate: {grid_profit_rate:.5f} c/s")

                    # Consider replacing with a better symbol
                    if len(active_grids) < MAX_SYMBOLS:
                        new_candidates = get_best_symbols(ex, 1)
                        if new_candidates and new_candidates[0] not in active_grids:
                            console.print(f"[yellow]Replacing {symbol} with {new_candidates[0]}")

                            # Cancel all open orders
                            for order in grid_orders:
                                if order['status'] == 'open':
                                    try:
                                        ex.cancel_order(order['id'], symbol)
                                    except Exception:
                                        pass

                            # Remove from active grids
                            with thread_lock:
                                if symbol in active_grids:
                                    del active_grids[symbol]

                            # Start grid for new symbol
                            setup_grid_for_symbol(ex, new_candidates[0], position_size_usd)
                            break

            # Sleep to avoid API rate limits
            time.sleep(5)

        except Exception as e:
            console.print(f"[red]Error monitoring grid for {symbol}: {e}")
            time.sleep(10)

def setup_grid_for_symbol(ex, symbol, position_size_usd):
    """Initialize and start grid for a symbol"""
    try:
        ticker = ex.fetch_ticker(symbol)
        current_price = ticker['last']

        # Calculate grid levels
        grid_levels = calculate_grid_levels(
            symbol,
            current_price,
            NUM_GRID_CIRCLES,
            GRID_SPACING_PERCENT
        )

        # Place initial grid orders
        grid_orders = place_grid_orders(ex, symbol, grid_levels, position_size_usd, LEVERAGE)

        # Start monitoring thread
        monitor_thread = threading.Thread(
            target=monitor_grid,
            args=(ex, symbol, grid_orders, position_size_usd),
            daemon=True
        )
        monitor_thread.start()

        console.print(f"[bold green]Grid setup complete for {symbol} with {len(grid_orders)} orders")

    except Exception as e:
        console.print(f"[red]Error setting up grid for {symbol}: {e}")

def display_dashboard(ex):
    """Display live dashboard with grid performance"""
    while True:
        if not check_account_health(ex):
            emergency_liquidation(ex)
            break
        table = Table(title="HyperGrid Hydra Performance")

        table.add_column("Symbol", justify="left", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Profit $", justify="right")
        table.add_column("Volatility", justify="right")
        table.add_column("Spread %", justify="right")

        with thread_lock:
            for symbol, data in active_grids.items():
                table.add_row(
                    symbol,
                    str(data['trades']),
                    f"${data['profit']:.4f}",
                    f"{symbol_data.get(symbol, {}).get('volatility', 0):.4f}",
                    f"{symbol_data.get(symbol, {}).get('spread', 0)*100:.3f}%"
                )

            elapsed = time.time() - start_time if start_time else 0
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)

            overall_stats = f"""
            Running time: {hours:02d}:{minutes:02d}:{seconds:02d}
            Total trades: {total_trades}
            Total profit: ${total_profit:.4f}
            Profit rate: {profit_rate:.5f} cents/second
            Target rate: {TARGET_CPS:.5f} cents/second
            Rate achieved: {(profit_rate/TARGET_CPS*100):.1f}%
            """

            status_color = "green" if profit_rate >= TARGET_CPS * 0.9 else "yellow" if profit_rate >= TARGET_CPS * 0.5 else "red"

        console.print(Panel(overall_stats, title="Overall Performance", style=status_color))
        console.print(table)

        # Sleep to avoid console flickering
        time.sleep(1)

def main():
    global start_time

    console.print("[bold green]Starting HyperGrid Hydra Trading System")
    console.print(f"[bold]Target profit rate: {TARGET_CPS} cents per second")

    # Initialize exchange
    ex = create_exchange()

    try:
        # Check account balance
        available_balance = 0.0
        try:
            if GATE_API_KEY != "YOUR_GATE_API_KEY":
                balance = ex.fetch_balance()
                available_balance = balance['USDT']['free']
        except Exception as e:
            if not DRY_RUN:
                raise e
            console.print(f"[yellow]Warning: Could not fetch balance, using $0.00 for dry run. {e}")

        console.print(f"[bold]Available balance: ${available_balance:.2f} USDT")

        if available_balance < INITIAL_DEPOSIT:
            if not DRY_RUN:
                console.print(f"[bold red]Warning: Available balance is less than configured deposit amount")
                console.print(f"[bold yellow]Proceeding with available balance: ${available_balance:.2f}")
                position_size = available_balance
            else:
                console.print(f"[bold yellow][DRY RUN] Using configured INITIAL_DEPOSIT for simulation: ${INITIAL_DEPOSIT:.2f}")
                position_size = INITIAL_DEPOSIT
        else:
            position_size = INITIAL_DEPOSIT

        # Initialize start time
        start_time = time.time()

        # Find best symbols
        symbols = get_best_symbols(ex, MAX_SYMBOLS)

        if not symbols:
            console.print("[bold red]Error: No suitable symbols found")
            return

        console.print(f"[bold green]Selected symbols: {', '.join(symbols)}")

        # Calculate position size per symbol
        position_size_per_symbol = position_size / len(symbols)

        # Setup grids for each symbol
        for symbol in symbols:
            setup_grid_for_symbol(ex, symbol, position_size_per_symbol)

        # Start dashboard
        display_dashboard(ex)

    except Exception as e:
        console.print(f"[bold red]Critical error: {e}")
        return

if __name__ == "__main__":
    main()
