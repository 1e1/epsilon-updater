import QtQuick

Column {
    property string title: ""
    property string subtitle: ""
    property int count: 0
    spacing: 1
    Row {
        spacing: 8
        Text {
            text: parent.parent.title
            color: Theme.muted
            font.pixelSize: 10
            font.weight: Font.Bold
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 0.8
        }
        Text {
            text: parent.parent.count
            color: Theme.muted
            font.pixelSize: 10
            font.weight: Font.Bold
        }
    }
    Text {
        text: parent.subtitle
        color: Theme.muted
        font.pixelSize: 11
        opacity: 0.85
    }
}
