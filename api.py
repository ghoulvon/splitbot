import os
import json
import threading
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "expenses": [], "payments": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

MEMBERS = {
    "Ардақ":    {"id": "ardak",    "initials": "АР", "color": "r"},
    "Ақбота":   {"id": "akbota",   "initials": "АБ", "color": "a"},
    "Ұлболсын": {"id": "ulbolsyn", "initials": "ҰЛ", "color": "u"},
}

def get_name(data, uid):
    stored = data["users"].get(str(uid), {})
    name = stored.get("name", "")
    for known in MEMBERS:
        if known.lower() in name.lower():
            return known
    return name or f"User{str(uid)[-4:]}"

def calc_balances(data):
    # net[A][B] = сколько A должен B (положительное значение)
    names = list(MEMBERS.keys())
    net = {a: {b: 0.0 for b in names} for a in names}

    for exp in data["expenses"]:
        payer_uid = str(exp["payer_id"])
        payer_name = get_name(data, payer_uid)
        if payer_name not in MEMBERS:
            continue
        split = exp["split_count"]
        share = exp["amount"] / split
        for uid in exp["participants"]:
            debtor_name = get_name(data, uid)
            if debtor_name not in MEMBERS or debtor_name == payer_name:
                continue
            net[debtor_name][payer_name] += share

    for pay in data["payments"]:
        if pay.get("confirmed"):
            frm = get_name(data, pay["from_id"])
            to  = get_name(data, pay["to_id"])
            amt = pay["amount"]
            if frm in MEMBERS and to in MEMBERS:
                net[frm][to] = max(0, net[frm][to] - amt)

    return net

@app.route("/api/balance")
def balance():
    data = load_data()
    net = calc_balances(data)
    result = {}
    for person in MEMBERS:
        owes = []    # кому person должен
        owed = []    # кто должен person
        for other in MEMBERS:
            if other == person:
                continue
            if net[person][other] > 0.5:
                owes.append({"to": other, "amount": round(net[person][other])})
            if net[other][person] > 0.5:
                owed.append({"from": other, "amount": round(net[other][person])})
        total_owes = sum(x["amount"] for x in owes)
        total_owed = sum(x["amount"] for x in owed)
        result[person] = {
            "owes": owes,
            "owed_by": owed,
            "net": round(total_owed - total_owes),
        }
    return jsonify(result)

@app.route("/api/history")
def history():
    data = load_data()
    items = []
    for exp in reversed(data["expenses"][-30:]):
        payer = get_name(data, exp["payer_id"])
        items.append({
            "id": exp["id"],
            "payer": payer,
            "amount": exp["amount"],
            "description": exp["description"],
            "split_count": exp["split_count"],
            "share": round(exp["amount"] / exp["split_count"]),
            "date": exp["date"][:10],
            "type": "expense"
        })
    for pay in reversed(data["payments"][-10:]):
        frm = get_name(data, pay["from_id"])
        to  = get_name(data, pay["to_id"])
        items.append({
            "id": f"pay_{pay['id']}",
            "from": frm,
            "to": to,
            "amount": pay["amount"],
            "confirmed": pay.get("confirmed", False),
            "date": pay["date"][:10],
            "type": "payment"
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return jsonify(items[:30])

@app.route("/api/add_expense", methods=["POST"])
def add_expense():
    data = load_data()
    body = request.json
    payer_name = body.get("payer")
    desc = body.get("description", "")
    amount = float(body.get("amount", 0))
    participants = body.get("participants", [])

    if not payer_name or not desc or amount <= 0 or not participants:
        return jsonify({"error": "Қате деректер"}), 400

    # Find payer uid
    payer_uid = None
    for uid, udata in data["users"].items():
        if payer_name.lower() in udata.get("name", "").lower():
            payer_uid = uid
            break

    if not payer_uid:
        # Create placeholder
        payer_uid = f"web_{payer_name}"
        data["users"][payer_uid] = {"name": payer_name, "username": None}

    participant_uids = []
    for p_name in participants:
        p_uid = None
        for uid, udata in data["users"].items():
            if p_name.lower() in udata.get("name", "").lower():
                p_uid = uid
                break
        if not p_uid:
            p_uid = f"web_{p_name}"
            data["users"][p_uid] = {"name": p_name, "username": None}
        participant_uids.append(p_uid)

    expense = {
        "id": len(data["expenses"]) + 1,
        "payer_id": payer_uid,
        "amount": amount,
        "description": desc,
        "split_count": len(participant_uids),
        "participants": participant_uids,
        "date": datetime.now().isoformat(),
    }
    data["expenses"].append(expense)
    save_data(data)
    return jsonify({"ok": True, "expense": expense})

@app.route("/api/add_manual", methods=["POST"])
def add_manual():
    data = load_data()
    body = request.json
    from_name = body.get("from")
    to_name   = body.get("to")
    amount    = float(body.get("amount", 0))
    desc      = body.get("description", "қолмен жазылған")

    if not from_name or not to_name or amount <= 0 or from_name == to_name:
        return jsonify({"error": "Қате деректер"}), 400

    def get_or_create(name):
        for uid, udata in data["users"].items():
            if name.lower() in udata.get("name", "").lower():
                return uid
        uid = f"web_{name}"
        data["users"][uid] = {"name": name, "username": None}
        return uid

    from_uid = get_or_create(from_name)
    to_uid   = get_or_create(to_name)

    # Manual debt = expense where "to" paid, split only between from and to
    expense = {
        "id": len(data["expenses"]) + 1,
        "payer_id": to_uid,
        "amount": amount,
        "description": desc,
        "split_count": 1,
        "participants": [from_uid],
        "date": datetime.now().isoformat(),
        "manual": True,
    }
    data["expenses"].append(expense)
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/confirm_payment", methods=["POST"])
def confirm_payment():
    data = load_data()
    body = request.json
    pay_id = body.get("pay_id")
    confirmed = body.get("confirmed", False)

    payment = next((p for p in data["payments"] if p["id"] == pay_id), None)
    if not payment:
        return jsonify({"error": "Аударым табылмады"}), 404

    payment["confirmed"] = confirmed
    if not confirmed:
        payment["denied"] = True
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/mark_paid", methods=["POST"])
def mark_paid():
    data = load_data()
    body = request.json
    from_name = body.get("from")
    to_name   = body.get("to")
    amount    = float(body.get("amount", 0))

    def find_uid(name):
        for uid, udata in data["users"].items():
            if name.lower() in udata.get("name", "").lower():
                return uid
        return f"web_{name}"

    payment = {
        "id": len(data["payments"]) + 1,
        "from_id": find_uid(from_name),
        "to_id":   find_uid(to_name),
        "amount":  amount,
        "confirmed": False,
        "date": datetime.now().isoformat(),
    }
    data["payments"].append(payment)
    save_data(data)
    return jsonify({"ok": True, "pay_id": payment["id"]})

def run_api():
    port = int(os.environ.get("PORT", 8080))
    print(f"API server starting on port {port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_api()
