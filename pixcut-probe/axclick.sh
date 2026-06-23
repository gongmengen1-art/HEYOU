#!/bin/bash
# axclick.sh "<label substring>" [occurrence] — click center of an AX element whose label contains the substring
LABEL="$1"; N="${2:-1}"
osascript - "$LABEL" "$PWD/click" "$N" <<'EOF'
on run argv
  set lbl to item 1 of argv
  set clicker to item 2 of argv
  set want to (item 3 of argv) as integer
  tell application "System Events"
    tell process "Liene Photo"
      set frontmost to true
      delay 0.3
      set els to {}
      repeat 8 times
        try
          set els to entire contents of window 1
          if (count of els) > 0 then exit repeat
        end try
        delay 0.6
      end repeat
      set hit to 0
      repeat with e in els
        set lab to ""
        try
          set lab to (value of e as string)
        end try
        if lab is "" or lab is "missing value" then
          try
            set lab to (title of e as string)
          end try
        end if
        if lab is "" or lab is "missing value" then
          try
            set lab to (description of e as string)
          end try
        end if
        if lab contains lbl then
          set hit to hit + 1
          if hit is want then
            set p to position of e
            set s to size of e
            set cx to (round ((item 1 of p) + (item 1 of s) / 2))
            set cy to (round ((item 2 of p) + (item 2 of s) / 2))
            do shell script clicker & " " & cx & " " & cy
            return "clicked '" & lab & "' @" & cx & "," & cy
          end if
        end if
      end repeat
      return "NOTFOUND:" & lbl
    end tell
  end tell
end run
EOF
