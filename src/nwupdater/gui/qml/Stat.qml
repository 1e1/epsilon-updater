import QtQuick

Column {
    property string value: ""
    property string label: ""
    spacing: 0
    Text { text: parent.value; color: Theme.ink; font.pixelSize: 15; font.weight: Font.Bold; font.family: Theme.mono }
    Text { text: parent.label; color: Theme.muted; font.pixelSize: 10 }
}
