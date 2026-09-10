import QtQuick
import QtQuick.Layouts

/* Tab navigation, plus the two class-mode actions that belong on this line. Navigation only:
   what a tab DOES lives in the pane it opens. */
Rectangle {
    id: root
    property var tabs: []          // [{ k, l, n }] — n < 0 hides the count chip
    property string current: ""
    property bool classroom: false
    property bool canDeleteClass: false

    signal picked(string key)
    signal deleteClassRequested()
    signal batchRequested()

    implicitHeight: 42
    color: Theme.card
    Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.line }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        spacing: 4
        Repeater {
            model: root.tabs
            delegate: Item {
                id: tab
                required property var modelData
                readonly property bool active: root.current === tab.modelData.k
                implicitWidth: tabRow.implicitWidth + 20
                implicitHeight: 42
                Row {
                    id: tabRow
                    anchors.centerIn: parent
                    spacing: 7
                    Text {
                        text: tab.modelData.l
                        color: tab.active ? Theme.ink : Theme.muted
                        font.pixelSize: 14
                        font.weight: tab.active ? Font.DemiBold : Font.Normal
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Chip {
                        visible: tab.modelData.n >= 0
                        anchors.verticalCenter: parent.verticalCenter
                        text: tab.modelData.n
                        fg: Theme.muted
                        bg: Theme.panel
                    }
                }
                Rectangle {
                    visible: tab.active
                    width: parent.width - 12
                    height: 2
                    x: 6
                    y: parent.height - 2
                    color: Theme.accent
                }
                TapHandler { onTapped: root.picked(tab.modelData.k) }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
        Item { Layout.fillWidth: true }
        AppButton {
            visible: root.classroom
            ghost: true
            text: "🗑"
            implicitWidth: 38
            enabled: root.canDeleteClass
            onClicked: root.deleteClassRequested()
        }
        AppButton {
            visible: root.classroom
            text: "▶  " + i18n.t("batch_mode")
            onClicked: root.batchRequested()
        }
    }
}
