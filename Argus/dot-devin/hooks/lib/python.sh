# Shared by the Devin hooks and the git hooks: sdlc_python runs a Python 3 that works here.
# On Windows `python3` is often missing or only the Microsoft Store alias in WindowsApps, so a real
# python3 comes first, then python, then the py launcher. SDLC_PYTHON overrides all of them.
sdlc_python() {
  local py
  if [ -n "${SDLC_PYTHON:-}" ]; then
    "$SDLC_PYTHON" "$@"
    return
  fi
  for py in python3 python; do
    case "$(command -v "$py" 2>/dev/null)" in
      "" | *WindowsApps*) ;;
      *) "$py" "$@"; return ;;
    esac
  done
  if command -v py >/dev/null 2>&1; then
    py -3 "$@"
    return
  fi
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      "$py" "$@"
      return
    fi
  done
  printf 'no Python 3 on PATH (tried python3, python, py); set SDLC_PYTHON\n' >&2
  return 127
}
