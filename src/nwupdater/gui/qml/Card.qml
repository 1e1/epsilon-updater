import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    default property alias content: inner.data
    property string title: ""
    implicitHeight: layout.implicitHeight + 28
    radius: 11
    color: Theme.card
    border.width: 1
    border.color: Theme.line

    ColumnLayout {
        id: layout
        x: 14; y: 14
        width: root.width - 28
        spacing: 10
        Text {
            text: root.title
            color: Theme.muted
            font.pixelSize: 10
            font.weight: Font.Bold
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 0.8
        }
        ColumnLayout { id: inner; Layout.fillWidth: true; spacing: 10 }
    }
}
