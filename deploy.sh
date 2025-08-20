#!/bin/bash
#
# deploy.sh - Firestore Database and Collection Setup Script
#
# This script performs the following actions for a specified Google Cloud project:
# 1. Checks for and creates a new Firestore database if it doesn't exist.
# 2. Creates the 'queries', 'manual_blocks', and 'fraud_configuration' collections
#    within the database by adding a sample document to each.
#

# --- Configuration ---
# IMPORTANT: Set your Google Cloud Project ID here.
PROJECT_ID="your-gcp-project-id"

# The ID for the new Firestore database.
DATABASE_ID="fraud_manager"

# The location for the new Firestore database. This cannot be changed later.
# Choose a multi-region (e.g., nam5, eur3) or a regional location (e.g., us-central1).
# See full list: https://cloud.google.com/firestore/docs/locations
LOCATION="nam5"

# --- Script Logic ---

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Define color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Pre-flight Check ---
if [ "$PROJECT_ID" == "your-gcp-project-id" ]; then
    echo -e "${YELLOW}ERROR: Please update the PROJECT_ID variable in this script before running.${NC}"
    exit 1
fi

echo -e "${BLUE}--- Firestore Deployment Script ---${NC}"
echo "Project:      ${PROJECT_ID}"
echo "Database ID:  ${DATABASE_ID}"
echo "Location:     ${LOCATION}"
echo

# Set the active project for all subsequent gcloud commands
gcloud config set project "$PROJECT_ID"

# --- 1. Create Firestore Database (if it doesn't exist) ---
echo -e "${BLUE}STEP 1: Checking for Firestore database '${DATABASE_ID}'...${NC}"

# The `describe` command fails if the database doesn't exist. We leverage this.
if gcloud firestore databases describe --database="$DATABASE_ID" &> /dev/null; then
    echo -e "${YELLOW}Database '${DATABASE_ID}' already exists. Skipping creation.${NC}"
else
    echo "Database not found. Creating Firestore database '${DATABASE_ID}' in location '${LOCATION}'..."
    gcloud firestore databases create --database="$DATABASE_ID" --location="$LOCATION" --type=firestore-native
    echo -e "${GREEN}Database '${DATABASE_ID}' created successfully.${NC}"
fi
echo

# --- 2. Create Collections by Adding Sample Documents ---
echo -e "${BLUE}STEP 2: Creating collections in database '${DATABASE_ID}'...${NC}"

# Create the 'queries' collection
echo "--> Creating 'queries' collection..."
gcloud firestore documents write "queries/SAMPLE_QUERY_001" \
  --database="$DATABASE_ID" \
  "phone_number:string=+56912345678" \
  "national_id:string=12345678-9" \
  "query_timestamp:timestamp=2023-10-27T10:00:00Z"

# Create the 'manual_blocks' collection
echo "--> Creating 'manual_blocks' collection..."
gcloud firestore documents write "manual_blocks/+56987654321" \
  --database="$DATABASE_ID" \
  "reason:string=Reported by customer for fraudulent call" \
  "block_timestamp:timestamp=2023-10-27T10:05:00Z" \
  "agent_id:string=agent-007"

# Create the 'fraud_configuration' collection
echo "--> Creating 'fraud_configuration' collection..."
gcloud firestore documents write "fraud_configuration/national_id_thresholds" \
  --database="$DATABASE_ID" \
  "unique_national_id_limit:integer=3" \
  "day_period:integer=1" \
  "week_period:integer=7" \
  "month_period:integer=30"

echo
echo -e "${GREEN}All collections created successfully.${NC}"
echo -e "${GREEN}--- Deployment Complete ---${NC}"