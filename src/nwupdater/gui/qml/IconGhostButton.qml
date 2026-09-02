import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    property string glyph: ""
    property string tip: ""
    property bool filled: false
    property bool accent: false
    property bool active: true
    signal triggered()

    width: 28; height: 28; radius: 8
    color: !root.active ? "transparent"
         : filled ? Theme.accent
         : hover.hovered ? Theme.panel : "transparent"
    border.width: filled ? 0 : 1
    border.color: root.active ? Theme.line : "transparent"

    HoverHandler { id: hover; cursorShape: root.active ? Qt.PointingHandCursor : Qt.ArrowCursor }
    ToolTip.visible: hover.hovered && root.tip !== ""
    ToolTip.text: root.tip
    ToolTip.delay: 450

    Text {
        anchors.centerIn: parent
        text: root.glyph
        font.pixelSize: 13
        color: !root.active ? Theme.lineStrong
             : root.filled ? "#ffffff"
             : root.accent ? Theme.ok : Theme.muted
    }
    TapHandler { enabled: root.active; onTapped: root.triggered() }
}
