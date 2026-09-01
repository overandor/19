#!/usr/bin/env bash
# Build MemoryShell.dmg — the macOS distribution of memory_shell.
#
# What ends up in the image: the memory_shell package, a launcher, a
# launchd agent that runs it as a per-user background service, and an
# installer that puts both in place. The service is what reduces RAM: a
# single resident copy of the weights that every local client maps,
# instead of one copy per app.
#
# This must run on macOS — hdiutil is the only tool that writes a real
# .dmg, and it does not exist elsewhere. The script refuses to run on
# other platforms rather than producing something that looks like a disk
# image and is not. It has not been executed on macOS by its author; run
# it with --dry-run first to see exactly what it would do.
set -euo pipefail

APP_NAME="MemoryShell"
BUNDLE_ID="dev.overandor.memoryshell"
VERSION="${MEMORY_SHELL_VERSION:-0.1.0}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"
DMG_PATH="${DIST_DIR}/${APP_NAME}-${VERSION}.dmg"
DRY_RUN=0
SIGN_IDENTITY="${MEMORY_SHELL_SIGN_IDENTITY:-}"

usage() {
    cat <<'USAGE'
usage: build_dmg.sh [--dry-run] [--sign "Developer ID Application: ..."]

  --dry-run   print the steps without creating anything
  --sign ID   codesign the bundle with this identity before packaging
              (also settable via MEMORY_SHELL_SIGN_IDENTITY)

Unsigned images are fine for local use; Gatekeeper will warn on any
machine that did not build them. Notarization is a separate step and is
deliberately not automated here — it uploads your build to Apple, which
should be a decision rather than a side effect of running a script.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --sign) SIGN_IDENTITY="${2:?--sign needs an identity}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

run() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '  would run: %s\n' "$*"
    else
        "$@"
    fi
}

if [[ "$(uname -s)" != "Darwin" && "${DRY_RUN}" != "1" ]]; then
    echo "error: .dmg images can only be built on macOS (hdiutil is required)." >&2
    echo "       Re-run with --dry-run to see the steps." >&2
    exit 1
fi

if [[ "${DRY_RUN}" != "1" ]]; then
    command -v hdiutil >/dev/null || { echo "error: hdiutil not found" >&2; exit 1; }
    command -v python3 >/dev/null || { echo "error: python3 not found" >&2; exit 1; }
fi

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/memoryshell-stage.XXXXXX")"
trap 'rm -rf "${STAGING}"' EXIT

VOLUME_ROOT="${STAGING}/${APP_NAME}"
RESOURCES="${VOLUME_ROOT}/${APP_NAME}.app/Contents/Resources"
MACOS_DIR="${VOLUME_ROOT}/${APP_NAME}.app/Contents/MacOS"

echo "Staging ${APP_NAME} ${VERSION}"
run mkdir -p "${RESOURCES}" "${MACOS_DIR}" "${DIST_DIR}"

# The package itself, without caches or test detritus.
run cp -R "${REPO_ROOT}/memory_shell" "${RESOURCES}/memory_shell"
run rm -rf "${RESOURCES}/memory_shell/__pycache__"

# proof_of_avoided_work is optional at runtime: memory_shell only imports
# it when a signer is configured. Ship it so metering works out of the box.
if [[ -d "${REPO_ROOT}/proof_of_avoided_work" ]]; then
    run cp -R "${REPO_ROOT}/proof_of_avoided_work" "${RESOURCES}/proof_of_avoided_work"
    run rm -rf "${RESOURCES}/proof_of_avoided_work/__pycache__"
fi

echo "Writing launcher"
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "  would write: ${MACOS_DIR}/memoryshell"
else
    cat > "${MACOS_DIR}/memoryshell" <<'LAUNCHER'
#!/bin/bash
# Runs memory_shell from inside the app bundle, using the system python3.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../Resources" && pwd)"
export PYTHONPATH="${HERE}${PYTHONPATH:+:${PYTHONPATH}}"
exec /usr/bin/env python3 -m memory_shell "$@"
LAUNCHER
    chmod +x "${MACOS_DIR}/memoryshell"
fi

echo "Writing Info.plist"
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "  would write: ${VOLUME_ROOT}/${APP_NAME}.app/Contents/Info.plist"
else
    cat > "${VOLUME_ROOT}/${APP_NAME}.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleExecutable</key><string>memoryshell</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>LSBackgroundOnly</key><true/>
</dict>
</plist>
PLIST
fi

echo "Copying installer and launchd agent"
run cp "${REPO_ROOT}/packaging/install.sh" "${VOLUME_ROOT}/Install.command"
run chmod +x "${VOLUME_ROOT}/Install.command"
run cp "${REPO_ROOT}/packaging/${BUNDLE_ID}.plist" "${RESOURCES}/${BUNDLE_ID}.plist"
run cp "${REPO_ROOT}/docs/MEMORY_SHELL.md" "${VOLUME_ROOT}/README.md"

if [[ -n "${SIGN_IDENTITY}" ]]; then
    echo "Signing with ${SIGN_IDENTITY}"
    run codesign --force --deep --options runtime \
        --sign "${SIGN_IDENTITY}" "${VOLUME_ROOT}/${APP_NAME}.app"
fi

echo "Building ${DMG_PATH}"
run rm -f "${DMG_PATH}"
run hdiutil create \
    -volname "${APP_NAME} ${VERSION}" \
    -srcfolder "${VOLUME_ROOT}" \
    -fs HFS+ \
    -format UDZO \
    "${DMG_PATH}"

if [[ "${DRY_RUN}" == "1" ]]; then
    echo
    echo "Dry run complete. Nothing was created."
else
    echo
    echo "Built ${DMG_PATH}"
    shasum -a 256 "${DMG_PATH}"
fi
