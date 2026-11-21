$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$build = Join-Path $PSScriptRoot 'build'
$work = Join-Path $build ([Guid]::NewGuid().ToString('N'))
New-Item -Type Directory "$work/classes" | Out-Null
$tools = Join-Path $env:ANDROID_HOME 'build-tools/35.0.0'
$platform = Join-Path $env:ANDROID_HOME 'platforms/android-35/android.jar'
$sources = Get-ChildItem "$PSScriptRoot/src" -Recurse -Filter *.java
javac --release 8 -encoding UTF-8 -classpath $platform -d "$work/classes" $sources.FullName
jar cf "$work/app.jar" -C "$work/classes" .
& "$tools/d8.bat" --min-api 26 --lib $platform --output $work "$work/app.jar"
& "$tools/aapt.exe" package -f -M "$PSScriptRoot/AndroidManifest.xml" -I $platform -F "$work/base.apk"
Push-Location $work
try { & "$tools/aapt.exe" add base.apk classes.dex } finally { Pop-Location }
& "$tools/zipalign.exe" -f 4 "$work/base.apk" "$work/aligned.apk"
$key = $env:ANDROID_REMOTE_GUARD_KEYSTORE
if (!$key) { $key = $env:DEVICEWATCH_KEYSTORE }
$oldKey = Join-Path $PSScriptRoot '../android/build/devicewatch.p12'
if (!$key -and (Test-Path -LiteralPath $oldKey)) { $key = $oldKey }
if (!$key) { $key = Join-Path $build 'android-remote-guard.p12' }
if (!(Test-Path -LiteralPath $key)) {
    keytool -genkeypair -keystore $key -storetype PKCS12 -alias androidremoteguard -keyalg RSA -keysize 3072 -validity 3650 -dname 'CN=AndroidRemoteGuard'
}
$signArgs = @('sign','--ks',$key)
$passFile = $env:ANDROID_REMOTE_GUARD_PASS_FILE
if (!$passFile) { $passFile = $env:DEVICEWATCH_PASS_FILE }
if ($passFile) { $signArgs += @('--ks-pass',("file:" + $passFile)) }
& "$tools/apksigner.bat" @signArgs --out "$build/AndroidRemoteGuard.apk" "$work/aligned.apk"
& "$tools/apksigner.bat" verify "$build/AndroidRemoteGuard.apk"
Write-Output "$build/AndroidRemoteGuard.apk"
