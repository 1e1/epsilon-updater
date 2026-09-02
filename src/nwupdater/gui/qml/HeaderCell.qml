import QtQuick

Item {
    property alias text: label.text
    height: parent ? parent.height : 40
    Text {
        id: label
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.muted
        font.pixelSize: 10
        font.weight: Font.Bold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.8
    }
}
