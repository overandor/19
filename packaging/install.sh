#!/usr/bin/env bash
# Installs MemoryShell from the mounted disk image.
#
# Copies the app to /Applications and loads the launchd agent for the
# current user. Deliberately a LaunchAgent rather than a system daemon:
# the cache stays inside one user's session, because sharing cached state
# between accounts is the cross-tenant leak this project exists to avoid.
set -euo pipefail

APP_NAME="MemoryShell"
BUNDLE_ID="dev.overandor.memoryshell"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_DEST="${AGENTS_DIR}/${BUNDLE_ID}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: this installer is for macOS." >&2
    exit 1
fi

echo "Installing ${APP_NAME} to /Applications"
rm -rf "/Applications/${APP_NAME}.app"
cp -R "${HERE}/${APP_NAME}.app" "/Applications/${APP_NAME}.app"

echo "Installing launchd agent"
mkdir -p "${AGENTS_DIR}"
if launchctl list | grep -q "${BUNDLE_ID}"; then
    launchctl unload "${PLIST_DEST}" 2>/dev/null || true
fi
cp "/Applications/${APP_NAME}.app/Contents/Resources/${BUNDLE_ID}.plist" "${PLIST_DEST}"
launchctl load "${PLIST_DEST}"

echo
echo "Installed. Check the memory it is saving with:"
echo "  /Applications/${APP_NAME}.app/Contents/MacOS/memoryshell measure"
echo
echo "To remove:"
echo "  launchctl unload ${PLIST_DEST}"
echo "  rm -rf /Applications/${APP_NAME}.app ${PLIST_DEST}"
