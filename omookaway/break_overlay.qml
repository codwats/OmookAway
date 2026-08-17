import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
  id: root

  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") ||
    (Quickshell.env("HOME") || "") + "/.cache"
  readonly property string statusPath: runtimeDir + "/omookaway/status.json"
  property var status: ({})
  property bool readinessSent: false
  property bool failureSent: false
  property string lastTopology: ""
  property double unhealthySince: 0

  function screenNames(screens) {
    var names = []
    for (var index = 0; index < screens.length; index++) names.push(screens[index].name)
    names.sort()
    return names
  }

  function send(command) {
    if (commandProcess.running) return false
    commandProcess.command = command
    commandProcess.running = true
    return true
  }

  function validateCoverage() {
    var displays = screenNames(Quickshell.screens)
    var covered = []
    var healthy = displays.length > 0 && windows.instances.length === displays.length
    for (var index = 0; index < windows.instances.length; index++) {
      var window = windows.instances[index]
      healthy = healthy && window.visible &&
        window.WlrLayershell.keyboardFocus === WlrKeyboardFocus.Exclusive
      covered.push(window.modelData.name)
    }
    var topology = JSON.stringify(displays)
    if (readinessSent && topology !== lastTopology) {
      if (!failureSent &&
          send(["omookaway", "overlay-failed", "display topology changed"])) {
        failureSent = true
      }
      return
    }
    if (healthy && JSON.stringify(covered.sort()) === topology) {
      unhealthySince = 0
      if ((!readinessSent || topology !== lastTopology) &&
          send(["omookaway", "overlay-ready", topology,
                JSON.stringify(covered), "true"])) {
        readinessSent = true
        lastTopology = topology
      }
      return
    }
    if (unhealthySince === 0) unhealthySince = Date.now()
    if (readinessSent && !failureSent &&
        send(["omookaway", "overlay-failed", "display coverage or input inhibition was lost"])) {
      failureSent = true
    }
  }

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.status = JSON.parse(String(text() || "{}")) }
      catch (error) { root.status = ({}) }
    }
  }

  Process { id: commandProcess }

  Timer {
    interval: 100
    running: !root.failureSent
    repeat: true
    onTriggered: root.validateCoverage()
  }

  Timer {
    id: readinessTimeout
    interval: 2000
    running: !root.readinessSent && !root.failureSent
    repeat: true
    onTriggered: {
      if (root.send(["omookaway", "overlay-failed",
                     "Break overlay readiness timed out"])) root.failureSent = true
    }
  }

  Timer {
    interval: 250
    running: true
    repeat: true
    onTriggered: statusFile.reload()
  }

  Variants {
    id: windows
    model: Quickshell.screens

    PanelWindow {
      required property var modelData
      screen: modelData
      color: "#16181d"
      exclusionMode: ExclusionMode.Ignore
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
      WlrLayershell.namespace: "omookaway-break"
      anchors { top: true; right: true; bottom: true; left: true }

      Column {
        anchors.centerIn: parent
        spacing: 28

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          color: "#f4f1e8"
          font.pixelSize: 34
          text: "Break"
        }

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          color: "#f4f1e8"
          font.pixelSize: 72
          font.bold: true
          text: Math.ceil(Number(root.status.break_remaining_seconds || 0)) + "s"
        }

        Rectangle {
          width: controlText.implicitWidth + 48
          height: controlText.implicitHeight + 28
          radius: 8
          color: control.containsMouse ? "#d97757" : "#a9513a"

          Text {
            id: controlText
            anchors.centerIn: parent
            color: "white"
            font.pixelSize: 20
            text: "End Break"
          }

          MouseArea {
            id: control
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.send(["omookaway", "finish-break"])
          }
        }
      }
    }
  }
}
