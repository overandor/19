import os
import asyncio
import base58
import base64
import numpy as np
import aiohttp
import json
import random
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Processed, Confirmed
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.instruction import Instruction
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.system_program import transfer, TransferParams

# Drift SDK Imports
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.types import (
    MarketType,
    OrderParams,
    OrderType,
    PositionDirection,
    PostOnlyParams
)
from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
import anchorpy

# =============================================================================
# PRODUCTION CONFIG
# =============================================================================

RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
PRIVATE_KEY_B58 = os.getenv("WALLET_PRIVATE_KEY")

# Jito HTTP Endpoints
JITO_ENDPOINTS = [
    "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles"
]

# Jito Tip Accounts (Verified valid Base58)
TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "DfXygSm4jEPec2FfRSTRbskyK6QXq8R3Md6t5qrXG8r7",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopXSjbCpNSR24u3dG98hELe8Lw",
]
BASE_TIP_LAMPORTS = 100_000

# Market Constants
SOL_PERP_MARKET_INDEX = 0
TICK_SIZE = Decimal("0.001")
STEP_SIZE = Decimal("0.1")

# Risk & Strategy Constants
MAX_INVENTORY = Decimal("10.0") # Max SOL position before halting/flattening
BASE_SPREAD = Decimal("0.02")  # 2 cents base half-spread
GAMMA = Decimal("0.5")         # Inventory skew intensity
UPDATE_THRESHOLD = Decimal("0.0005") # 0.05% price move required to update

# =============================================================================
# ENGINE STATE & HELPERS
# =============================================================================

@dataclass
class MMState:
    inventory: Decimal = Decimal("0")
    price_buffer: List[float] = field(default_factory=list)

    @property
    def sigma_sq(self) -> float:
        if len(self.price_buffer) < 10: return 0.0004
        returns = np.diff(np.log(self.price_buffer))
        return float(np.var(returns))

class OrderManager:
    """Tracks active quotes to avoid redundant updates (Toxicity Fix)."""
    def __init__(self, min_update_threshold: Decimal):
        self.active_bid: Optional[Dict] = None # {price: float, size: float}
        self.active_ask: Optional[Dict] = None
        self.min_update_threshold = min_update_threshold

    def should_update(self, new_bid: Decimal, new_ask: Decimal, current_mid: Decimal) -> bool:
        if not self.active_bid or not self.active_ask:
            return True

        old_bid_px = Decimal(str(self.active_bid['price']))
        old_ask_px = Decimal(str(self.active_ask['price']))

        # Check if price moved significantly
        bid_diff = abs(new_bid - old_bid_px) / current_mid
        ask_diff = abs(new_ask - old_ask_px) / current_mid

        if bid_diff > self.min_update_threshold or ask_diff > self.min_update_threshold:
            return True

        return False

    def update_local_state(self, new_bid: Decimal, bid_size: Decimal, new_ask: Decimal, ask_size: Decimal):
        self.active_bid = {'price': float(new_bid), 'size': float(bid_size)}
        self.active_ask = {'price': float(new_ask), 'size': float(ask_size)}

class JitoBundleBuilder:
    def __init__(self, kp: Keypair, connection: AsyncClient):
        self.kp = kp
        self.connection = connection
        self.tip_accounts = [Pubkey.from_string(t) for t in TIP_ACCOUNTS]
        self.session: Optional[aiohttp.ClientSession] = None

    async def get_recent_blockhash(self) -> Hash:
        resp = await self.connection.get_latest_blockhash(commitment=Processed)
        return resp.value.blockhash

    def build_tip_transaction(self, tip_amount: int, blockhash: Hash) -> VersionedTransaction:
        tip_account = random.choice(self.tip_accounts)
        ix_tip = transfer(
            TransferParams(
                from_pubkey=self.kp.pubkey(),
                to_pubkey=tip_account,
                lamports=tip_amount
            )
        )
        msg = MessageV0.try_compile(
            payer=self.kp.pubkey(),
            instructions=[ix_tip],
            address_lookup_tables=[],
            recent_blockhash=blockhash
        )
        return VersionedTransaction(msg, [self.kp])

    def build_drift_transaction(self, ixs: List[Instruction], blockhash: Hash) -> VersionedTransaction:
        ix_cu_limit = set_compute_unit_limit(400_000)
        ix_cu_price = set_compute_unit_price(25_000)

        final_ixs = [ix_cu_limit, ix_cu_price] + ixs

        msg = MessageV0.try_compile(
            payer=self.kp.pubkey(),
            instructions=final_ixs,
            address_lookup_tables=[],
            recent_blockhash=blockhash
        )
        return VersionedTransaction(msg, [self.kp])

    async def send_bundle(self, transactions: List[VersionedTransaction]):
        if not self.session:
            self.session = aiohttp.ClientSession()

        serialized = [base64.b64encode(bytes(tx)).decode("utf-8") for tx in transactions]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [serialized]
        }

        for url in JITO_ENDPOINTS:
            try:
                async with self.session.post(url, json=payload) as r:
                    if r.status == 200:
                        res = await r.json()
                        if "result" in res:
                            return res
            except Exception as e:
                print(f"[JITO] Error sending to {url}: {e}")
                continue
        return None

    async def close(self):
        if self.session:
            await self.session.close()

# =============================================================================
# MAIN MM ENGINE
# =============================================================================

class DriftJitoMM:
    def __init__(self):
        if not PRIVATE_KEY_B58:
            # For testing purposes we allow missing key if just initializing
            self.kp = Keypair()
        else:
            self.kp = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_B58))

        self.wallet = anchorpy.Wallet(self.kp)
        self.rpc = AsyncClient(RPC_URL)
        self.state = MMState()
        self.order_manager = OrderManager(UPDATE_THRESHOLD)
        self.jito = JitoBundleBuilder(self.kp, self.rpc)
        self.drift: Optional[DriftClient] = None
        self.market_index = SOL_PERP_MARKET_INDEX

    async def init_drift(self):
        self.drift = DriftClient(
            self.rpc,
            self.wallet,
            "mainnet",
            account_subscription=AccountSubscriptionConfig("websocket")
        )
        await self.drift.subscribe()

        if self.drift.get_user() is None:
            print("[*] Initializing Drift User Account...")
            await self.drift.initialize_user(sub_account_id=0)

        print(f"[*] Engine Active. User: {self.drift.get_user_account_public_key()}")

    async def update_inventory_from_chain(self):
        position = self.drift.get_user().get_perp_position(self.market_index)
        if position is None:
            self.state.inventory = Decimal("0")
            return
        raw_size = position.base_asset_amount
        self.state.inventory = Decimal(raw_size) / Decimal(BASE_PRECISION)

    async def risk_check(self) -> bool:
        inv = abs(self.state.inventory)
        if inv > MAX_INVENTORY:
            print(f"[RISK] Inventory limit breached: {inv} SOL. Flattening...")
            await self.flatten_position()
            return False

        oracle = self.drift.get_oracle_price_data_for_perp_market(self.market_index)
        if oracle is None:
            return False

        if oracle.confidence > oracle.price * 0.01:
            print(f"[RISK] Oracle confidence too wide: {oracle.confidence}. Halting quotes.")
            return False

        return True

    async def flatten_position(self):
        pos = self.drift.get_user().get_perp_position(self.market_index)
        if not pos or pos.base_asset_amount == 0:
            return

        direction = PositionDirection.Short() if pos.base_asset_amount > 0 else PositionDirection.Long()
        size = abs(Decimal(pos.base_asset_amount) / Decimal(BASE_PRECISION))
        size_int = self.quantize(size, STEP_SIZE, ROUND_FLOOR)

        oracle = self.drift.get_oracle_price_data_for_perp_market(self.market_index)
        px = Decimal(oracle.price / PRICE_PRECISION)

        price_offset = Decimal("0.99") if direction == PositionDirection.Short() else Decimal("1.01")
        price_int = self.quantize(px * price_offset, TICK_SIZE, ROUND_FLOOR)

        ix = self.build_place_ix(price_int, size_int, direction, post_only=False)
        bh = await self.jito.get_recent_blockhash()

        tx = self.jito.build_drift_transaction([ix], bh)
        tip_tx = self.jito.build_tip_transaction(BASE_TIP_LAMPORTS, bh)

        await self.jito.send_bundle([tx, tip_tx])
        print("[RISK] Emergency flatten bundle submitted.")

    def quantize(self, value: Decimal, step: Decimal, rounding=ROUND_FLOOR) -> int:
        quantized = (value / step).to_integral_value(rounding=rounding) * step
        precision = PRICE_PRECISION if step == TICK_SIZE else BASE_PRECISION
        return int(quantized * Decimal(precision))

    def build_cancel_ix(self) -> Instruction:
        return self.drift.get_cancel_orders_ix(MarketType.Perp(), self.market_index, None, 0)

    def build_place_ix(self, price_int: int, size_int: int, direction: PositionDirection, post_only: bool = True) -> Instruction:
        params = OrderParams(
            order_type=OrderType.Limit(),
            market_type=MarketType.Perp(),
            market_index=self.market_index,
            direction=direction,
            base_asset_amount=size_int,
            price=price_int,
            post_only=PostOnlyParams.MustPostOnly() if post_only else PostOnlyParams.NONE(),
            reduce_only=False,
            immediate_or_cancel=not post_only,
            user_order_id=0,
            trigger_price=0,
            trigger_condition=0,
            oracle_price_offset=0,
            auction_duration=0,
            max_ts=0,
            auction_start_price=0,
            auction_end_price=0,
        )
        return self.drift.get_place_perp_order_ix(params, sub_account_id=0)

    async def tick(self):
        if not self.drift or not self.drift.is_subscribed: return

        # 1. Update Inventory and Verify Risk
        await self.update_inventory_from_chain()
        if not await self.risk_check():
            return

        # 2. Market Data
        oracle_data = self.drift.get_oracle_price_data_for_perp_market(self.market_index)
        if not oracle_data: return

        price = Decimal(oracle_data.price) / Decimal(PRICE_PRECISION)
        self.state.price_buffer.append(float(price))
        if len(self.state.price_buffer) > 50: self.state.price_buffer.pop(0)

        # 3. Strategy Math
        sigma = Decimal(str(self.state.sigma_sq)).sqrt()
        vol_adj = sigma * Decimal("2.5")

        inv = self.state.inventory
        inv_ratio = max(min(inv / MAX_INVENTORY, Decimal("1")), Decimal("-1"))

        mid_shift = GAMMA * inv_ratio * (BASE_SPREAD + vol_adj)
        mid_price = price - mid_shift

        half_spread = BASE_SPREAD + vol_adj
        raw_bid = mid_price - half_spread
        raw_ask = mid_price + half_spread

        bid_px_dec = (raw_bid / TICK_SIZE).to_integral_value(rounding=ROUND_FLOOR) * TICK_SIZE
        ask_px_dec = (raw_ask / TICK_SIZE).to_integral_value(rounding=ROUND_CEILING) * TICK_SIZE

        # 4. Check if update is needed
        if not self.order_manager.should_update(bid_px_dec, ask_px_dec, price):
            return

        print(f"⚡ Update Required: Bid {bid_px_dec} | Ask {ask_px_dec} | Inv {inv}")

        bid_px_int = self.quantize(bid_px_dec, TICK_SIZE, ROUND_FLOOR)
        ask_px_int = self.quantize(ask_px_dec, TICK_SIZE, ROUND_CEILING)

        base_size = Decimal("1.0") * (Decimal("1") - abs(inv_ratio))
        size_dec = max(base_size, Decimal("0.2"))
        size_int = self.quantize(size_dec, STEP_SIZE, ROUND_FLOOR)

        if bid_px_int >= ask_px_int:
            return

        # 5. Build and Send Jito Bundle
        bh = await self.jito.get_recent_blockhash()

        ix_cancel = self.build_cancel_ix()
        ix_bid = self.build_place_ix(bid_px_int, size_int, PositionDirection.Long())
        ix_ask = self.build_place_ix(ask_px_int, size_int, PositionDirection.Short())

        tx_cancel = self.jito.build_drift_transaction([ix_cancel], bh)
        tx_bid = self.jito.build_drift_transaction([ix_bid], bh)
        tx_ask = self.jito.build_drift_transaction([ix_ask], bh)
        tx_tip = self.jito.build_tip_transaction(BASE_TIP_LAMPORTS, bh)

        bundle = [tx_cancel, tx_bid, tx_ask, tx_tip]

        resp = await self.jito.send_bundle(bundle)
        if resp and "result" in resp:
            self.order_manager.update_local_state(bid_px_dec, size_dec, ask_px_dec, size_dec)
            print(f"[JITO] Bundle Submitted: {resp.get('result')}")

    async def run(self):
        try:
            await self.init_drift()
            while True:
                await self.tick()
                await asyncio.sleep(2.0)
        finally:
            if self.drift: await self.drift.unsubscribe()
            await self.jito.close()
            await self.rpc.close()

if __name__ == "__main__":
    asyncio.run(DriftJitoMM().run())
