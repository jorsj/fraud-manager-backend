podman build . -t fraud-manager-backend

podman run \
    --volume $(echo $GOOGLE_APPLICATION_CREDENTIALS):/root/.google/credentials.json:ro \
    --env PORT=8080 \
    --env GOOGLE_APPLICATION_CREDENTIALS=/root/.google/credentials.json \
    --env FIRESTORE_DATABASE_ID=fraud-manager \
    --env GOOGLE_CLOUD_PROJECT=sandcastle-401718 \
    --publish 8080:8080 \
    fraud-manager-backend:latest