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
import asyncio
import telegram
import tempfile
from datetime import datetime

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # You can change this to DEBUG for more detailed output
)
logger = logging.getLogger(__name__)

user_specific_data = {}
PROFESSIONAL_ID_COL_MAIN_SHEET = 0 # Assuming 'Professional_ID' is in column A
PROFESSIONAL_NAME_COL_MAIN_SHEET = 2 # Assuming 'Full_Name' is in column B
# Define your conversation states (if not already defined)
# EDUCATIONAL_DOCS = 1 # Example state
# FINISHED_REGISTRATION = 2 # Example state, or whatever comes next
# Assuming 'import os' is at the very top of your file.

# --- Telegram Bot Token Setup ---
# This section should be placed very early in your script, after imports.
DEBO_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_DEBO")
print(f"DEBUG: Debo_registration.py is attempting to use token: '{DEBO_TOKEN}'")
if not DEBO_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN_DEBO environment variable not set.")
# --- End Telegram Bot Token Setup ---


APPS_SCRIPT_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyEbwoX6hglK7cCES1GeVKFhtwmajvVAI1WDBfh03bsQbA3DKgkfCe_jJfH-8EZ0HUc/exec"



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
logger = logging.getLogger(__name__)
yes_no_keyboard = [
    ["Yes አዎ✅", "No አይ❌"]
]
yes_no_markup = ReplyKeyboardMarkup(yes_no_keyboard, one_time_keyboard=True, resize_keyboard=True)




def find_user_row(user_id, worksheet_from_bot_data): # IMPORTANT: Added worksheet_from_bot_data parameter
    """
    Finds the row index and data for a given user_id in the specified worksheet.
    Args:
        user_id (int): The Telegram user ID.
        worksheet_from_bot_data: The gspread worksheet object.
    Returns:
        tuple: (row_index, row_data) or (None, None) if not found/error.
    """
    try:
        records = worksheet_from_bot_data.get_all_records()
        # enumerate starts from 0, but sheet rows are 1-based, and we skip header (row 1), so start=2
        for idx, row in enumerate(records, start=2):
            if str(row.get("User ID")) == str(user_id):
                logger.info(f"User {user_id} found in sheet at row {idx}. Data: {row.get('Full_Name', 'N/A')}")
                return idx, row
    except Exception as e:
        logger.error(f"Error in find_user_row for user {user_id}: {e}", exc_info=True)
        return None, None
    logger.info(f"User {user_id} not found in sheet.")
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
def upload_to_drive(file_path, folder_id, filename, creds):
    drive_service = build('drive', 'v3', credentials=creds)
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

# --- Sheet Update Helper ---
async def update_sheet_cell(context: ContextTypes.DEFAULT_TYPE, field_name: str, new_value):
    """Updates a specific cell in the user's row."""
    row_idx = context.user_data.get('edit_row_idx')
    user_id = context.user_data.get('user_id') # Get user_id for logging

    if not row_idx:
        logger.error(f"update_sheet_cell called without row_idx in user_data for user {user_id}")
        return False

    col_letter = COLUMN_MAP.get(field_name)
    if not col_letter:
        logger.error(f"Invalid field name '{field_name}' provided for update for user {user_id}.")
        return False

    # Retrieve the worksheet object
    worksheet = context.application.bot_data.get("main_worksheet")
    if not worksheet:
        logger.critical(f"ERROR: worksheet not found in bot_data for update_sheet_cell for user {user_id}.")
        return False

    try:
        # Use update_cells for potentially better performance or batching if needed later
        worksheet.update(f"{col_letter}{row_idx}", [[new_value]])
        logger.info(f"Updated row {row_idx}, column {col_letter} for user {user_id}. New value: '{new_value}'")
        return True
    except Exception as e:
        logger.error(f"Failed to update sheet for row {row_idx}, column {col_letter} for user {user_id}: {e}", exc_info=True)
        return False

# Global lookup for professional names (populated by startup_task)
professional_names_lookup = {}


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
    Sends the initial feedback message to the user with choices including individual Professionals.
    Stores the professional_ids in user_data for later reference.
    """
    # Store the list of Professionals sent for this user, so we can refer back to them later.
    user_specific_data[chat_id] = {'initial_professional_ids': professional_ids, 'rated_professional_ids': set()}
    keyboard = []

    # Add the static choices
    keyboard.append([InlineKeyboardButton("I will not contact them", callback_data="feedback_no_contact")])
    keyboard.append([InlineKeyboardButton("I will contact them soon", callback_data="feedback_will_contact")])
    keyboard.append([InlineKeyboardButton("Please don't send me this message again", callback_data="feedback_opt_out")])

    # Add buttons for each professional
    keyboard.append([InlineKeyboardButton("--- Choose Professional(s) You Contacted ---", callback_data="ignore_me")]) # Separator

    for pro_id in professional_ids:
        # Assuming you want to display the ID on the button. You could fetch names if needed.
        pro_name = professional_names_lookup.get(pro_id, pro_id) # <--- CHANGE THIS LINE
        keyboard.append([InlineKeyboardButton(pro_name, callback_data=f"feedback_select_pro_{pro_id}")])
    keyboard.append([
        InlineKeyboardButton("I have not contacted any of them", callback_data="feedback_no_contact"),
        InlineKeyboardButton("I will contact them soon", callback_data="feedback_will_contact")
    ])
    keyboard.append([InlineKeyboardButton("Opt-out of these messages", callback_data="feedback_opt_out")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Hello! Regarding the professional(s) we shared, please let us know your status or select whom you contacted:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    logger.info(f"Initial feedback message sent to {chat_id} for Professionals: {professional_ids}")

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
    
    # CORRECTED: Use the global user_specific_data dictionary
    user_session_data = user_specific_data.get(chat_id, {'initial_professional_ids': [], 'rated_professional_ids': set()})
    # These variables aren't directly used in *this* function's current logic,
    # but the line is kept for consistency in accessing session data.
    initial_professional_ids = user_session_data.get('initial_professional_ids', [])
    rated_professional_ids = user_session_data.get('rated_professional_ids', set())
  
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


# CODE.txt (modify the existing send_rating_to_apps_script function)

async def send_rating_to_apps_script(professional_id: str, rating_value: int, user_telegram_id: int, query_object: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the rating data as a JSON POST request to the Apps Script Web App.
    """
    payload = {
        "professional_id": professional_id,
        "rating": rating_value,
        "user_telegram_id": str(user_telegram_id)
    }
    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(APPS_SCRIPT_WEB_APP_URL, data=json.dumps(payload), headers=headers)
        response.raise_for_status()

        response_json = response.json()
        if response_json.get("success"):
            pro_name = professional_names_lookup.get(professional_id, professional_id) # <--- CHANGE THIS LINE
            await query_object.edit_message_text(
                text=f"✅ Thanks! Your *{rating_value}-star* rating for professional *{pro_name}* has been recorded.", # <--- CHANGE THIS LINE (use pro_name)
                parse_mode='Markdown',
                reply_markup=None
            )
            logger.info(f"Successfully sent rating for {professional_id} by {user_telegram_id}: {rating_value} stars.")

            # --- NEW LOGIC: Store that this professional has been rated ---
            # CORRECTED: Use the global user_specific_data dictionary
            # Ensure the user's entry exists before trying to access its keys
            if user_telegram_id not in user_specific_data:
                user_specific_data[user_telegram_id] = {'initial_professional_ids': [], 'rated_professional_ids': set()}
            user_specific_data[user_telegram_id]['rated_professional_ids'].add(professional_id)
            # --- END NEW LOGIC ---

            await send_follow_up_rating_prompt(user_telegram_id, context)

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
                f"Initial feedback request sent to chat ID `{target_chat_id}` for Professionals: `{', '.join(professional_ids_to_send)}`.",
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

# CODE.txt (modify the existing handle_initial_feedback_callback function)

async def handle_initial_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles callback queries from the initial feedback message and follow-up prompts.
    """
    query = update.callback_query
    callback_data = query.data
    user_chat_id = query.from_user.id

    await query.answer()

    # --- Retrieve user data for current session ---
    # CORRECTED: Use the global user_specific_data dictionary
    user_session_data = user_specific_data.get(user_chat_id, {'initial_professional_ids': [], 'rated_professional_ids': set()})
    # --- END Retrieve user data ---

    # --- Handle initial feedback choices ---
    if callback_data == "feedback_no_contact":
        await query.edit_message_text(
            text="Understood! We won't send rating requests for these Professionals. Thank you for the update.",
            reply_markup=None
        )
        # Clear session data
        if user_chat_id in user_specific_data:
            del user_specific_data[user_chat_id]
        logger.info(f"User {user_chat_id} chose 'no contact'. Session data cleared.")

    elif callback_data == "feedback_will_contact":
        await query.edit_message_text(
            text="Okay, please let us know if you contact them! We won't send immediate rating requests.",
            reply_markup=None
        )
        # Clear session data
        if user_chat_id in user_specific_data:
            del user_specific_data[user_chat_id]
        logger.info(f"User {user_chat_id} chose 'will contact soon'. Session data cleared.")

    elif callback_data == "feedback_opt_out":
        await query.edit_message_text(
            text="Got it. We won't send you these types of messages again. You can always reactivate feedback requests by contacting support.",
            reply_markup=None
        )
        # IMPORTANT: Implement logic here to store this opt-out preference persistently
        # e.g., in your Google Sheet for this user ID.
        # Clear session data
        if user_chat_id in user_specific_data:
            del user_specific_data[user_chat_id]
        logger.info(f"User {user_chat_id} opted out of feedback requests. Session data cleared.")
        
    elif callback_data.startswith("feedback_select_pro_"):
        try:
            professional_id = callback_data.split('_')[2]
            pro_name = professional_names_lookup.get(professional_id, professional_id)
            await query.edit_message_text(
                text=f"You selected professional: *{pro_name}*."
                     f"\nNow, please use the stars in the *next message* to rate them.",
                parse_mode='Markdown'
            )
            
            await send_rating_request(user_chat_id, professional_id, context)
            logger.info(f"User {user_chat_id} selected {professional_id} for rating.")

        except IndexError:
            await query.edit_message_text(text="Error processing professional selection.", reply_markup=None)
            logger.error(f"Error parsing feedback_select_pro_ callback data: {callback_data}")
            
    # --- Handle follow-up choices after a rating ---
    elif callback_data == "followup_rate_another":
        # Retrieve the original list of professional IDs sent to this user
        initial_professional_ids = user_session_data.get('initial_professional_ids', [])
        # Retrieve the list of Professionals already rated in this session
        rated_professional_ids = user_session_data.get('rated_professional_ids', set())

        # Calculate the unrated Professionals
        unrated_professional_ids = [
            pro_id for pro_id in initial_professional_ids if pro_id not in rated_professional_ids
        ]
        
        if unrated_professional_ids:
            # Re-send the initial feedback message with only the unrated Professionals
            await send_initial_feedback_message(user_chat_id, unrated_professional_ids, context)
            # Remove the follow-up prompt buttons
            await query.edit_message_text(
                text="Please choose another professional to rate from the message above, or click 'End rating process'.",
                reply_markup=None
            )
            logger.info(f"User {user_chat_id} chose to rate another professional. Resending initial choices (filtered).")
        else:
            await query.edit_message_text(
                text="You have rated all Professionals from this list! Thank you for your feedback. The rating process has ended.",
                reply_markup=None
            )
            # Clear session data as all Professionals have been rated
            if user_chat_id in user_specific_data:
                del user_specific_data[user_chat_id]
            logger.info(f"User {user_chat_id} rated all Professionals. Session data cleared.")

    elif callback_data == "followup_end_rating":
        await query.edit_message_text(
            text="Thank you for your feedback! The rating process has ended.",
            reply_markup=None
        )
        # Clear session data
        if user_chat_id in user_specific_data:
            del user_specific_data[user_chat_id]
        logger.info(f"User {user_chat_id} ended the rating process. Session data cleared.")

    return




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
        await context.bot.send_message(chat_id, "\n.\n               🎉Welcome to MUYA Bot!                                🎉እንኳን ወደ ሙያ ቦት በሰላም መጡ \n this bot is used to registor any Ethiopian" \
        "professionals who are interested to find new job opportunities from their nighbour to their city. \n ይህ ቦት የሙያ ባለቤት የሆኑ ማንኛውም  ኢትይጵያውያንን የምንመዘግብበትና ባቅርያብያቸው ያሉ የስራ እድሎችን እና ባለሙያ ፈላጊዎችን በቀላሉ እንዲያገኙ የምናመቻችበት የምናደርግበት ቴክኖልጂ ነው። \n " \
        "any information you give to this bot will be given to people that want your contact to make you work for them \n በዚህ ቦት ላይ የሚያጋሯቸው መርጃዎችዎ ስራ ሊያሰሯቹ ለሚፈልጉ ሰዎች ይሰጣልይ \ን" \
        "ስለአሰራራችን የበለጠ ለማውቅ ወይም የትኛውም ጥይቄ ካልዎት ይህንን ይጫኑይጫኑ", reply_markup=main_menu_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
     await update.message.reply_text("                              \n                              🎉 *Welcome to Muya Bot!* \n                              🎉 *እንኳን ወደ ሙያ ቦት በሰላም መጡ* \n \n📌  this bot is used to registor any Ethiopian professionals who are interested to find new job opportunities from thier nighbour to thier city. \n \n 📌  some of the information you give to this bot will be given to people that want your contact to make you work for them \n  \n \n📌  ይህ ቦት የሙያ ባለቤት የሆኑ ማንኛውም  ኢትይጵያውያንን የምንመዘግብበትና ባቅርያብያቸው ያሉ የስራ እድሎችን እንዲያገኙ ከባለሙያ ፈላጊዎች ጋር በቀላሉ እንዲገናኙ የምናደርግበት ነው። \n " \
         " \n📌  በዚህ ቦት ላይ የሚያጋሯቸው አንዳንድ መርጃዎችዎ ስራ ሊያሰሯችሁችሁ ለሚፈልጉ ሰዎች ይጋራሉ።\n \n📢 *please use the below menu to continue* \n *ለመቀጠል ከስር ካሉት አማራጮች አንዱን ይጫኑ።* \n \n ስለአሰራራችን የበለጠ ለማውቅ ወይም የትኛውም ጥይቄ ካልዎት ይህንን ይጫኑ", reply_markup=main_menu_markup, parse_mode="Markdown")



async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # IMPORTANT: Retrieve worksheet from bot_data and pass it
    worksheet = context.application.bot_data.get("main_worksheet")
    if not worksheet:
        logger.critical(f"main_worksheet not available in register function for user {user_id}.")
        await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    _, existing = find_user_row(user_id, worksheet) # <--- MODIFIED
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
    await update.message.reply_text(
    "🛠️Enter your profession: / ሙያዎን ያስገቡ\n\n"
    "📌 እባክዎን የተሰማሩበትን የትኛውንም የስራ ዘርፍ በጥንቃቄ እና በግልጽ ይጻፉ።\n\n"
    "*ለምሳሌ:*\n"
    "✔ ዶክተር ከማለት ኦንኮሎጂስት\n"
    "✔ የቧምቧ ባለሙያ\n"
    "✔ ኢንጂነር ከማለት ሲቪል ኢንጂነር\n"
    "✔ ተምላላሽ ሰራተኛ\n"
    "✔ የኤሌክትሪክ ሰራተኛ\n"
    "✔ ጠበቃ\n",
    
    parse_mode="Markdown"
    )
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
    # Retrieve credentials from bot_data
    creds = context.application.bot_data.get("gdrive_creds")
    if not creds:
        logger.error(f"Google Drive credentials not found in bot_data for user {update.effective_user.id}.")
        await update.message.reply_text("Error: Could not access Google Drive for uploads. Please try again later or contact support.")
        return ConversationHandler.END # Or a more appropriate return state

    if update.message.text:
        text = update.message.text.lower()
        if "skip" in text or "አሳልፍ" in text:
            logger.info(f"User {update.effective_user.id} skipped testimonials. Proceeding to ask for educational docs.")
            return await ask_for_educational_docs(update, context)
        elif "done" in text or "ተጠናቋል" in text:
            if not context.user_data.get('testimonial_links'):
                await update.message.reply_text("No testimonial files were uploaded. Skipping. \n ምንም አይነት የሰሯቸውን ስራዎች ማስርጃ አላስገቡም!", reply_markup=ReplyKeyboardRemove())
            logger.info(f"User {update.effective_user.id} finished testimonials. Proceeding to ask for educational docs.")
            return await ask_for_educational_docs(update, context)
        else:
            await update.message.reply_text("Please upload a document/photo or use the buttons. የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ", reply_markup=skip_done_markup)
            return TESTIMONIALS


    if update.message.document or update.message.photo:
        testimonial_folder_id = "1TMehhfN9tExqoaHIYya-B-SCcFeBTj2y" # Your folder ID

        file = update.message.document or update.message.photo[-1]
        file_id = file.file_id
        file_obj = await context.bot.get_file(file_id)

        filename = file.file_name if update.message.document else f"photo_{file_id}.jpg"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            await file_obj.download_to_drive(temp_path)

        try:
            link = upload_to_drive(temp_path, testimonial_folder_id, filename, creds)

            if 'testimonial_links' not in context.user_data:
                context.user_data['testimonial_links'] = []
            context.user_data['testimonial_links'].append(link)
            logger.info(f"Uploaded testimonial file for user {update.effective_user.id}: {link}")

            await update.message.reply_text("File received. Upload more or select an option: ማስረጃዎን በትክክል አስገብተዋል። ተጨማሪ ማስረጃ ያስገቡ ወይም ታች ካሉት አማርጮች አንዱን ይጠቀሙ።", reply_markup=skip_done_markup)
            return TESTIMONIALS

        except Exception as e:
            logger.error(f"Error uploading testimonial file {filename} to Drive for user {update.effective_user.id}: {e}", exc_info=True)
            await update.message.reply_text("There was an error uploading your file. Please try again.")
            return TESTIMONIALS

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    else:
        await update.message.reply_text("Please upload a document/photo or use the buttons. የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ ", reply_markup=skip_done_markup)
        return TESTIMONIALS


async def ask_for_educational_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓Please upload your educational background documents or images. You can upload multiple files. Or use the buttons below:  \n የትምህርት ማስረጃ ካልዎትያስገቡ። \n✅ የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። \n ✅ከአንድ በላይ ፋይል ማስግባት ይችላሉ። ✅ አስገብተው ሲጨርሱ Done /ጨርሻለው የሚለውን ይጫኑ። \n ✅ የሚያስገቡት ማስረጃ ከሌሎት skip /አሳልፍን ይጫኑ።ይጫኑ።",
         reply_markup=skip_done_markup # Show keyboard immediately
    )
    context.user_data['education_links'] = []
    logger.info(f"User {update.effective_user.id} asked for educational docs. Initializing education_links.")
    return EDUCATIONAL_DOCS

async def handle_educational_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Retrieve credentials from bot_data
    creds = context.application.bot_data.get("gdrive_creds")
    if not creds:
        logger.error(f"Google Drive credentials not found in bot_data for user {update.effective_user.id}.")
        await update.message.reply_text("Error: Could not access Google Drive for uploads. Please try again later or contact support.")
        return ConversationHandler.END # Or a more appropriate return state

    if update.message.text:
        text = update.message.text.lower()
        if "skip" in text or "አሳልፍ" in text:
            logger.info(f"User {update.effective_user.id} skipped educational documents. Calling finish_registration.")
            return await finish_registration(update, context) # <--- CRITICAL CHANGE: Call finish_registration
        elif "done" in text or "ተጠናቋል" in text:
            if not context.user_data.get('educational_links'):
                await update.message.reply_text("No educational files were uploaded. Skipping. ምንም አይነት የሰሯቸውን ስራዎች ማስርጃ አላስገቡም!", reply_markup=ReplyKeyboardRemove())
            logger.info(f"User {update.effective_user.id} finished educational documents. Calling finish_registration.")
            return await finish_registration(update, context) # <--- CRITICAL CHANGE: Call finish_registration
        else:
            await update.message.reply_text("Please upload a document/photo or use the buttons. የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ ", reply_markup=skip_done_markup)
            return EDUCATIONAL_DOCS

    if update.message.document or update.message.photo:
        education_folder_id = "1i9a2G7EXByrY9LxXtv4yY-CMExDWI7hM" # Replace with your actual folder ID

        file = update.message.document or update.message.photo[-1]
        file_id = file.file_id
        file_obj = await context.bot.get_file(file_id)

        filename = file.file_name if update.message.document else f"edu_photo_{file_id}.jpg"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name
            await file_obj.download_to_drive(temp_path)

        try:
            link = upload_to_drive(temp_path, education_folder_id, filename, creds)

            if 'educational_links' not in context.user_data:
                context.user_data['educational_links'] = []
            context.user_data['educational_links'].append(link)
            logger.info(f"Uploaded educational file for user {update.effective_user.id}: {link}")

            await update.message.reply_text("File received. Upload more or select an option: ማስረጃዎን በትክክል አስገብተዋል። ተጨማሪ ማስረጃ ያስገቡ ወይም ታች ካሉት አማርጮች አንዱን ይጠቀሙ።", reply_markup=skip_done_markup)
            return EDUCATIONAL_DOCS

        except Exception as e:
            logger.error(f"Error uploading educational file {filename} to Drive for user {update.effective_user.id}: {e}", exc_info=True)
            await update.message.reply_text("There was an error uploading your file. Please try again.")
            return EDUCATIONAL_DOCS

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    else:
        await update.message.reply_text("Please upload a document/photo or use the buttons. የትኛውንም የፋይል አይነት ማስገባት ይችላሉ። አስገብተው ከጨረሱ skip / አሳልፍ ይጫኑይጫኑ ", reply_markup=skip_done_markup)
        return EDUCATIONAL_DOCS

async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    logger.info(f"finish_registration initiated for user ID: {user_id}")

    # --- Step 1: Retrieve the worksheet object ---
    # This is CRUCIAL. The 'sheet' global might not be correctly initialized or accessible.
    # Always get the worksheet from bot_data if it was stored in startup_task.
    worksheet = context.application.bot_data.get("main_worksheet")
    if not worksheet:
        logger.critical(f"ERROR: Google Sheet worksheet 'main_worksheet' not found in bot_data for user {user_id}. Bot startup might have failed.")
        await update.message.reply_text(
            "❌ System Error: Could not access the registration sheet. Please contact support. / ስህተት: ምዝገባው አልተሳካም። እባክዎ ድጋፍ ያግኙ።",
            reply_markup=main_menu_markup
        )
        return ConversationHandler.END

    logger.info(f"Worksheet '{worksheet.title}' successfully retrieved from bot_data.")

    # --- Step 2: Prepare the data to be written ---
    testimonial_links = ", ".join(context.user_data.get('testimonial_links', []))
    education_links = ", ".join(context.user_data.get('educational_links', []))

    # This 'data' list order MUST match your Google Sheet's columns from A to K
    data = [
        str(user_id),                               # Column A: User ID
        context.user_data.get('username', ''),      # Column B: Username
        context.user_data.get('full_name', ''),     # Column C: Full Name
        context.user_data.get('PROFESSION', ''),    # Column D: Profession
        context.user_data.get('phone', ''),         # Column E: Phone
        context.user_data.get('location', ''),      # Column F: Location
        context.user_data.get('region_city_woreda', ''), # Column G: Region/City/Woreda
        "",                                         # Column H: Placeholder (e.g., CONFIRM_DELETE, if used)
        "",                                         # Column I: Placeholder (e.g., COMMENT, if used)
        testimonial_links,                          # Column J: Testimonials
        education_links                             # Column K: Educational Docs
    ]
    logger.info(f"Data prepared for writing to sheet for user {user_id}: {data}")

    # --- Step 3: Attempt to write data to Google Sheet ---
    try:
        # Pass the retrieved worksheet to find_user_row
        row_idx, existing_row_data = find_user_row(user_id, worksheet) # <--- MODIFIED: Pass worksheet

        if row_idx:
            logger.info(f"User {user_id} found at row {row_idx}. Attempting to UPDATE existing row.")
            # Update the entire row from A to K with the new data
            worksheet.update(f"A{row_idx}:K{row_idx}", [data])
            logger.info(f"Successfully UPDATED row {row_idx} for user {user_id}.")
        else:
            logger.info(f"User {user_id} not found. Attempting to APPEND new row.")
            # Append a new row with the collected data
            worksheet.append_row(data)
            logger.info(f"Successfully APPENDED new row for user {user_id}.")

        # --- Step 4: Confirm success to the user and clear data ---
        await update.message.reply_text(
            "✅Congradulations! Registration complete! from now on people who needs your profession will get you easily.\n እንኳን ደስ አለዎት ምዝገባዎን አጠናቀዋል። \n ከዚህ በኋላ ማንኛውም የርስዎን ሙያ የሚፈልግ ሰው በቀላሉ ያገኝዎታል!!!",
            reply_markup=main_menu_markup
        )
        logger.info(f"Registration successfully completed and confirmed for user {user_id}.")

        # Clear user data to avoid storing stale information
        context.user_data.clear()

    except gspread.exceptions.APIError as api_e:
        # This catches errors directly from the Google Sheets API (e.g., permission denied, invalid range)
        logger.error(f"Google Sheets API Error while saving data for user {user_id}: {api_e.response.text}", exc_info=True)
        await update.message.reply_text(
            f"❌ Error saving your data to Google Sheet due to API issue. Please contact support. / በመረጃ ማስቀመጥ ላይ የኤፒአይ ስህተት ተከስቷል። እባክዎ ድጋፍ ያግኙ።",
            reply_markup=main_menu_markup
        )
    except Exception as e:
        # Catch any other unexpected errors during the saving process
        logger.error(f"General Error saving data for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Error saving your data: /መረጃዎን መመዝገብ አልተቻለም። እባክዎ ትንሽ ቆይተው ይሞክሩ። {e}",
            reply_markup=main_menu_markup
        )

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
    worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet
    if not worksheet:
        logger.critical(f"main_worksheet not available in profile function for user {user_id}.")
        await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
        return

    _, row = find_user_row(user_id, worksheet) # <--- MODIFIED
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
    except KeyError as e:
        logger.error(f"KeyError in profile for user {user_id}: {e}. Row data: {row}", exc_info=True)
        await update.message.reply_text("Your profile seems incomplete. Please re-register. / ምዝገባዎ አ እባክዎ ምዝገባ የሚለውን ተጭነው እንደገና ይመዝገቡ።", reply_markup=main_menu_markup)



# --- NEW EDIT PROFILE FLOW ---

async def editprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the edit profile conversation."""
    user_id = update.message.from_user.id
    worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet
    if not worksheet:
        logger.critical(f"main_worksheet not available in editprofile function for user {user_id}.")
        await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    row_idx, row_data = find_user_row(user_id, worksheet) # <--- MODIFIED

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
        await context.bot.send_message(chat_id=query.message.chat_id, text="Main Menu:", reply_markup=main_menu_markup)
        return ConversationHandler.END

    edit_option = EDIT_OPTIONS.get(query.data)
    if not edit_option:
        await query.edit_message_text("Invalid option selected. Please try again። / የተሳሳተ አማርጭ መርጠዋል። እንደገና ይሞክሩ።")
        context.user_data.clear()
        await context.bot.send_message(chat_id=query.message.chat_id, text="Main Menu:", reply_markup=main_menu_markup)
        return ConversationHandler.END

    context.user_data['editing_field'] = edit_option['name']
    context.user_data['next_edit_state'] = edit_option['next_state']

    await query.edit_message_reply_markup(reply_markup=None)

    reply_markup_to_send = ReplyKeyboardRemove()
    if edit_option['name'] == "Location":
        location_button = [[KeyboardButton("Share Location / አካባቢዎን ያጋሩ ", request_location=True)], [KeyboardButton("Skip / አሳልፍ")]]
        reply_markup_to_send=ReplyKeyboardMarkup(location_button, one_time_keyboard=True, resize_keyboard=True)
    elif edit_option['name'] in ["Testimonials", "Educational Docs"]:
        context.user_data['new_file_links'] = []
        context.user_data['file_type_being_edited'] = edit_option['name']
        reply_markup_to_send = skip_done_markup

    await query.message.reply_text(edit_option['prompt'], reply_markup=reply_markup_to_send)
    return edit_option['next_state']

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
    field_name = context.user_data.get('file_type_being_edited')

    if not field_name:
        await update.message.reply_text("An error occurred. Please start the edit process again.", reply_markup=main_menu_markup)
        context.user_data.clear()
        return ConversationHandler.END

    if update.message.text:
        text = update.message.text.lower()
        if "done" in text or "skip" in text or "ተጠናቋል" in text or "አሳልፍ" in text:
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

    if update.message.document or update.message.photo:
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
            creds = context.application.bot_data.get("gdrive_creds") # Get creds for upload_to_drive
            if not creds:
                raise ValueError("Google Drive credentials not found for file upload.")

            link = upload_to_drive(temp_path, folder_id, filename, creds)

            if 'new_file_links' not in context.user_data:
                context.user_data['new_file_links'] = []
            context.user_data['new_file_links'].append(link)

            os.remove(temp_path)

            await update.message.reply_text("File received. Upload more or select an option:", reply_markup=skip_done_markup)
            return context.user_data['next_edit_state']

        except Exception as e:
            logger.error(f"Error processing file upload during edit: {e}", exc_info=True)
            await update.message.reply_text("Sorry, there was an error processing your file. Please try uploading again or use the buttons.", reply_markup=skip_done_markup)
            return context.user_data['next_edit_state']
    else:
        await update.message.reply_text("Please upload a document/photo or use the buttons.", reply_markup=skip_done_markup)
        return context.user_data['next_edit_state']


async def deleteprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet
    if not worksheet:
        logger.critical(f"main_worksheet not available in deleteprofile function for user {user_id}.")
        await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    row_idx, row = find_user_row(user_id, worksheet) # <--- MODIFIED
    if not row:
        await update.message.reply_text("You are not registered. / አልተመዘገቡም", reply_markup=main_menu_markup)
        return ConversationHandler.END
    await update.message.reply_text("Are you sure you want to delete your profile? / መርጃዎን ለማጥፋት እርግጠኛ ነዎት?", reply_markup=yes_no_markup)
    context.user_data['row_idx'] = row_idx
    return CONFIRM_DELETE



async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and ("yes" in update.message.text.lower() or "አዎ" in update.message.text.lower()):
        row_idx = context.user_data.get('row_idx')
        user_id = update.message.from_user.id
        worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet

        if not worksheet:
            logger.critical(f"main_worksheet not available for delete operation for user {user_id}.")
            await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
            return ConversationHandler.END

        try:
            worksheet.delete_rows(row_idx)
            logger.info(f"Successfully deleted row {row_idx} for user {user_id}.")
            await update.message.reply_text("Profile deleted. / መረጃዎ ተደምስሷል", reply_markup=main_menu_markup)
        except Exception as e: # <--- MODIFIED: Catch specific exception and log it
            logger.error(f"Failed to delete profile for user {user_id} at row {row_idx}: {e}", exc_info=True)
            await update.message.reply_text(f"Service is temporarily unavailable. Please try again later. Error: {e}", reply_markup=main_menu_markup) # Show specific error
    else:
        await update.message.reply_text("Deletion cancelled. / ድምሰሳው ትቋርጧል", reply_markup=main_menu_markup)
    context.user_data.clear() # Clear user_data regardless of success/failure for deletion
    return ConversationHandler.END

async def comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet
    if not worksheet:
        logger.critical(f"main_worksheet not available in comment function for user {user_id}.")
        await update.message.reply_text("Error: Database connection not ready. Please try again later.", reply_markup=main_menu_markup)
        return ConversationHandler.END

    row_idx, row = find_user_row(user_id, worksheet) # <--- MODIFIED
    if not row:
        await update.message.reply_text("You are not registered. / አልተመዘገቡም", reply_markup=main_menu_markup)
        return ConversationHandler.END
    await update.message.reply_text("Send your comment:  / አስተያየቶን ያላኩ፡", reply_markup=ReplyKeyboardRemove())
    context.user_data['row_idx'] = row_idx
    return COMMENT


async def save_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment_text = update.message.text
    row_idx = context.user_data.get('row_idx')
    user_id = update.message.from_user.id
    worksheet = context.application.bot_data.get("main_worksheet") # <--- MODIFIED: Get worksheet

    if not worksheet or not row_idx:
        logger.critical(f"worksheet or row_idx not available for save_comment for user {user_id}.")
        await update.message.reply_text("Could not locate your registration. ምዝገባዎን ማገኘት አልቻልንም", reply_markup=main_menu_markup)
        return ConversationHandler.END

    try:
        worksheet.update(range_name=f'I{row_idx}', values=[[comment_text]])
        logger.info(f"Comment saved for user {user_id} at row {row_idx}.")
        await update.message.reply_text("Comment saved.", reply_markup=main_menu_markup)
    except Exception as e: # <--- MODIFIED: Catch specific exception and log it
        logger.error(f"Failed to save comment for user {user_id} at row {row_idx}: {e}", exc_info=True)
        await update.message.reply_text(f"Service is temporarily unavailable. Please try again later. Error: {e}", reply_markup=main_menu_markup)
    context.user_data.clear() # Clear user_data after comment is saved/failed
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

async def startup_task(application: Application):
    logger.info("Running startup_task...")
    # Google Sheets setup
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    # Get the Google Credentials JSON path from its dedicated environment variable
    GOOGLE_CREDENTIALS_JSON_PATH = os.environ.get("GOOGLE_CREDENTIALS_JSON")

    try:
        logger.info(f"DEBUG: GOOGLE_CREDENTIALS_JSON_PATH within script: '{GOOGLE_CREDENTIALS_JSON_PATH}'")

        if not GOOGLE_CREDENTIALS_JSON_PATH:
            logger.error("GOOGLE_CREDENTIALS_JSON environment variable not set. Cannot proceed with Google Sheets connection.")
            raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set.")

        logger.info("Attempting to authorize gspread client...")
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_JSON_PATH, scope)
        gc = gspread.authorize(creds)
        logger.info("gspread client authorized successfully.")
        # Store credentials for later use by other functions
        application.bot_data["gdrive_creds"] = creds # <--- ADD THIS LINE

        try:
            logger.info("Attempting to open Google Spreadsheet 'debo_registration'...")
            # Use 'gc' for the client, as defined above
            spreadsheet_id = "16l_rYpXX1hrEUNS9DOCU2naCij-U635unpD12WDDggA"
            spreadsheet = gc.open_by_key(spreadsheet_id)
            logger.info(f"Successfully opened Google Spreadsheet: '{spreadsheet.title}' (ID: {spreadsheet.id})")

            logger.info("Attempting to open worksheet 'Sheet1' within 'debo_registration'...")
            worksheet = spreadsheet.worksheet("Sheet1")
            logger.info(f"Successfully opened worksheet: '{worksheet.title}'")

            application.bot_data["main_worksheet"] = worksheet
            logger.info("Worksheet 'Sheet1' loaded into bot_data successfully as 'main_worksheet'.")

        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"Google Spreadsheet 'debo_registration' not found. Please check the name and sharing permissions for service account {creds.service_account_email}.", exc_info=True)
            raise ValueError("Worksheet not loaded in bot_data. Spreadsheet not found.")
        except gspread.exceptions.WorksheetNotFound:
            logger.error(f"Worksheet 'Sheet1' not found within spreadsheet 'debo_registration'. Please check the worksheet name.", exc_info=True)
            raise ValueError("Worksheet not loaded in bot_data. Worksheet not found.")
        except Exception as e:
            logger.error(f"Failed to open Google Sheet 'debo_registration' or 'Sheet1' with gspread: {e}", exc_info=True)
            raise ValueError(f"Worksheet not loaded in bot_data. Detailed error: {e}")

    except Exception as e:
        logger.error(f"Critical error during gspread authorization or initial sheet loading: {e}", exc_info=True)
        # Re-raise the ValueError to ensure the bot startup fails if the sheet isn't loaded
        raise ValueError(f"Worksheet not loaded in bot_data. Critical startup error: {e}")

    # Ensure main_worksheet is available before proceeding
    worksheet = application.bot_data.get("main_worksheet")
    if not worksheet:
        logger.critical("main_worksheet is still None after attempts to load. This should not happen if previous errors are handled correctly.")
        raise ValueError("Worksheet not loaded in bot_data during final check.")

    await load_professional_names_from_sheet(worksheet)
    logger.info("Professional names loaded successfully on startup.")

async def load_professional_names_from_sheet(worksheet):
    """
    Loads all professional IDs and their full names from the provided Google Sheet
    into the global `professional_names_lookup` dictionary.
    """
    global professional_names_lookup
    logger.info("Loading professional names from Google Sheet...")

    try:
        all_data = worksheet.get_all_values()

        if not all_data:
            logger.warning("No data found in the Professionals sheet.")
            return

        # Skip header row
        data_rows = all_data[1:] if len(all_data) > 1 else []

        lookup = {}
        for row in data_rows:
            if len(row) > max(PROFESSIONAL_ID_COL_MAIN_SHEET, PROFESSIONAL_NAME_COL_MAIN_SHEET):
                pro_id = row[PROFESSIONAL_ID_COL_MAIN_SHEET].strip()
                pro_name = row[PROFESSIONAL_NAME_COL_MAIN_SHEET].strip()
                if pro_id:  # Only add if professional ID is not empty
                    lookup[pro_id] = pro_name

        professional_names_lookup = lookup
        logger.info(f"✅ Loaded {len(professional_names_lookup)} professional names.")

    except Exception as e:
        logger.error(f"❌ Error loading professional names from sheet: {e}")


def main():
    
    app = Application.builder().token(DEBO_TOKEN).build()
    # --- Google Sheets Setup ---
    # This block needs to be here to initialize gspread and open the sheet
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    GOOGLE_CREDENTIALS_JSON_PATH = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not GOOGLE_CREDENTIALS_JSON_PATH:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set.")
    
    # CORRECTED LINE: Directly use the path from the environment variable
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_JSON_PATH, scope)
    gc = gspread.authorize(creds)
    
    spreadsheet_id = os.environ.get("SPREADSHEET_ID_DEBO")
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID_DEBO environment variable not set.")
    
    try:
        # Assuming your main Professionals sheet is named "Sheet1"
        main_worksheet = gc.open_by_key(spreadsheet_id).worksheet("Sheet1")
        app.bot_data["main_worksheet"] = main_worksheet # Store worksheet in bot_data for easy access
        logger.info("Google Sheet 'Sheet1' opened successfully.") # Changed to Sheet1 based on code
    except Exception as e:
        logger.error(f"Failed to open Google Sheet 'Sheet1': {e}") # Changed to Sheet1 based on code
    
    # IMPORTANT: Also remove the os.remove(temp_creds_file.name) line (around line 1195)
    # as the temporary file is no longer created.
    # --- End Google Sheets Setup ---

  
    # --- End Google Sheets Setup ---

    # Register the startup task to load names
    app.post_init = startup_task
  

    app.add_handler(ChatMemberHandler(greet_new_user, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", start))

    app.add_handler(CommandHandler("request_feedback", request_feedback_command, filters=filters.User(os.environ.get("401674551"))))
    app.add_handler(CallbackQueryHandler(handle_initial_feedback_callback, pattern='^feedback_|^followup_'))
    app.add_handler(CallbackQueryHandler(handle_rating_callback, pattern='^rate_'))
    app.add_error_handler(error_handler)
    
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

    class FakeContext: # A minimalist context for startup tasks
        def __init__(self, app_instance):
            self.application = app_instance
            self.bot_data = app_instance.bot_data # Ensure bot_data is accessible

    fake_context = FakeContext(app)
    

    app.post_init = startup_task # This is the cleanest way in PTB v20+
    app.add_handler(CommandHandler("reload_names", lambda update, context: load_professional_names_from_sheet(context)))
    app.add_handler(register_conv)
    app.add_handler(edit_conv)
    app.add_handler(delete_conv)
    app.add_handler(comment_conv)
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CallbackQueryHandler(handle_rating_callback, pattern='^rate_'))
    app.add_handler(CallbackQueryHandler(handle_initial_feedback_callback, pattern='^feedback_|^followup_')) # <--- ADD THIS LINE
    app.add_error_handler(error_handler) # <--- This line adds the new feature
    YOUR_ADMIN_TELEGRAM_ID =401674551 # <--- REPLACE WITH YOUR TELEGRAM USER ID
    app.add_handler(CommandHandler("request_feedback", request_feedback_command, filters=filters.User(401674551))) # <--- ADD THIS LINE
    app.run_polling()
if __name__ == '__main__':
    main()
