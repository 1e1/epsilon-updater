import QtQuick
import QtQuick.Controls.Basic

/* CheckBox on Theme tokens. The Basic indicator is a 28 px square painted from the system
   palette — oversized for a table row, and still white when the window is switched to dark.
   15 px and accent-filled, like the web table's `accent-color` boxes. */
CheckBox {
    id: control
    padding: 3

    indicator: Rectangle {
        implicitWidth: 16
        implicitHeight: 16
        x: control.text ? control.leftPadding
                        : control.leftPadding + (control.availableWidth - width) / 2
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: 5
        color: control.checked ? Theme.accent : Theme.card
        border.width: 1
        border.color: control.checked ? Theme.accent
                    : control.hovered || control.visualFocus ? Theme.accent : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: 90 } }

        Text {
            anchors.centerIn: parent
            text: control.checkState === Qt.PartiallyChecked ? "–" : "✓"
            color: Theme.onAccent
            font.pixelSize: 11
            font.weight: Font.Bold
            visible: control.checkState !== Qt.Unchecked
        }
    }

    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: control.enabled ? Theme.ink : Theme.muted
        font: control.font
        verticalAlignment: Text.AlignVCenter
    }

    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
