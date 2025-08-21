# Fraud Manager

A simple fraud detection service that identifies and blocks phone numbers based on query patterns. It's designed to be deployed as a Cloud Run service and uses Firestore as its database.

## Features

*   Blocks phone numbers that are associated with too many national IDs within a configurable time period.
*   Asynchronous fraud rule checking to ensure fast API responses.
*   RESTful API for integration with other services (like Dialogflow).
*   Configurable fraud detection rules via environment variables.

## Architecture

*   **Application:** A Python Flask application.
*   **Deployment:** Designed to be containerized and deployed on Google Cloud Run.
*   **Database:** Uses Google Firestore to store queries and a list of blocked phone numbers.

## Setup and Deployment

1.  **Prerequisites:**
    *   Google Cloud SDK installed and configured.
    *   A Google Cloud project with the Cloud Run and Firestore APIs enabled.
    *   Docker installed.

2.  **Configuration:**
    Set the following environment variables:
    *   `FIRESTORE_DATABASE_ID`: The ID of your Firestore database.
    *   `MAX_DISTINCT_NATIONAL_IDS`: (Optional) The maximum number of distinct national IDs that can query from the same phone number before it's blocked. Defaults to `3`.
    *   `DAY_PERIOD`: (Optional) The number of days for the "day" period check. Defaults to `1`.
    *   `WEEK_PERIOD`: (Optional) The number of days for the "week" period check. Defaults to `7`.
    *   `MONTH_PERIOD`: (Optional) The number of days for the "month" period check. Defaults to `30`.

3.  **Deployment:**
    Use the `deploy.sh` script to build and deploy the service to Cloud Run.
    ```bash
    ./deploy.sh
    ```

## API Usage

The service exposes a single endpoint: `/`.

*   **Method:** `POST`
*   **Payload:** A JSON object with the following structure (emulating a Dialogflow webhook request):
    ```json
    {
      "payload": {
        "telephony": {
          "caller_id": "+1234567890"
        }
      },
      "sessionInfo": {
        "parameters": {
          "national_id": "123456789"
        }
      }
    }
    ```
*   **Success Response:**
    ```json
    {
      "sessionInfo": {
        "parameters": {
          "block": false
        }
      },
      "fulfillmentResponse": {
        "messages": [
          {
            "text": {
              "text": [
                "The phone number is allowed."
              ]
            }
          }
        ]
      }
    }
    ```
*   **Blocked Response:**
    ```json
    {
      "sessionInfo": {
        "parameters": {
          "block": true
        }
      },
      "fulfillmentResponse": {
        "messages": [
          {
            "text": {
              "text": [
                "The phone number is blocked."
              ]
            }
          }
        ]
      }
    }
    ```
