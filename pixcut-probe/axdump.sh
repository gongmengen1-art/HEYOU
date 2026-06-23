#!/bin/bash
osascript <<'EOF'
tell application "System Events"
  tell process "Liene Photo"
    set els to {}
    repeat 8 times
      try
        set els to entire contents of window 1
        if (count of els) > 0 then exit repeat
      end try
      delay 0.5
    end repeat
    set out to "els=" & (count of els) & "\n"
    repeat with e in els
      try
        set r to (role of e as string)
        if r is in {"AXButton","AXLink","AXStaticText","AXTextField","AXImage","AXCheckBox","AXMenuButton","AXPopUpButton"} then
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
          if lab is not "" and lab is not "missing value" then set out to out & r & " '" & lab & "' @" & (position of e as string) & "\n"
        end if
      end try
    end repeat
    return out
  end tell
end tell
EOF
