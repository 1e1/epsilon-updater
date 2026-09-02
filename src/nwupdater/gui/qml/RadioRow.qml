import QtQuick
import QtQuick.Layouts

/* A radio choice whose label wraps. The Basic style's RadioButton cannot wrap, and overriding
   its contentItem moves the indicator out of place — so the row is drawn directly. */
RowLayout {
    id: root
    property bool checked: false
    property string text: ""
    signal picked()

    Layout.fillWidth: true
    spacing: 9

    Rectangle {
        Layout.alignment: Qt.AlignTop
        width: 17
        height: 17
        radius: 9
        color: "transparent"
        border.width: root.checked ? 5 : 1.5
        border.color: root.checked ? Theme.accent : Theme.lineStrong
        Behavior on border.width { NumberAnimation { duration: 90 } }
    }
    Text {
        Layout.fillWidth: true
        text: root.text
        color: Theme.ink
        font.pixelSize: 13
        wrapMode: Text.Wrap
    }
    TapHandler { onTapped: root.picked() }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
