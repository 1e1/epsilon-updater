import QtQuick
import QtQuick.Controls.Basic

/* ComboBox on Theme tokens, popup included. The Basic one is a 40 px system-palette button with
   a system-palette drop-down: in the dark theme it stayed light, and next to AppButton it never
   lined up. Sized and coloured like the web UI's `select` (9 px radius, card on line-strong). */
ComboBox {
    id: control
    font.pixelSize: 12
    padding: 6   // keeps the box at the background's 30 px, AppButton's height
    spacing: 6

    background: Rectangle {
        implicitWidth: 140
        implicitHeight: 30
        radius: 9
        color: control.enabled ? Theme.card : Theme.panel
        border.width: 1
        border.color: control.visualFocus || control.down ? Theme.accent : Theme.lineStrong
        Behavior on border.color { ColorAnimation { duration: 90 } }
    }

    contentItem: Text {
        leftPadding: 2
        text: control.displayText
        font: control.font
        color: control.enabled ? Theme.ink : Theme.muted
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: control.mirrored ? control.padding : control.width - width - control.padding
        y: control.topPadding + (control.availableHeight - height) / 2
        text: "▾"
        color: control.enabled ? Theme.muted : Theme.line
        font.pixelSize: 12
    }

    delegate: ItemDelegate {
        id: option
        required property var model
        required property int index

        width: ListView.view ? ListView.view.width : control.width
        height: 28
        padding: 8
        text: model[control.textRole]
        highlighted: control.highlightedIndex === index
        hoverEnabled: control.hoverEnabled

        contentItem: Text {
            text: option.text
            font.pixelSize: control.font.pixelSize
            font.weight: control.currentIndex === option.index ? Font.DemiBold : Font.Normal
            color: option.highlighted ? Theme.accentInk : Theme.ink
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 7
            color: option.highlighted ? Theme.accentSoft : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        padding: 4

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            highlightMoveDuration: 0
            ScrollBar.vertical: AppScrollBar {}
        }
        background: Rectangle {
            radius: 10
            color: Theme.card
            border.width: 1
            border.color: Theme.lineStrong
        }
    }

    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
