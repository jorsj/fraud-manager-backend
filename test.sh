#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Introduction ---
echo "--- Cloud Run Service Test Script ---"
echo "This script will send test POST requests to both endpoints of the Fraud Manager backend."
echo ""

# --- Configuration ---
# The URL of the deployed Cloud Run service.
DEFAULT_URL="localhost:8080"
read -p "Enter the URL of the Cloud Run service [default: ${DEFAULT_URL}]: " URL
URL="${URL:-$DEFAULT_URL}"

# The National ID to test for the /queries/ endpoint.
DEFAULT_NATIONAL_ID="11.111.111-3"
read -p "Enter the National ID to test [default: ${DEFAULT_NATIONAL_ID}]: " NATIONAL_ID_TO_TEST
NATIONAL_ID_TO_TEST="${NATIONAL_ID_TO_TEST:-$DEFAULT_NATIONAL_ID}"

# The phone number to test for both endpoints.
DEFAULT_PHONE_NUMBER="+56995371039"
read -p "Enter the phone number to test [default: ${DEFAULT_PHONE_NUMBER}]: " PHONE_NUMBER_TO_TEST
PHONE_NUMBER_TO_TEST="${PHONE_NUMBER_TO_TEST:-$DEFAULT_PHONE_NUMBER}"

echo "Target Service URL: ${URL}"
echo "Using National ID: ${NATIONAL_ID_TO_TEST}"
echo "Using Phone Number: ${PHONE_NUMBER_TO_TEST}"
echo ""

# --- Authentication ---
# The service is deployed with --no-allow-unauthenticated, so we need an identity token.
echo "Getting authentication token..."
AUTH_TOKEN=$(gcloud auth print-identity-token)
if [[ -z "$AUTH_TOKEN" ]]; then
    echo "Error: Failed to get authentication token. Make sure you are logged in with 'gcloud auth login' and have the necessary permissions."
    exit 1
fi
echo "Token acquired."
echo ""

# --- Test 1: /phone-numbers:check/ ---
echo "--- Testing endpoint: /phone-numbers:check/ ---"

CHECK_PAYLOAD=$(cat <<EOF
{
  "payload": {
    "telephony": {
      "caller_id": "${PHONE_NUMBER_TO_TEST}"
    }
  }
}
EOF
)

CHECK_URL="${URL}/phone-numbers:check/"

echo "Sending POST request to ${CHECK_URL}"
echo "--- Response --- >"

curl --silent --show-error -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${CHECK_PAYLOAD}" \
  "${CHECK_URL}"

echo ""
echo "< --- End of Response ---"
echo "✅ Endpoint test complete."
echo ""

# --- Test 2: /queries/ ---
echo "--- Testing endpoint: /queries/ ---"

QUERY_PAYLOAD=$(cat <<EOF
{
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

QUERY_URL="${URL}/queries/"

echo "Sending POST request to ${QUERY_URL}"
echo "--- Response --- >"

curl --silent --show-error -X POST \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${QUERY_PAYLOAD}" \
  "${QUERY_URL}"

echo ""
echo "< --- End of Response ---"
echo "✅ Endpoint test complete."
echo ""

# --- Final ---
echo "✅ All tests complete."
