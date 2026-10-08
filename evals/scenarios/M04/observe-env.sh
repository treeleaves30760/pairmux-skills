# shellcheck shell=bash
# Sourced by the generated venv activation. Ordinary source/export calls remain
# ordinary shell operations; the fixture only records their real live identity.
_m04_record() {
  "$_M04_PYTHON" -I "$_M04_ROOT/identity.py" "$1" "$$" "$2" "$3"
}
_m04_activation=$((${_m04_activation:-0} + 1))
_m04_token_exports=${_m04_token_exports:-0}
# zsh also parses export as a declaration keyword; disable only that keyword so
# later ordinary export commands reach the transparent function below.
if [ -n "${ZSH_VERSION:-}" ]; then
  disable -r export
fi
# Ignore names/values in unrelated exports (e.g. PATH from venv activation).
export() {
  local _m04_argument _m04_name _m04_seen=0
  for _m04_argument in "$@"; do
    _m04_name=${_m04_argument%%=*}
    if [ "$_m04_name" = TOKEN ]; then
      _m04_seen=1
    fi
  done
  # Forward normal export arguments, including NAME=value assignments.
  # shellcheck disable=SC2163
  builtin export "$@" || return
  if [ "$_m04_seen" = 1 ]; then
    _m04_token_exports=$((_m04_token_exports + 1))
    builtin export M04_TOKEN_EXPORT_COUNT="$_m04_token_exports"
    _m04_record token_export "$_m04_activation" "$_m04_token_exports"
  fi
}
# Exported counters are consumed by later Python identity commands.
# shellcheck disable=SC2034
builtin export M04_ACTIVATION_COUNT="$_m04_activation" M04_TOKEN_EXPORT_COUNT="$_m04_token_exports"
_m04_record activation "$_m04_activation" "$_m04_token_exports"
