#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-reelindex:unraid}"
TEMPLATE_DIR="/boot/config/plugins/dockerMan/templates-user"
TEMPLATE_NAME="my-ReelIndex.xml"
ICON_NAME="reelindex-icon.png"
ICON_DIR="/boot/config/plugins/dockerMan/images"

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

echo "Installing the Unraid template and icon ..."
mkdir -p "$TEMPLATE_DIR" "$ICON_DIR"
install -m 0644 "$SCRIPT_DIR/$TEMPLATE_NAME" "$TEMPLATE_DIR/$TEMPLATE_NAME"
install -m 0644 "$SCRIPT_DIR/$ICON_NAME" "$ICON_DIR/$ICON_NAME"

# Prime Unraid's icon caches when those locations are available. The persistent
# source remains on the flash drive under dockerMan/images.
for cache_dir in \
    /var/lib/docker/unraid/images \
    /var/local/emhttp/plugins/dynamix.docker.manager/images; do
    if [[ -d "$cache_dir" ]]; then
        install -m 0644 "$SCRIPT_DIR/$ICON_NAME" "$cache_dir/$ICON_NAME" || true
    fi
done

echo
echo "ReelIndex image, template, and icon are ready."
echo "1. Open the Unraid Docker tab."
echo "2. Select Add Container."
echo "3. Choose ReelIndex from the Template list."
echo "4. Confirm the appdata and movie paths, then select Apply."
echo "5. Open the WebUI and add a filesystem source using /media."
