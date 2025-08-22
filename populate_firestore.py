import asyncio
import datetime
import argparse
import random

from google.cloud import firestore

# A list of sample phone numbers in E.164 format
SAMPLE_PHONE_NUMBERS = [
    "+56911111111",
    "+56922222222",
    "+56933333333",
    "+56944444444",
    "+56955555555",
]

# A list of sample national IDs
SAMPLE_NATIONAL_IDS = [
    "11111111-1",
    "22222222-2",
    "33333333-3",
    "44444444-4",
    "55555555-5",
    "66666666-6",
    "77777777-7",
]


async def populate_fraud_configuration(db: firestore.AsyncClient):
    """Populates the fraud_configuration collection with default values."""
    print("Populating fraud_configuration...")
    config_ref = db.collection("fraud_configuration").document("thresholds")
    await config_ref.set(
        {
            "unique_national_id_limit": 3,
            "day_period": 1,
            "week_period": 7,
            "month_period": 30,
        }
    )
    print("...fraud_configuration populated.")


async def populate_blocked_phone_numbers(db: firestore.AsyncClient):
    """Populates the blocked_phone_numbers collection with sample data."""
    print("Populating blocked_phone_numbers...")
    batch = db.batch()

    # Block the first phone number
    phone_to_block = SAMPLE_PHONE_NUMBERS[0]
    block_ref = db.collection("blocked_phone_numbers").document(phone_to_block)
    batch.set(
        block_ref,
        {
            "reason": "Reported by customer for fraudulent call",
            "block_timestamp": datetime.datetime.now(datetime.timezone.utc),
            "agent_id": "Conversational Agent",
        },
    )

    # Block another phone number
    phone_to_block_2 = SAMPLE_PHONE_NUMBERS[1]
    block_ref_2 = db.collection("blocked_phone_numbers").document(phone_to_block_2)
    batch.set(
        block_ref_2,
        {
            "reason": "Suspicious activity detected.",
            "block_timestamp": datetime.datetime.now(datetime.timezone.utc),
            "agent_id": "Conversational Agent",
        },
    )

    await batch.commit()
    print(
        f"...blocked_phone_numbers populated with {phone_to_block} and {phone_to_block_2}."
    )


async def populate_queries(db: firestore.AsyncClient, num_queries: int = 20):
    """Populates the queries collection with random sample data."""
    print(f"Populating queries with {num_queries} entries...")
    batch = db.batch()

    for i in range(num_queries):
        # Create a new document with an auto-generated ID
        query_ref = db.collection("queries").document()

        # Pick a random phone number and national ID
        phone_number = random.choice(SAMPLE_PHONE_NUMBERS)
        national_id = random.choice(SAMPLE_NATIONAL_IDS)

        # Generate a random timestamp within the last 30 days
        now = datetime.datetime.now(datetime.timezone.utc)
        days_ago = random.randint(0, 30)
        query_timestamp = now - datetime.timedelta(
            days=days_ago, hours=random.randint(0, 23)
        )

        batch.set(
            query_ref,
            {
                "phone_number": phone_number,
                "national_id": national_id,
                "query_timestamp": query_timestamp,
            },
        )

        # Commit in batches of 500 (Firestore limit)
        if (i + 1) % 500 == 0:
            await batch.commit()
            batch = db.batch()  # Start a new batch
            print(f"  ...committed {i + 1} queries")

    await batch.commit()  # Commit any remaining queries
    print("...queries populated.")


async def main():
    """Main function to connect to Firestore and populate collections."""
    parser = argparse.ArgumentParser(
        description="Populate a Firestore database with sample data for the Fraud Manager."
    )
    parser.add_argument(
        "--database-id",
        default="fraud-manager",
        help="The ID of the Firestore database to populate. Defaults to 'fraud-manager'.",
    )
    args = parser.parse_args()

    try:
        print(f"Attempting to connect to database: '{args.database_id}'...")
        db = firestore.AsyncClient(database=args.database_id)
        await populate_fraud_configuration(db)
        await populate_blocked_phone_numbers(db)
        await populate_queries(db, num_queries=50)
        print(f"\nFirestore database '{args.database_id}' populated successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")
        print(
            "Please ensure your GCP project is configured correctly, you have authenticated,\n"
            f"and the database '{args.database_id}' exists in your project."
        )


if __name__ == "__main__":
    asyncio.run(main())
