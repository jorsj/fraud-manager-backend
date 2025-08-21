#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Introduction ---
echo "--- Interactive Cloud Run Service Deployment ---"
echo "This script will guide you through deploying the Fraud Manager Backend."
echo "Please provide the following details. Press Enter to accept the default values."
echo

# --- Gather User Input ---

# 1. Get Project ID, suggesting the currently configured gcloud project as a default
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
read -p "Enter your Google Cloud Project ID [default: ${CURRENT_PROJECT}]: " PROJECT_ID
PROJECT_ID=${PROJECT_ID:-$CURRENT_PROJECT}

if [[ -z "$PROJECT_ID" ]]; then
    echo "Error: Project ID is a required field."
    exit 1
fi

# 2. Get Region
read -p "Enter the GCP Region (e.g., us-central1) [default: us-central1]: " REGION
REGION=${REGION:-us-central1}

# 3. Get Service Name
read -p "Enter a name for the Cloud Run Service [default: fraud-manager-backend]: " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-fraud-manager-backend}

# 4. Get Service Account Name
read -p "Enter a name for the Service Account [default: fraud-manager-backend-sa]: " SERVICE_ACCOUNT_NAME
SERVICE_ACCOUNT_NAME=${SERVICE_ACCOUNT_NAME:-fraud-manager-backend-sa}

# 5. Get Firestore Database ID
read -p "Enter the ID for the Firestore Database [default: fraud-manager]: " DATABASE_ID
DATABASE_ID=${DATABASE_ID:-fraud-manager}


# --- Configuration Summary and Confirmation ---
echo
echo "--- Deployment Summary ---"
echo "Project ID:            ${PROJECT_ID}"
echo "Region:                ${REGION}"
echo "Service Name:          ${SERVICE_NAME}"
echo "Service Account Name:  ${SERVICE_ACCOUNT_NAME}"
echo "Firestore Database ID: ${DATABASE_ID}"
echo "--------------------------"
echo

read -p "Is this configuration correct? (Y/n): " CONFIRM
CONFIRM=${CONFIRM:-y}
# Use a regex to check if the input starts with 'y' or 'Y'
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled by user."
    exit 1
fi

echo
echo "--- Starting Deployment for Project: ${PROJECT_ID} ---"

# --- Derived Variables ---
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# 1. Set the active project
echo "Step 1: Setting active project to ${PROJECT_ID}"
gcloud config set project ${PROJECT_ID}

# 2. Enable necessary APIs
echo "Step 2: Enabling required Google Cloud APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  logging.googleapis.com \
  iam.googleapis.com

# 3. Create Firestore Named Database if it doesn\'t exist
echo "Step 3: Checking for and creating Firestore database: ${DATABASE_ID}"
if gcloud firestore databases describe --database=${DATABASE_ID} &> /dev/null; then
    echo "Firestore database '${DATABASE_ID}' already exists."
else
    echo "Firestore database '${DATABASE_ID}' not found. Creating in region ${REGION}..."
    gcloud firestore databases create \
      --database=${DATABASE_ID} \
      --location=${REGION} \
      --type=firestore-native \
      --delete-protection
    echo "Database '${DATABASE_ID}' created successfully."
fi

# 4. Create a dedicated service account for the service
echo "Step 4: Checking for and creating service account: ${SERVICE_ACCOUNT_NAME}"
if gcloud iam service-accounts list --filter="email=${SERVICE_ACCOUNT_EMAIL}" | grep -q ${SERVICE_ACCOUNT_EMAIL}; then
  echo "Service account ${SERVICE_ACCOUNT_NAME} already exists."
else
  gcloud iam service-accounts create ${SERVICE_ACCOUNT_NAME} \
    --display-name="Service Account for ${SERVICE_NAME}"
fi

# 5. Grant the service account permissions to access Firestore
echo "Step 5: Granting Firestore User role to the service account..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/datastore.user" \
  --condition=None # Explicitly set no condition to avoid prompts

# 6. Deploy the Cloud Run Service
echo "Step 6: Deploying the Cloud Run Service '${SERVICE_NAME}'..."
gcloud run deploy ${SERVICE_NAME} \
  --source . \
  --platform managed \
  --no-cpu-throttling \
  --min-instances 1 \
  --max-instances 4 \
  --region ${REGION} \
  --no-allow-unauthenticated \
  --service-account ${SERVICE_ACCOUNT_EMAIL} \
  --set-env-vars DATABASE_ID="${DATABASE_ID}",MAX_DISTINCT_NATIONAL_IDS=3,DAY_PERIOD=1,WEEK_PERIOD=7,MONTH_PERIOD=30

# 7. Retrieve the service URL after deployment
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --platform managed --region ${REGION} --format="value(status.url)")

echo "---"
echo "✅ Deployment Successful!"
echo "---"
echo "Service Name: ${SERVICE_NAME}"
echo "Region: ${REGION}"
echo "Database ID: ${DATABASE_ID}"
echo "Service URL: ${SERVICE_URL}"
echo "---"
echo "You can now use this URL as the webhook endpoint in your Dialogflow CX agent."