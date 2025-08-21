from flask import Flask, request, jsonify
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime, timedelta
import asyncio
import google.cloud.logging
import logging
import os
import re
import threading

# Initialize Flask app
app = Flask(__name__)
app.json.ensure_ascii = False
app.json.mimetype = "application/json; charset=utf-8"


# Initialize the Google Cloud Logging client
log_client = google.cloud.logging.Client()
log_client.setup_logging()

logging.info("Starting Fraud Manager Backend...")

# Number of distinct national ids which are allowed to call from the same number
MAX_DISTINCT_NATIONAL_IDS = int(os.environ.get("MAX_DISTINCT_NATIONAL_IDS", 3))
# Defines a one day period
DAY_PERIOD = int(os.environ.get("DAY_PERIOD", 1))
# Defines a one week period
WEEK_PERIOD = int(os.environ.get("WEEK_PERIOD", 7))
# Defines a one month period
MONTH_PERIOD = int(os.environ.get("MONTH_PERIOD", 30))

logging.info(f"MAX_DISTINCT_NATIONAL_IDS: {MAX_DISTINCT_NATIONAL_IDS}")
logging.info(f"DAY_PERIOD: {DAY_PERIOD}")
logging.info(f"WEEK_PERIOD: {WEEK_PERIOD}")
logging.info(f"MONTH_PERIOD: {MONTH_PERIOD}")

# Standardized dictionary for Dialogflow response messages.
DIALOGFLOW_MESSAGES = {
    "ERROR_EXTRACTING_PARAMS": "No se pudo obtener el número de teléfono o el rut.",
    "BLOCKED_NUMBER": "Este número de teléfono ha sido bloqueado por actividad sospechosa. Por favor, contacte con soporte.",
    "ALLOWED_NUMBER": "Número de teléfono permitido.",
}

# Get the Firestore database id from an environment variable.
# Fall back to '(default)' if the variable is not set, for local testing or backward compatibility.
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")

# Initialize the Firestore client globally, specifying the database to use.
db = firestore.Client(database=FIRESTORE_DATABASE_ID)

logging.info(f"Successfully connected to Firestore database: '{FIRESTORE_DATABASE_ID}'")

# --- Async Loop Management ---
# Create a new event loop for background tasks
background_loop = asyncio.new_event_loop()
background_thread = None


def run_background_loop(loop):
    """Runs a dedicated asyncio event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def start_background_loop():
    """Starts the background event loop thread."""
    global background_thread
    if background_thread is None or not background_thread.is_alive():
        background_thread = threading.Thread(
            target=run_background_loop, args=(background_loop,), daemon=True
        )
        background_thread.start()
        logging.info("Background asyncio loop started in a new thread.")


# Start the background loop when the application starts
# This will ensure the loop is ready before requests come in.
start_background_loop()


# Function to submit a coroutine to the background loop
def submit_to_background_loop(coro):
    """Submits a coroutine to the background asyncio event loop."""
    asyncio.run_coroutine_threadsafe(coro, background_loop)
    logging.debug(f"Coroutine {coro.__name__} submitted to background loop.")


# --- End Async Loop Management ---


@app.route("/", methods=["POST"])
def check_phone_number():
    """
    Checks if a phone number is blocked due to suspicious activity.

    This function is triggered by an HTTP request and expects a JSON payload
    containing the 'caller_id' (phone number) under 'payload.telephony'.
    It queries the 'blocked_phone_numbers' collection in Firestore to determine if
    the provided phone number is present.

    Args:
        request (flask.Request): The HTTP request object. Expected to contain
                                 JSON with 'payload.telephony.caller_id'.

    Returns:
        flask.Response: A JSON response indicating whether the phone number
                        is blocked and a corresponding message. The response
                        is formatted for Dialogflow CX, setting a 'block'
                        session parameter.
    """
    request_json = request.get_json(silent=True)
    logging.info("Received request", extra={"json_fields": request_json})

    try:
        # The caller_id is obtained from the telephony payload
        phone_number = request_json["payload"]["telephony"]["caller_id"]
        phone_number = clean_string_regex(phone_number)

        queried_national_id = request_json["sessionInfo"]["parameters"]["national_id"]
        queried_national_id = clean_string_regex(queried_national_id)
    except (KeyError, TypeError) as e:
        logging.error(
            f"Error extracting parameters: {e}", extra={"json_fields": request_json}
        )
        return build_dialogflow_response(
            True, DIALOGFLOW_MESSAGES["ERROR_EXTRACTING_PARAMS"]
        )

    if not phone_number or not queried_national_id:
        logging.error(
            "Missing phone_number or national_id", extra={"json_fields": request_json}
        )
        return build_dialogflow_response(
            True, DIALOGFLOW_MESSAGES["ERROR_EXTRACTING_PARAMS"]
        )

    log_payload = {
        "phone_number": phone_number,
        "queried_national_id": queried_national_id,
        "database_id": FIRESTORE_DATABASE_ID,
    }

    # Register the new query synchronously to ensure it's recorded immediately
    try:
        db.collection("queries").add(
            {
                "phone_number": phone_number,
                "national_id": queried_national_id,
                "query_timestamp": datetime.now(),
            }
        )
        logging.info(
            "Query registered successfully", extra={"json_fields": log_payload}
        )
    except Exception as e:
        logging.error(
            f"Error registering query: {e}", extra={"json_fields": log_payload}
        )
        # Decide how to handle this error - for now, proceed but log heavily

    # Check if the phone number is blocked
    block_ref = db.collection("blocked_phone_numbers").document(phone_number).get()

    if block_ref.exists:
        logging.info(
            "Phone number found in block list", extra={"json_fields": log_payload}
        )
        return build_dialogflow_response(True, DIALOGFLOW_MESSAGES["BLOCKED_NUMBER"])
    else:
        logging.info(
            "Phone number not found in block list", extra={"json_fields": log_payload}
        )
        # Asynchronously update blocked numbers using the background loop
        submit_to_background_loop(
            update_blocked_phone_numbers(phone_number, queried_national_id)
        )
        return build_dialogflow_response(False, DIALOGFLOW_MESSAGES["ALLOWED_NUMBER"])


async def update_blocked_phone_numbers(phone_number: str, queried_national_id: str):
    """
    Asynchronously updates the blocked phone numbers list based on fraud rules.

    This function is called asynchronously to avoid blocking the main request
    thread. It checks if the given `phone_number` has been associated with
    too many distinct `national_id`s within defined time periods (day, week, month).
    If a fraud rule is triggered, the phone number is added to the
    `blocked_phone_numbers` collection in Firestore.

    Args:
        phone_number (str): The phone number to check and potentially block.
        queried_national_id (str): The national ID associated with the current query.
    """
    log_payload = {
        "phone_number": phone_number,
        "queried_national_id": queried_national_id,
        "database_id": FIRESTORE_DATABASE_ID,
    }

    # Check by day, week, and month using configured periods
    # Iterate from longest period to shortest, as a block on longer period implies block
    for days, period_name in [
        (MONTH_PERIOD, "month"),
        (WEEK_PERIOD, "week"),
        (DAY_PERIOD, "day"),
    ]:
        limit_timestamp = datetime.now() - timedelta(days=days)

        logging.debug(
            f"Checking fraud rule for {phone_number} for {period_name} period (>= {limit_timestamp})"
        )

        # Query Firestore to get National IDs for a phone number in a period
        # Use await with stream() to make it truly async if Firestore client supports it.
        # However, the current google-cloud-firestore client methods are not inherently async.
        # This will still block the background event loop, but not the main Flask request.
        try:
            queries_ref = (
                db.collection("queries")
                .where(filter=FieldFilter("phone_number", "==", phone_number))
                .where(filter=FieldFilter("query_timestamp", ">=", limit_timestamp))
            )

            docs = queries_ref.stream()  # This is a synchronous blocking call
            unique_national_ids = {doc.to_dict().get("national_id") for doc in docs}

            logging.debug(
                f"For {phone_number} in {period_name}: found {len(unique_national_ids)} unique NIDs: {unique_national_ids}"
            )

            # If the number of unique national IDs exceeds the limit
            if len(unique_national_ids) >= MAX_DISTINCT_NATIONAL_IDS:
                logging.warning(
                    f"Fraud rule triggered for {phone_number} for {period_name} period: {len(unique_national_ids)} distinct NIDs >= {MAX_DISTINCT_NATIONAL_IDS}",
                    extra={"json_fields": log_payload},
                )
                db.collection("blocked_phone_numbers").document(phone_number).set(
                    {
                        "reason": f"Automatic block (rule: {period_name} period)",
                        "block_timestamp": datetime.now(),
                        "agent_id": "automatic_block",
                    }
                )
                logging.info(
                    f"Phone number {phone_number} blocked.",
                    extra={"json_fields": log_payload},
                )
                break  # Once blocked, no need to check shorter periods
        except Exception as e:
            logging.error(
                f"Error checking fraud rule for {phone_number} in {period_name}: {e}",
                extra={"json_fields": log_payload},
            )


def build_dialogflow_response(block, message):
    """
    Builds the JSON response that Dialogflow CX expects.
    Sets a session parameter 'block' to control the flow.

    Args:
        block (bool): True if the transaction should be blocked, False otherwise.
        message (str): The message to be displayed to the user.

    Returns:
        flask.Response: A JSON response suitable for Dialogflow CX.
    """

    response = {
        "sessionInfo": {"parameters": {"block": block}},
        "fulfillment_response": {"messages": [{"text": {"text": [message]}}]},
    }
    logging.info("Sending Dialogflow response", extra={"json_fields": response})
    return jsonify(response)


def clean_string_regex(input_string: str) -> str:
    """
    Removes all non-alphanumeric characters from a string using regex.

    Args:
        input_string: The string to clean.

    Returns:
        A new string containing only alphanumeric characters.
    """
    return re.sub(r"[^a-zA-Z0-9]", "", input_string)


if __name__ == "__main__":
    # Ensure the background loop is running when running directly
    start_background_loop()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
