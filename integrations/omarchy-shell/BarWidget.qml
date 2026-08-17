import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "omookaway.status"

  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || home + "/.cache"
  readonly property string statusPath: runtimeDir + "/omookaway/status.json"
  property var status: ({})

  function parseStatus(content) {
    try {
      var value = JSON.parse(String(content || ""))
      status = value && typeof value === "object" ? value : ({})
    } catch (error) {
      status = ({})
    }
  }

  function displayText() {
    if (!status.state) return "Breaks --"
    if (status.state === "dormant") return "Breaks dormant"
    if (status.state === "warning") return "Break in " + Math.ceil(Number(status.deadline_in_seconds || 0)) + "s"
    if (status.state === "snooze") return "Break snoozed " + Math.ceil(Number(status.deadline_in_seconds || 0) / 60) + "m"
    var elapsed = Number(status.active_elapsed_seconds || 0)
    var total = Number(status.work_interval_seconds || 1800)
    return Math.floor(elapsed / 60) + "/" + Math.floor(total / 60) + "m"
  }

  function canStartManualBreak() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("start_manual_break") !== -1
  }

  function canSnooze() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("snooze") !== -1
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.parseStatus(text())
    onLoadFailed: root.status = ({})
  }

  Timer {
    interval: 1000
    running: true
    repeat: true
    onTriggered: statusFile.reload()
  }

  Process {
    id: manualBreakProcess
    command: ["omookaway", "start-break"]
    onExited: statusFile.reload()
  }

  Process {
    id: snoozeProcess
    command: ["omookaway", "snooze"]
    onExited: statusFile.reload()
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText()
    active: root.status.state === "warning"
    interactive: (root.canSnooze() && !snoozeProcess.running)
      || (root.canStartManualBreak() && !manualBreakProcess.running)
    tooltipText: root.status.state === "dormant"
      ? "Outside Work Hours"
      : root.status.state === "warning"
        ? root.canSnooze()
          ? "Snooze Upcoming Break (" + Number(root.status.snoozes_remaining) + " remaining)"
          : "Upcoming Break is owed"
        : root.canStartManualBreak()
          ? "Start a Manual Break"
          : "Active Work Interval progress"
    onPressed: function(mouseButton) {
      if (mouseButton !== Qt.LeftButton) return
      if (root.canSnooze() && !snoozeProcess.running)
        snoozeProcess.running = true
      else if (root.canStartManualBreak() && !manualBreakProcess.running)
        manualBreakProcess.running = true
    }
  }
}
