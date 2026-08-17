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
    if (status.state === "activity_unavailable") return "Activity unavailable"
    if (status.state === "enforcement_unavailable") return "Enforcement unavailable"
    var mode = status.degraded_wall_clock_mode
      ? "Wall clock · "
      : status.activity_observation_error ? "Observer off · " : ""
    if (status.state === "warning") return mode + "Break in " + Math.ceil(Number(status.deadline_in_seconds || 0)) + "s"
    if (status.state === "snooze") return mode + "Break snoozed " + Math.ceil(Number(status.deadline_in_seconds || 0) / 60) + "m"
    if (status.state === "pause") {
      var deadline = new Date(String(status.pause_deadline || ""))
      return mode + (isNaN(deadline.getTime()) ? "Paused" : "Paused until " + Qt.formatTime(deadline, "h:mm AP"))
    }
    var elapsed = Number(status.active_elapsed_seconds || 0)
    var total = Number(status.work_interval_seconds || 1800)
    return mode + Math.floor(elapsed / 60) + "/" + Math.floor(total / 60) + "m"
  }

  function canStartManualBreak() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("start_manual_break") !== -1
  }

  function canSnooze() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("snooze") !== -1
  }

  function canResume() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("resume") !== -1
  }

  function canPause() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("pause") !== -1
  }

  function canRetryEnforcement() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("retry_enforcement") !== -1
  }

  function canEnterDegradedMode() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("enter_degraded_wall_clock_mode") !== -1
  }

  function canLeaveDegradedMode() {
    var commands = status.permitted_commands
    return Array.isArray(commands) && commands.indexOf("leave_degraded_wall_clock_mode") !== -1
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

  Process {
    id: resumeProcess
    command: ["omookaway", "resume"]
    onExited: statusFile.reload()
  }

  Process {
    id: pauseProcess
    onExited: statusFile.reload()
  }

  Process {
    id: retryProcess
    command: ["omookaway", "retry-enforcement"]
    onExited: statusFile.reload()
  }

  Process {
    id: enterDegradedProcess
    command: ["omookaway", "degraded-wall-clock", "enter"]
    onExited: statusFile.reload()
  }

  Process {
    id: leaveDegradedProcess
    command: ["omookaway", "degraded-wall-clock", "leave"]
    onExited: statusFile.reload()
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText()
    active: root.status.state === "warning" || root.status.degraded_wall_clock_mode
    interactive: (root.canEnterDegradedMode() && !enterDegradedProcess.running)
      || (root.canLeaveDegradedMode() && !leaveDegradedProcess.running)
      || (root.canResume() && !resumeProcess.running)
      || (root.canPause() && !pauseProcess.running)
      || (root.canRetryEnforcement() && !retryProcess.running)
      || (root.canSnooze() && !snoozeProcess.running)
      || (root.canStartManualBreak() && !manualBreakProcess.running)
    tooltipText: root.status.state === "dormant"
      ? "Outside Work Hours"
      : root.canEnterDegradedMode()
        ? "Activity observation unavailable; use wall-clock cadence"
      : root.canLeaveDegradedMode()
        ? "Using Degraded Wall-Clock Mode; stop fallback"
      : root.status.state === "pause"
        ? "Paused until " + String(root.status.pause_deadline || "the chosen time")
      : root.canRetryEnforcement()
        ? "Retry enforcement for the owed Upcoming Break"
      : root.status.state === "warning"
        ? root.canSnooze()
          ? "Snooze Upcoming Break (" + Number(root.status.snoozes_remaining) + " remaining); right-click to Pause for one hour"
          : "Upcoming Break is owed"
        : root.canStartManualBreak()
          ? "Start a Manual Break; right-click to Pause for one hour"
          : "Active Work Interval progress"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton && root.canPause() && !pauseProcess.running) {
        var resumeAt = new Date(Date.now() + 60 * 60 * 1000).toISOString()
        pauseProcess.command = ["omookaway", "pause", resumeAt]
        pauseProcess.running = true
        return
      }
      if (mouseButton !== Qt.LeftButton) return
      if (root.canResume() && !resumeProcess.running)
        resumeProcess.running = true
      else if (root.canSnooze() && !snoozeProcess.running)
        snoozeProcess.running = true
      else if (root.canRetryEnforcement() && !retryProcess.running)
        retryProcess.running = true
      else if (root.canEnterDegradedMode() && !enterDegradedProcess.running)
        enterDegradedProcess.running = true
      else if (root.canLeaveDegradedMode() && !leaveDegradedProcess.running)
        leaveDegradedProcess.running = true
      else if (root.canStartManualBreak() && !manualBreakProcess.running)
        manualBreakProcess.running = true
    }
  }
}
