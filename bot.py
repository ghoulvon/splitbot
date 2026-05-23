import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # Railway URL + /webapp
DATA_FILE = "data.json"

AMOUNT, DESCRIPTION, SPLIT = range(3)
CONFIRM_PAYMENT = range(3, 4)

MEMBER_NAMES = ["Ардақ", "Ақбота", "Ұлболсын"]

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "expenses": [], "payments": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_display_name(data, user_id):
    uid = str(user_id)
    stored = data["users"].get(uid, {})
    name = stored.get("name", "")
    for known in MEMBER_NAMES:
        if known.lower() in name.lower() or name.lower() in known.lower():
            return known
    return name if name else f"User{uid[-4:]}"

def calc_balances(data):
    balance = {}
    for u in data["users"]:
        balance[u] = 0.0
    for exp in data["expenses"]:
        payer = str(exp["payer_id"])
        share = exp["amount"] / exp["split_count"]
        for uid in exp["participants"]:
            uid = str(uid)
            if uid not in balance:
                balance[uid] = 0.0
            if uid == payer:
                balance[uid] += exp["amount"] - share
            else:
                balance[uid] -= share
    for pay in data["payments"]:
        if pay.get("confirmed"):
            frm = str(pay["from_id"])
            to  = str(pay["to_id"])
            amt = pay["amount"]
            if frm not in balance: balance[frm] = 0.0
            if to  not in balance: balance[to]  = 0.0
            balance[frm] += amt
            balance[to]  -= amt
    return balance

def build_balance_text(data):
    balance = calc_balances(data)
    if not balance:
        return "Әзірше деректер жоқ 🤷"
    lines = ["💰 *Ағымдағы баланс:*\n"]
    for uid, amt in balance.items():
        name = get_display_name(data, uid)
        if abs(amt) < 1:
            lines.append(f"✅ {name}: теңестірілді")
        elif amt > 0:
            lines.append(f"📥 {name}: *{amt:,.0f} ₸* алуы керек")
        else:
            lines.append(f"📤 {name}: *{abs(amt):,.0f} ₸* қарыз")
    debts = []
    uids = list(balance.keys())
    for i in range(len(uids)):
        for j in range(len(uids)):
            if i == j: continue
            if balance[uids[i]] < -0.5 and balance[uids[j]] > 0.5:
                amt = min(abs(balance[uids[i]]), balance[uids[j]])
                debts.append(
                    f"  ➡️ {get_display_name(data, uids[i])} → "
                    f"{get_display_name(data, uids[j])}: *{amt:,.0f} ₸*"
                )
    if debts:
        lines.append("\n📋 *Аударымдар:*")
        lines += debts
    return "\n".join(lines)

# ── Commands ──────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    name = update.effective_user.first_name
    if uid not in data["users"]:
        data["users"][uid] = {"name": name, "username": update.effective_user.username}
        save_data(data)

    keyboard = []
    if WEBAPP_URL:
        keyboard.append([InlineKeyboardButton(
            "📊 Балансты ашу",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )])

    keyboard.append([
        InlineKeyboardButton("➕ Шығын қосу", callback_data="menu_add"),
        InlineKeyboardButton("📊 Баланс", callback_data="menu_balance"),
    ])
    keyboard.append([
        InlineKeyboardButton("💸 Аударым", callback_data="menu_pay"),
        InlineKeyboardButton("📋 Тарих", callback_data="menu_history"),
    ])

    await update.message.reply_text(
        f"Сәлем, {name}! 👋\n"
        "Ардақ, Ақбота және Ұлболсынның ортақ шығындар боты!\n\n"
        "Командалар:\n"
        "➕ /add — шығын қосу\n"
        "💸 /pay — аударым белгілеу\n"
        "📊 /balance — баланс\n"
        "📋 /history — тарих\n",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def balance_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    keyboard = []
    if WEBAPP_URL:
        keyboard.append([InlineKeyboardButton(
            "📊 Толық балансты ашу →",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )])
    await update.message.reply_text(
        build_balance_text(data),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def history_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["expenses"]:
        await update.message.reply_text("Тарих бос 📭")
        return
    lines = ["📋 *Соңғы шығындар:*\n"]
    for exp in reversed(data["expenses"][-10:]):
        payer_name = get_display_name(data, exp["payer_id"])
        date = exp["date"][:10]
        lines.append(
            f"📅 {date} | {payer_name} *{exp['amount']:,.0f} ₸* төледі\n"
            f"   📝 {exp['description']} (÷{exp['split_count']})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "menu_balance":
        data = load_data()
        keyboard = []
        if WEBAPP_URL:
            keyboard.append([InlineKeyboardButton("📊 Толық балансты ашу →", web_app=WebAppInfo(url=WEBAPP_URL))])
        await query.edit_message_text(
            build_balance_text(data),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
    elif query.data == "menu_history":
        data = load_data()
        if not data["expenses"]:
            await query.edit_message_text("Тарих бос 📭")
            return
        lines = ["📋 *Соңғы шығындар:*\n"]
        for exp in reversed(data["expenses"][-10:]):
            payer_name = get_display_name(data, exp["payer_id"])
            date = exp["date"][:10]
            lines.append(f"📅 {date} | {payer_name} *{exp['amount']:,.0f} ₸*\n   📝 {exp['description']} (÷{exp['split_count']})")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    elif query.data == "menu_add":
        await query.edit_message_text("➕ Шығын қосу үшін /add жаз")
    elif query.data == "menu_pay":
        await query.edit_message_text("💸 Аударым белгілеу үшін /pay жаз")

# ── Add expense ────────────────────────────────────────────

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Қанша жұмсалды? Сумманы теңгемен жаз:\n(мысалы: `15000`)",
        parse_mode="Markdown"
    )
    return AMOUNT

async def add_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(" ", "").replace(",", "")
    try:
        amount = float(text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Дұрыс сумманы жаз, мысалы: `5000`", parse_mode="Markdown")
        return AMOUNT
    ctx.user_data["amount"] = amount
    await update.message.reply_text(
        f"✅ Сумма: *{amount:,.0f} ₸*\n\n📝 Не үшін жұмсалды? Сипаттама жаз:\n(мысалы: азық-түлік, кешкі ас)",
        parse_mode="Markdown"
    )
    return DESCRIPTION

async def add_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["description"] = update.message.text.strip()
    keyboard = [[
        InlineKeyboardButton("👥 Екіге бөлу (÷2)", callback_data="split_2"),
        InlineKeyboardButton("👨‍👩‍👦 Үшке бөлу (÷3)", callback_data="split_3"),
    ], [InlineKeyboardButton("❌ Болдырмау", callback_data="cancel")]]
    await update.message.reply_text(
        f"📝 Сипаттама: *{ctx.user_data['description']}*\n"
        f"💰 Сумма: *{ctx.user_data['amount']:,.0f} ₸*\n\nҚанша адамға бөлеміз?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SPLIT

async def add_split(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Болдырылмады")
        return ConversationHandler.END

    split_count = int(query.data.split("_")[1])
    data = load_data()
    uid = str(query.from_user.id)
    amount = ctx.user_data["amount"]
    share = amount / split_count
    participants = list(data["users"].keys())
    if len(participants) < split_count:
        split_count = max(len(participants), 1)
        share = amount / split_count

    expense = {
        "id": len(data["expenses"]) + 1,
        "payer_id": uid,
        "amount": amount,
        "description": ctx.user_data["description"],
        "split_count": split_count,
        "participants": participants[:split_count] if len(participants) >= split_count else participants,
        "date": datetime.now().isoformat(),
    }
    if uid not in expense["participants"]:
        expense["participants"].append(uid)
        expense["split_count"] = len(expense["participants"])
        share = amount / expense["split_count"]

    data["expenses"].append(expense)
    save_data(data)

    payer_name = get_display_name(data, uid)
    lines = [
        f"✅ Шығын қосылды!\n",
        f"👤 Төлеген: *{payer_name}*",
        f"💰 Сумма: *{amount:,.0f} ₸*",
        f"📝 Сипаттама: {expense['description']}",
        f"➗ {expense['split_count']}-ке бөлу: *{share:,.0f} ₸*-тан\n",
        "📋 *Аударуы керек:*"
    ]
    for p_uid in expense["participants"]:
        p_name = get_display_name(data, p_uid)
        if str(p_uid) != str(uid):
            lines.append(f"  💸 {p_name} → {payer_name}: *{share:,.0f} ₸*")

    keyboard = []
    if WEBAPP_URL:
        keyboard.append([InlineKeyboardButton("📊 Балансты көру →", web_app=WebAppInfo(url=WEBAPP_URL))])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )
    return ConversationHandler.END

# ── Pay ────────────────────────────────────────────────────

async def pay_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    balance = calc_balances(data)
    if uid not in balance or balance[uid] >= -1:
        await update.message.reply_text("✅ Сенің қарызың жоқ!")
        return ConversationHandler.END

    creditors = []
    for other_uid, amt in balance.items():
        if other_uid != uid and amt > 0.5:
            creditors.append((other_uid, min(abs(balance[uid]), amt)))

    if not creditors:
        await update.message.reply_text("✅ Барлығы таза, қарыз жоқ!")
        return ConversationHandler.END

    lines = ["💸 Сенің қарызың:\n"]
    keyboard = []
    for cred_uid, amt in creditors:
        name = get_display_name(data, cred_uid)
        lines.append(f"  ➡️ {name}: *{amt:,.0f} ₸*")
        keyboard.append([InlineKeyboardButton(
            f"✅ {name}-ге аудардым ({amt:,.0f} ₸)",
            callback_data=f"paid_{cred_uid}_{amt:.0f}"
        )])
    keyboard.append([InlineKeyboardButton("❌ Болдырмау", callback_data="cancel_pay")])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_PAYMENT

async def pay_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_pay":
        await query.edit_message_text("❌ Болдырылмады")
        return ConversationHandler.END

    _, to_uid, amt_str = query.data.split("_", 2)
    amount = float(amt_str)
    data = load_data()
    from_uid = str(query.from_user.id)
    from_name = get_display_name(data, from_uid)
    to_name = get_display_name(data, to_uid)

    payment = {
        "id": len(data["payments"]) + 1,
        "from_id": from_uid,
        "to_id": to_uid,
        "amount": amount,
        "confirmed": False,
        "date": datetime.now().isoformat(),
    }
    data["payments"].append(payment)
    pay_id = payment["id"]
    save_data(data)

    keyboard = [[
        InlineKeyboardButton("✅ Иә, алдым!", callback_data=f"confirm_{pay_id}"),
        InlineKeyboardButton("❌ Жоқ", callback_data=f"deny_{pay_id}"),
    ]]
    await query.edit_message_text(
        f"⏳ {from_name} саған *{amount:,.0f} ₸* аударды дейді\n"
        f"{to_name}-тің растауын күтемін...",
        parse_mode="Markdown"
    )
    try:
        await ctx.bot.send_message(
            chat_id=int(to_uid),
            text=f"💰 *{from_name}* саған *{amount:,.0f} ₸* аударды дейді\nАқшаны алдың ба?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.warning(f"Хабарлама жіберу мүмкін болмады {to_uid}: {e}")
    return ConversationHandler.END

async def handle_payment_response(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, pay_id_str = query.data.split("_", 1)
    pay_id = int(pay_id_str)
    data = load_data()
    payment = next((p for p in data["payments"] if p["id"] == pay_id), None)
    if not payment:
        await query.edit_message_text("❌ Аударым табылмады")
        return

    from_name = get_display_name(data, payment["from_id"])
    to_name = get_display_name(data, payment["to_id"])
    amount = payment["amount"]

    if action == "confirm":
        payment["confirmed"] = True
        save_data(data)
        await query.edit_message_text(
            f"✅ Расталды! {from_name} → {to_name}: *{amount:,.0f} ₸*",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=int(payment["from_id"]),
                text=f"✅ *{to_name}* *{amount:,.0f} ₸* алғанын растады! Қарыз жабылды 🎉",
                parse_mode="Markdown"
            )
        except Exception: pass
    else:
        payment["denied"] = True
        save_data(data)
        await query.edit_message_text(
            f"❌ {to_name} {from_name}-нан аударымды растамады",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=int(payment["from_id"]),
                text=f"❌ *{to_name}* *{amount:,.0f} ₸* алғанын растамады. Сөйлес!",
                parse_mode="Markdown"
            )
        except Exception: pass

async def webapp_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Веб-қосымшадан деректерді өңдеу"""
    try:
        payload = json.loads(update.effective_message.web_app_data.data)
        data = load_data()
        uid = str(update.effective_user.id)

        if payload["type"] == "expense":
            participants = payload.get("participants", [])
            split_count = len(participants)
            if split_count == 0: return
            amount = float(payload["amount"])
            share = amount / split_count

            participant_ids = []
            for p_name in participants:
                for u_id, u_data in data["users"].items():
                    if p_name.lower() in u_data.get("name","").lower():
                        participant_ids.append(u_id)
                        break

            expense = {
                "id": len(data["expenses"]) + 1,
                "payer_id": uid,
                "amount": amount,
                "description": payload["desc"],
                "split_count": split_count,
                "participants": participant_ids if participant_ids else [uid],
                "date": datetime.now().isoformat(),
            }
            data["expenses"].append(expense)
            save_data(data)
            payer_name = get_display_name(data, uid)
            await update.message.reply_text(
                f"✅ Шығын қосылды: *{amount:,.0f} ₸* — {payload['desc']}\n"
                f"Әрқайсысынан *{share:,.0f} ₸*",
                parse_mode="Markdown"
            )

        elif payload["type"] == "manual":
            await update.message.reply_text(
                f"✅ Қарыз жазылды: {payload['to']} → {payload['from']} *{float(payload['amount']):,.0f} ₸*",
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"WebApp деректерін өңдеу қатесі: {e}")

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Болдырылмады")
    return ConversationHandler.END

# ── Main ───────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            AMOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            SPLIT:       [CallbackQueryHandler(add_split, pattern="^split_|^cancel$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    pay_conv = ConversationHandler(
        entry_points=[CommandHandler("pay", pay_start)],
        states={
            CONFIRM_PAYMENT: [CallbackQueryHandler(pay_confirm, pattern="^paid_|^cancel_pay$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(add_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(handle_payment_response, pattern="^confirm_|^deny_"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))

    logger.info("Бот іске қосылды!")
    app.run_polling()

if __name__ == "__main__":
    main()

async def run_async():
    """Run bot asynchronously for use with threading"""
    application = Application.builder().token(TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            AMOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            SPLIT:       [CallbackQueryHandler(add_split, pattern="^split_|^cancel$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    pay_conv = ConversationHandler(
        entry_points=[CommandHandler("pay", pay_start)],
        states={
            CONFIRM_PAYMENT: [CallbackQueryHandler(pay_confirm, pattern="^paid_|^cancel_pay$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("history", history_cmd))
    application.add_handler(add_conv)
    application.add_handler(pay_conv)
    application.add_handler(CallbackQueryHandler(handle_payment_response, pattern="^confirm_|^deny_"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))

    async with application:
        await application.start()
        await application.updater.start_polling()
        # Keep running
        import asyncio
        while True:
            await asyncio.sleep(3600)
