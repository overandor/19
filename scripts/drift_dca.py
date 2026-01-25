import asyncio
import os
import json
import time
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from anchorpy import Provider, Wallet
from driftpy.drift_client import DriftClient
from driftpy.drift_user import DriftUser
from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
from driftpy.types import PositionDirection, OrderType, MarketType, OrderParams
from driftpy.constants.config import configs

# Configuration from environment
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DRIFT_WALLET_KEY = os.getenv("DRIFT_WALLET_KEY")
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

# DCA Settings
DCA_INTERVAL_SEC = 600  # 10 minutes
DCA_AMOUNT_SOL = 0.1
PROFIT_TARGET_USD = 1.0
HEDGE_RATIO = 0.5       # Hedge 50% of the position delta

class DriftDCABot:
    def __init__(self):
        self.drift_client = None
        self.drift_user = None
        self.active = True
        self.total_profit = 0.0
        self.total_trades = 0

    async def initialize(self):
        if not DRIFT_WALLET_KEY and not DRY_RUN:
            print("Warning: DRIFT_WALLET_KEY not set. Running in forced DRY_RUN mode.")
            globals()['DRY_RUN'] = True

        # Use a dummy key if in DRY_RUN and no key provided
        if DRY_RUN and not DRIFT_WALLET_KEY:
            kp = Keypair()
        else:
            # Assume DRIFT_WALLET_KEY is a JSON list of ints or a base58 string
            try:
                secret = json.loads(DRIFT_WALLET_KEY)
                kp = Keypair.from_secret_key(bytes(secret))
            except:
                print("Failed to parse DRIFT_WALLET_KEY, using dummy for initialization")
                kp = Keypair()

        wallet = Wallet(kp)
        connection = AsyncClient(SOLANA_RPC_URL)

        # Initialize DriftClient using config
        env = "mainnet"
        config = configs[env]
        self.drift_client = DriftClient(
            connection,
            wallet,
            env,
        )
        # Ensure sub-accounts are initialized for hedging
        if not DRY_RUN:
            await self.drift_client.subscribe()
            try:
                await self.drift_client.add_user(1) # Sub-account for hedge
            except:
                print("Hedge sub-account (1) not found or already exists")

        user_pubkey = self.drift_client.get_user_account_public_key(0)
        self.drift_user = DriftUser(self.drift_client, user_pubkey)
        print(f"Initialized DriftDCABot (DRY_RUN={DRY_RUN}) for user {user_pubkey}")

    async def update_telemetry(self):
        try:
            status = {
                "ts": int(time.time()),
                "total_profit": self.total_profit,
                "total_trades": self.total_trades,
                "active": self.active,
                "dry_run": DRY_RUN,
                "venue": "DRIFT"
            }
            os.makedirs("cache", exist_ok=True)
            with open("cache/drift_status.json", "w") as f:
                json.dump(status, f)
        except Exception as e:
            print(f"Telemetry update failed: {e}")

    async def hedge_position(self, base_asset_amount: int):
        target_hedge_amount = int(base_asset_amount * HEDGE_RATIO)
        print(f"Managing hedge for {base_asset_amount} units. Target short hedge: {target_hedge_amount}")

        if DRY_RUN:
            self.total_trades += 1
            return "dry_run_hedge_sig"

        # In Drift, we use sub-account 1 for the hedge to allow simultaneous Long/Short
        # We place a SHORT order on SOL-PERP in sub-account 1
        params = OrderParams(
            order_type=OrderType.Market(),
            market_type=MarketType.Perp(),
            direction=PositionDirection.Short(),
            base_asset_amount=target_hedge_amount,
            market_index=0,
        )
        try:
            return await self.drift_client.place_perp_order(params, sub_account_id=1)
        except Exception as e:
            print(f"Hedge order failed: {e}")

    async def check_profit_and_exit(self):
        if DRY_RUN:
            # Randomly simulate profit for dry run
            import random
            u_pnl = random.uniform(-0.5, 1.5)
            print(f"[DRY RUN] Current Unrealized PnL: ${u_pnl:.2f}")
            if u_pnl > PROFIT_TARGET_USD:
                print(f"Profit target reached! Closing position...")
                self.total_profit += u_pnl
                return True
            return False

        # Live logic
        u_pnl = await self.drift_user.get_unrealized_pnl() / PRICE_PRECISION
        print(f"Current Unrealized PnL: ${u_pnl:.2f}")
        if u_pnl > PROFIT_TARGET_USD:
            print(f"Profit target reached! Closing position...")
            # Close all positions logic
            await self.drift_client.close_position(0) # SOL market
            self.total_profit += u_pnl
            return True
        return False

    async def place_dca_order(self, amount: float, side: PositionDirection):
        print(f"Placing DCA {side} order for {amount} SOL")
        if DRY_RUN:
            self.total_trades += 1
            return "dry_run_sig"

        # In a real scenario, we'd use drift_client.place_perp_order
        # market_index 0 is usually SOL-PERP
        params = OrderParams(
            order_type=OrderType.Market(),
            market_type=MarketType.Perp(),
            direction=side,
            base_asset_amount=int(amount * BASE_PRECISION),
            market_index=0,
        )
        return await self.drift_client.place_perp_order(params)

    async def run(self):
        await self.initialize()
        last_dca_time = 0
        while self.active:
            now = time.time()

            # Check for profit and exit
            if await self.check_profit_and_exit():
                # For this strategy, we might wait before starting again
                print("Exited with profit. Waiting 1 hour before restart...")
                await self.update_telemetry()
                await asyncio.sleep(3600)
                continue

            # DCA Cycle
            if now - last_dca_time > DCA_INTERVAL_SEC:
                await self.place_dca_order(DCA_AMOUNT_SOL, PositionDirection.Long())
                last_dca_time = now

            # Hedge Management
            if not DRY_RUN:
                user_pos = await self.drift_user.get_perp_position(0)
                if user_pos:
                    await self.hedge_position(user_pos.base_asset_amount)
            else:
                await self.hedge_position(int(DCA_AMOUNT_SOL * BASE_PRECISION))

            await self.update_telemetry()
            await asyncio.sleep(60)

if __name__ == "__main__":
    bot = DriftDCABot()
    asyncio.run(bot.run())
