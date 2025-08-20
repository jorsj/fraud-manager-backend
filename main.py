import functions_framework
from flask import jsonify
from google.cloud import firestore
from datetime import datetime, timedelta
import pytz
import google.cloud.logging
import logging

# Initialize the Google Cloud Logging client
log_client = google.cloud.logging.Client()
log_client.setup_logging()

# Initialize the Firestore client globally to reuse the connection
db = firestore.Client()


@functions_framework.http
def national_id_fraud_manager(request):
    """
    Cloud Function that integrates all fraud detection logic for Dialogflow CX.
    1. Receives the phone number and National ID from Dialogflow CX.
    2. Checks if the phone number is manually blocked.
    3. Applies the "maximum 3 distinct National IDs" rules per day, week, and month.
    4. Registers the new query if it is valid.
    5. Returns a response to Dialogflow CX to continue or block the flow.
    """
    # 1. Extract parameters from the Dialogflow CX request
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
            True, "Error: Could not get caller number or National ID."
        )

    if not phone_number or not queried_national_id:
        logging.warning(
            "Missing phone_number or national_id", extra={"json_fields": request_json}
        )
        return build_dialogflow_response(
            True, "Error: Missing 'phone_number' or 'national_id' parameters."
        )

    log_payload = {
        "phone_number": phone_number,
        "queried_national_id": queried_national_id,
    }

    # 2. Manual block verification
    block_ref = db.collection("manual_blocks").document(phone_number).get()
    if block_ref.exists:
        message = "Service is unavailable for this number. Please contact support."
        logging.warning(
            "Manual block found for number", extra={"json_fields": log_payload}
        )
        return build_dialogflow_response(True, message)

    # 3. Application of automatic fraud rules
    tz = pytz.timezone("America/Santiago")  # Use the appropriate time zone
    now = datetime.now(tz)
    max_distinct_national_ids = (
        3  # This value could be loaded from the 'fraud_configuration' collection
    )

    # Check by day, week, and month
    for days, period_name in [(1, "day"), (7, "week"), (30, "month")]:
        limit_timestamp = now - timedelta(days=days)

        # Query Firestore to get National IDs for a phone number in a period
        queries_ref = (
            db.collection("queries")
            .where("phone_number", "==", phone_number)
            .where("query_timestamp", ">=", limit_timestamp)
        )

        docs = queries_ref.stream()
        unique_national_ids = {doc.to_dict().get("national_id") for doc in docs}

        # Apply the rule: if there are already 3 or more IDs and the current one is new, block.
        if (
            len(unique_national_ids) >= max_distinct_national_ids
            and queried_national_id not in unique_national_ids
        ):
            message = f"You have exceeded the limit of {max_distinct_national_ids} distinct National IDs consulted in the last {period_name}."
            log_payload["reason"] = f"Automatic block: {message}"
            logging.info("Fraud rule triggered", extra={"json_fields": log_payload})
            # Optional: Add the number to the automatic block list
            db.collection("manual_blocks").document(phone_number).set(
                {"reason": f"Automatic block: {message}", "block_timestamp": now}
            )
            return build_dialogflow_response(True, message)

    # 4. If all validations pass, register the new query
    db.collection("queries").add(
        {
            "phone_number": phone_number,
            "national_id": queried_national_id,
            "query_timestamp": now,
        }
    )
    logging.info("Query registered successfully", extra={"json_fields": log_payload})

    # 5. Return response to continue the flow
    message = "Query validated successfully."
    return build_dialogflow_response(False, message)


def build_dialogflow_response(block, message):
    """
    Builds the JSON response that Dialogflow CX expects.
    Sets a session parameter 'block' to control the flow.
    """
    response = {
        "sessionInfo": {"parameters": {"block": block}},
        "fulfillment_response": {"messages": [{"text": {"text": [message]}}]},
    }
    logging.info("Sending Dialogflow response", extra={"json_fields": response})
    return jsonify(response)
