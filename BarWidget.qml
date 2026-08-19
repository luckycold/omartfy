import QtQuick
import QtQuick.Effects
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "dailen.omartfy"

  readonly property var ntfyService: bar && bar.shell
    ? bar.shell.serviceFor("dailen.omartfy") : null
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false
  readonly property int unreadCount: ntfyService ? ntfyService.unreadCount : 0
  readonly property int urgentUnreadCount: ntfyService ? ntfyService.urgentUnreadCount : 0
  readonly property var servers: ntfyService ? ntfyService.servers : []
  readonly property int enabledCount: servers.filter(function(server) { return server.enabled !== false }).length
  readonly property int connectedCount: servers.filter(function(server) {
    return server.enabled !== false && server.state === "connected"
  }).length
  readonly property color iconColor: urgentUnreadCount > 0 ? Color.urgent
    : (unreadCount > 0 ? Color.accent : (bar ? bar.foreground : Color.foreground))
  readonly property string badgeText: unreadCount > 99 ? "99+" : String(unreadCount)

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() {
    if (panelLoader.item && typeof panelLoader.item.closeForPopoutSwitch === "function")
      panelLoader.item.closeForPopoutSwitch()
    else root.close()
  }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
    panelLoader.item.ntfyService = root.ntfyService
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onNtfyServiceChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    tooltipText: root.servers.length === 0
      ? "Add a server to begin"
      : Model.serverSummary(root.servers, root.unreadCount)
    iconComponent: Component {
      Item {
        Image {
          id: mark
          anchors.fill: parent
          source: Qt.resolvedUrl("assets/ntfy-mask.svg")
          fillMode: Image.PreserveAspectFit
          sourceSize.width: Math.round(width * Screen.devicePixelRatio)
          sourceSize.height: Math.round(height * Screen.devicePixelRatio)
          visible: false
          layer.enabled: true
        }

        MultiEffect {
          anchors.fill: mark
          source: mark
          visible: mark.status === Image.Ready
          // The upstream mask is black. Lift opaque pixels to white before
          // tinting so symbolic colorization tracks the bar foreground.
          brightness: 1.0
          colorization: 1.0
          colorizationColor: root.iconColor
        }

        Text {
          anchors.centerIn: parent
          visible: mark.status === Image.Error
          text: "󰂚"
          color: root.iconColor
          font.family: button.fontFamily
          font.pixelSize: button.fontSize
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
      else if (buttonCode === Qt.MiddleButton && root.ntfyService) root.ntfyService.reload()
    }
  }

  Rectangle {
    visible: root.unreadCount > 0
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.rightMargin: -Style.space(2)
    anchors.topMargin: -Style.space(2)
    radius: height / 2
    color: root.urgentUnreadCount > 0 ? Color.urgent : Color.accent
    implicitWidth: Math.max(implicitHeight, badgeLabel.implicitWidth + Style.space(4))
    implicitHeight: Style.space(12)

    Text {
      id: badgeLabel
      anchors.centerIn: parent
      text: root.badgeText
      color: Color.background
      font.family: button.fontFamily
      font.pixelSize: Style.space(8)
      font.bold: true
    }
  }

  Rectangle {
    visible: root.enabledCount > 0 && root.connectedCount < root.enabledCount
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    width: Style.space(5)
    height: width
    radius: width / 2
    color: root.connectedCount > 0 ? "#d89b35" : Color.urgent
  }
}
