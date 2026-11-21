$ErrorActionPreference = 'Stop'
$config = Get-Content (Join-Path $PSScriptRoot 'config.local.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$deviceIp = $config.device_ip
$target = "${deviceIp}:5555"
$scrcpy = (Get-Command scrcpy.exe).Source
Write-Host $config.device_name
$adb = Join-Path (Split-Path $scrcpy) 'adb.exe'
if (-not (Test-Path -LiteralPath $adb)) { $adb = (Get-Command adb.exe).Source }
$serial = $null
$deadline = [DateTime]::UtcNow.AddSeconds(120)
Write-Host '正在等待受控端的 IPv4 连接和 ADB 授权...'
do {
    $probe = [Net.Sockets.TcpClient]::new()
    try { $ready = $probe.ConnectAsync($deviceIp, 5555).Wait(2000) }
    catch { $ready = $false }
    finally { $probe.Dispose() }
    if ($ready) {
        & $adb connect $target | Out-Null
        $devices = & $adb devices
        if ($devices -contains "$target`tunauthorized") { throw '请在受控端上批准本机的 ADB 密钥。' }
        if ($devices -contains "$target`tdevice") {
            $serial = & $adb -s $target shell getprop ro.serialno
            if ($LASTEXITCODE -eq 0) {
                if ($serial -ne $config.device_serial) { throw '连接的设备序列号与受控端不符。' }
                break
            }
        }
    }
    Start-Sleep -Seconds 2
} while ([DateTime]::UtcNow -lt $deadline)
if ($serial -ne $config.device_serial) { throw '等待超时：受控端的网络 ADB 尚未就绪。' }
$status = & $adb -s $target shell am broadcast --receiver-foreground --user 0 -n local.devicewatch.guard/.RemoteLock --es op challenge
if (($status -join " ") -match 'data="disabled"') {
    & $scrcpy -s $target
} else {
    & python (Join-Path $PSScriptRoot "../remote_session.py") $adb $target $scrcpy -s $target
}
exit $LASTEXITCODE