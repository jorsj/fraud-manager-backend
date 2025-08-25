from fastapi import FastAPI, BackgroundTasks, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime, timedelta
import google.cloud.logging
import logging
import os
import re

# Import the Pydantic models from the new models file
from app.models import CheckRequest, QueryRequest

# Initialize FastAPI app
app = FastAPI()

# Initialize the Google Cloud Logging client
log_client = google.cloud.logging.Client()
log_client.setup_logging()

logging.info("Starting Fraud Manager Backend...")

# Constants for fraud detection
# Maximum number of distinct national IDs allowed per phone number within a given period
MAX_DISTINCT_NATIONAL_IDS = int(os.environ.get("MAX_DISTINCT_NATIONAL_IDS", 3))
# Defines the period in days for fraud detection (e.g., 1 for daily)
DAY_PERIOD = int(os.environ.get("DAY_PERIOD", 1))
# Defines the period in days for fraud detection (e.g., 7 for weekly)
WEEK_PERIOD = int(os.environ.get("WEEK_PERIOD", 7))
# Defines the period in days for a month (e.g., 30 for monthly)
MONTH_PERIOD = int(os.environ.get("MONTH_PERIOD", 30))


# Standardized dictionary for Dialogflow response messages.
DIALOGFLOW_MESSAGES = {
    "ERROR_EXTRACTING_PARAMS": "No se pudo obtener el número de teléfono o el rut.",
    "BLOCKED_NUMBER": "Este número de teléfono ha sido bloqueado por actividad sospechosa.",
    "ALLOWED_NUMBER": "Número de teléfono permitido.",
}

# Get the Firestore database id from an environment variable.
# Fall back to '(default)' if the variable is not set, for local testing or backward compatibility.
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")

# Initialize the Firestore client globally, specifying the database to use.
db = AsyncClient(database=FIRESTORE_DATABASE_ID)

logging.info(f"Successfully connected to Firestore database: '{FIRESTORE_DATABASE_ID}'")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Custom exception handler for Pydantic validation errors.

    This handler catches errors when the incoming request body does not match
    the Pydantic models (e.g., a required field is missing). Instead of returning
    the default 422 error, it returns a JSON response formatted for Dialogflow CX.
    """
    if request.url.path == "/queries/":
        return await request_validation_exception_handler(request, exc)
    # Log the detailed validation errors for debugging
    logging.error(
        f"Request validation failed: {exc.errors()}",
        extra={"json_fields": {"errors": exc.errors()}},
    )
    # Build and return a Dialogflow-formatted response
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=build_dialogflow_response(
            True, DIALOGFLOW_MESSAGES["ERROR_EXTRACTING_PARAMS"]
        ),
    )


@app.get("/healthcheck")
async def healthcheck():
    """
    Healthcheck endpoint to verify the API is running.
    """

    return {"status": "ok"}


@app.post("/phone-numbers:check/")
async def check_phone_number(check_request: CheckRequest):
    """
    Checks if a phone number is blocked due to suspicious activity.

    This endpoint receives a request from Dialogflow containing a phone number.
    It then checks if this phone number exists in the 'blocked_phone_numbers'
    collection in Firestore.

    Args:
        check_request (CheckRequest): The incoming request body, automatically
                                      validated by FastAPI against the Pydantic model.

    Returns:
        dict: A JSON response formatted for Dialogflow CX, indicating whether
              the phone number is blocked and a corresponding message.
    """

    # Log the validated request data
    logging.info(
        "Received check request", extra={"json_fields": check_request.model_dump()}
    )

    # Access data using dot notation; FastAPI has already validated the structure.
    phone_number = check_request.payload.telephony.caller_id
    phone_number = clean_string_regex(phone_number)

    log_payload = {
        "phone_number": phone_number,
        "database_id": FIRESTORE_DATABASE_ID,
    }

    # Check if the phone number is blocked
    block_ref = (
        await db.collection("blocked_phone_numbers").document(phone_number).get()
    )

    if block_ref.exists:
        logging.info(
            "Phone number found in block list", extra={"json_fields": log_payload}
        )
        return build_dialogflow_response(True, DIALOGFLOW_MESSAGES["BLOCKED_NUMBER"])
    else:
        logging.info(
            "Phone number not found in block list", extra={"json_fields": log_payload}
        )
        return build_dialogflow_response(False, DIALOGFLOW_MESSAGES["ALLOWED_NUMBER"])


@app.post("/queries/")
async def register_query(
    query_request: QueryRequest, background_tasks: BackgroundTasks
):
    """
    Registers a new query and triggers a background task to check for fraud.

    This endpoint receives a request from Dialogflow containing a phone number
    and a national ID. It extracts these parameters, cleans them, and then
    adds a background task to `update_blocked_phone_numbers` to perform
    fraud detection.

    Args:
        query_request (QueryRequest): The incoming request body, automatically
                                      validated by FastAPI.
        background_tasks (BackgroundTasks): FastAPI's dependency for adding
                                            background tasks.

    Returns:
        dict: A simple JSON response indicating the status of the request.
    """

    logging.info(
        "Received query request", extra={"json_fields": query_request.model_dump()}
    )

    # Access data using dot notation. No more manual parsing or try/except blocks.
    phone_number = query_request.payload.telephony.caller_id
    phone_number = clean_string_regex(phone_number)

    queried_national_id = query_request.session_info.parameters.national_id
    queried_national_id = clean_string_regex(queried_national_id)

    # Pass the extracted and cleaned parameters to the background task
    background_tasks.add_task(
        update_blocked_phone_numbers, phone_number, queried_national_id
    )
    return {"status": "ok"}


async def update_blocked_phone_numbers(phone_number: str, queried_national_id: str):
    """
    Asynchronously updates the blocked phone numbers list based on fraud rules.

    This function is called as a background task to avoid blocking the main request
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

    # Register the new query synchronously to ensure it's recorded immediately
    try:
        await db.collection("queries").add(
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
        try:
            # Run the blocking Firestore query in a thread pool
            docs_stream = (
                db.collection("queries")
                .where(filter=FieldFilter("phone_number", "==", phone_number))
                .where(filter=FieldFilter("query_timestamp", ">=", limit_timestamp))
                .stream()
            )
            unique_national_ids = {
                doc.to_dict().get("national_id") async for doc in docs_stream
            }

            logging.debug(
                f"For {phone_number} in {period_name}: found {len(unique_national_ids)} unique NIDs: {unique_national_ids}"
            )

            # If the number of unique national IDs exceeds the limit
            if len(unique_national_ids) >= MAX_DISTINCT_NATIONAL_IDS:
                logging.warning(
                    f"Fraud rule triggered for {phone_number} for {period_name} period: {len(unique_national_ids)} distinct NIDs >= {MAX_DISTINCT_NATIONAL_IDS}",
                    extra={"json_fields": log_payload},
                )
                # Run the blocking Firestore query in a thread pool
                await (
                    db.collection("blocked_phone_numbers")
                    .document(phone_number)
                    .set(
                        {
                            "reason": f"Automatic block (rule: {period_name} period)",
                            "block_timestamp": datetime.now(),
                            "agent_id": "automatic_block",
                        },
                    )
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
        dict: A JSON response suitable for Dialogflow CX.
    """

    response = {
        "sessionInfo": {"parameters": {"block": block}},
        "fulfillment_response": {"messages": [{"text": {"text": [message]}}]},
    }
    logging.info("Sending Dialogflow response", extra={"json_fields": response})
    return response


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
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
