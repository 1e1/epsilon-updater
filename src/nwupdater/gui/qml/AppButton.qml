import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property bool ghost: false
    property bool danger: false
    // A running operation: a spinner turns before the label so a long job never looks idle.
    property bool busy: false
    implicitHeight: 30
    padding: 12
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 6
            Item {
                visible: control.busy
                width: 12
                height: 12
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: 2
                    border.color: label.color
                    opacity: 0.25
                }
                Rectangle {
                    width: 4
                    height: 4
                    radius: 2
                    color: label.color
                    x: parent.width / 2 - width / 2
                    y: 0
                }
                RotationAnimator on rotation {
                    running: control.busy
                    from: 0
                    to: 360
                    duration: 900
                    loops: Animation.Infinite
                }
            }
            Text {
                id: label
                text: control.text
                color: !control.enabled && !control.busy ? Theme.muted
                     : control.danger ? "#ffffff"
                     : control.ghost ? Theme.ink : Theme.accentInk
                font.pixelSize: 12
                font.weight: Font.DemiBold
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
    background: Rectangle {
        radius: 9
        color: !control.enabled ? Theme.panel
             : control.danger ? Theme.err
             : control.ghost ? Theme.card : Theme.accentSoft
        border.width: 1
        border.color: !control.enabled ? Theme.line
                    : control.danger ? Theme.err
                    : control.ghost ? Theme.lineStrong : Qt.darker(Theme.accentSoft, 1.1)
        opacity: control.down ? 0.75 : 1
        Behavior on opacity { NumberAnimation { duration: 90 } }
    }
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
