#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Introduction ---
echo "--- Cloud Run Service Test Script ---"
echo "This script will send a test POST request to the deployed Fraud Manager backend."
echo

# --- Configuration ---
# The URL of the deployed Cloud Run service.
# This should be the 'URL' from your deployment output.
DEFAULT_URL="https://fraud-manager-backend-452617479319.us-central1.run.app"
read -p "Enter the URL of the Cloud Run service [default: ${DEFAULT_URL}]: " URL
URL="${URL:-$DEFAULT_URL}"

# The National ID to test.
# Replace with a valid, invalid, or fraudulent ID for different test cases.
DEFAULT_NATIONAL_ID="11.111.111-4"
read -p "Enter the National ID to test [default: ${DEFAULT_NATIONAL_ID}]: " NATIONAL_ID_TO_TEST
NATIONAL_ID_TO_TEST="${NATIONAL_ID_TO_TEST:-$DEFAULT_NATIONAL_ID}"

# The phone number to test, in E.164 format.
DEFAULT_PHONE_NUMBER="+56912345671"
read -p "Enter the phone number to test [default: ${DEFAULT_PHONE_NUMBER}]: " PHONE_NUMBER_TO_TEST
PHONE_NUMBER_TO_TEST="${PHONE_NUMBER_TO_TEST:-$DEFAULT_PHONE_NUMBER}"

echo "Testing with National ID: ${NATIONAL_ID_TO_TEST}"
echo "Testing with Phone Number: ${PHONE_NUMBER_TO_TEST}"
echo "Target URL: ${URL}"
echo

# --- Authentication ---
# The service is deployed with --no-allow-unauthenticated, so we need an identity token.
# This command gets an identity token for the currently authenticated gcloud user.
# The user or service account calling the service needs the "Cloud Run Invoker" role.
echo "Getting authentication token..."
AUTH_TOKEN=$(gcloud auth print-identity-token)
if [[ -z "$AUTH_TOKEN" ]]; then
    echo "Error: Failed to get authentication token. Make sure you are logged in with 'gcloud auth login' and have the necessary permissions."
    exit 1
fi
echo "Token acquired."
echo

# --- Prepare JSON Payload ---
# This JSON mimics a request from a Dialogflow CX webhook.
# The service expects the national ID
# in the 'sessionInfo.parameters.national_id' field.
# It also expects the caller's phone number in 'payload.telephony.caller_id'.
JSON_PAYLOAD=$(cat <<EOF
{
  "fulfillmentInfo": {
    "tag": "validate_national_id"
  },
  "sessionInfo": {
    "parameters": {
      "national_id": "${NATIONAL_ID_TO_TEST}"
    }
  },
  "payload": {
    "telephony": {
      "caller_id": "${PHONE_NUMBER_TO_TEST}"
    }
  }
}
EOF
)

# --- Send Request ---
echo "Sending POST request..."
echo "--- Response ---"

curl --silent --show-error -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${JSON_PAYLOAD}" \
  "${URL}"

echo
echo "---"
echo "✅ Test complete."
