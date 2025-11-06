import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import logging
import asyncio
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- تنظیمات ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8280505234:AAFYDaH1QrR5UCgSWzEYNAzZWekvxSdMxak")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6097462059"))

# --- اتصال به PostgreSQL ---
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)  # برای سازگاری SQLAlchemy
else:
    raise ValueError("DATABASE_URL not set in environment variables.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- مدل‌های دیتابیس ---
class User(Base):
    __tablename__ = 'users'
    user_id = Column(String, primary_key=True)
    plan = Column(String)
    users = Column(Integer)
    expiry = Column(DateTime)
    status = Column(String)
    full_name = Column(String)
    username = Column(String)

class PendingReceipt(Base):
    __tablename__ = 'pending_receipts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String)
    username = Column(String)
    full_name = Column(String)
    plan_id = Column(String)
    user_count = Column(Integer)
    price = Column(Float)
    photo_file_id = Column(String)
    timestamp = Column(DateTime)

class FreeClaim(Base):
    __tablename__ = 'free_claims'
    user_id = Column(String, primary_key=True)
    last_claim = Column(DateTime)

Base.metadata.create_all(bind=engine)

# --- توابع دیتابیس ---
def get_user(user_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.user_id == user_id).first()
    db.close()
    if user:
        return {
            "plan": user.plan,
            "users": user.users,
            "expiry": user.expiry,
            "status": user.status,
            "full_name": user.full_name,
            "username": user.username
        }
    return None

def save_user(user_id: str, plan: str, users: int, expiry: datetime, status: str = "active", full_name: str = "", username: str = ""):
    db = SessionLocal()
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.plan = plan
        user.users = users
        user.expiry = expiry
        user.status = status
        user.full_name = full_name
        user.username = username
    else:
        user = User(
            user_id=user_id,
            plan=plan,
            users=users,
            expiry=expiry,
            status=status,
            full_name=full_name,
            username=username
        )
        db.add(user)
    db.commit()
    db.close()

def can_claim_free(user_id: str) -> bool:
    db = SessionLocal()
    claim = db.query(FreeClaim).filter(FreeClaim.user_id == user_id).first()
    db.close()
    if not claim:
        return True
    return (datetime.now() - claim.last_claim) > timedelta(hours=2)

def update_free_claim(user_id: str):
    db = SessionLocal()
    claim = db.query(FreeClaim).filter(FreeClaim.user_id == user_id).first()
    if claim:
        claim.last_claim = datetime.now()
    else:
        claim = FreeClaim(user_id=user_id, last_claim=datetime.now())
        db.add(claim)
    db.commit()
    db.close()

def save_pending_receipt(user_id: str, username: str, full_name: str, plan_id: str, user_count: int, price: float, photo_file_id: str):
    db = SessionLocal()
    receipt = PendingReceipt(
        user_id=user_id,
        username=username or 'N/A',
        full_name=full_name,
        plan_id=plan_id,
        user_count=user_count,
        price=price,
        photo_file_id=photo_file_id,
        timestamp=datetime.now()
    )
    db.add(receipt)
    db.commit()
    db.close()

def get_pending_receipts():
    db = SessionLocal()
    receipts = db.query(PendingReceipt).order_by(PendingReceipt.timestamp.desc()).all()
    db.close()
    return [(r.id, r.user_id, r.username, r.full_name, r.plan_id, r.user_count, r.price, r.photo_file_id, r.timestamp) for r in receipts]

def delete_pending_receipt(user_id: str):
    db = SessionLocal()
    db.query(PendingReceipt).filter(PendingReceipt.user_id == user_id).delete()
    db.commit()
    db.close()

def get_all_active_users():
    db = SessionLocal()
    users = db.query(User).filter(User.status == "active").all()
    db.close()
    return [(u.user_id, u.plan, u.users, u.expiry, u.full_name, u.username) for u in users]

# --- منوی هوشمند ---
def get_main_menu(user_id: int):
    is_admin = (user_id == ADMIN_CHAT_ID)
    keyboard = [
        [KeyboardButton("📊 وضعیت اشتراک"), KeyboardButton("🛒 خرید اشتراک")],
        [KeyboardButton("🎁 اشتراک رایگان")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("👨‍💼 پنل ادمین")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# --- دستور شروع ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(str(user.id), "free", 1, datetime.now(), "inactive", user.full_name, user.username or "")
    await update.message.reply_text(
        "سلام! 👋\nبرای شروع، یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=get_main_menu(user.id)
    )

# --- نمایش پنل ادمین ---
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ دسترسی محدود!")
        return

    active_users = get_all_active_users()
    lines = ["👤 لیست کاربران فعال:\n"]
    if active_users:
        for user_id, plan, users, expiry, full_name, username in active_users:
            remaining = max(0, (expiry - datetime.now()).days)
            uname = f"@{username}" if username else "بدون آیدی"
            lines.append(f"📄 {full_name} | {uname} | {plan} | {users} کاربر | ⏳ {remaining} روز")
    else:
        lines.append("هیچ کاربر فعالی وجود ندارد.")

    lines.append("\n\n📥 رسیدهای در انتظار تأیید:")
    pending = get_pending_receipts()
    if pending:
        for row in pending:
            _, uid, uname_db, fname, plan_id, ucount, price, _, _ = row
            plan_name = BASE_PLANS.get(plan_id, {}).get("name", plan_id)
            lines.append(f"🆔 {uid} | 📄 {fname} (@{uname_db}) | {plan_name} | {ucount} کاربر | 💰 {price}$")
    else:
        lines.append("هیچ رسیدی در انتظار نیست.")

    msg = "\n".join(lines)
    if len(msg) > 4096:
        msg = msg[:4090] + "..."
    await update.message.reply_text(msg, reply_markup=get_main_menu(ADMIN_CHAT_ID))

# --- اشتراک رایگان ---
async def send_free_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not can_claim_free(user_id):
        await update.message.reply_text(
            "⏳ شما می‌توانید هر ۲ ساعت یک‌بار اشتراک رایگان دریافت کنید.\nلطفاً بعداً دوباره امتحان کنید.",
            reply_markup=get_main_menu(update.effective_user.id)
        )
        return

    update_free_claim(user_id)

    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=vless%3A%2F%2F47f998fd-3f24-420f-9324-aeb4d4618795%40free1.mainonline.link%3A8080%3Ftype%3Dws%26security%3Dnone%26path%3D%2F%26host%3D%23%2A%20%7C%20W%203005%20-%20%40iBlueWEB"
    caption = (
        "🎉 اشتراک رایگان!\n\n"
        "📌 اطلاعات اشتراک شما:\n"
        "✅ نام: W 3005 - @iBlueWEB\n"
        "⭐️ نوع: اشتراک رایگان\n"
        "🌐 مقدار حجم: GB 2.0\n"
        "⏱️ مقدار زمان: کمتر از یک روز (روز مانده روز)\n"
        "🔗 کانفیگ شما:\n"
        "```\nvless://47f998fd-3f24-420f-9324-aeb4d4618795@free1.mainonline.link:8080?type=ws&security=none&path=/&host=#★ | W 3005 - @iBlueWEB\n```"
    )
    await update.message.reply_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=get_main_menu(update.effective_user.id)
    )

# --- نمایش وضعیت ---
async def show_status_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = get_user(user_id)
    if not user_data or user_data["status"] != "active":
        msg = "❌ اشتراک فعالی ندارید."
    else:
        remaining = max(0, (user_data["expiry"] - datetime.now()).days)
        msg = (
            f"📊 وضعیت اشتراک:\n"
            f"📦 پلن: {user_data['plan']}\n"
            f"👥 کاربر: {user_data['users']}\n"
            f"⏳ باقی‌مانده: {remaining} روز\n"
            f"📅 انقضا: {user_data['expiry'].strftime('%Y/%m/%d')}"
        )
    await update.message.reply_text(msg, reply_markup=get_main_menu(update.effective_user.id))

# --- شروع خرید ---
async def start_purchase_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_counts = [1, 2, 3, 4, 10, 100]
    keyboard = []
    row = []
    for i, count in enumerate(user_counts):
        row.append(InlineKeyboardButton(f"{count} کاربر", callback_data=f"users_{count}"))
        if (i + 1) % 3 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("« بازگشت به منو", callback_data='back_to_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("تعداد کاربران را انتخاب کنید:", reply_markup=reply_markup)

# --- بازگشت به منو ---
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("منوی اصلی:", reply_markup=get_main_menu(query.from_user.id))

# --- انتخاب پلن ---
async def choose_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_count = int(query.data.split("_")[1])
    await query.answer()
    context.user_data['user_count'] = user_count
    keyboard = []
    for plan_id, plan in BASE_PLANS.items():
        price = round(BASE_PRICES[plan_id] * USER_MULTIPLIERS[user_count], 2)
        keyboard.append([InlineKeyboardButton(f"{plan['name']} – ${price}", callback_data=f"plan_{plan_id}")])
    keyboard.append([InlineKeyboardButton("« بازگشت", callback_data='users')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("پلن مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

# --- نمایش اطلاعات پرداخت ---
async def show_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    plan_id = query.data.split("_")[1]
    user_count = context.user_data.get('user_count', 1)
    plan = BASE_PLANS[plan_id]
    price = round(BASE_PRICES[plan_id] * USER_MULTIPLIERS[user_count], 2)
    context.user_data.update({'selected_plan': plan_id, 'final_price': price})
    msg = (
        f"💳 پرداخت دستی\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"👥 تعداد کاربر: {user_count}\n"
        f"📅 مدت: {plan['days']} روز\n"
        f"💰 مبلغ: ${price}\n\n"
        "لطفاً پرداخت را به یکی از موارد زیر انجام دهید:\n\n"
        "💳 شماره کارت:\n6037 XXXX XXXX 1234\n"
        "📱 همراه‌بانک: 0912 XXX XXXX\n\n"
        "✅ سپس عکس رسید را اینجا ارسال کنید."
    )
    await query.edit_message_text(msg, parse_mode="Markdown")

# --- دریافت و ذخیره رسید ---
async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    required = ['selected_plan', 'final_price', 'user_count']
    if not all(k in context.user_data for k in required):
        await update.message.reply_text("لطفاً از طریق منوی «خرید اشتراک» شروع کنید.", reply_markup=get_main_menu(user.id))
        return

    plan_id = context.user_data['selected_plan']
    user_count = context.user_data['user_count']
    price = context.user_data['final_price']

    save_pending_receipt(str(user.id), user.username, user.full_name, plan_id, user_count, price, update.message.photo[-1].file_id)

    keyboard = [
        [InlineKeyboardButton("✅ تأیید", callback_data=f"confirm_{user.id}_{plan_id}_{user_count}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"reject_{user.id}")]
    ]
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=update.message.photo[-1].file_id,
        caption=(
            f"📥 رسید جدید\n👤 {user.full_name} (@{user.username or 'N/A'})\n"
            f"🆔 {user.id}\n📦 {BASE_PLANS[plan_id]['name']}\n👥 {user_count} کاربر\n💰 ${price}"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ رسید ارسال شد. پس از تأیید، اشتراک فعال می‌شود.", reply_markup=get_main_menu(user.id))

# --- تأیید/رد توسط ادمین ---
async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("confirm_"):
        _, user_id, plan_id, user_count = data.split("_")
        user_id = int(user_id)
        user_count = int(user_count)

        plan = BASE_PLANS[plan_id]
        expiry = datetime.now() + timedelta(days=plan['days'])

        try:
            user_info = await context.bot.get_chat(user_id)
            full_name = user_info.full_name
            username = user_info.username
        except:
            user_record = get_user(str(user_id))
            full_name = user_record["full_name"] if user_record else "نام ناشناس"
            username = user_record["username"] if user_record else "نام کاربری ندارد"

        save_user(str(user_id), plan['name'], user_count, expiry, "active", full_name, username)
        delete_pending_receipt(str(user_id))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 اشتراک شما فعال شد!\n📦 {plan['name']}\n👥 {user_count} کاربر\n📅 انقضا: {expiry.strftime('%Y/%m/%d')}",
                reply_markup=get_main_menu(user_id)
            )
        except:
            pass
        await query.edit_message_caption("✅ فعال شد.")

    elif data.startswith("reject_"):
        user_id = int(data.split("_")[1])
        delete_pending_receipt(str(user_id))
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ پرداخت شما تأیید نشد.", reply_markup=get_main_menu(user_id))
        except:
            pass
        await query.edit_message_caption("❌ رد شد.")

# --- هندلر منوی متنی ---
async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "📊 وضعیت اشتراک":
        await show_status_reply(update, context)
    elif text == "🛒 خرید اشتراک":
        await start_purchase_flow(update, context)
    elif text == "🎁 اشتراک رایگان":
        await send_free_subscription(update, context)
    elif text == "👨‍💼 پنل ادمین" and user_id == ADMIN_CHAT_ID:
        await show_admin_panel(update, context)
    else:
        await update.message.reply_text("لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_menu(user_id))

# --- پلن‌ها ---
BASE_PLANS = {
    "10gb": {"name": "10 گیگابایت", "days": 7},
    "20gb": {"name": "20 گیگابایت", "days": 15},
    "50gb": {"name": "50 گیگابایت", "days": 30},
}
BASE_PRICES = {"10gb": 5, "20gb": 9, "50gb": 20}
USER_MULTIPLIERS = {1: 1.0, 2: 1.8, 3: 2.5, 4: 3.2, 10: 6.0, 100: 25.0}

# --- راه‌اندازی ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))
    application.add_handler(CallbackQueryHandler(choose_plan, pattern='^users_'))
    application.add_handler(CallbackQueryHandler(show_payment_info, pattern='^plan_'))
    application.add_handler(CallbackQueryHandler(handle_admin_action, pattern='^(confirm_|reject_)'))
    application.add_handler(MessageHandler(filters.PHOTO, handle_receipt))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    print("ربات با پنل ادمین، نمایش اسم و آیدی و محدودیت رایگان در حال اجراست...")
    application.run_polling()