#Requires -Version 7.0
<#
Create only the new powered-off installation VM described by the reviewed plan.
Default invocation prints the exact operations and makes no changes.
Provisioning requires -Apply and the approval reference; downloading also requires -DownloadIso.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$DownloadIso,
    [string]$ApprovalReference,
    [string]$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$plan = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'provisioning-plan.json') -Raw | ConvertFrom-Json
if ($plan.schema_version -ne 1 -or $plan.start_vm -or $plan.install_guest_os -or $plan.host_network_changes) {
    throw 'Unexpected provisioning scope; review the script and plan together.'
}

function Get-WorkspacePath([string]$RelativePath) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $workspaceRoot $RelativePath))
    $prefix = $workspaceRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes the workspace: $RelativePath"
    }
    $cursor = $resolved
    while ($cursor.Length -ge $workspaceRoot.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse points are not allowed in provisioning paths: $cursor"
            }
        }
        if ($cursor -eq $workspaceRoot) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $resolved
}

$baseFolder = Get-WorkspacePath $plan.output_root
$vmFolder = Get-WorkspacePath (Join-Path $plan.output_root $plan.vm_name)
$disk = Get-WorkspacePath (Join-Path (Join-Path $plan.output_root $plan.vm_name) 'installation.vdi')
$iso = Get-WorkspacePath (Join-Path $plan.installer_root $plan.iso.filename)
$operations = [Collections.Generic.List[object]]::new()
$operations.Add([string[]]@('createvm', '--name', $plan.vm_name, '--uuid', $plan.vm_uuid, '--ostype', $plan.os_type, '--basefolder', $baseFolder, '--register'))
$settings = [Collections.Generic.List[string]]::new()
@('modifyvm', $plan.vm_uuid, '--memory', [string]$plan.memory_mib, '--cpus', [string]$plan.cpus,
  '--ioapic', 'on', '--rtc-use-utc', 'on', '--firmware', 'efi', '--graphicscontroller', 'vmsvga', '--vram', '16',
  '--clipboard-mode', 'disabled', '--clipboard-file-transfers', 'disabled', '--drag-and-drop', 'disabled',
  '--usb-ohci', 'off', '--usb-ehci', 'off', '--usb-xhci', 'off', '--audio-enabled', 'off', '--vrde', 'off',
  '--boot1', 'dvd', '--boot2', 'disk', '--boot3', 'none', '--boot4', 'none') | ForEach-Object { $settings.Add($_) }
1..8 | ForEach-Object { $settings.Add("--nic$_"); $settings.Add('none') }
$operations.Add($settings.ToArray())
$operations.Add([string[]]@('createmedium', 'disk', '--filename', $disk, '--size', [string]$plan.installation_disk_mib, '--format', 'VDI', '--variant', 'Standard'))
$operations.Add([string[]]@('storagectl', $plan.vm_uuid, '--name', 'SATA', '--add', 'sata', '--controller', 'IntelAhci', '--portcount', '4', '--bootable', 'on'))
$operations.Add([string[]]@('storageattach', $plan.vm_uuid, '--storagectl', 'SATA', '--port', '0', '--device', '0', '--type', 'hdd', '--medium', $disk))
$operations.Add([string[]]@('storageattach', $plan.vm_uuid, '--storagectl', 'SATA', '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', $iso))

if (-not $Apply) {
    [ordered]@{ mode = 'plan-only'; plan = $plan; executable = $VBoxManage; operations = $operations.ToArray() } | ConvertTo-Json -Depth 12
    return
}
if ([string]::IsNullOrWhiteSpace($ApprovalReference)) { throw '-ApprovalReference is required for provisioning.' }
if (-not (Test-Path -LiteralPath $VBoxManage -PathType Leaf)) { throw 'VBoxManage was not found.' }
if (Test-Path -LiteralPath $vmFolder) { throw 'The new VM directory already exists; refusing to overwrite or modify it.' }
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($workspaceRoot))
if ($drive.AvailableFreeSpace -lt 40GB) { throw 'At least 40 GiB free space is required for installer, installation disk and preparation overhead.' }

function Invoke-VBox([string[]]$Arguments) {
    $output = & $VBoxManage @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "VBoxManage failed: $($Arguments[0])`n$output" }
    return $output
}
$version = [string](Invoke-VBox -Arguments @('--version'))
if ($version.Trim() -ne $plan.vbox_version) { throw "VirtualBox version changed: $version" }
$registered = @(Invoke-VBox -Arguments @('list', 'vms'))
if ($registered | Where-Object { $_ -match [regex]::Escape($plan.vm_uuid) -or $_.StartsWith('"' + $plan.vm_name + '" ') }) {
    throw 'VM name or UUID is already registered; existing VMs must not be modified.'
}
if (-not (Test-Path -LiteralPath $iso -PathType Leaf)) {
    if (-not $DownloadIso) { throw 'Installer absent. A reviewed download requires -DownloadIso.' }
    $installerFolder = Get-WorkspacePath $plan.installer_root
    New-Item -ItemType Directory -Path $installerFolder -Force | Out-Null
    $partial = Get-WorkspacePath (Join-Path $plan.installer_root ($plan.iso.filename + '.' + [guid]::NewGuid() + '.partial'))
    Invoke-WebRequest -Uri $plan.iso.url -OutFile $partial -MaximumRedirection 0
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.iso.sha256) {
        throw "Installer checksum mismatch; no VM created. Partial download retained at $partial"
    }
    Move-Item -LiteralPath $partial -Destination $iso
}
if ((Get-FileHash -LiteralPath $iso -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.iso.sha256) {
    throw 'Installer checksum mismatch; no VM created.'
}
New-Item -ItemType Directory -Path $baseFolder -Force | Out-Null
foreach ($operation in $operations) { Invoke-VBox -Arguments $operation | Out-Null }
$configuration = @(Invoke-VBox -Arguments @('showvminfo', $plan.vm_uuid, '--machinereadable'))
if ($configuration -notcontains 'VMState="poweroff"') { throw 'Unexpected VM state after creation.' }
foreach ($number in 1..8) {
    if ($configuration -notcontains "nic$number=`"none`"") { throw "NIC $number was not disabled." }
}
$receipt = [ordered]@{
    approval = $ApprovalReference; vm_uuid = $plan.vm_uuid; vm_name = $plan.vm_name
    vbox_version = $version.Trim(); created_at_utc = [DateTime]::UtcNow.ToString('O')
    plan_sha256 = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'provisioning-plan.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    installer_sha256 = $plan.iso.sha256; installer_bytes = (Get-Item -LiteralPath $iso).Length
    state = 'powered-off-installer-attached'; runtime_qualified = $false
    configuration = $configuration
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $vmFolder 'provisioning-receipt.json') -Encoding utf8NoBOM
$receipt | ConvertTo-Json -Depth 8
