from flask import Flask, request, jsonify
from google.cloud import firestore
from datetime import datetime, timedelta
import asyncio
import google.cloud.logging
import logging
import os

# Initialize Flask app
app = Flask(__name__)

# Initialize the Google Cloud Logging client
log_client = google.cloud.logging.Client()
log_client.setup_logging()

logging.info("Starting Fraud Manager Backend...")

# Number of distinct national ids which are allowed to call from the same number
MAX_DISTINCT_NATIONAL_IDS = os.environ.get("MAX_DISTINCT_NATIONAL_IDS", 3)
# Defines a one day period
DAY_PERIOD = os.environ.get("DAY_PERIOD", 1)
# Defines a one week period
WEEK_PERIOD = os.environ.get("WEEK_PERIOD", 7)
# Defines a one month period
MONTH_PERIOD = os.environ.get("MONTH_PERIOD", 30)

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

# Get the database ID from an environment variable.
# Fall back to '(default)' if the variable is not set, for local testing or backward compatibility.
DATABASE_ID = os.environ.get("DATABASE_ID", "(default)")

# Initialize the Firestore client globally, specifying the database to use.
db = firestore.Client(database=DATABASE_ID)

logging.info(f"Successfully connected to Firestore database: '{DATABASE_ID}'")


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
        queried_national_id = request_json["sessionInfo"]["parameters"].get(
            "national_id"
        )
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
        "database_id": DATABASE_ID,
    }

    # Register the new query
    db.collection("queries").add(
        {
            "phone_number": phone_number,
            "national_id": queried_national_id,
            "query_timestamp": datetime.now(),
        }
    )

    logging.info("Query registered successfully", extra={"json_fields": log_payload})

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
        # Asynchronously update blocked numbers and register the query
        asyncio.create_task(
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
                                   (Note: This parameter is currently not directly
                                   used in the fraud logic but is kept for context
                                   and potential future use).
    """
    log_payload = {
        "phone_number": phone_number,
        "queried_national_id": queried_national_id,
        "database_id": DATABASE_ID,
    }

    # Check by day, week, and month using configured periods
    for days, period_name in [MONTH_PERIOD, WEEK_PERIOD, DAY_PERIOD]:
        limit_timestamp = datetime.now() - timedelta(days=days)

        # Query Firestore to get National IDs for a phone number in a period
        queries_ref = (
            db.collection("queries")
            .where("phone_number", "==", phone_number)
            .where("query_timestamp", ">=", limit_timestamp)
        )

        docs = queries_ref.stream()
        unique_national_ids = {doc.to_dict().get("national_id") for doc in docs}

        # If the number of unique national IDs exceeds the limit
        if len(unique_national_ids) >= MAX_DISTINCT_NATIONAL_IDS:
            logging.info("Fraud rule triggered", extra={"json_fields": log_payload})
            db.collection("blocked_phone_numbers").document(phone_number).set(
                {"reason": "Automatic block", "block_timestamp": datetime.now()}
            )
            break


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
