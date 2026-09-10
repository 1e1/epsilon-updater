import QtQuick

Rectangle {
    id: root
    property string text: ""
    property color fg: Theme.accentInk
    property color bg: Theme.accentSoft
    implicitWidth: label.implicitWidth + 16
    implicitHeight: 19
    radius: 999
    color: root.bg
    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.fg
        font.pixelSize: 10
        font.weight: Font.DemiBold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.4
    }
}
