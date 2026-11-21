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
$key = $env:DEVICEWATCH_KEYSTORE
if (!$key) { $key = Join-Path $build 'devicewatch.p12' }
if (!(Test-Path -LiteralPath $key)) {
    keytool -genkeypair -keystore $key -storetype PKCS12 -alias devicewatch -keyalg RSA -keysize 3072 -validity 3650 -dname 'CN=DeviceWatch'
}
$signArgs = @('sign','--ks',$key)
if ($env:DEVICEWATCH_PASS_FILE) { $signArgs += @('--ks-pass',("file:" + $env:DEVICEWATCH_PASS_FILE)) }
& "$tools/apksigner.bat" @signArgs --out "$build/AndroidRemoteGuard.apk" "$work/aligned.apk"
& "$tools/apksigner.bat" verify "$build/AndroidRemoteGuard.apk"
Write-Output "$build/AndroidRemoteGuard.apk"
