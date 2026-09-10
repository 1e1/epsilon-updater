import QtQuick
import QtQuick.Layouts

/* One "push this set to the whole class" list: chosen items as removable chips, plus a picker
   for what is left in the pool. */
Card {
    id: root
    property string kind: "apps"
    property var available: []
    property var chosen: []
    property string emptyText: ""
    readonly property var pool: (root.available || []).filter(
        (n) => (root.chosen || []).indexOf(n) < 0)

    Text {
        Layout.fillWidth: true
        visible: (root.chosen || []).length === 0
        text: root.emptyText
        color: Theme.muted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: root.chosen
            delegate: Rectangle {
                required property string modelData
                width: chipRow.implicitWidth + 18
                height: 30
                radius: 8
                color: Theme.panel
                border.width: 1
                border.color: Theme.line
                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: 7
                    Rectangle {
                        width: 20; height: 20; radius: 6
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.kind === "scripts" ? Theme.blueSoft : Theme.blue
                        Text {
                            anchors.centerIn: parent
                            text: root.kind === "scripts"
                                  ? "py" : modelData.charAt(0).toUpperCase()
                            color: root.kind === "scripts" ? Theme.blue : "#ffffff"
                            font.pixelSize: root.kind === "scripts" ? 9 : 11
                            font.weight: Font.Bold
                        }
                    }
                    Text {
                        text: modelData
                        color: Theme.ink
                        font.pixelSize: 13
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    IconGhostButton {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: "✕"
                        tip: i18n.t("roster_delete")
                        width: 20; height: 20
                        onTriggered: backend.distToggleItem(root.kind, modelData, false)
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        AppComboBox {
            id: picker
            Layout.preferredWidth: 260
            font.pixelSize: 13
            model: root.pool
            enabled: root.pool.length > 0
        }
        AppButton {
            text: i18n.t("dist_add")
            enabled: root.pool.length > 0
            onClicked: backend.distToggleItem(root.kind, root.pool[picker.currentIndex], true)
        }
        Item { Layout.fillWidth: true }
    }
}
