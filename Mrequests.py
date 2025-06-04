# Professional_request_bot.py

import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          ConversationHandler, ContextTypes)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from datetime import datetime

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Sheets setup
# Make sure you have your service account key file named 'service_account_key.json'
# in the same directory as your script, or provide the correct path.
# Replace 'YOUR_SERVICE_ACCOUNT_FILE.json' with the actual name of your JSON key file
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Replace 'YOUR_SERVICE_ACCOUNT_FILE.json' with the actual name of your JSON key file
    creds = ServiceAccountCredentials.from_json_keyfile_name("debo-registration-ad20d23ce5bd.json", scope)
    client = gspread.authorize(creds)
    # Replace 'requests' with the exact name of your Google Sheet
    sheet = client.open("Requests").sheet1
    logger.info("Successfully connected to Google Sheet 'Requests'")
except Exception as e:
    logger.error(f"Error connecting to Google Sheet: {e}")
    sheet = None # Handle the case where sheet connection fails

# States for conversation
(REQUEST_PROFESSIONAL_FULL_NAME, REQUEST_PROFESSIONAL_PHONE, REQUEST_PROFESSIONAL_TYPE,
 REQUEST_PROFESSIONAL_FILTER, REQUEST_PROFESSIONAL_LOCATION, REQUEST_PROFESSIONAL_ADDRESS,
 REQUEST_PROFESSIONAL_COUNT, COMPLAINT_COMMENT_TEXT) = range(8)

# Custom keyboards
main_menu_keyboard = [
    ["REQUEST PROFESSIONAL | ባለሙያ ይጠይቁ", "COMPLAINT OR COMMENT | ቅሬታ ወይም አስተያየት"]
]
main_menu_markup = ReplyKeyboardMarkup(main_menu_keyboard, resize_keyboard=True)

professional_filter_keyboard = [
    ["Near Me | ባቅራብያዬ"],
    ["Anywhere | የትም ቦታ"]
]
professional_filter_markup = ReplyKeyboardMarkup(professional_filter_keyboard, one_time_keyboard=True, resize_keyboard=True)

professional_count_keyboard = [
    ["3", "5", "10"],
    ["20", "More than 20"]
]
professional_count_markup = ReplyKeyboardMarkup(professional_count_keyboard, one_time_keyboard=True, resize_keyboard=True)

location_request_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("Share Location | አካባቢዎን ያጋሩ", request_location=True)]], # Added Amharic here too
    one_time_keyboard=True,
    resize_keyboard=True
)

# Helper function to check if text is a main menu button (checks for the full button text)
def is_main_menu_button(text):
    return text in ["REQUEST PROFESSIONAL | ባለሙያ ይጠይቁ", "COMPLAINT OR COMMENT | ቅሬታ ወይም አስተያየት"]

# Helper function to validate phone number
def is_valid_phone_number(phone_number: str) -> bool:
    """
    Validates if the input string looks like a valid phone number.
    Allows digits, spaces, hyphens, parentheses, and an optional leading plus sign.
    Requires at least 7 digits.
    """
    cleaned_number = re.sub(r'[()\s-]', '', phone_number)
    if re.fullmatch(r'^\+?\d{7,}$', cleaned_number):
        return True
    return False

# Helper function to save data to Google Sheet
def save_request_data(data):
    if sheet is None:
        logger.error("Google Sheet connection failed, cannot save data.")
        return False
    try:
        sheet.append_row(data)
        logger.info("Data successfully appended to Google Sheet.")
        return True
    except Exception as e:
        logger.error(f"Error appending data to Google Sheet: {e}")
        return False

# Handlers for REQUEST PROFESSIONAL flow
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Please choose an option from the menu:\nእንኳን በሰላም መጡ! ከዝርዝሩ ውስጥ አንዱን ይምረጡ:",
        reply_markup=main_menu_markup
    )
    return ConversationHandler.END # Start is not part of the main conversation

async def request_professional_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please provide your full name:\nእባክዎ ሙሉ ስምዎን ያስገቡ:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REQUEST_PROFESSIONAL_FULL_NAME

async def get_requester_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the input is a main menu button text
    if is_main_menu_button(update.message.text):
        await update.message.reply_text("You are already in the process of requesting a professional. Please provide your full name or /cancel.\nባለሙያ እየጠየቁ ነው። እባክዎ ሙሉ ስምዎን ያስገቡ ወይም /cancel ይጫኑ።")
        return REQUEST_PROFESSIONAL_FULL_NAME # Stay in the current state

    context.user_data['requester_full_name'] = update.message.text
    await update.message.reply_text("Please provide your phone number:\nእባክዎ ስልክ ቁጥርዎን ያስገቡ:")
    return REQUEST_PROFESSIONAL_PHONE

async def get_requester_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the input is a main menu button text
    if is_main_menu_button(update.message.text):
        await update.message.reply_text("You are currently providing your phone number. Please enter your phone number or /cancel.\nአሁን የስልክ ቁጥርዎን እያስገቡ ነው። እባክዎ ስልክ ቁጥርዎን ያስገቡ ወይም /cancel ይጫኑ።")
        return REQUEST_PROFESSIONAL_PHONE # Stay in the current state

    phone_number = update.message.text
    if not is_valid_phone_number(phone_number):
        await update.message.reply_text("Invalid phone number format. Please enter a valid phone number (e.g., +251912345678 or 0912345678):\nየስልክ ቁጥር ቅርጸት ትክክል አይደለም። እባክዎ ትክክለኛ የስልክ ቁጥር ያስገቡ (ለምሳሌ +251912345678 ወይም 0912345678):")
        return REQUEST_PROFESSIONAL_PHONE # Stay in the PHONE state

    context.user_data['requester_phone'] = phone_number
    await update.message.reply_text("What type of professional are you looking for?\nየምን አይነት ባለሙያ ይፈልጋሉ?")
    return REQUEST_PROFESSIONAL_TYPE

async def get_professional_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the input is a main menu button text
    if is_main_menu_button(update.message.text):
        await update.message.reply_text("You are currently specifying the professional type. Please enter the type of professional you are looking for or /cancel.\nአሁን የባለሙያ አይነት እየመረጡ ነው። እባክዎ የሚፈልጉትን የባለሙያ አይነት ያስገቡ ወይም /cancel ይጫኑ።")
        return REQUEST_PROFESSIONAL_TYPE # Stay in the current state

    context.user_data['professional_type'] = update.message.text
    await update.message.reply_text(
        "How should the professionals be filtered?\nባለሙያዎቹ እንዴት ተደርገው ይፈለጉ?",
        reply_markup=professional_filter_markup
    )
    return REQUEST_PROFESSIONAL_FILTER

async def get_professional_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filter_type = update.message.text

    # Check if the selected filter is 'Near Me' (English or Amharic)
    if filter_type == "Near Me | ባቅራብያዬ":
        context.user_data['professional_filter'] = "Near Me"
        await update.message.reply_text(
            "Please share your location:\nእባክዎ አካባቢዎን ያጋሩ:",
            reply_markup=location_request_keyboard
        )
        return REQUEST_PROFESSIONAL_LOCATION
    # Check if the selected filter is 'Anywhere' (English or Amharic)
    elif filter_type == "Anywhere | የትም ቦታ":
        context.user_data['professional_filter'] = "Anywhere"
        context.user_data['requester_location'] = "Anywhere" # No location needed
        await update.message.reply_text("Please enter your City/Subcity/Wereda:\nእባክዎ ከተማ / ክፍለ ከተማ / ወረዳ ያስገቡ:")
        return REQUEST_PROFESSIONAL_ADDRESS
    else:
        await update.message.reply_text(
            "Invalid option. Please choose 'Near Me | ባቅራብያዬ' or 'Anywhere | የትም ቦታ'.",
            reply_markup=professional_filter_markup
        )
        return REQUEST_PROFESSIONAL_FILTER # Stay in the filter state

async def get_requester_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        context.user_data['requester_location'] = f"{lat}, {lon}"
        await update.message.reply_text(
             "Thank you for sharing your location. Please enter your City/Subcity/Wereda:\nአካባቢዎን ስላጋሩ እናመሰግናለን። እባክዎ ከተማ / ክፍለ ከተማ / ወረዳ ያስገቡ:",
             reply_markup=ReplyKeyboardRemove() # Remove location keyboard
        )
        return REQUEST_PROFESSIONAL_ADDRESS
    else:
        # Handle cases where user sends text instead of location while in LOCATION state
        await update.message.reply_text(
             "Invalid input. Please share your location using the button.\nየተሳሳተ ግቤት። እባክዎ ቁልፉን በመጠቀም አካባቢዎን ያጋሩ።",
             reply_markup=location_request_keyboard # Show location keyboard again
        )
        return REQUEST_PROFESSIONAL_LOCATION # Stay in location state


async def get_requester_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the input is a main menu button text
    if is_main_menu_button(update.message.text):
        await update.message.reply_text("You are currently providing your address. Please enter your City/Subcity/Wereda or /cancel.\nአሁን አድራሻዎን እያስገቡ ነው። እባክዎ ከተማ / ክፍለ ከተማ / ወረዳ ያስገቡ ወይም /cancel ይጫኑ።")
        return REQUEST_PROFESSIONAL_ADDRESS # Stay in the current state

    context.user_data['requester_address'] = update.message.text
    await update.message.reply_text(
        "How many professional contacts do you need?\nስንት የባለሙያ አድራሻ ይፈልጋሉ?",
        reply_markup=professional_count_markup
    )
    return REQUEST_PROFESSIONAL_COUNT

async def get_professional_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = update.message.text
    context.user_data['professional_count'] = count

    # Get current timestamp
    request_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Save data to Google Sheet
    data_row = [
        context.user_data.get('requester_full_name', ''),
        context.user_data.get('requester_phone', ''),
        context.user_data.get('professional_type', ''),
        context.user_data.get('professional_filter', ''),
        context.user_data.get('requester_location', ''),
        context.user_data.get('requester_address', ''),
        context.user_data.get('professional_count', ''),
        "", # Placeholder for Complaint/Comment
        update.message.from_user.id, # User ID
        update.message.from_user.username if update.message.from_user.username else "N/A", # Username
        request_timestamp # Add the timestamp here
    ]

    if save_request_data(data_row):
        await update.message.reply_text(
            "Thank you! Your request has been submitted. We will get back to you shortly.\nአመሰግናለሁ! ጥያቄዎ ገብቷል. በቅርቡ ምላሽ እንሰጥዎታለን።",
            reply_markup=main_menu_markup
        )
    else:
        await update.message.reply_text(
            "Sorry, there was an error submitting your request. Please try again later.\nይቅርታ፣ ጥያቄዎን በማስገባት ላይ ስህተት ተፈጥሯል። እባክዎ ቆይተው እንደገና ይሞክሩ።",
            reply_markup=main_menu_markup
        )

    context.user_data.clear() # Clear user data after request is saved
    return ConversationHandler.END

# Handlers for COMPLAINT OR COMMENT flow
async def complaint_comment_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please enter your complaint or comment:\nእባክዎ ቅሬታዎን ወይም አስተያየትዎን ያስገቡ:",
        reply_markup=ReplyKeyboardRemove()
    )
    return COMPLAINT_COMMENT_TEXT

async def save_complaint_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the input is a main menu button text
    if is_main_menu_button(update.message.text):
        await update.message.reply_text("You are currently writing a complaint or comment. Please enter your feedback or /cancel.\nአሁን ቅሬታ ወይም አስተያየት እየጻፉ ነው። እባክዎ ግብረመልስዎን ያስገቡ ወይም /cancel ይጫኑ።")
        return COMPLAINT_COMMENT_TEXT # Stay in the current state

    comment_text = update.message.text

    # Get current timestamp for comment/complaint
    comment_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


    # Save data to Google Sheet - in this case, only the comment and user info
    data_row = [
        "", "", "", "", "", "", "", # Empty columns for request fields
        comment_text, # Complaint/Comment
        update.message.from_user.id, # User ID
        update.message.from_user.username if update.message.from_user.username else "N/A", # Username
        comment_timestamp # Add the timestamp here as well
    ]

    if save_request_data(data_row):
        await update.message.reply_text(
            "Thank you! Your complaint or comment has been submitted.\nአመሰግናለሁ! ቅሬታዎ ወይም አስተያየትዎ ገብቷል።",
            reply_markup=main_menu_markup
        )
    else:
         await update.message.reply_text(
            "Sorry, there was an error submitting your complaint or comment. Please try again later.\nይቅርታ፣ ቅሬታዎን ወይም አስተያየትዎን በማስገባት ላይ ስህተት ተፈጥሯል። እባክዎ ቆይተው እንደገና ይሞክሩ።",
            reply_markup=main_menu_markup
        )


    context.user_data.clear() # Clear user data
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Operation cancelled.\nስራው ተቋርጧል።",
        reply_markup=main_menu_markup
    )
    context.user_data.clear()
    return ConversationHandler.END

def main():
    # Replace with your new bot token
    application = Application.builder().token("7985992390:AAHjON8SnDyD2U9ZXp1la24fIgFe8_JS3Ec").build()

    # Handler for the /start command
    application.add_handler(CommandHandler("start", start))

    # Conversation handler for REQUEST PROFESSIONAL
    request_professional_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^REQUEST PROFESSIONAL | ባለሙያ ይጠይቁ$"), request_professional_entry)],
        states={
            REQUEST_PROFESSIONAL_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_requester_full_name)],
            REQUEST_PROFESSIONAL_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_requester_phone)],
            REQUEST_PROFESSIONAL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_professional_type)],
            REQUEST_PROFESSIONAL_FILTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_professional_filter)],
            REQUEST_PROFESSIONAL_LOCATION: [MessageHandler(filters.LOCATION, get_requester_location)], # Only process location updates here
            REQUEST_PROFESSIONAL_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_requester_address)],
            REQUEST_PROFESSIONAL_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_professional_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation handler for COMPLAINT OR COMMENT
    complaint_comment_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^COMPLAINT OR COMMENT | ቅሬታ ወይም አስተያየት$"), complaint_comment_entry)],
        states={
            COMPLAINT_COMMENT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_complaint_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(request_professional_conv)
    application.add_handler(complaint_comment_conv)

    # Add a handler for any other text that is not part of a conversation, to show the main menu
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))


    application.run_polling()

if __name__ == '__main__':
    main()