import QtQuick
import QtQuick.Controls.Basic

/* One row of a workshop column. Values arrive as plain properties rather than a reference to
   the delegate's model object: Qt recycles that object, and holding it in a `var` makes every
   nested binding read freed memory. */
Rectangle {
    id: root
    property string name: ""
    property string sizeText: ""
    property string status: ""
    property string kind: "apps"
    property string source: ""
    property string initial: "?"
    property color iconColor: Theme.accent
    property int apiLevel: -1
    property bool movable: false
    property bool onDevice: false
    property bool deleted: false
    property bool isLocal: false
    property bool available: false
    property bool busy: false

    signal primary()
    signal exportRequested()
    signal moveUp()
    signal moveDown()

    height: 58
    radius: 10
    color: Theme.card
    border.width: 1
    border.color: hover.hovered ? Theme.lineStrong : Theme.line
    opacity: root.deleted ? 0.45 : 1

    HoverHandler { id: hover }

    Rectangle {          // status stripe, like the web `.item` border-left
        visible: !root.available
        width: 3
        height: root.height - 16
        x: 0
        y: 8
        radius: 2
        color: Theme.statusColor(root.status)
    }

    Row {
        id: content
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 10
        spacing: 11

        Rectangle {
            width: 30
            height: 30
            anchors.verticalCenter: parent.verticalCenter
            radius: 8
            color: root.kind === "scripts" ? Theme.blueSoft : root.iconColor
            Text {
                anchors.centerIn: parent
                text: root.kind === "scripts" ? "py" : root.initial
                color: root.kind === "scripts" ? Theme.blue : "#ffffff"
                font.pixelSize: root.kind === "scripts" ? 11 : 14
                font.weight: Font.Bold
            }
        }

        Item {
            width: Math.max(40, content.width - 30 - actions.width - 2 * content.spacing)
            height: parent.height

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 3

                Row {
                    spacing: 7
                    Text {
                        text: root.name
                        color: Theme.ink
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        font.strikeout: root.deleted
                    }
                    Chip {
                        visible: !root.available && root.status !== ""
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.status === "un" ? i18n.t("leg_un")
                            : root.status === "rw" ? i18n.t("leg_rw")
                            : root.status === "new" ? i18n.t("leg_new") : i18n.t("del")
                        fg: root.status === "un" ? Theme.ok
                          : root.status === "new" ? Theme.blue : Theme.accentInk
                        bg: root.status === "un" ? Theme.okSoft
                          : root.status === "new" ? Theme.blueSoft : Theme.accentSoft
                    }
                }
                Text {
                    width: parent.width
                    text: root.sizeText
                          + (root.apiLevel >= 0 ? " · API " + root.apiLevel : "")
                          + (root.source !== "" ? " · " + root.source : "")
                    color: Theme.muted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }
        }

        Row {
            id: actions
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4

            IconGhostButton {
                visible: !root.available && root.movable && !root.busy
                glyph: "▲"
                tip: i18n.t("move_up")
                onTriggered: root.moveUp()
            }
            IconGhostButton {
                visible: !root.available && root.movable && !root.busy
                glyph: "▼"
                tip: i18n.t("move_down")
                onTriggered: root.moveDown()
            }
            IconGhostButton {
                visible: !root.available && root.onDevice && !root.busy
                glyph: "⤓"
                tip: root.isLocal ? i18n.t("export_pc_have") : i18n.t("export_pc")
                accent: root.isLocal
                onTriggered: root.exportRequested()
            }
            IconGhostButton {
                active: !root.busy && !(root.available && root.status === "staged")
                glyph: root.available ? "+" : (root.deleted ? "↺" : "✕")
                tip: root.available ? i18n.t("add")
                                    : (root.deleted ? i18n.t("restore") : i18n.t("remove"))
                filled: root.available && root.status !== "staged"
                onTriggered: root.primary()
            }
        }
    }
}
