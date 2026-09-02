import QtQuick
import QtQuick.Layouts

/* Key on the left, value(s) hugging the right. The key is the element that gives way when the
   rail narrows — a truncated label still reads, a truncated version number does not. */
RowLayout {
    id: root
    property string label: ""
    default property alias content: holder.data

    Layout.fillWidth: true
    spacing: 8

    Text {
        Layout.fillWidth: true
        Layout.preferredWidth: 0
        Layout.minimumWidth: 24
        text: root.label
        color: Theme.muted
        font.pixelSize: 13
        elide: Text.ElideRight
    }
    RowLayout {
        id: holder
        Layout.alignment: Qt.AlignRight
        spacing: 6
    }
}
