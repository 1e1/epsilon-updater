import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

/* One column of a workshop: a header, the rows, and an empty state.

   Both sides of the pane — what is on the calculator, and what is available — are the same
   list of the same rows differing only by which actions a row offers, which ItemRow already
   decides from `available`. They were two near-identical 70-line blocks; the drift risk was
   the point of factoring them, not the line count. */
ColumnLayout {
    id: root
    property string kind: "apps"
    property var rows: null
    property string title: ""
    property string subtitle: ""
    property int count: 0
    property bool available: false
    property bool busy: false
    property string emptyText: ""

    signal primary(string name, bool deleted)
    signal moveUp(string name)
    signal moveDown(string name)
    signal exportRequested(string name)

    spacing: 6

    ColumnHeader {
        Layout.fillWidth: true
        title: root.title
        subtitle: root.subtitle
        count: root.count
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 7
        model: root.rows
        // The model updates rows in place, so this scroll position survives a refresh.
        ScrollBar.vertical: AppScrollBar {}

        // The delegate root is a plain Item so the required properties do not shadow ItemRow's
        // own API; it forwards them as values.
        delegate: Item {
            id: cell
            required property string name
            required property string sizeText
            required property string status
            required property bool movable
            required property bool onDevice
            required property bool deleted
            required property bool local
            required property bool incompatible
            required property int apiLevel
            required property string source
            required property string initial
            required property string iconColor

            width: list.width
            height: itemRow.height

            ItemRow {
                id: itemRow
                width: parent.width
                kind: root.kind
                available: root.available
                busy: root.busy
                name: cell.name
                sizeText: cell.sizeText
                status: cell.status
                movable: cell.movable
                onDevice: cell.onDevice
                deleted: cell.deleted
                isLocal: cell.local
                incompatible: cell.incompatible
                apiLevel: cell.apiLevel
                source: cell.source
                initial: cell.initial
                iconColor: cell.iconColor
                onPrimary: root.primary(cell.name, cell.deleted)
                onMoveUp: root.moveUp(cell.name)
                onMoveDown: root.moveDown(cell.name)
                onExportRequested: root.exportRequested(cell.name)
            }
        }

        Text {
            anchors.centerIn: parent
            visible: list.count === 0
            text: root.emptyText
            color: Theme.muted
            font.pixelSize: 12
        }
    }
}
