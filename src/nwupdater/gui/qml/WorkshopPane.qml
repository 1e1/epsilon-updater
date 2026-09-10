import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

/* Apps / Scripts workshop: what is on the calculator (memory order) facing what is available,
   the write plan on top, the footer actions at the bottom. */
Item {
    id: root
    property string kind: "apps"
    property var plan: ({})
    property var deviceModel
    property var availModel
    readonly property bool busy: backend.busy === "write:" + root.kind

    FileDialog {
        id: picker
        title: root.kind === "apps" ? i18n.t("choose_nwa") : i18n.t("choose_py")
        nameFilters: root.kind === "apps" ? ["NumWorks app (*.nwa)"] : ["Python (*.py)"]
        onAccepted: backend.addLocalFile(root.kind, selectedFile)
    }
    FolderDialog {
        id: exportDir
        property string pendingName: ""
        onAccepted: backend.exportItem(root.kind, exportDir.pendingName, selectedFolder)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // -- plan header ------------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: root.plan.usedText || "—"
                color: Theme.ink
                font.pixelSize: 15
                font.weight: Font.Bold
                font.family: Theme.mono
            }
            Text {
                text: "/ " + (root.plan.capText || "—") + " " + i18n.t("used_suffix")
                color: Theme.muted
                font.pixelSize: 13
            }
            Item { Layout.fillWidth: true }
            Text {
                text: (root.plan.freeText || "—") + " " + i18n.t("free_suffix")
                color: Theme.muted
                font.pixelSize: 12
            }
        }

        MemoryBar { Layout.fillWidth: true; plan: root.plan }

        // -- two columns ------------------------------------------------------------
        SplitView {
            id: columns
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            property bool userSized: false
            handle: Rectangle {
                implicitWidth: 9
                onXChanged: if (SplitHandle.pressed) columns.userSized = true
                color: "transparent"
                Rectangle {
                    anchors.centerIn: parent
                    width: 1
                    height: parent.height
                    color: SplitHandle.pressed || SplitHandle.hovered ? Theme.accent : Theme.line
                }
            }

            // on the calculator
            ColumnLayout {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 260
                spacing: 6

                WorkshopColumn {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    kind: root.kind
                    rows: root.deviceModel
                    busy: root.busy
                    title: i18n.t("on_calc")
                    subtitle: root.kind === "apps" ? i18n.t("mem_order") : i18n.t("storage_order")
                    count: root.plan.deviceCount || 0
                    emptyText: i18n.t("no_installed")
                    onPrimary: (name, deleted) => deleted ? backend.stageRestore(root.kind, name)
                                                          : backend.stageRemove(root.kind, name)
                    onMoveUp: (name) => backend.stageMove(root.kind, name, -1)
                    onMoveDown: (name) => backend.stageMove(root.kind, name, 1)
                    onExportRequested: (name) => { exportDir.pendingName = name; exportDir.open() }
                }

                // Drop zone — accepts a real drop from Finder/Explorer, or click to browse.
                DropArea {
                    id: drop
                    Layout.fillWidth: true
                    Layout.preferredHeight: 74
                    onDropped: (ev) => {
                        for (let i = 0; i < ev.urls.length; i++)
                            backend.addLocalFile(root.kind, ev.urls[i])
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: 11
                        color: drop.containsDrag ? Theme.accentSoft : "transparent"
                        border.width: 1.5
                        border.color: drop.containsDrag ? Theme.accent : Theme.lineStrong
                        Column {
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "⤒"
                                font.pixelSize: 19
                                color: Theme.muted
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: (root.kind === "apps" ? ".nwa" : ".py") + " — "
                                      + (root.kind === "apps" ? i18n.t("choose_nwa")
                                                              : i18n.t("choose_py"))
                                color: Theme.accentInk
                                font.pixelSize: 12
                                font.underline: true
                            }
                        }
                        TapHandler { onTapped: picker.open() }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }
                }
            }

            // available
            WorkshopColumn {
                // 50/50 by default — recomputed only while the user has not moved the divider.
                SplitView.preferredWidth: columns.userSized ? undefined : (columns.width - 9) / 2
                SplitView.minimumWidth: 260
                kind: root.kind
                rows: root.availModel
                available: true
                busy: root.busy
                title: i18n.t("available")
                subtitle: i18n.t("src_clr")
                count: root.plan.availCount || 0
                emptyText: i18n.t("no_compat")
                onPrimary: (name) => backend.stageAdd(root.kind, name)
            }
        }

        // -- footer plan + actions ---------------------------------------------------
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
        RowLayout {
            Layout.fillWidth: true
            spacing: 22
            Stat { value: (root.plan.un || 0) + ""; label: i18n.t("wp_unchanged") }
            Stat { value: (root.plan.rewrite || 0) + ""; label: i18n.t("wp_rewrite") }
            Stat { value: root.plan.freeText || "—"; label: i18n.t("wp_free") }
            Item { Layout.fillWidth: true }
            AppButton {
                ghost: true
                text: i18n.t("undo")
                enabled: !!root.plan.canUndo && !root.busy
                onClicked: backend.stageUndo(root.kind)
            }
            AppButton {
                ghost: true
                text: i18n.t("reset")
                enabled: !!root.plan.dirty && !root.busy
                onClicked: backend.stageReset(root.kind)
            }
            AppButton {
                text: root.busy ? i18n.t("writing")
                                : (root.plan.dirty ? i18n.t("write") : i18n.t("nothing"))
                enabled: !!root.plan.dirty && !root.busy
                onClicked: backend.commit(root.kind)
            }
        }
    }
}
