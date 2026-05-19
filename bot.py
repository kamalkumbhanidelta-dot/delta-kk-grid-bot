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

# GRID GAP
GRID_SIZE = float(
    os.getenv("GRID_SIZE", "15")
)

# START LOT
BASE_LOT = int(
    os.getenv("BASE_LOT", "1")
)

# add / multiply
SCALING_MODE = os.getenv(
    "SCALING_MODE",
    "add"
).lower()

# add=+1
# multiply=*2
SCALING_VALUE = float(
    os.getenv("SCALING_VALUE", "1")
)

# SERIES STEP
# 100 => 4500 / 4400 / 4300
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
        "base_price": None
    }

def load_state():

    if not os.path.exists(STATE_FILE):

        return default_state()

    try:

        with open(STATE_FILE, "r") as f:

            return json.load(f)

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

    # FIRST BUY PRICE
    if state["base_price"] is None:

        state["base_price"] = float(price)

        save_state()

    base_price = float(
        state["base_price"]
    )

    # EXAMPLE:
    #
    # BASE = 4541
    #
    # 4541 = 1 LOT
    # 4501 = 1 LOT
    # 4499 = 2 LOT
    # 4400 BELOW = 3 LOT

    base_zone = int(
        base_price // LEVEL_STEP
    )

    current_zone = int(
        price // LEVEL_STEP
    )

    # HOW MANY SERIES DOWN
    levels_down = max(
        0,
        base_zone - current_zone
    )

    lot = BASE_LOT

    for _ in range(levels_down):

        # MULTIPLY MODE
        if SCALING_MODE == "multiply":

            lot = lot * SCALING_VALUE

        # ADD MODE
        elif SCALING_MODE == "add":

            lot = lot + SCALING_VALUE

    return max(
        1,
        int(round(lot))
    )

# =========================================================
# PLACE ORDER
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

    qty = get_lot_size(price)

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

# =========================================================
# SELL
# =========================================================

def execute_sell(position):

    pos_size = get_position_size()

    qty = min(

        int(position["qty"]),

        int(pos_size)

    )

    # NEVER SHORT SELL
    if qty <= 0:

        print("SELL BLOCKED")

        return

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
        # SAFETY RESET
        # =================================================

        if pos_size <= 0 and len(state["positions"]) > 0:

            print("RESETTING POSITION STATE")

            state["positions"] = []

            state["base_price"] = None

            save_state()

            time.sleep(SLEEP_SECONDS)

            continue

        # =================================================
        # FIRST AUTO BUY
        # =================================================

        if pos_size <= 0 and len(state["positions"]) == 0:

            print("NO POSITION -> AUTO BUY")

            execute_buy(price)

            time.sleep(SLEEP_SECONDS)

            continue

        # =================================================
        # GRID BUY
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

                    # SAME BUY BLOCK
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
