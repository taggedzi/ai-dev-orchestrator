#Requires -Version 7.0
<# Create only a new stopped guard VM. The default preview makes no native calls.
Apply requires a separately approved plan digest. Failures preserve partial state.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$ApprovalReference,
    [string]$PlanSha256,
    [string]$VBoxManage = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$planFile = Join-Path $PSScriptRoot 'guard-provisioning-plan.json'
$plan = Get-Content -LiteralPath $planFile -Raw | ConvertFrom-Json
$actualPlanHash = (Get-FileHash -LiteralPath $planFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($plan.schema_version -ne 1 -or $plan.stage -ne 'create-powered-off-guard-from-full-disk-clone' -or
    $plan.start_vm -or $plan.install_packages -or $plan.host_network_changes -or $plan.modify_source_vm -or
    $plan.qualifies_isolation -or $plan.network -ne 'all eight adapters disabled' -or
    $plan.vm_uuid -eq $plan.source_vm_uuid -or $plan.cpus -ne 1 -or $plan.memory_mib -ne 1024) {
    throw 'Unexpected guard provisioning scope.'
}

function Get-WorkspacePath([string]$RelativePath) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $workspaceRoot $RelativePath))
    $prefix = $workspaceRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes workspace.' }
    $cursor = $resolved
    while ($cursor.Length -ge $workspaceRoot.Length) {
        if ((Test-Path -LiteralPath $cursor) -and
            (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'Reparse points are forbidden in provisioning paths.'
        }
        if ($cursor -eq $workspaceRoot) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $resolved
}

$baseFolder = Get-WorkspacePath $plan.output_root
$vmFolder = Get-WorkspacePath (Join-Path $plan.output_root $plan.vm_name)
$sourceDisk = Get-WorkspacePath $plan.source_disk
$targetDisk = Get-WorkspacePath (Join-Path (Join-Path $plan.output_root $plan.vm_name) $plan.disk_filename)
$receiptFolder = Get-WorkspacePath $plan.receipt_root
$operations = [Collections.Generic.List[object]]::new()
$operations.Add([string[]]@('createvm', '--name', $plan.vm_name, '--uuid', $plan.vm_uuid,
    '--ostype', $plan.os_type, '--basefolder', $baseFolder, '--register'))
$settings = [Collections.Generic.List[string]]::new()
@('modifyvm', $plan.vm_uuid, '--memory', [string]$plan.memory_mib, '--cpus', [string]$plan.cpus,
    '--ioapic', 'on', '--acpi', 'on', '--x86-x2apic', $plan.x2apic, '--apic', $plan.apic,
    '--nested-hw-virt', 'off', '--rtc-use-utc', 'on', '--firmware', $plan.firmware,
    '--graphicscontroller', 'vmsvga', '--vram', '16', '--accelerate-3d', 'off',
    '--clipboard-mode', 'disabled', '--clipboard-file-transfers', 'disabled', '--drag-and-drop', 'disabled',
    '--usb-ohci', 'off', '--usb-ehci', 'off', '--usb-xhci', 'off', '--audio-enabled', 'off', '--vrde', 'off',
    '--boot1', 'disk', '--boot2', 'none', '--boot3', 'none', '--boot4', 'none') | ForEach-Object { $settings.Add($_) }
1..8 | ForEach-Object { $settings.Add("--nic$_"); $settings.Add('none') }
1..4 | ForEach-Object { $settings.Add("--uart$_"); $settings.Add('off') }
1..2 | ForEach-Object { $settings.Add("--lpt$_"); $settings.Add('off') }
$operations.Add($settings.ToArray())
$operations.Add([string[]]@('clonemedium', $sourceDisk, $targetDisk, 'disk', '--format', 'VDI', '--variant', 'Standard'))
$operations.Add([string[]]@('storagectl', $plan.vm_uuid, '--name', 'SATA', '--add', 'sata',
    '--controller', 'IntelAhci', '--portcount', '1', '--bootable', 'on'))
$operations.Add([string[]]@('storageattach', $plan.vm_uuid, '--storagectl', 'SATA', '--port', '0',
    '--device', '0', '--type', 'hdd', '--medium', $targetDisk))

if (-not $Apply) {
    [ordered]@{ mode = 'plan-only'; plan_sha256 = $actualPlanHash; plan = $plan;
        executable = $VBoxManage; operations = $operations.ToArray() } | ConvertTo-Json -Depth 12
    return
}
if ([string]::IsNullOrWhiteSpace($ApprovalReference)) { throw '-ApprovalReference is required.' }
if ($PlanSha256 -cne $actualPlanHash) { throw 'An exact reviewed -PlanSha256 is required.' }
if (Test-Path -LiteralPath $vmFolder) { throw 'Guard VM directory exists; preserve and reconcile partial state.' }
if (Test-Path -LiteralPath $receiptFolder) { throw 'Provisioning receipt directory exists; do not replay.' }
if (-not (Test-Path -LiteralPath $sourceDisk -PathType Leaf)) { throw 'Pinned source disk is absent.' }
if (-not (Test-Path -LiteralPath $VBoxManage -PathType Leaf)) { throw 'VBoxManage is absent.' }
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($workspaceRoot))
if ($drive.AvailableFreeSpace -lt 40GB) { throw 'At least 40 GiB free space is required.' }

function Invoke-VBox([string[]]$Arguments) {
    $output = @(& $VBoxManage @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $receiptFolder) {
        $entry = [ordered]@{ utc = [DateTime]::UtcNow.ToString('O'); args = $Arguments; exit = $exitCode; output = $output }
        $entry | ConvertTo-Json -Depth 6 -Compress | Add-Content -LiteralPath (Join-Path $receiptFolder 'commands.jsonl') -Encoding utf8NoBOM
    }
    if ($exitCode -ne 0) { throw "VBoxManage failed: $($Arguments[0]); preserve partial state and reconcile." }
    return $output
}
function Assert-SourceStopped {
    $configuration = @(Invoke-VBox -Arguments @('showvminfo', $plan.source_vm_uuid, '--machinereadable'))
    if ($configuration -notcontains 'VMState="poweroff"' -or
        $configuration -notcontains ('"SATA-ImageUUID-0-0"="' + $plan.source_disk_uuid + '"')) {
        throw 'Source identity or stopped state changed.'
    }
    foreach ($number in 1..8) {
        if ($configuration -notcontains "nic$number=`"none`"") { throw 'Source NIC settings changed.' }
    }
    return $configuration
}
if (([string](Invoke-VBox -Arguments @('--version'))).Trim() -ne $plan.vbox_version) { throw 'VirtualBox version changed.' }
$registered = @(Invoke-VBox -Arguments @('list', 'vms'))
if ($registered | Where-Object { $_ -match [regex]::Escape($plan.vm_uuid) -or $_.StartsWith('"' + $plan.vm_name + '" ') }) {
    throw 'Guard identity is already registered.'
}
$sourceBefore = @(Assert-SourceStopped)
$medium = (Invoke-VBox -Arguments @('showmediuminfo', 'disk', $plan.source_disk_uuid)) -join "`n"
if ($medium -notmatch '(?m)^Parent UUID:\s+base\s*$' -or $medium -notmatch '(?m)^Type:\s+normal \(base\)\s*$' -or
    $medium -notmatch ('(?m)^Capacity:\s+' + $plan.disk_capacity_mib + ' MBytes\s*$')) {
    throw 'Source is not the expected full base disk.'
}
if ((Get-FileHash -LiteralPath $sourceDisk -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.source_disk_sha256) {
    throw 'Stopped source disk digest changed.'
}
# Reserve a one-use intent before the first mutation. No automatic cleanup or replay.
New-Item -ItemType Directory -Path $receiptFolder -ErrorAction Stop | Out-Null
[ordered]@{ approval = $ApprovalReference; plan_sha256 = $actualPlanHash; script_sha256 =
    (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();
    utc = [DateTime]::UtcNow.ToString('O'); state = 'possible-provisioning'; source_configuration = $sourceBefore;
    operations = $operations.ToArray() } | ConvertTo-Json -Depth 12 |
    Set-Content -LiteralPath (Join-Path $receiptFolder 'intent.json') -Encoding utf8NoBOM
foreach ($operation in $operations) { Invoke-VBox -Arguments $operation | Out-Null }
$configuration = @(Invoke-VBox -Arguments @('showvminfo', $plan.vm_uuid, '--machinereadable'))
$required = @('VMState="poweroff"', 'cpus=1', 'memory=1024', 'firmware="EFI"', 'apic="on"', 'x2apic="off"',
    'clipboard="disabled"', 'clipboard_file_transfers="off"', 'draganddrop="disabled"', 'vrde="off"',
    'usb="off"', 'ehci="off"', 'xhci="off"', 'audio="none"', 'boot1="disk"', 'boot2="none"',
    'boot3="none"', 'boot4="none"')
foreach ($line in $required) { if ($configuration -notcontains $line) { throw "Guard postcondition failed: $line" } }
foreach ($number in 1..8) { if ($configuration -notcontains "nic$number=`"none`"") { throw 'Guard NIC is enabled.' } }
foreach ($number in 1..4) { if ($configuration -notcontains "uart$number=`"off`"") { throw 'Guard UART is enabled.' } }
if ($configuration | Where-Object { $_ -match '^SharedFolder' }) { throw 'Unexpected shared folder.' }
$clonedMedium = (Invoke-VBox -Arguments @('showmediuminfo', 'disk', $targetDisk)) -join "`n"
if ($clonedMedium -notmatch '(?m)^UUID:\s+([0-9a-f-]+)\s*$') { throw 'Clone UUID is missing.' }
$cloneUuid = $Matches[1]
if ($cloneUuid -eq $plan.source_disk_uuid -or $clonedMedium -notmatch '(?m)^Parent UUID:\s+base\s*$' -or
    $clonedMedium -notmatch '(?m)^Type:\s+normal \(base\)\s*$' -or
    $clonedMedium -notmatch ('(?m)^Capacity:\s+' + $plan.disk_capacity_mib + ' MBytes\s*$') -or
    $configuration -notcontains ('"SATA-ImageUUID-0-0"="' + $cloneUuid + '"')) { throw 'Guard clone identity/type mismatch.' }
$sourceAfter = @(Assert-SourceStopped)
if (($sourceBefore -join "`n") -cne ($sourceAfter -join "`n") -or
    (Get-FileHash -LiteralPath $sourceDisk -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.source_disk_sha256) {
    throw 'Source changed during cloning; hold all dependent work.'
}
$receipt = [ordered]@{ approval = $ApprovalReference; plan_sha256 = $actualPlanHash; vm_uuid = $plan.vm_uuid;
    disk_uuid = $cloneUuid; source_disk_sha256 = $plan.source_disk_sha256; guard_disk_sha256 =
    (Get-FileHash -LiteralPath $targetDisk -Algorithm SHA256).Hash.ToLowerInvariant();
    utc = [DateTime]::UtcNow.ToString('O'); state = 'poweroff'; network = 'eight NICs disabled';
    source_unchanged = $true; qualified = $false; configuration = $configuration }
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $receiptFolder 'result.json') -Encoding utf8NoBOM
$receipt | ConvertTo-Json -Depth 8
