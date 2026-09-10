import QtQuick

Column {
    id: root
    property string value: ""
    property string label: ""
    spacing: 0
    Text { text: root.value; color: Theme.ink; font.pixelSize: 15; font.weight: Font.Bold; font.family: Theme.mono }
    Text { text: root.label; color: Theme.muted; font.pixelSize: 10 }
}
