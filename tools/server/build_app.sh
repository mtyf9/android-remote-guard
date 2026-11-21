#!/usr/bin/env bash
set -euo pipefail
app=$(cd "$(dirname "$0")/../../AndroidGuardApp" && pwd)
build="$app/build"
tools="${ANDROID_HOME:?Set ANDROID_HOME}/build-tools/35.0.0"
platform="$ANDROID_HOME/platforms/android-35/android.jar"
mkdir -p "$build"
work=$(mktemp -d "$build/work.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/classes"
sources=()
while IFS= read -r -d '' source; do
    sources+=("$source")
done < <(find "$app/src" -name '*.java' -print0)
javac --release 8 -encoding UTF-8 -classpath "$platform" -d "$work/classes" "${sources[@]}"
jar cf "$work/app.jar" -C "$work/classes" .
"$tools/d8" --min-api 26 --lib "$platform" --output "$work" "$work/app.jar"
"$tools/aapt" package -f -M "$app/AndroidManifest.xml" -I "$platform" -F "$work/base.apk"
(cd "$work" && "$tools/aapt" add base.apk classes.dex)
"$tools/zipalign" -f 4 "$work/base.apk" "$work/aligned.apk"
key=${ANDROID_REMOTE_GUARD_KEYSTORE:-"$build/android-remote-guard.p12"}
if [[ ! -f "$key" ]]; then
    keytool -genkeypair -keystore "$key" -storetype PKCS12 -alias androidremoteguard -keyalg RSA -keysize 3072 -validity 3650 -dname CN=AndroidRemoteGuard
fi
sign_args=(--ks "$key")
if [[ -n "${ANDROID_REMOTE_GUARD_PASS_FILE:-}" ]]; then
    sign_args+=(--ks-pass "file:$ANDROID_REMOTE_GUARD_PASS_FILE")
fi
"$tools/apksigner" sign "${sign_args[@]}" --out "$work/signed.apk" "$work/aligned.apk"
"$tools/apksigner" verify "$work/signed.apk"
mv "$work/signed.apk" "$build/AndroidRemoteGuard.apk"
echo "$build/AndroidRemoteGuard.apk"
