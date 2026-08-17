import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
  id: root
  property string pendingState: ""

  function publish(active) {
    var state = active ? "active" : "idle"
    if (activityProcess.running) {
      pendingState = state
      return
    }
    activityProcess.command = ["omookaway", "activity", state]
    activityProcess.running = true
  }

  IdleMonitor {
    id: idleMonitor
    enabled: true
    timeout: 300
    respectInhibitors: true
    onIsIdleChanged: root.publish(!isIdle)
  }

  Process {
    id: activityProcess
    onExited: {
      if (root.pendingState === "") return
      var state = root.pendingState
      root.pendingState = ""
      root.publish(state === "active")
    }
  }

  Component.onCompleted: publish(!idleMonitor.isIdle)
}
