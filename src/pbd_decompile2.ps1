# PbdViewer batch driver — aggregate all function p-code per object into one file
param(
    [string]$InputFile,
    [string]$OutDir,
    [switch]$IncludeEmpty
)
$ErrorActionPreference = 'Continue'
$dst = "$PSScriptRoot\PbdViewer-bin"
$dll = Join-Path $dst 'PbdViewerCore.dll'

[System.Reflection.Assembly]::LoadFrom($dll) | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom($dll)

$pbdP = $asm.GetType('PbdViewer.Uitils.PbClass.PbProject')
$helper = $asm.GetType('PbdViewer.Uitils.PCodeHelper')
$parsePCode = $helper.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static') | Where-Object { $_.Name -eq 'ParsePCode' } | Select-Object -First 1

$proj = New-Object $pbdP $InputFile
if (-not $OutDir) { $OutDir = "$env:TEMP\pbd_out_test" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$pblSource = $proj.Files | Where-Object { $_.FileName -ne 'system' } | Select-Object -First 1 -ExpandProperty FileName
$lib = [System.IO.Path]::GetFileNameWithoutExtension($pblSource)
$objCount = 0
$fnCount = 0
$writtenFiles = 0

foreach ($f in $proj.Files) {
    if ($f.FileName -eq 'system') { continue }
    foreach ($e in $f.Entries) {
        $objCount++
        $objName = if ($e.Name) { $e.Name + '.' + $e.Suffix } else { "obj_$objCount" }
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.AppendLine("`$PBExportHeader$" + $objName)
        [void]$sb.AppendLine("// decompiled by PbdViewer from $pblSource")
        [void]$sb.AppendLine("")

        try {
            $obj = $e.EntryObject
            if ($obj) {
                # Variables (instance/shared)
                if ($obj.Variables -and $obj.Variables.Length -gt 0) {
                    [void]$sb.AppendLine("// ===== Variables (" + $obj.Variables.Length + ") =====")
                    foreach ($v in $obj.Variables) {
                        if ($v) {
                            try {
                                $vt = if ($v.Type) { $v.Type.Name } else { '?' }
                                $vn = $v.Name
                                $vs = $v.PrecisionOrSize
                                $va = $v.AccessString
                                $kind = if ($v.IsShared) { 'shared' } elseif ($v.IsInstance) { 'instance' } elseif ($v.IsConstant) { 'const' } else { 'local' }
                                $line = "$kind $vt $vn"
                                if ($vs) { $line += " {$vs}" }
                                if ($va) { $line += " access=$va" }
                                [void]$sb.AppendLine("// $line")
                            } catch {
                                [void]$sb.AppendLine("// " + $v.ToString())
                            }
                        }
                    }
                    [void]$sb.AppendLine("")
                }

                # All function definitions (signatures)
                $allDefs = $obj.AllFunctionDefinitions
                if ($allDefs -and $allDefs.Length -gt 0) {
                    [void]$sb.AppendLine("// ===== All Function Definitions (" + $allDefs.Length + ") =====")
                    foreach ($fd in $allDefs) {
                        if ($fd) {
                            $kind = if ($fd.IsEvent) { "event" } else { "function" }
                            $name = $fd.Name
                            $params = ""
                            if ($fd.Params) {
                                $pnames = @()
                                foreach ($p in $fd.Params) { if ($p) { $pnames += $p.ToString() } }
                                $params = $pnames -join ', '
                            }
                            $rt = if ($fd.ReturnType) { $fd.ReturnType.Name } else { '' }
                            $rtStr = if ($rt) { " returns $rt" } else { '' }
                            [void]$sb.AppendLine("// $kind $name($params)$rtStr")
                        }
                    }
                    [void]$sb.AppendLine("")
                }

                # All variables (inherit chain)
                $allVars = $obj.AllVariables
                if ($allVars -and $allVars.Length -gt 0) {
                    [void]$sb.AppendLine("// ===== All Variables incl inherit (" + $allVars.Length + ") =====")
                    foreach ($v in $allVars) {
                        if ($v) {
                            try {
                                $vt = if ($v.Type) { $v.Type.Name } else { '?' }
                                $vn = $v.Name
                                $kind = if ($v.IsShared) { 'shared' } elseif ($v.IsInstance) { 'instance' } elseif ($v.IsConstant) { 'const' } else { 'local' }
                                [void]$sb.AppendLine("// $kind $vt $vn")
                            } catch { }
                        }
                    }
                    [void]$sb.AppendLine("")
                }

                # Functions (actual p-code bodies)
                if ($obj.Functions -and $obj.Functions.Length -gt 0) {
                    [void]$sb.AppendLine("// ===== Functions with p-code (" + $obj.Functions.Length + ") =====")
                    foreach ($fn in $obj.Functions) {
                        if (-not $fn) { continue }
                        $fnCount++
                            try {
                                # p-code 函数 Index = 对象自身定义表 FunctionDefinitions 的位置
                                # (AllFunctionDefinitions 按 GlobalIndex 编址且含继承系统定义，
                                #  $fn.Definition 在非 GUI 路径恒为 null -> 实测见 docs/20-pcode-funcname-fix.md)
                                $fd = $null
                                $idx = -1
                                try { $idx = [int]$fn.Index } catch { }
                                if ($obj.FunctionDefinitions -and $idx -ge 0 -and $idx -lt $obj.FunctionDefinitions.Length) {
                                    $fd = $obj.FunctionDefinitions[$idx]
                                }
                                $name = if ($fd -and $fd.Name) { $fd.Name } else { "func_$fnCount" }
                            $kind = if ($fd -and $fd.IsEvent) { "event" } else { "function" }
                            $params = ""
                            if ($fd -and $fd.Params) {
                                $pnames = @()
                                foreach ($p in $fd.Params) { if ($p) { $pnames += $p.ToString() } }
                                $params = $pnames -join ', '
                            }
                            [void]$sb.AppendLine("")
                            [void]$sb.AppendLine("$kind $name($params)")
                            [void]$sb.AppendLine("")

                            if ($parsePCode) {
                                $lines = $parsePCode.Invoke($null, @($fn, $true))
                                if ($lines) {
                                    foreach ($line in $lines) {
                                        [void]$sb.AppendLine($line)
                                    }
                                }
                            }
                            [void]$sb.AppendLine("")
                        } catch {
                            [void]$sb.AppendLine("// err: $($_.Exception.Message)")
                        }
                    }
                }
            }
        } catch {
            [void]$sb.AppendLine("// obj err: $($_.Exception.Message)")
        }

        $content = $sb.ToString()
        if (-not $IncludeEmpty -and $content.Length -lt 80) { continue }
        $safe = ($objName -replace '[/\\:*?]','_')
        $outFile = Join-Path $OutDir ($lib + '__' + $safe + '.sr.txt')
        try {
            [System.IO.File]::WriteAllText($outFile, $content, [System.Text.Encoding]::UTF8)
            $writtenFiles++
        } catch {
            Write-Host "  ERR write $outFile : $($_.Exception.Message)"
        }
    }
}
return [PSCustomObject]@{
    Library = $lib
    Objects = $objCount
    Functions = $fnCount
    Files = $writtenFiles
    Version = $proj.Version
}