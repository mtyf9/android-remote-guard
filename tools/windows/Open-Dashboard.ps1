$ErrorActionPreference = 'Stop'
$config = Get-Content (Join-Path $PSScriptRoot 'config.local.json') -Raw | ConvertFrom-Json
$sshArgs = @('-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-L','127.0.0.1:18762:127.0.0.1:18762')
if ($config.ssh_identity) { $sshArgs += @('-i',('"' + $config.ssh_identity + '"')) }
$sshArgs += $config.ssh_host
$tunnel = Start-Process ssh -ArgumentList $sshArgs -WindowStyle Hidden -PassThru
try {
    Start-Sleep -Seconds 2
    if ($tunnel.HasExited) { throw '无法建立到服务端的 SSH 隧道，请检查局域网连接和本机 18762 端口。' }
    Start-Process 'http://127.0.0.1:18762/'
    Read-Host '管理页使用完毕后按回车关闭 SSH 隧道'
} finally {
    if (!$tunnel.HasExited) { $tunnel.Kill() }
}
