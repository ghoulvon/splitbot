import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
DATA_FILE = "data.json"

# Conversation states
AMOUNT, DESCRIPTION, SPLIT = range(3)
CONFIRM_PAYMENT = range(3, 4)

# ─── Data helpers ────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "expenses": [], "payments": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

MEMBER_NAMES = ["Ардақ", "Ақбота", "Ұлболсын"]

def get_display_name(data, user_id):
    uid = str(user_id)
    stored = data["users"].get(uid, {})
    name = stored.get("name", "")
    # Если имя из Telegram совпадает с одним из участников — используем его
    for known in MEMBER_NAMES:
        if known.lower() in name.lower() or name.lower() in known.lower():
            return known
    return name if name else f"User{uid[-4:]}"

def calc_balances(data):
    """Кто кому сколько должен (чистый баланс)."""
    # balance[uid] = сколько ему должны (+ = должны ему, - = он должен)
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
        return "Пока нет данных 🤷"

    lines = ["💰 *Текущий баланс:*\n"]
    for uid, amt in balance.items():
        name = get_display_name(data, uid)
        if abs(amt) < 1:
            lines.append(f"✅ {name}: всё ровно")
        elif amt > 0:
            lines.append(f"📥 {name}: ему должны *{amt:,.0f} ₸*")
        else:
            lines.append(f"📤 {name}: должен *{abs(amt):,.0f} ₸*")

    # Кто кому конкретно
    debts = []
    uids = list(balance.keys())
    for i in range(len(uids)):
        for j in range(len(uids)):
            if i == j:
                continue
            if balance[uids[i]] < -0.5 and balance[uids[j]] > 0.5:
                amt = min(abs(balance[uids[i]]), balance[uids[j]])
                debts.append(
                    f"  ➡️ {get_display_name(data, uids[i])} → "
                    f"{get_display_name(data, uids[j])}: *{amt:,.0f} ₸*"
                )
    if debts:
        lines.append("\n📋 *Переводы:*")
        lines += debts

    return "\n".join(lines)

# ─── Commands ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    name = update.effective_user.first_name

    if uid not in data["users"]:
        data["users"][uid] = {"name": name, "username": update.effective_user.username}
        save_data(data)
        await update.message.reply_text(
            f"Сәлем, {name}! 👋\n"
            "Ардақ, Ақбота және Ұлболсынның ортақ шығындар боты!\n\n"
            "Команды:\n"
            "➕ /add — добавить расход\n"
            "💸 /pay — отметить перевод\n"
            "📊 /balance — посмотреть баланс\n"
            "📋 /history — история расходов\n"
        )
    else:
        data["users"][uid]["name"] = name
        save_data(data)
        await update.message.reply_text(
            f"Қайта келдің, {name}! 👋\n\n"
            "➕ /add — добавить расход\n"
            "💸 /pay — отметить перевод\n"
            "📊 /balance — посмотреть баланс\n"
            "📋 /history — история расходов\n"
        )

async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.message.reply_text(build_balance_text(data), parse_mode="Markdown")

async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["expenses"]:
        await update.message.reply_text("История пустая 📭")
        return

    lines = ["📋 *Последние расходы:*\n"]
    for exp in reversed(data["expenses"][-10:]):
        payer_name = get_display_name(data, exp["payer_id"])
        date = exp["date"][:10]
        lines.append(
            f"📅 {date} | {payer_name} заплатил *{exp['amount']:,.0f} ₸*\n"
            f"   📝 {exp['description']} (÷{exp['split_count']})"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─── Add expense conversation ─────────────────────────────────────────────────

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Сколько потратил? Введи сумму в тенге:\n"
        "(например: `15000`)",
        parse_mode="Markdown"
    )
    return AMOUNT

async def add_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(" ", "").replace(",", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи правильную сумму, например: `5000`", parse_mode="Markdown")
        return AMOUNT

    ctx.user_data["amount"] = amount
    await update.message.reply_text(
        f"✅ Сумма: *{amount:,.0f} ₸*\n\n"
        "📝 На что потратил? Напиши описание:\n"
        "(например: продукты, ужин, бытовая химия)",
        parse_mode="Markdown"
    )
    return DESCRIPTION

async def add_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["description"] = update.message.text.strip()

    keyboard = [
        [
            InlineKeyboardButton("👥 На двоих (÷2)", callback_data="split_2"),
            InlineKeyboardButton("👨‍👩‍👦 На троих (÷3)", callback_data="split_3"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
    ]
    await update.message.reply_text(
        f"📝 Описание: *{ctx.user_data['description']}*\n"
        f"💰 Сумма: *{ctx.user_data['amount']:,.0f} ₸*\n\n"
        "На сколько делим?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SPLIT

async def add_split(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return ConversationHandler.END

    split_count = int(query.data.split("_")[1])
    data = load_data()

    uid = str(query.from_user.id)
    amount = ctx.user_data["amount"]
    share = amount / split_count

    # Все зарегистрированные участники
    participants = list(data["users"].keys())
    # Если участников меньше split_count, берём тех кто есть
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
    # Убедимся что плательщик в участниках
    if uid not in expense["participants"]:
        expense["participants"].append(uid)
        expense["split_count"] = len(expense["participants"])
        share = amount / expense["split_count"]

    data["expenses"].append(expense)
    save_data(data)

    payer_name = get_display_name(data, uid)

    # Формируем сообщение с должниками
    lines = [
        f"✅ Расход добавлен!\n",
        f"👤 Платил: *{payer_name}*",
        f"💰 Сумма: *{amount:,.0f} ₸*",
        f"📝 Описание: {expense['description']}",
        f"➗ Делим на {expense['split_count']}: по *{share:,.0f} ₸*\n",
        "📋 *Должны скинуть:*"
    ]
    for p_uid in expense["participants"]:
        p_name = get_display_name(data, p_uid)
        if str(p_uid) != str(uid):
            lines.append(f"  💸 {p_name} → {payer_name}: *{share:,.0f} ₸*")

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    return ConversationHandler.END

# ─── Pay conversation ─────────────────────────────────────────────────────────

async def pay_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    balance = calc_balances(data)

    if uid not in balance or balance[uid] >= -1:
        await update.message.reply_text("✅ Ты никому ничего не должен!")
        return ConversationHandler.END

    # Кому ты должен
    creditors = []
    for other_uid, amt in balance.items():
        if other_uid != uid and amt > 0.5:
            creditors.append((other_uid, min(abs(balance[uid]), amt)))

    if not creditors:
        await update.message.reply_text("✅ Всё чисто, нет долгов!")
        return ConversationHandler.END

    lines = [f"💸 Ты должен:\n"]
    keyboard = []
    for cred_uid, amt in creditors:
        name = get_display_name(data, cred_uid)
        lines.append(f"  ➡️ {name}: *{amt:,.0f} ₸*")
        keyboard.append([InlineKeyboardButton(
            f"✅ Перевёл {name} ({amt:,.0f} ₸)",
            callback_data=f"paid_{cred_uid}_{amt:.0f}"
        )])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_pay")])

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
        await query.edit_message_text("❌ Отменено")
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

    # Сообщение получателю для подтверждения
    keyboard = [[
        InlineKeyboardButton("✅ Да, получил!", callback_data=f"confirm_{pay_id}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"deny_{pay_id}"),
    ]]
    await query.edit_message_text(
        f"⏳ {from_name} говорит что перевёл тебе *{amount:,.0f} ₸*\n"
        f"Жду подтверждения от {to_name}...",
        parse_mode="Markdown"
    )

    # Уведомление получателю
    try:
        await ctx.bot.send_message(
            chat_id=int(to_uid),
            text=f"💰 *{from_name}* говорит что перевёл тебе *{amount:,.0f} ₸*\n"
                 f"Ты получил деньги?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.warning(f"Не смог отправить уведомление {to_uid}: {e}")

    return ConversationHandler.END

async def handle_payment_response(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, pay_id_str = query.data.split("_", 1)
    pay_id = int(pay_id_str)
    data = load_data()

    payment = next((p for p in data["payments"] if p["id"] == pay_id), None)
    if not payment:
        await query.edit_message_text("❌ Платёж не найден")
        return

    from_name = get_display_name(data, payment["from_id"])
    to_name = get_display_name(data, payment["to_id"])
    amount = payment["amount"]

    if action == "confirm":
        payment["confirmed"] = True
        save_data(data)
        await query.edit_message_text(
            f"✅ Подтверждено! {from_name} → {to_name}: *{amount:,.0f} ₸*",
            parse_mode="Markdown"
        )
        # Уведомить плательщика
        try:
            await ctx.bot.send_message(
                chat_id=int(payment["from_id"]),
                text=f"✅ *{to_name}* подтвердил получение *{amount:,.0f} ₸*! Долг закрыт 🎉",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    else:
        payment["confirmed"] = False
        payment["denied"] = True
        save_data(data)
        await query.edit_message_text(
            f"❌ {to_name} не подтвердил получение от {from_name}",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=int(payment["from_id"]),
                text=f"❌ *{to_name}* не подтвердил получение *{amount:,.0f} ₸*. Уточни у него!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    # Add expense conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            AMOUNT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            SPLIT:       [CallbackQueryHandler(add_split, pattern="^split_|^cancel$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Pay conversation
    pay_conv = ConversationHandler(
        entry_points=[CommandHandler("pay", pay_start)],
        states={
            CONFIRM_PAYMENT: [CallbackQueryHandler(pay_confirm, pattern="^paid_|^cancel_pay$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(add_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(handle_payment_response, pattern="^confirm_|^deny_"))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
