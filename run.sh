#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
IMAGE_NAME="fraud-manager-backend"
IMAGE_TAG="latest"
CONTAINER_NAME="fraud-manager-backend-container"
CONTAINER_PORT="8080"

# --- Interactive Configuration ---
echo "Please confirm the configuration (press Enter to accept defaults):"

# Get default project from gcloud if available
GCLOUD_PROJECT_DEFAULT=$(gcloud config get-value project 2>/dev/null || echo "sandcastle-401718")

read -p "Google Cloud Project [${GCLOUD_PROJECT_DEFAULT}]: " GOOGLE_CLOUD_PROJECT_INPUT
GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT_INPUT:-$GCLOUD_PROJECT_DEFAULT}

read -p "Firestore Database ID [fraud-manager]: " FIRESTORE_DATABASE_ID_INPUT
FIRESTORE_DATABASE_ID=${FIRESTORE_DATABASE_ID_INPUT:-"fraud-manager"}

read -p "Host Port [8080]: " HOST_PORT_INPUT
HOST_PORT=${HOST_PORT_INPUT:-"8080"}


# --- Pre-flight checks ---
if [[ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    echo "Error: GOOGLE_APPLICATION_CREDENTIALS environment variable is not set."
    echo "Please set it to the path of your Google Cloud service account key file."
    exit 1
fi

if [[ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    echo "Error: The file specified by GOOGLE_APPLICATION_CREDENTIALS does not exist: $GOOGLE_APPLICATION_CREDENTIALS"
    exit 1
fi

# --- Build ---
echo "Building the Docker image..."
podman build . -t "${IMAGE_NAME}:${IMAGE_TAG}"

# --- Run ---
echo "Stopping and removing existing container if it exists..."
podman stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
podman rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "Running the container..."
podman run \
    --name "${CONTAINER_NAME}" \
    --rm \
    --detach \
    --volume "$(echo $GOOGLE_APPLICATION_CREDENTIALS):/root/.google/credentials.json:ro" \
    --env PORT="${CONTAINER_PORT}" \
    --env GOOGLE_APPLICATION_CREDENTIALS=/root/.google/credentials.json \
    --env FIRESTORE_DATABASE_ID="${FIRESTORE_DATABASE_ID}" \
    --env GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
    --publish "${HOST_PORT}:${CONTAINER_PORT}" \
    "${IMAGE_NAME}:${IMAGE_TAG}"

echo "Container '${CONTAINER_NAME}' is running on port ${HOST_PORT}."
echo "To see logs, run: podman logs -f ${CONTAINER_NAME}"
echo "To stop the container, run: podman stop ${CONTAINER_NAME}"