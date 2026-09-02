import QtQuick

Rectangle {
    property string text: ""
    property color fg: Theme.accentInk
    property color bg: Theme.accentSoft
    implicitWidth: label.implicitWidth + 16
    implicitHeight: 19
    radius: 999
    color: bg
    Text {
        id: label
        anchors.centerIn: parent
        text: parent.text
        color: parent.fg
        font.pixelSize: 10
        font.weight: Font.DemiBold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.4
    }
}
