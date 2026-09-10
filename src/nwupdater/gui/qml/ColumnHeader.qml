import QtQuick

/* A column label: title + item count on one line, a quiet subtitle under it.

   Everything reads `root`, never `parent.parent`: inside the Row the chain was two levels deep,
   which qmllint cannot resolve and a later re-nesting would silently break. */
Column {
    id: root
    property string title: ""
    property string subtitle: ""
    property int count: 0
    spacing: 1
    Row {
        spacing: 8
        Text {
            text: root.title
            color: Theme.muted
            font.pixelSize: 10
            font.weight: Font.Bold
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 0.8
        }
        Text {
            text: root.count
            color: Theme.muted
            font.pixelSize: 10
            font.weight: Font.Bold
        }
    }
    Text {
        text: root.subtitle
        color: Theme.muted
        font.pixelSize: 11
        opacity: 0.85
    }
}
