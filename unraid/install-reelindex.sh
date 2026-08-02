#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-reelindex:unraid}"
TEMPLATE_DIR="/boot/config/plugins/dockerMan/templates-user"
TEMPLATE_NAME="my-ReelIndex.xml"

if [[ ! -d /boot/config/plugins/dockerMan ]]; then
    echo "This installer is intended to run from an Unraid terminal." >&2
    exit 1
fi

command -v docker >/dev/null 2>&1 || {
    echo "Docker is not available. Start the Unraid Docker service and retry." >&2
    exit 1
}

echo "Building $IMAGE_NAME from $PROJECT_DIR ..."
docker build --pull -f "$PROJECT_DIR/Dockerfile.unraid" -t "$IMAGE_NAME" "$PROJECT_DIR"

echo "Installing the Unraid template ..."
mkdir -p "$TEMPLATE_DIR"
install -m 0644 "$SCRIPT_DIR/$TEMPLATE_NAME" "$TEMPLATE_DIR/$TEMPLATE_NAME"

echo
echo "ReelIndex image and template are ready."
echo "1. Open the Unraid Docker tab."
echo "2. Select Add Container."
echo "3. Choose ReelIndex from the Template list."
echo "4. Confirm the appdata and movie paths, then select Apply."
echo "5. Open the WebUI and add a filesystem source using /media."
