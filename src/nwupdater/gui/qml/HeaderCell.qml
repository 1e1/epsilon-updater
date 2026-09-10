import QtQuick

/* A column label. It has to carry its own implicit size: wrapped in a layout, an Item that
   sizes itself from nothing is a 0-wide cell whose text spills over the next column. */
Item {
    property alias text: label.text
    implicitWidth: label.implicitWidth
    implicitHeight: label.implicitHeight
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
