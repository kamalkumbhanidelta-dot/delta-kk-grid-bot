import os
import time
import json
import hmac
import hashlib
import requests
import traceback
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

BASE_URL = "https://api.india.delta.exchange"

SYMBOL = "XAUTUSD"
PRODUCT_ID = 131253

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

GRID_SIZE = float(
    os.getenv("GRID_SIZE", "15")
)

BASE_LOT = int(
    os.getenv("BASE_LOT", "1")
)

SCALING_MODE = os.getenv(
    "SCALING_MODE",
    "add"
).lower()

SCALING_VALUE = float(
    os.getenv("SCALING_VALUE", "1")
)

LEVEL_STEP = int(
    os.getenv("LEVEL_STEP", "100")
)

SLEEP_SECONDS = int(
    os.getenv("SLEEP_SECONDS", "5")
)

STATE_FILE = "state.json"

# =========================================================
# VALIDATION
# =========================================================

if not API_KEY:
    raise Exception("DELTA_API_KEY missing")

if not API_SECRET:
    raise Exception("DELTA_API_SECRET missing")

# =========================================================
# STATE
# =========================================================

def default_state():

    return {
        "positions": [],
        "base_price": None,

        # FIX ONLY
        "zero_counter": 0,
        "pending_order": False
    }

def load_state():

    if not os.path.exists(STATE_FILE):

        return default_state()

    try:

        with open(STATE_FILE, "r") as f:

            data = json.load(f)

            if "zero_counter" not in data:
                data["zero_counter"] = 0

            if "pending_order" not in data:
                data["pending_order"] = False

            return data

    except:

        return default_state()

def save_state():

    with open(STATE_FILE, "w") as f:

        json.dump(state, f, indent=2)

state = load_state()

# =========================================================
# SIGNATURE
# =========================================================

def generate_signature(message):

    return hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

# =========================================================
# PRIVATE GET
# =========================================================

def private_get(endpoint):

    timestamp = str(int(time.time()))

    signature_data = (
        "GET"
        + timestamp
        + endpoint
    )

    signature = generate_signature(
        signature_data
    )

    headers = {
        "Accept": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature
    }

    r = requests.get(
        BASE_URL + endpoint,
        headers=headers,
        timeout=20
    )

    return r.json()

# =========================================================
# PRIVATE POST
# =========================================================

def private_post(endpoint, payload):

    body = json.dumps(
        payload,
        separators=(",", ":")
    )

    timestamp = str(int(time.time()))

    signature_data = (
        "POST"
        + timestamp
        + endpoint
        + body
    )

    signature = generate_signature(
        signature_data
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": signature
    }

    r = requests.post(
        BASE_URL + endpoint,
        headers=headers,
        data=body,
        timeout=20
    )

    return r.json()

# =========================================================
# LIVE PRICE
# =========================================================

def get_live_price():

    r = requests.get(
        f"{BASE_URL}/v2/tickers/{SYMBOL}",
        timeout=10
    )

    data = r.json()

    return float(
        data["result"]["close"]
    )

# =========================================================
# POSITION SIZE
# =========================================================

def get_position_size():

    endpoint = "/v2/positions/margined"

    data = private_get(endpoint)

    total = 0

    for p in data.get("result", []):

        if p.get("product_symbol") == SYMBOL:

            total += int(
                float(
                    p.get("size", 0)
                )
            )

    return total

# =========================================================
# LOT ENGINE
# =========================================================

def get_lot_size(price):

    if state["base_price"] is None:

        state["base_price"] = float(price)

        save_state()

    base_price = float(
        state["base_price"]
    )

    base_zone = int(
        base_price // LEVEL_STEP
    )

    current_zone = int(
        price // LEVEL_STEP
    )

    levels_down = max(
        0,
        base_zone - current_zone
    )

    lot = BASE_LOT

    for _ in range(levels_down):

        if SCALING_MODE == "multiply":

            lot = lot * SCALING_VALUE

        elif SCALING_MODE == "add":

            lot = lot + SCALING_VALUE

    return max(
        1,
        int(round(lot))
    )

# =========================================================
# ORDER
# =========================================================

def place_market_order(side, qty):

    qty = int(qty)

    payload = {
        "product_id": PRODUCT_ID,
        "product_symbol": SYMBOL,
        "size": qty,
        "side": side,
        "order_type": "market_order"
    }

    print("ORDER PAYLOAD:", payload)

    response = private_post(
        "/v2/orders",
        payload
    )

    print("ORDER RESPONSE:", response)

    return response

# =========================================================
# BUY
# =========================================================

def execute_buy(price):

    if state["pending_order"]:
        return

    qty = get_lot_size(price)

    state["pending_order"] = True
    save_state()

    response = place_market_order(
        "buy",
        qty
    )

    if response.get("success") is True:

        state["positions"].append({

            "buy_price": float(price),

            "qty": int(qty)

        })

        save_state()

        print(
            f"BUY SUCCESS -> PRICE={price} QTY={qty}"
        )

    state["pending_order"] = False
    save_state()

# =========================================================
# SELL
# =========================================================

def execute_sell(position):

    if state["pending_order"]:
        return

    pos_size = get_position_size()

    qty = min(

        int(position["qty"]),

        int(pos_size)

    )

    if qty <= 0:

        print("SELL BLOCKED")

        return

    state["pending_order"] = True
    save_state()

    response = place_market_order(
        "sell",
        qty
    )

    if response.get("success") is True:

        if position in state["positions"]:

            state["positions"].remove(
                position
            )

        save_state()

        print(
            f"SELL SUCCESS -> {position}"
        )

    state["pending_order"] = False
    save_state()

# =========================================================
# STARTUP
# =========================================================

print("===================================")
print("XAUTUSD GRID BOT STARTED")
print("PRODUCT ID:", PRODUCT_ID)
print("GRID SIZE:", GRID_SIZE)
print("BASE LOT:", BASE_LOT)
print("SCALING MODE:", SCALING_MODE)
print("SCALING VALUE:", SCALING_VALUE)
print("LEVEL STEP:", LEVEL_STEP)
print("STATE:", state)
print("===================================")

# =========================================================
# MAIN LOOP
# =========================================================

while True:

    try:

        price = get_live_price()

        pos_size = get_position_size()

        print(
            datetime.now(),
            "| PRICE:", price,
            "| POSITION:", pos_size,
            "| OPEN_BUYS:", len(state["positions"])
        )

        # =================================================
        # FIX:
        # DELTA API temporary zero ignore
        # =================================================

        if pos_size <= 0:
            state["zero_counter"] += 1
        else:
            state["zero_counter"] = 0

        save_state()

        # =================================================
        # SAFETY RESET
        # same logic
        # only confirm 3 times
        # =================================================

        if (
            state["zero_counter"] >= 3
            and
            pos_size <= 0
            and
            len(state["positions"]) > 0
        ):

            print("RESETTING POSITION STATE")

            state["positions"] = []

            state["base_price"] = None

            save_state()

            time.sleep(SLEEP_SECONDS)

            continue

        # =================================================
        # FIRST AUTO BUY
        # EXACT SAME
        # =================================================

        if pos_size <= 0 and len(state["positions"]) == 0:

            print("NO POSITION -> AUTO BUY")

            execute_buy(price)

            time.sleep(SLEEP_SECONDS)

            continue

        # =================================================
        # GRID BUY
        # EXACT SAME
        # =================================================

        if len(state["positions"]) > 0:

            last_buy_price = state["positions"][-1]["buy_price"]

            next_buy = (
                last_buy_price
                - GRID_SIZE
            )

            if price <= next_buy:

                duplicate = False

                for p in state["positions"]:

                    if abs(
                        p["buy_price"] - price
                    ) < 1:

                        duplicate = True
                        break

                if not duplicate:

                    print(
                        "GRID BUY TRIGGER"
                    )

                    execute_buy(price)

        # =================================================
        # GRID SELL
        # EXACT SAME
        # =================================================

        for position in state["positions"][:]:

            target = (
                position["buy_price"]
                + GRID_SIZE
            )

            if price >= target:

                print(
                    "GRID SELL TRIGGER ->",
                    position
                )

                execute_sell(position)

        time.sleep(SLEEP_SECONDS)

    except Exception as e:

        print("ERROR:", str(e))

        traceback.print_exc()

        time.sleep(SLEEP_SECONDS)
