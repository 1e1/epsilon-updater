import QtQuick
import QtQuick.Controls.Basic

/* The web UI's `.seg` control: a pill of mutually exclusive buttons. */
Rectangle {
    id: root
    property var options: []          // [{key, label}]
    property string current: ""
    property color activeBg: Theme.accentSoft
    property color activeFg: Theme.accentInk
    signal picked(string key)

    implicitWidth: row.implicitWidth + 6
    implicitHeight: 28
    radius: 10
    color: Theme.card
    border.color: Theme.lineStrong
    border.width: 1

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: root.options
            delegate: Rectangle {
                required property var modelData
                readonly property bool active: modelData.key === root.current
                width: txt.implicitWidth + 22
                height: 22
                radius: 7
                color: active ? root.activeBg : "transparent"
                Text {
                    id: txt
                    anchors.centerIn: parent
                    text: modelData.label
                    color: parent.active ? root.activeFg : Theme.muted
                    font.pixelSize: 12
                    font.weight: parent.active ? Font.DemiBold : Font.Normal
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.picked(modelData.key)
                }
            }
        }
    }
}
