#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:19732/}"
BASE_URL="${2:-${URL%%\?*}}"

if pgrep -x "Google Chrome" >/dev/null 2>&1; then
  if ! osascript - "$URL" "$BASE_URL" <<'APPLESCRIPT'
on run argv
  set targetURL to item 1 of argv
  set baseURL to item 2 of argv
  set foundTab to false
  set targetWindowId to missing value
  tell application "Google Chrome"
    repeat with browserWindow in windows
      repeat with tabIndex from (count of tabs of browserWindow) to 1 by -1
        set browserTab to tab tabIndex of browserWindow
        if (URL of browserTab starts with baseURL) then
          if foundTab then
            close browserTab
          else
            set foundTab to true
            set targetWindowId to id of browserWindow
            set active tab index of browserWindow to tabIndex
            set URL of browserTab to targetURL
          end if
        end if
      end repeat
    end repeat
    if foundTab then
      set index of (first window whose id is targetWindowId) to 1
      activate
      return
    end if
  end tell
  open location targetURL
end run
APPLESCRIPT
  then
    open "$URL"
  fi
else
  open "$URL"
fi
