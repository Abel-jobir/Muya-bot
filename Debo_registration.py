import logging
import json
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, CallbackQuery
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          ConversationHandler, ContextTypes, ChatMemberHandler,
                          CallbackQueryHandler)
from telegram.error import NetworkError, TelegramError # <--- Added NetworkError and TelegramError imports
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import tempfile
import os
import requests
import re

APPS_SCRIPT_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyEbwoX6hglK7cCES1GeVKFhtwmajvVAI1WDBfh03bsQbA3DKgkfCe_jJfH-8EZ0HUc/exec"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json_str = os.environ.get("deboregist")
if not creds_json_str:
    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set.")
with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as temp_creds_file:
    temp_creds_file.write(creds_json_str)
    temp_file_path = temp_creds_file.name
creds = ServiceAccountCredentials.from_json_keyfile_name(temp_file_path, scope)
client = gspread.authorize(creds)
sheet = client.open("Professionals").sheet1

# Add new states for editing flow
(ASK_EDIT_FIELD, GET_NEW_VALUE, GET_NEW_LOCATION, GET_NEW_TESTIMONIALS, GET_NEW_EDUCATIONAL_DOCS) = range(10, 15) # Start from 10



# States for conversation
(FULL_NAME, username, PROFESSION, PHONE, LOCATION, REGION_CITY_WOREDA, CONFIRM_DELETE, COMMENT, TESTIMONIALS, EDUCATIONAL_DOCS) = range(10)


# --- Column Mapping ---
# Map user-friendly names to Google Sheet Column Letters/Indices (1-based index)
# Adjust these if your sheet columns are different!
COLUMN_MAP = {
    "Full_Name": "C",
    "PROFESSION": "D",
    "PHONE": "E",
    "LOCATION": "F", # For GPS coordinates or "Not Shared"
    "Region/City/Woreda": "G",
    "Testimonials": "J",
    "Educational Docs": "K",
    "COMMENT": "I",
}
# Map callback data (used in InlineKeyboard) to field names and states
EDIT_OPTIONS = {
    "edit_name": {"name": "Full_Name", "next_state": GET_NEW_VALUE, "prompt": "Enter your updated full name:", "handler": "get_new_text_value"},
    "edit_profession": {"name": "PROFESSION", "next_state": GET_NEW_VALUE, "prompt": "Enter your updated profession:", "handler": "get_new_text_value"},
    "edit_phone": {"name": "PHONE", "next_state": GET_NEW_VALUE, "prompt": "Enter your updated phone number:", "handler": "get_new_text_value"},
    "edit_location": {"name": "LOCATION", "next_state": GET_NEW_LOCATION, "prompt": "Share your updated location or type 'skip':", "handler": "get_new_location_value"},
    "edit_address": {"name": "Region/City/Woreda", "next_state": GET_NEW_VALUE, "prompt": "Enter your updated Region, City, Woreda:", "handler": "get_new_text_value"},
    "edit_testimonials": {"name": "Testimonials", "next_state": GET_NEW_TESTIMONIALS, "prompt": "Upload *all* your new testimonial documents/images. Type 'done' when finished or 'skip'.", "handler": "handle_new_files"},
    "edit_education": {"name": "Educational Docs", "next_state": GET_NEW_EDUCATIONAL_DOCS, "prompt": "Upload *all* your new educational documents/images. Type 'done' when finished or 'skip'.", "handler": "handle_new_files"},
}




# Custom keyboards
main_menu_keyboard = [
    ["/register ምዝገባ", "/editprofile መረጃ ያስተካክሉ"],
    ["/profile መረጃን አሳይ ", "/deleteprofile መረጃ ሰርዝ"],
    ["/comment አስተያየት"]
]
main_menu_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)

# Define new keyboards for skip/done and yes/no
skip_done_keyboard = [
    ["Done ጨርሻያለው✅ ", "Skip እለፍ⏭️"]
]

skip_done_markup = ReplyKeyboardMarkup(skip_done_keyboard, one_time_keyboard=True, resize_keyboard=True)

yes_no_keyboard = [
    ["Yes አዎ✅", "No አይ❌"]
]
yes_no_markup = ReplyKeyboardMarkup(yes_no_keyboard, one_time_keyboard=True, resize_keyboard=True)




# Helper functions
def find_user_row(user_id):
    try:
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if str(row.get("User ID")) == str(user_id):
                return idx, row
    except:
        return None, None
    return None, None

# Helper function to validate phone number
def is_valid_phone_number(phone_number: str) -> bool:
    """
    Validates if the input string looks like a valid phone number.
    This is a basic check and might need adjustment for specific formats.
    Allows digits, spaces, hyphens, parentheses, and an optional leading plus sign.
    Requires at least 7 digits.
    """
    # Remove common non-digit characters except '+' at the start
    cleaned_number = re.sub(r'[()\s-]', '', phone_number)

    # Check if the number starts with '+' and then digits, or just digits
    # Ensure there are enough digits (e.g., at least 7 after cleaning)
    if re.fullmatch(r'^\+?\d{7,}$', cleaned_number):
        return True
    return False

#upload_to_drive
def upload_to_drive(file_path, folder_id, filename):
    drive_service = build('drive', 'v3', credentials=creds)
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')  # fixed variable name
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

# --- Sheet Update Helper ---
async def update_sheet_cell(context: ContextTypes.DEFAULT_TYPE, field_name: str, new_value):
    """Updates a specific cell in the user's row."""
    row_idx = context.user_data.get('edit_row_idx')
    if not row_idx:
        logger.error("update_sheet_cell called without row_idx in user_data")
        return False # Indicate failure

    col_letter = COLUMN_MAP.get(field_name)
    if not col_letter:
        logger.error(f"Invalid field name '{field_name}' provided for update.")
        return False # Indicate failure

    try:
        sheet.update(f"{col_letter}{row_idx}", [[new_value]]) # Use update with range
        logger.info(f"Updated row {row_idx}, column {col_letter} for user {context.user_data.get('user_id')}")
        return True # Indicate success
    except Exception as e:
        logger.error(f"Failed to update sheet for row {row_idx}, column {col_letter}: {e}")
        return False # Indicate failure


# CODE.txt (after update_sheet_cell function)



# --- Rating Functions ---

async def send_rating_request(chat_id: int, professional_id_to_rate: str, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a message to the user with inline buttons for rating a specific professional.
    """
    keyboard = [
        [
            InlineKeyboardButton("⭐ 1", callback_data=f"rate_{professional_id_to_rate}_1"),
            InlineKeyboardButton("⭐ 2", callback_data=f"rate_{professional_id_to_rate}_2"),
            InlineKeyboardButton("⭐ 3", callback_data=f"rate_{professional_id_to_rate}_3"),
            InlineKeyboardButton("⭐ 4", callback_data=f"rate_{professional_id_to_rate}_4"),
            InlineKeyboardButton("⭐ 5", callback_data=f"rate_{professional_id_to_rate}_5"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Please rate the professional with ID *{professional_id_to_rate}*:",
        reply_markup=reply_markup,
        parse_mode='Markdown' # Use Markdown for bold text
    )

# CODE.txt (Add this new function)

async def send_initial_feedback_message(chat_id: int, professional_ids: list[str], context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the initial feedback message to the user with choices including individual professionals.
    Stores the professional_ids in user_data for later reference.
    """
    # Store the list of professionals sent for this user, so we can refer back to them later.
    user_data_for_target = await context.application.get_user_data(chat_id)
    user_data_for_target['initial_professional_ids'] = professional_ids
    keyboard = []

    # Add the static choices
    keyboard.append([InlineKeyboardButton("I will not contact them", callback_data="feedback_no_contact")])
    keyboard.append([InlineKeyboardButton("I will contact them soon", callback_data="feedback_will_contact")])
    keyboard.append([InlineKeyboardButton("Please don't send me this message again", callback_data="feedback_opt_out")])

    # Add buttons for each professional
    keyboard.append([InlineKeyboardButton("--- Choose Professional(s) You Contacted ---", callback_data="ignore_me")]) # Separator

    for pro_id in professional_ids:
        # Assuming you want to display the ID on the button. You could fetch names if needed.
        keyboard.append([InlineKeyboardButton(f"Contacted: {pro_id}", callback_data=f"feedback_select_pro_{pro_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Hello! Regarding the professional(s) we shared, please let us know your status or select whom you contacted:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    logger.info(f"Initial feedback message sent to {chat_id} for professionals: {professional_ids}")

# ... rest of your functions ...


async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles callback queries from rating buttons, parses data, and sends to Apps Script.
    """
    query = update.callback_query
    callback_data = query.data  # e.g., "rate_PRO_001_4"
    user_telegram_id = query.from_user.id

    # Always answer the callback query to remove the "loading" spinner on the button
    await query.answer()

    if callback_data.startswith("rate_"):
        try:
            # Parse the data: "rate_PROFESSIONALID_RATING"
            parts = callback_data.split('_')
            professional_id = parts[1]
            rating_value = int(parts[2])

            # Make the HTTP POST request to Apps Script
            await send_rating_to_apps_script(professional_id, rating_value, user_telegram_id, query, context)

        except (ValueError, IndexError) as e:
            await query.edit_message_text(text="Sorry, there was an error processing your rating. Please try again.")
            logger.error(f"Error parsing callback data: {callback_data} - {e}")
    else:
        # This handler will only process 'rate_' patterns due to the filter below
        pass


# CODE.txt (Add this new function)

async def send_follow_up_rating_prompt(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends a follow-up message asking the user if they want to rate another professional
    or end the rating process.
    """
    # Check if there are still professionals in the list that haven't been explicitly rated
    # This logic will be fully robust once we implement storing the list and tracking rated ones
    # For now, it just assumes the option to rate another is always available
    user_data_for_current = await context.application.get_user_data(chat_id)
    professional_ids_for_user = user_data_for_current.get('initial_professional_ids', [])
  
    keyboard = [
        [
            InlineKeyboardButton("Rate another professional", callback_data="followup_rate_another"),
            InlineKeyboardButton("End rating process", callback_data="followup_end_rating")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Successfully sent the rating! Would you like to rate another professional or finish?",
        reply_markup=reply_markup
    )




async def send_rating_to_apps_script(professional_id: str, rating_value: int, user_telegram_id: int, query_object: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the rating data as a JSON POST request to the Apps Script Web App.
    """
    payload = {
        "professional_id": professional_id,
        "rating": rating_value,
        "user_telegram_id": str(user_telegram_id) # Ensure user_telegram_id is a string for JSON
    }
    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(APPS_SCRIPT_WEB_APP_URL, data=json.dumps(payload), headers=headers)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)

        response_json = response.json()
        if response_json.get("success"):
            # Edit the original message to show confirmation of THIS rating
            await query_object.edit_message_text(
                text=f"✅ Thanks! Your *{rating_value}-star* rating for professional *{professional_id}* has been recorded.",
                parse_mode='Markdown',
                reply_markup=None # Remove the inline keyboard from the rated professional
            )
            logger.info(f"Successfully sent rating for {professional_id} by {user_telegram_id}: {rating_value} stars.")

            # --- NEW: Send the follow-up prompt ---
            # The list of professionals will be stored in context.user_data in a later step
            # For now, assume context.user_data['professional_ids_sent_for_rating'] exists
            await send_follow_up_rating_prompt(user_telegram_id, context) # <--- ADD THIS LINE

        else:
            error_message = response_json.get("error", "Unknown error from server.")
            await query_object.edit_message_text(
                text=f"❌ Failed to record rating: _{error_message}_. Please try again later."
                f"\n\n_If the problem persists, contact support._",
                parse_mode='Markdown',
                reply_markup=None
            )
            logger.error(f"Error from Apps Script for rating ({professional_id}, {rating_value}): {error_message}")

    except requests.exceptions.RequestException as e:
        await query_object.edit_message_text(
            text="❌ Failed to connect to rating service. Please try again later."
            f"\n\n_Network error: {e}_",
            parse_mode='Markdown',
            reply_markup=None
        )
        logger.error(f"HTTP request failed during rating for {professional_id}: {e}")


# CODE.txt (Replace your existing send_manual_rating_command function)

async def request_feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to initiate the enhanced feedback request for a user.
    Usage: /request_feedback <user_chat_id> <professional_id_1> <professional_id_2> ...
    """
    args = context.args
    
    if len(args) >= 2: # At least chat_id and one professional ID
        try:
            target_chat_id = int(args[0])
            professional_ids_to_send = args[1:] # All arguments after the first one are professional IDs
            
            if not professional_ids_to_send:
                await update.message.reply_text("Please provide at least one professional ID.")
                return

            # Call the new function to send the initial feedback message
            await send_initial_feedback_message(target_chat_id, professional_ids_to_send, context)
            
            await update.message.reply_text(
                f"Initial feedback request sent to chat ID `{target_chat_id}` for professionals: `{', '.join(professional_ids_to_send)}`.",
                parse_mode='Markdown'
            )
            logger.info(f"Admin triggered initial feedback for {target_chat_id} with {professional_ids_to_send}")

        except ValueError:
            await update.message.reply_text("Invalid chat ID. Please provide a numeric user ID.", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"An error occurred: `{e}`", parse_mode='Markdown')
            logger.error(f"Error in request_feedback_command: {e}")
    else:
        await update.message.reply_text(
            "Usage: `/request_feedback <user_chat_id> <professional_id_1> [professional_id_2] ...`",
            parse_mode='Markdown'
        )

# ... rest of your functions ...

# CODE.txt (Add this new function)

async def handle_initial_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles callback queries from the initial feedback message and follow-up prompts.
    """
    query = update.callback_query
    callback_data = query.data
    user_chat_id = query.from_user.id

    await query.answer() # Always answer the callback query to remove the "loading" spinner

    # --- Handle initial feedback choices ---
    if callback_data == "feedback_no_contact":
        await query.edit_message_text(
            text="Understood! We won't send rating requests for these professionals. Thank you for the update.",
            reply_markup=None # Remove buttons
        )
        # You can add logic here to record this in your sheet/database
        logger.info(f"User {user_chat_id} chose 'no contact'.")

    elif callback_data == "feedback_will_contact":
        await query.edit_message_text(
            text="Okay, please let us know if you contact them! We won't send immediate rating requests.",
            reply_markup=None # Remove buttons
        )
        # You can add logic here to record this in your sheet/database
        logger.info(f"User {user_chat_id} chose 'will contact soon'.")

    elif callback_data == "feedback_opt_out":
        await query.edit_message_text(
            text="Got it. We won't send you these types of messages again. You can always reactivate feedback requests by contacting support.",
            reply_markup=None # Remove buttons
        )
        # IMPORTANT: Implement logic here to store this opt-out preference in your sheet/database
        # and ensure you don't send future feedback requests to this user.
        logger.info(f"User {user_chat_id} opted out of feedback requests.")
        
    elif callback_data.startswith("feedback_select_pro_"):
        try:
            professional_id = callback_data.split('_')[2]
            
            # Edit the original message to indicate selection, but keep it so other buttons can be clicked
            # Or, you can send a new message with just the rating prompt.
            await query.edit_message_text(
                text=f"You selected professional: *{professional_id}*."
                     f"\nNow, please use the stars in the *next message* to rate them.",
                parse_mode='Markdown'
            )
            
            # Call the existing function to send the 1-5 star rating prompt for this professional
            await send_rating_request(user_chat_id, professional_id, context)
            logger.info(f"User {user_chat_id} selected {professional_id} for rating.")

        except IndexError:
            await query.edit_message_text(text="Error processing professional selection.", reply_markup=None)
            logger.error(f"Error parsing feedback_select_pro_ callback data: {callback_data}")
            
    # --- Handle follow-up choices after a rating ---
    elif callback_data == "followup_rate_another":
        # Retrieve the original list of professional IDs sent to this user
        # This assumes the list is stored in context.user_data[user_chat_id]['initial_professional_ids']
        user_data_for_current = await context.application.get_user_data(user_chat_id)
        professional_ids_for_user = user_data_for_current.get('initial_professional_ids', [])
        
        if professional_ids_for_user:
            # Re-send the initial feedback message to allow choosing another professional
            await send_initial_feedback_message(user_chat_id, professional_ids_for_user, context)
            # Remove the follow-up prompt buttons
            await query.edit_message_text(
                text="Please choose another professional to rate from the message above, or click 'End rating process'.",
                reply_markup=None
            )
            logger.info(f"User {user_chat_id} chose to rate another professional. Resending initial choices.")
        else:
            await query.edit_message_text(
                text="No other professionals found to rate, or the list was not saved. Please contact support if you believe this is an error.",
                reply_markup=None
            )
            logger.warning(f"User {user_chat_id} chose to rate another, but no 'initial_professional_ids' found in user_data.")

    elif callback_data == "followup_end_rating":
        await query.edit_message_text(
            text="Thank you for your feedback! The rating process has ended.",
            reply_markup=None # Remove buttons
        )
        # You might also want to clear context.user_data[user_chat_id] here if no longer needed
        if user_chat_id in context.user_data:
            del context.user_data[user_chat_id]
        logger.info(f"User {user_chat_id} ended the rating process.")

    # Prevent the general handle_rating_callback from processing these specific callbacks
    return

# ... rest of your functions ...




# In your main() function, register this handler
def main():
    updater = Updater("YOUR_BOT_TOKEN", use_context=True)
    dispatcher = updater.dispatcher

    # ... (other handlers) ...

    # Add the new command handler for manual rating requests
    # Make sure only YOUR chat_id can use this command if you want to restrict it
    dispatcher.add_handler(CommandHandler("request_rating", send_manual_rating_command))

    updater.start_polling()
    updater.idle()




# Handlers
async def greet_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member.new_chat_member.status == "member":
        chat_id = update.my_chat_member.chat.id
        await context.bot.send_message(chat_id, "\n               🎉Welcome to MUYA Bot!                                🎉እንኳን ወደ ሙያ ቦት በሰላም መጡ \n this bot is used to registor any Ethiopian" \
        "professionals who are interested to find new job opportunities from their nighbour to their city. \n ይህ ቦት የሙያ ባለቤት የሆኑ ማንኛውም  ኢትይጵያውያንን የምንመዘግብበትና ባቅርያብያቸው ያሉ የስራ እድሎችን እና ባለሙያ ፈላጊዎችን በቀላሉ እንዲያገኙ የምናመቻችበት የምናደርግበት ቴክኖልጂ ነው። \n " \
        "any information you give to this bot will be given to people that want your contact to make you work for them \n በዚህ ቦት ላይ የሚያጋሯቸው መርጃዎችዎ ስራ ሊያሰሯቹ ለሚፈልጉ ሰዎች ይሰጣልይ \ን" \
        "ስለአሰራራችን የበለጠ ለማውቅ ወይም የትኛውም ጥይቄ ካልዎት ይህንን ይጫኑይጫኑ", reply_markup=main_menu_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n🎉 Welcome to Debo Bot! \n🎉 እንኳን ወደ ደቦ ቦት በሰላም መጡ \n \n✅ this bot is used to registor any Ethiopian professionals who are interested to find new job opportunities from thier nighbour to thier city. \n \n ⚠️any information you give to this bot will be given to people that want your contact to make you work for them \n \nplease use the below menu to continue \n \n✅ይህ ቦት የሙያ ባለቤት የሆኑ ማንኛውም  ኢትይጵያውያንን የምንመዘግብበትና ባቅርያብያቸው ያሉ የስራ እድሎችን እንዲያገኙ ከባለሙያ ፈላጊዎች ጋር በቀላሉ እንዲገናኙ የምናደርግበት ነው። \n " \
        " \n⚠️ በዚህ ቦት ላይ የሚያጋሯቸው መርጃዎችዎ ስራ ሊያሰሯችሁችሁ ለሚፈልጉ ሰዎች ይጋራሉ። \n \nለመቀጠል ከከስር ካሉት አማራጮች አንዱን ይጫኑ። \n \n ስለአሰራራችን የበለጠ ለማውቅ ወይም የትኛውም ጥይቄ ካልዎት ይህንን ይጫኑ", reply_markup=main_menu_markup)


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    _, existing = find_user_row(user_id)
    if existing:
        await update.message.reply_text("ℹ️You are already registered. / ደቦ ላይ ተመዝግበዋል", reply_markup=main_menu_markup)
        return ConversationHandler.END
    await update.message.reply_text("📝Enter your full name: / ሙሉ ስምዎን ያስገቡ", reply_markup=ReplyKeyboardRemove())
    return FULL_NAME

async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    context.user_data['user_id'] = user.id
    context.user_data['username'] = user.username if user.username else "Not set"
    context.user_data['full_name'] = update.message.text
    print("USER DATA:", context.user_data)
    await update.message.reply_text("🛠️Enter your profession: / ሙያዎን ያስገቡ \n⚠️ እባክዎን የተሰማሩበትን የስራ ዘርፍ በጥንቃቄ እና በግልጽ ይጻፉ።። \n \n ለምሳሌ ✅ ዶክተር ከማለት ኦንኮሎጂስት \n \n ✅ የቧምቧ ባለሙያ \n \n✅ ኢንጂነር ከማለት ሲቪል ኢንጂነር \n \n ✅ ተምላላሽ ሰራተኛ \n \n ✅ የኤሌክትሪክ ሰራተኛ \n \n✅ጠበቃ")
    return PROFESSION

async def get_profession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['PROFESSION'] = update.message.text
    await update.message.reply_text("📞Enter your phone number: / ስል ቁጥርዎን ያስገቡ")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_number = update.message.text
    if not is_valid_phone_number(phone_number):
        await update.message.reply_text("Invalid phone number format. Please enter a valid phone number \n የተሳሳተ መረጃ አስገብተዋል እባክዎ ትክክለኝ የስልክ ቁጥር ፎርማት ይጠቀሙ (e.g., +251912345678 or 0912345678): / የስልክ ቁጥርዎ ትክክል አይደለም። ትክክለኛ ስልክ ቁጥር ያስገቡ (ለምሳሌ +251912345678 ወይም 0912345678):")
        return PHONE # Stay in the PHONE state to ask again

    context.user_data['phone'] = phone_number
    location_button = [[KeyboardButton("📍Share Location / የርስዎን ወይም የቢሮዎን መገኛ ያጋሩ ", request_location=True)], [KeyboardButton("Skip / አሳልፍ")]]
    await update.message.reply_text(
        "Share your location or press Skip:/ የርስዎን ወይም የቢሮዎን መገኛ ያጋሩ ወይም Skip / አሳልፍ ይጫኑ",
        reply_markup=ReplyKeyboardMarkup(location_button, one_time_keyboard=True, resize_keyboard=True)
    )
    return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        location = f"{lat}, {lon}"
    else:
        location = "Not shared"
    context.user_data['location'] = location  # NEW
    await update.message.reply_text("📍Enter your city / Region , subcity, wereda  \n የሚገኙበትን ክልል / ከተማ፣ ክፍለ ከተማ ፣ ወረዳ በቅደም ተከተል ያስገቡ \n ለምሳሌ ✅ አዲስ አበባ፣ አዲስ ከተማ፣ 11")
    return  REGION_CITY_WOREDA  # Let the user input it next


async def handle_region_city_woreda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["region_city_woreda"] = update.message.text
    return await ask_for_testimonials(update, context)


async def ask_for_testimonials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄Please upload your testimonial documents or images. You can upload multiple. use the buttons below skip or finish : \n እርስዎ ከዚ በፊት የሰርዋቸው እንደማስረጃ የሚያገለግሉ ስራዎችዎን ያስገቡ። \n \n ✅ የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። \n \n ✅ከአንድ በላይ ፋይል ማስግባት ይችላሉ። \n \n ✅ አስገብተው ሲጨርሱ Done /ጨርሻለው የሚለውን ይጫኑ። \n \n ✅ የሚያስገቡት ማስረጃ ከሌሎት skip /አሳልፍን ይጫኑ።ይጫኑ።",
        reply_markup=skip_done_markup # Show keyboard immediately
    )
    context.user_data['testimonial_links'] = []
    return TESTIMONIALS



async def handle_testimonials(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text:
        text = update.message.text.lower()
        # Check if 'Skip' button text is included - handle both English and Amharic if possible, or just English for buttons
        if "skip" in text or "አሳልፍ" in text:
            return await ask_for_educational_docs(update, context)
        # Check if 'Done' button text is included - handle both English and Amharic if possible
        elif "done" in text or "ተጠናቋል" in text:
             # User clicked done, proceed to next step (ask for educational docs)
             if not context.user_data.get('testimonial_links'):
                 await update.message.reply_text("No testimonial files were uploaded. Skipping.  \n ምንም አይነት የሰሯቸውን ስራዎች ማስርጃ አላስገቡም!", reply_markup=ReplyKeyboardRemove())
             return await ask_for_educational_docs(update, context)

    if update.message.document or update.message.photo:
        testimonial_folder_id = "1TMehhfN9tExqoaHIYya-B-SCcFeBTj2y"

        file = update.message.document or update.message.photo[-1]
        file_id = file.file_id
        file_obj = await context.bot.get_file(file_id)
        # Create temp file and download into it
        with tempfile.NamedTemporaryFile(delete=False) as tf:

            temp_path = tf.name
            await file_obj.download_to_drive(temp_path)

        # Now the temp file is closed and safe to use
        filename = file.file_name if update.message.document else f"photo_{file_id}.jpg"
        link = upload_to_drive(temp_path, testimonial_folder_id, filename)

        # Safely append to testimonial_links
        if 'testimonial_links' not in context.user_data:
            context.user_data['testimonial_links'] = []
        context.user_data['testimonial_links'].append(link)

        # Now it's safe to delete the temp file
        os.remove(temp_path)

        await update.message.reply_text("File received. Upload more or select an option: ማስረጃዎን በትክክል አስገብተዋል። ተጨማሪ ማስረጃ ያስገቡ ወይም ታች ካሉት አማርጮች አንዱን ይጠቀሙ።", reply_markup=skip_done_markup)
        return TESTIMONIALS
    else: 
        # Handle unexpected input
        await update.message.reply_text("Please upload a document/photo or use the buttons.  የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ  ", reply_markup=skip_done_markup)
        return TESTIMONIALS

async def ask_for_educational_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓Please upload your educational background documents or images. You can upload multiple files. Or use the buttons below:  \n የትምህርት ማስረጃ ካልዎትያስገቡ። \n✅ የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። \n ✅ከአንድ በላይ ፋይል ማስግባት ይችላሉ። ✅ አስገብተው ሲጨርሱ Done /ጨርሻለው የሚለውን ይጫኑ። \n ✅ የሚያስገቡት ማስረጃ ከሌሎት skip /አሳልፍን ይጫኑ።ይጫኑ።",
         reply_markup=skip_done_markup # Show keyboard immediately
    )
    context.user_data['education_links'] = []
    return EDUCATIONAL_DOCS


async def handle_educational_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        text = update.message.text.lower()
        # Check if 'Skip' button text is included - handle both English and Amharic if possible
        if "skip" in text or "አሳልፍ" in text:
             return await finish_registration(update, context)
        # Check if 'Done' button text is included - handle both English and Amharic if possible
        elif "done" in text or "ተጠናቋል" in text:
            # User clicked done, proceed to finish registration
            if not context.user_data.get('educational_links'):
                 await update.message.reply_text("No educational files were uploaded. Skipping. ምንም አይነት የሰሯቸውን ስራዎች ማስርጃ አላስገቡም!", reply_markup=ReplyKeyboardRemove())
            return await finish_registration(update, context)


    if update.message.document or update.message.photo:
        education_folder_id = "1i9a2G7EXByrY9LxXtv4yY-CMExDWI7hM"

        file = update.message.document or update.message.photo[-1]
        file_id = file.file_id
        file_obj = await context.bot.get_file(file_id)

        # Create and close the temp file first
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            await file_obj.download_to_drive(temp_path)

        filename = file.file_name if update.message.document else f"photo_{file_id}.jpg"
        link = upload_to_drive(temp_path, education_folder_id, filename)

        # Ensure educational_links is initialized and append the link
        if 'educational_links' not in context.user_data:
            context.user_data['educational_links'] = []
        context.user_data['educational_links'].append(link)

        os.remove(temp_path)

        await update.message.reply_text("Educational file received. Upload more or select an option:የትምህርት ማስረጃዎን በትክክል አስገብተዋል። ተጨማሪ ማስረጃ ያስገቡ ወይም ታች ካሉት አማርጮች አንዱን ይጠቀሙ።", reply_markup=skip_done_markup)
        return EDUCATIONAL_DOCS
    else:
        # Handle unexpected input
        await update.message.reply_text("Please upload a document/photo or use the buttons. የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ", reply_markup=skip_done_markup)
        return EDUCATIONAL_DOCS
    
async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Join testimonial and educational links into separate strings
    testimonial_links = ", ".join(context.user_data.get('testimonial_links', []))
    education_links = ", ".join(context.user_data.get('educational_links', []))

    # Prepare the data to be written to the Google Sheet
    data = [
        str(user_id),  # User ID
        context.user_data.get('username', ''),  # Username
        context.user_data.get('full_name', ''),  # Full Name (changed from 'Full_Name')
        context.user_data.get('PROFESSION', ''),  # Profession
        context.user_data.get('phone', ''),  # Phone (changed from 'PHONE')
        context.user_data.get('location', ''),  # Location
        context.user_data.get('region_city_woreda', ''),  # Region/City/Woreda
        "",  # CONFIRM_DELETE column (empty for now)
        "",  # COMMENT column (empty for now)
        testimonial_links,  # TESTIMONIALS column
        education_links  # EDUCATIONAL_DOCS column
    ]
    print("DATA TO WRITE:", data)
    try:
        worksheet = sheet  # Use the global `sheet` variable

        # Update the row if it exists, otherwise append a new row
        # Need to find the row again here in case the sheet changed since registration started
        # This part might need refinement if concurrent registrations are expected.
        # For simplicity, let's assume find_user_row is reliable here after gathering all data.
        row_idx, _ = find_user_row(user_id)
        if row_idx:
             worksheet.update(f"A{row_idx}:K{row_idx}", [data]) # Use found row_idx
        else:
            worksheet.append_row(data)


        # Notify the user of successful registration
        await update.message.reply_text("✅Congradulations! Registration complete! from now on people who needs your profession will get you easily.\n እንኳን ደስ አለዎት ምዝገባዎን አጠናቀዋል። \n ከዚህ በኋላ ማንኛውም የርስዎን ሙያ የሚፈልግ ሰው በቀላሉ ያገኝዎታል!!!", reply_markup=main_menu_markup) # Add main menu markup

        # Clear user data to avoid reuse
        context.user_data.clear()

    except Exception as e:
        # Notify the user of any errors
        await update.message.reply_text(f"❌ Error saving your data: /መረጃዎን መመዝገብ አልተቻለም። እባክዎ ትንሽ ቆይተው ይሞክሩ። {e}", reply_markup=main_menu_markup) # Add main menu markup

    return ConversationHandler.END


# CODE.txt (near your other CommandHandler functions)

async def send_manual_rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for an admin command like /send_rating <user_chat_id> <professional_id>
    Sends a rating request to a specified user for a specified professional.
    """
    args = context.args
    
    if len(args) == 2:
        try:
            target_chat_id = int(args[0])
            professional_id = args[1]
            
            # Call the function to send the rating request
            await send_rating_request(target_chat_id, professional_id, context)
            
            await update.message.reply_text(
                f"Rating request sent to chat ID `{target_chat_id}` for professional `{professional_id}`.",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("Invalid chat ID. Please provide a numeric user ID.")
        except Exception as e:
            await update.message.reply_text(f"An error occurred: {e}")
            logger.error(f"Error in send_manual_rating_command: {e}")
    else:
        await update.message.reply_text("Usage: `/send_rating <user_chat_id> <professional_id>`", parse_mode='Markdown')

# ... rest of your existing functions ...




async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    _, row = find_user_row(user_id)
    if not row:
        await update.message.reply_text("You are not registered. please click regiser. / አልተመዘገቡም. እባክዎ ምዝገባ የሚለውን ተጭነው ይመዝገቡ", reply_markup=main_menu_markup)
        return
    try:
        text = (
            f"Name: {row['Full_Name']}\n"
            f"Profession: {row['PROFESSION']}\n"
            f"Phone: {row['PHONE']}\n"
            f"Location: {row['LOCATION']}"
        )
        await update.message.reply_text(text, reply_markup=main_menu_markup)
    except KeyError:
        await update.message.reply_text("Your profile seems incomplete. Please re-register. / ምዝገባዎ አ እባክዎ ምዝገባ የሚለውን ተጭነው እንደገና ይመዝገቡ።", reply_markup=main_menu_markup)


# --- NEW EDIT PROFILE FLOW ---

async def editprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the edit profile conversation."""
    user_id = update.message.from_user.id
    row_idx, row_data = find_user_row(user_id)

    if not row_data:
        await update.message.reply_text("You are not registered. Please use /register. / ከዚህ በፊት አልተመዘገቡም እባክዎን /ምዝገባን ተጭነው ይመዝገቡ።", reply_markup=main_menu_markup)
        return ConversationHandler.END

    context.user_data['edit_row_idx'] = row_idx
    context.user_data['user_id'] = user_id # Store user_id for logging if needed

    keyboard = [
        [InlineKeyboardButton("📝 Full Name / ሙሉ ስም", callback_data="edit_name")],
        [InlineKeyboardButton("🛠️ Profession / ሙያ", callback_data="edit_profession")],
        [InlineKeyboardButton("📞 Phone / ስልክ", callback_data="edit_phone")],
        [InlineKeyboardButton("📍 Location (GPS) / አካባቢ (GPS)", callback_data="edit_location")],
        [InlineKeyboardButton("🗺️ Region/City/Woreda / ክልል/ከተማ/ወረዳ", callback_data="edit_address")],
        [InlineKeyboardButton("📄 Testimonials / ምስክር ወረቀቶች", callback_data="edit_testimonials")],
        [InlineKeyboardButton("🎓 Educational Docs / የትምህርት ማስረጃ", callback_data="edit_education")],
        [InlineKeyboardButton("❌ Cancel / አቋርጥ", callback_data="edit_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Which information would you like to update? / የትኛውን መረጃዎን ማስተካከል ይፈልጋሉ?", reply_markup=reply_markup)
    return ASK_EDIT_FIELD

async def ask_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the user's choice of field to edit."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    if query.data == "edit_cancel":
        await query.edit_message_text("Edit cancelled. / ማስተካክየ አቋርጠዋል።", reply_markup=None)
        context.user_data.clear()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Main Menu:", reply_markup=main_menu_markup) # Send main menu again
        return ConversationHandler.END

    edit_option = EDIT_OPTIONS.get(query.data)
    if not edit_option:
        await query.edit_message_text("Invalid option selected. Please try again። / የተሳሳተ አማርጭ መርጠዋል። እንደገና ይሞክሩ።")
        context.user_data.clear()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Main Menu:", reply_markup=main_menu_markup) # Send main menu again
        return ConversationHandler.END

    context.user_data['editing_field'] = edit_option['name']
    # Corrected: Use 'next_state' as defined in EDIT_OPTIONS
    context.user_data['next_edit_state'] = edit_option['next_state'] # Store for potential reuse

    # Remove the inline keyboard from the previous message
    await query.edit_message_reply_markup(reply_markup=None)

    # Send the prompt for the specific field
    reply_markup_to_send = ReplyKeyboardRemove() # Default remove keyboard
    if edit_option['name'] == "Location":
         location_button = [[KeyboardButton("Share Location / አካባቢዎን ያጋሩ ", request_location=True)], [KeyboardButton("Skip / አሳልፍ")]]
         reply_markup_to_send=ReplyKeyboardMarkup(location_button, one_time_keyboard=True, resize_keyboard=True)
    elif edit_option['name'] in ["Testimonials", "Educational Docs"]:
         # Prepare for file uploads and show skip/done keyboard
         context.user_data['new_file_links'] = []
         context.user_data['file_type_being_edited'] = edit_option['name'] # Track which file type
         reply_markup_to_send = skip_done_markup # Show skip/done keyboard


    await query.message.reply_text(edit_option['prompt'], reply_markup=reply_markup_to_send)

    # Corrected: Use 'next_state' as defined in EDIT_OPTIONS
    return edit_option['next_state'] # Use the stored next state

async def get_new_text_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input for updated fields."""
    new_value = update.message.text
    field_name = context.user_data.get('editing_field')

    if not field_name:
         await update.message.reply_text("An error occurred. Please start the edit process again. / ብልሽት አጋጥሟል። እባክዎ ማስተካከያዎን እንደገና ይጀምሩ።", reply_markup=main_menu_markup)
         context.user_data.clear()
         return ConversationHandler.END

    if field_name == "PHONE":
        if not is_valid_phone_number(new_value):
            await update.message.reply_text("Invalid phone number format. Please enter a valid phone number (e.g., +251912345678 or 0912345678): / የስልክ ቁጥርዎ ትክክል አይደለም። ትክክለኛ ስልክ ቁጥር ያስገቡ (ለምሳሌ +251912345678 ወይም 0912345678):")
            return GET_NEW_VALUE # Stay in the GET_NEW_VALUE state for phone

    # If it's not the phone field or if the phone number is valid
    success = await update_sheet_cell(context, field_name, new_value)

    if success:
        await update.message.reply_text(f"✅ Your {field_name.lower()} has been updated.", reply_markup=main_menu_markup)
    else:
        await update.message.reply_text("❌ Sorry, there was an error updating your information. Please try again later.", reply_markup=main_menu_markup)

    context.user_data.clear()
    return ConversationHandler.END

async def get_new_location_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles updated location input (GPS or skip)."""
    field_name = context.user_data.get('editing_field') # Should be "Location"
    new_value = "Not shared"

    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        new_value = f"{lat}, {lon}"
    elif update.message.text and "skip" in update.message.text.lower(): # Check for 'Skip' button text
        new_value = "Not shared"
    else:
        # If user sent text other than 'skip' when location was expected
         await update.message.reply_text("Invalid input. Please share location or use the 'Skip' button.", reply_markup=main_menu_markup) # Guide user to use button
         context.user_data.clear()
         return ConversationHandler.END


    if not field_name:
         await update.message.reply_text("An error occurred. Please start the edit process again.", reply_markup=main_menu_markup)
         context.user_data.clear()
         return ConversationHandler.END

    success = await update_sheet_cell(context, field_name, new_value)

    if success:
        await update.message.reply_text(f"✅ Your {field_name.lower()} has been updated.", reply_markup=main_menu_markup)
    else:
        await update.message.reply_text("❌ Sorry, there was an error updating your information. Please try again later.", reply_markup=main_menu_markup)

    context.user_data.clear()
    return ConversationHandler.END

async def handle_new_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles file uploads (testimonials/educational docs) during edit."""
    field_name = context.user_data.get('file_type_being_edited') # "Testimonials" or "Educational Docs"

    if not field_name:
        await update.message.reply_text("An error occurred. Please start the edit process again.", reply_markup=main_menu_markup)
        context.user_data.clear()
        return ConversationHandler.END

    # Check for 'done' or 'skip' command from buttons
    if update.message.text:
        text = update.message.text.lower()
        if "done" in text or "skip" in text or "ተጠናቋል" in text or "አሳልፍ" in text:
            # Combine collected links
            final_links = ", ".join(context.user_data.get('new_file_links', []))
            if ("skip" in text or "አሳልፍ" in text) and not final_links:
                final_links = "Skipped"
            elif ("done" in text or "ተጠናቋል" in text) and not final_links:
                 await update.message.reply_text(f"No new files uploaded. Keeping existing {field_name.lower()}.", reply_markup=main_menu_markup)
                 context.user_data.clear()
                 return ConversationHandler.END


            success = await update_sheet_cell(context, field_name, final_links)
            if success:
                 await update.message.reply_text(f"✅ Your {field_name.lower()} have been updated.", reply_markup=main_menu_markup)
            else:
                 await update.message.reply_text(f"❌ Error saving your {field_name.lower()}. Please try again.", reply_markup=main_menu_markup)

            context.user_data.clear()
            return ConversationHandler.END

    # Process uploaded file
    if update.message.document or update.message.photo:
        # Define folder IDs (ensure these are correct)
        testimonial_folder_id = "1TMehhfN9tExqoaHIYya-B-SCcFeBTj2y"
        education_folder_id = "1i9a2G7EXByrY9LxXtv4yY-CMExDWI7hM"

        folder_id = testimonial_folder_id if field_name == "Testimonials" else education_folder_id

        file = update.message.document or update.message.photo[-1]
        file_id = file.file_id
        try:
            file_obj = await context.bot.get_file(file_id)

            with tempfile.NamedTemporaryFile(delete=False) as tf:
                temp_path = tf.name
                await file_obj.download_to_drive(temp_path)

            filename = getattr(file, 'file_name', None) or f"photo_{file_id}.jpg"
            link = upload_to_drive(temp_path, folder_id, filename)

            if 'new_file_links' not in context.user_data:
                context.user_data['new_file_links'] = []
            context.user_data['new_file_links'].append(link)

            os.remove(temp_path)

            await update.message.reply_text("File received. Upload more or select an option:", reply_markup=skip_done_markup)
            return context.user_data['next_edit_state']

        except Exception as e:
            logger.error(f"Error processing file upload during edit: {e}")
            await update.message.reply_text("Sorry, there was an error processing your file. Please try uploading again or use the buttons.", reply_markup=skip_done_markup)
            return context.user_data['next_edit_state']
    else:
        # Handle unexpected input
        await update.message.reply_text("Please upload a document/photo or use the buttons.", reply_markup=skip_done_markup)
        return context.user_data['next_edit_state']


async def deleteprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    row_idx, row = find_user_row(user_id)
    if not row:
        await update.message.reply_text("You are not registered. / አልተመዘገቡም", reply_markup=main_menu_markup)
        return ConversationHandler.END
    # Use yes/no keyboard
    await update.message.reply_text("Are you sure you want to delete your profile? / መርጃዎን ለማጥፋት እርግጠኛ ነዎት?", reply_markup=yes_no_markup)
    context.user_data['row_idx'] = row_idx
    return CONFIRM_DELETE

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check for 'Yes' button text (case-insensitive, considering both English and Amharic button text)
    if update.message.text and ("yes" in update.message.text.lower() or "አዎ" in update.message.text.lower()):
        try:
            sheet.delete_rows(context.user_data['row_idx'])
            await update.message.reply_text("Profile deleted. / መረጃዎ ተደምስሷል", reply_markup=main_menu_markup) # Add main menu markup
        except:
            await update.message.reply_text("Service is temporarily unavailable. Please try again later.", reply_markup=main_menu_markup) # Add main menu markup
    else: # Assume any other text (including 'No' button text) cancels
        await update.message.reply_text("Deletion cancelled. / ድምሰሳው ትቋርጧል", reply_markup=main_menu_markup) # Add main menu markup
    return ConversationHandler.END

async def comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    row_idx, row = find_user_row(user_id)
    if not row:
        await update.message.reply_text("You are not registered. / አልተመዘገቡም", reply_markup=main_menu_markup)
        return ConversationHandler.END
    await update.message.reply_text("Send your comment:  / አስተያየቶን ያላኩ፡", reply_markup=ReplyKeyboardRemove()) # Remove keyboard for free text input
    context.user_data['row_idx'] = row_idx
    return COMMENT

async def save_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment_text = update.message.text
    row_idx = context.user_data.get('row_idx')
    if not row_idx:
        await update.message.reply_text("Could not locate your registration. ምዝገባዎን ማገኘት አልቻልንም", reply_markup=main_menu_markup)
        return ConversationHandler.END
    try:
        sheet.update(range_name=f'I{row_idx}', values=[[comment_text]])
        await update.message.reply_text("Comment saved.", reply_markup=main_menu_markup)
    except:
        await update.message.reply_text("Service is temporarily unavailable. Please try again later.", reply_markup=main_menu_markup)
    return ConversationHandler.END



# --- NEW: Global Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Log the error and send a user-friendly message if it's a network error.
    This handler catches exceptions that occur during the processing of updates,
    including network-related issues when communicating with the Telegram API.

    Note: This handles errors where the bot *attempts* to communicate with Telegram
    but fails due to network issues. It does *not* directly address a scenario
    where the bot's internal processing (e.g., Google Sheets operations) takes
    longer than 30 seconds, as Telegram's own API timeout (typically 10 seconds)
    would likely trigger first for that.
    """
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(context.error, NetworkError):
        # Attempt to send a network error message to the user
        if update and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ Network error! Please try again in a moment. / የአውታረ መረብ ስህተት! እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።"
                )
            except TelegramError as e:
                # If sending the error message itself fails due to network issues, just log it.
                logger.error(f"Failed to send network error message to user due to another TelegramError: {e}")
        else:
            logger.warning("Could not send network error message as effective_chat is not available.")
    # You can add more specific error handling here for other types of exceptions if needed.


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=main_menu_markup)
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(ChatMemberHandler(greet_new_user, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_name)],
            PROFESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_profession)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            LOCATION: [MessageHandler(filters.LOCATION | filters.TEXT, get_location)],
            REGION_CITY_WOREDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_region_city_woreda)],
            TESTIMONIALS: [MessageHandler(filters.ATTACHMENT | filters.PHOTO | filters.TEXT, handle_testimonials)],
            EDUCATIONAL_DOCS: [MessageHandler(filters.ATTACHMENT | filters.PHOTO | filters.TEXT, handle_educational_docs)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

     # --- Edit Profile Conversation --- (NEW/MODIFIED)
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("editprofile", editprofile)],
        states={
            ASK_EDIT_FIELD: [CallbackQueryHandler(ask_edit_field)],
            GET_NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_text_value)],
            GET_NEW_LOCATION: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_new_location_value)], # Allow text for skip
            GET_NEW_TESTIMONIALS: [MessageHandler(filters.ATTACHMENT | filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_new_files)], # Allow text for done/skip
            GET_NEW_EDUCATIONAL_DOCS: [MessageHandler(filters.ATTACHMENT | filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_new_files)], # Allow text for done/skip
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(ask_edit_field, pattern='^edit_cancel$') # Handle cancel via button
        ],
         map_to_parent={ # End edit and return to base level
            ConversationHandler.END: ConversationHandler.END
        }
    )

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("deleteprofile", deleteprofile)],
        states={
            CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    comment_conv = ConversationHandler(
        entry_points=[CommandHandler("comment", comment)],
        states={
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(register_conv)
    app.add_handler(edit_conv)
    app.add_handler(delete_conv)
    app.add_handler(comment_conv)
    app.add_handler(register_conv)
    app.add_handler(edit_conv)
    app.add_handler(delete_conv)
    app.add_handler(comment_conv)
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("editprofile", editprofile))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CallbackQueryHandler(handle_rating_callback, pattern='^rate_'))
    app.add_handler(CallbackQueryHandler(handle_initial_feedback_callback, pattern='^feedback_|^followup_')) # <--- ADD THIS LINE
    app.add_error_handler(error_handler) # <--- This line adds the new feature
    YOUR_ADMIN_TELEGRAM_ID =401674551 # <--- REPLACE WITH YOUR TELEGRAM USER ID
    app.add_handler(CommandHandler("request_feedback", request_feedback_command, filters=filters.User(YOUR_ADMIN_TELEGRAM_ID))) # <--- ADD THIS LINE
    app.run_polling()

if __name__ == '__main__':
    main()
