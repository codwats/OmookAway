import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
  id: root
  property string pendingState: ""
  property var pendingLifecycle: []
  property bool awaitingSleepValue: false
  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR")
    || home + "/.cache"
  property int idleThreshold: 300

  function loadConfig(content) {
    try {
      var status = JSON.parse(String(content || ""))
      idleThreshold = Number(status.idle_threshold_seconds || 300)
    } catch (error) {
      idleThreshold = 300
    }
  }

  function publish(active) {
    var state = active ? "active" : "idle"
    if (activityProcess.running) {
      pendingState = state
      return
    }
    activityProcess.command = ["omookaway", "activity", state]
    activityProcess.running = true
  }

  function publishLifecycle(command) {
    pendingLifecycle.push(command)
    if (!lifecycleProcess.running) runNextLifecycle()
  }

  function runNextLifecycle() {
    if (pendingLifecycle.length === 0) return
    lifecycleProcess.command = pendingLifecycle.shift()
    lifecycleProcess.running = true
  }

  function handleLogind(line) {
    if (line.indexOf("member=PrepareForSleep") !== -1) {
      awaitingSleepValue = true
    } else if (awaitingSleepValue && line.indexOf("boolean ") !== -1) {
      awaitingSleepValue = false
      var state = line.indexOf("true") !== -1 ? "suspended" : "resumed"
      publishLifecycle(["omookaway", "suspend", state])
    } else if (line.indexOf("member=Lock") !== -1) {
      publishLifecycle(["omookaway", "lock", "locked"])
    } else if (line.indexOf("member=Unlock") !== -1) {
      publishLifecycle(["omookaway", "lock", "unlocked"])
    }
  }

  IdleMonitor {
    id: idleMonitor
    enabled: true
    timeout: root.idleThreshold
    respectInhibitors: true
    onIsIdleChanged: root.publish(!isIdle)
  }

  FileView {
    id: statusFile
    path: root.runtimeDir + "/omookaway/status.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.loadConfig(text())
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
  Process {
    id: lifecycleProcess
    onExited: root.runNextLifecycle()
  }

  Process {
    id: logindMonitor
    running: true
    command: [
      "dbus-monitor", "--system",
      "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'",
      "type='signal',interface='org.freedesktop.login1.Session',member='Lock'",
      "type='signal',interface='org.freedesktop.login1.Session',member='Unlock'"
    ]
    stdout: SplitParser { onRead: function(line) { root.handleLogind(line) } }
  }

  Component.onCompleted: publish(!idleMonitor.isIdle)
}
