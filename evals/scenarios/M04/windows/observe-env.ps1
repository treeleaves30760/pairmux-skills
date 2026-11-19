# M04 observer for PowerShell, dot-sourced by the generated venv Activate.ps1. Activation and an
# ordinary `$env:TOKEN = ...` assignment remain ordinary operations; the fixture only records their
# real live identity (the Windows counterpart of observe-env.sh). A TOKEN assignment is observed at
# the next prompt, after the command that set it returns and before any later command runs.
function global:_m04_record([string]$kind) {
    & $global:_M04_PYTHON -I (Join-Path $global:_M04_ROOT 'identity.py') $kind $PID `
        $global:_m04_activation $global:_m04_token_exports
}
if ($null -eq $global:_m04_activation) { $global:_m04_activation = 0 }
if ($null -eq $global:_m04_token_exports) { $global:_m04_token_exports = 0 }
$global:_m04_activation = $global:_m04_activation + 1
# Exported counters are consumed by later Python identity commands.
$env:M04_ACTIVATION_COUNT = [string]$global:_m04_activation
$env:M04_TOKEN_EXPORT_COUNT = [string]$global:_m04_token_exports
_m04_record 'activation'
# Wrap whatever prompt is current (the venv's, which wraps pairmux's own) unless already wrapped.
if (-not ("$function:prompt" -match '_m04_inner_prompt')) {
    $global:_m04_token_value = $env:TOKEN
    $global:_m04_inner_prompt = $function:prompt
    function global:prompt {
        $lec = $global:LASTEXITCODE
        if ($env:TOKEN -and $env:TOKEN -ne $global:_m04_token_value) {
            $global:_m04_token_exports = $global:_m04_token_exports + 1
            $env:M04_TOKEN_EXPORT_COUNT = [string]$global:_m04_token_exports
            _m04_record 'token_export'
        }
        $global:_m04_token_value = $env:TOKEN
        $global:LASTEXITCODE = $lec
        & $global:_m04_inner_prompt
    }
}
