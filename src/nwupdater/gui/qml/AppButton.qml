import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property bool ghost: false
    property bool danger: false
    implicitHeight: 30
    padding: 12
    contentItem: Text {
        text: control.text
        color: !control.enabled ? Theme.muted
             : control.danger ? "#ffffff"
             : control.ghost ? Theme.ink : Theme.accentInk
        font.pixelSize: 12
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
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
